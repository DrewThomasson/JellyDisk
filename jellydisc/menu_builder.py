"""
Menu Builder Module

This module generates DVD menu assets including background images,
highlight masks, and dvdauthor XML configuration for commercial-grade
interactive DVD menus.
"""

import logging
import shutil
import subprocess
import textwrap
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Callable
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger(__name__)


class MenuStyle(Enum):
    """DVD menu visual styles."""
    MODERN = "modern"
    RETRO = "retro"


@dataclass
class MenuConfig:
    """Configuration for DVD menu generation."""
    style: MenuStyle = MenuStyle.MODERN
    title: str = "DVD Menu"
    season_overview: str = ""
    audio_loop_path: Optional[Path] = None
    include_subtitles: bool = True
    include_cast: bool = True
    actors: list[str] = field(default_factory=list)
    include_trailer: bool = False
    
    # Grid layout settings in 16:9 design space (853x480)
    thumbnail_width: int = 180
    thumbnail_height: int = 101
    grid_columns: int = 3
    grid_padding: int = 40
    
    # Colors (RGBA)
    background_color: tuple = (20, 20, 30, 255)
    highlight_color: tuple = (255, 215, 0, 255)  # Gold
    select_color: tuple = (255, 255, 255, 255)    # White
    text_color: tuple = (255, 255, 255, 255)
    subtitle_color: tuple = (200, 200, 200, 255)


@dataclass
class EpisodeThumbnail:
    """Episode thumbnail data for menu generation."""
    episode_index: int
    title: str
    thumbnail_path: Optional[Path] = None
    thumbnail_image: Optional[Image.Image] = None


class MenuBuilderError(Exception):
    """Base exception for menu builder errors."""
    pass


class DVDAuthorNotFoundError(MenuBuilderError):
    """Raised when dvdauthor binary is not found."""
    pass


class MenuBuilder:
    """
    Generates commercial-grade DVD menus with episode thumbnail grids,
    highlight masks, and dvdauthor configuration.
    
    Uses a 16:9 square-pixel design space (853x480) internally, downscaling 
    to NTSC anamorphic (720x480) before saving to correct Pixel Aspect Ratio (PAR) 
    distortion on TVs.
    """
    
    # Square-pixel design resolution (16:9)
    DESIGN_WIDTH = 853
    DESIGN_HEIGHT = 480
    
    # Final coded resolution (NTSC anamorphic)
    MENU_WIDTH = 720
    MENU_HEIGHT = 480
    
    # Safe area margins (TV overscan, relative to 853x480 design space)
    SAFE_MARGIN_X = 50
    SAFE_MARGIN_Y = 30
    
    def __init__(self, output_dir: Path, config: Optional[MenuConfig] = None):
        """
        Initialize the menu builder.
        
        Args:
            output_dir: Directory to store generated menu assets
            config: Menu configuration options
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.config = config or MenuConfig()
        self._font_path = self._find_font()
    
    def _find_font(self) -> Optional[str]:
        """Find a suitable font for text rendering."""
        # 1. Check local project assets folder first
        local_font_path = Path(__file__).resolve().parent.parent / "assets" / "font.ttf"
        if local_font_path.exists():
            return str(local_font_path)
            
        font_paths = [
            "/System/Library/Fonts/Supplemental/HelveticaNeue-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        ]
        
        # 2. Check system paths
        for path in font_paths:
            if Path(path).exists():
                return path
                
        # 3. Download open-source font from Google Font repo as fallback
        try:
            import requests
            font_url = "https://github.com/google/fonts/raw/main/apache/robotocondensed/RobotoCondensed-Bold.ttf"
            logger.info("Downloading RobotoCondensed-Bold.ttf font fallback to assets/font.ttf...")
            local_font_path.parent.mkdir(parents=True, exist_ok=True)
            r = requests.get(font_url, timeout=15)
            r.raise_for_status()
            local_font_path.write_bytes(r.content)
            return str(local_font_path)
        except Exception as e:
            logger.warning(f"Failed to download fallback font: {e}")
            
        return None
    
    def _get_font(self, size: int) -> ImageFont.FreeTypeFont:
        """Get a font at the specified size."""
        try:
            if self._font_path:
                return ImageFont.truetype(self._font_path, size)
        except Exception:
            pass
        return ImageFont.load_default()
    
    def _scale_x_to_coded(self, x: float) -> int:
        """Scale an x-coordinate from 853 design space to 720 coded space."""
        return int(x * self.MENU_WIDTH / self.DESIGN_WIDTH)
    
    def _scale_box_to_coded(self, box: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
        """Scale a bounding box (x0, y0, x1, y1) to 720x480 coded space."""
        x0, y0, x1, y1 = box
        return (
            self._scale_x_to_coded(x0),
            int(y0),
            self._scale_x_to_coded(x1),
            int(y1)
        )
    
    def _apply_style(self, image: Image.Image) -> Image.Image:
        """Apply visual style effects to the menu background."""
        if self.config.style == MenuStyle.RETRO:
            # Add scanlines effect for retro look
            overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            for y in range(0, image.height, 2):
                draw.line([(0, y), (image.width, y)], fill=(0, 0, 0, 80), width=1)
            image = Image.alpha_composite(image.convert('RGBA'), overlay)
            image = image.filter(ImageFilter.GaussianBlur(radius=0.5))
        else:
            # Modern style - add subtle radial vignette
            overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            cx, cy = image.width // 2, image.height // 2
            max_dist = (cx ** 2 + cy ** 2) ** 0.5
            
            # Fast radial gradient: draw concentric circles outwards
            for r in range(0, int(max_dist), 8):
                alpha = int(min(120, (r / max_dist) * 150))
                # Draw circles with thick strokes
                draw.ellipse(
                    [cx - r, cy - r, cx + r, cy + r],
                    outline=(0, 0, 0, alpha),
                    width=8
                )
            image = Image.alpha_composite(image.convert('RGBA'), overlay)
        return image
    
    def _load_backdrop(self, backdrop_path: Optional[Path]) -> Image.Image:
        """Load and prepare the background backdrop image."""
        if backdrop_path and backdrop_path.exists():
            backdrop = Image.open(backdrop_path)
            backdrop = backdrop.resize((self.DESIGN_WIDTH, self.DESIGN_HEIGHT), Image.Resampling.LANCZOS)
            # Darken backdrop to ensure text readability
            backdrop = Image.blend(
                backdrop.convert('RGBA'),
                Image.new('RGBA', backdrop.size, (15, 15, 25, 255)),
                0.65
            )
            return backdrop
        return Image.new('RGBA', (self.DESIGN_WIDTH, self.DESIGN_HEIGHT), self.config.background_color)
    
    def _draw_menu_header(self, image: Image.Image, draw: ImageDraw.ImageDraw, logo_path: Optional[Path]) -> int:
        """Draw the series logo or title text. Returns the ending Y coordinate."""
        title_y = self.SAFE_MARGIN_Y
        if logo_path and logo_path.exists():
            try:
                logo = Image.open(logo_path).convert('RGBA')
                max_w = self.DESIGN_WIDTH - 2 * self.SAFE_MARGIN_X
                logo.thumbnail((max_w, 65), Image.Resampling.LANCZOS)
                logo_x = (self.DESIGN_WIDTH - logo.width) // 2
                image.paste(logo, (logo_x, title_y), logo)
                return title_y + logo.height + 15
            except Exception as e:
                logger.error(f"Error drawing logo: {e}")
        
        # Fallback to text title
        font = self._get_font(36)
        bbox = draw.textbbox((0, 0), self.config.title, font=font)
        w = bbox[2] - bbox[0]
        x = (self.DESIGN_WIDTH - w) // 2
        draw.text((x, title_y), self.config.title, fill=self.config.text_color, font=font)
        return title_y + (bbox[3] - bbox[1]) + 15

    def _draw_text_button(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        cx: int,
        cy: int,
        font: ImageFont.FreeTypeFont,
        color: tuple,
        mask_draws: list[ImageDraw.ImageDraw] = None,
        padding: int = 15
    ) -> tuple[int, int, int, int]:
        """Draw a text button and return its design-space bounding box."""
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x0 = cx - w // 2
        y0 = cy - h // 2
        x1 = x0 + w
        y1 = y0 + h
        
        # Draw on background
        draw.text((x0, y0), text, fill=color, font=font)
        
        # Define button boundaries (with padding)
        btn_box = (x0 - padding, y0 - padding // 2, x1 + padding, y1 + padding // 2)
        
        # Draw highlight/select borders if draws list provided
        if mask_draws:
            hl_draw, sel_draw = mask_draws
            # Draw outlines on highlights (using solid colors for spumux)
            hl_draw.rectangle(btn_box, outline=self.config.highlight_color, width=3)
            sel_draw.rectangle(btn_box, outline=self.config.select_color, width=4)
            
        return btn_box

    def generate_main_menu(
        self,
        backdrop_path: Optional[Path] = None,
        logo_path: Optional[Path] = None,
        has_trailer: bool = False,
        show_episode_select: bool = True
    ) -> tuple[Path, Path, Path, list[tuple[int, int, int, int]]]:
        """
        Generate the Main Menu background and highlight masks.
        
        Returns:
            Tuple of (bg_path, highlight_path, select_path, coded_button_bounds)
        """
        bg_image = self._load_backdrop(backdrop_path)
        draw = ImageDraw.Draw(bg_image)
        bg_image = self._apply_style(bg_image)
        draw = ImageDraw.Draw(bg_image)
        
        # Create pure black backgrounds for spumux compatibility (black is transparent)
        hl_image = Image.new('RGB', (self.DESIGN_WIDTH, self.DESIGN_HEIGHT), (0, 0, 0))
        sel_image = Image.new('RGB', (self.DESIGN_WIDTH, self.DESIGN_HEIGHT), (0, 0, 0))
        hl_draw = ImageDraw.Draw(hl_image)
        sel_draw = ImageDraw.Draw(sel_image)
        
        # Draw Header
        header_end_y = self._draw_menu_header(bg_image, draw, logo_path)
        
        # Build button labels dynamically based on availability
        button_labels = ["PLAY ALL"]
        if show_episode_select:
            button_labels.append("EPISODE SELECT")
        if self.config.include_cast:
            button_labels.append("CAST & INFO")
        if has_trailer:
            button_labels.append("PLAY TRAILER")
            
        # Setup buttons layout
        btn_font = self._get_font(24)
        center_x = self.DESIGN_WIDTH // 2
        
        num_buttons = len(button_labels)
        if num_buttons == 2:
            gap = 80
            start_y = header_end_y + 80
        elif num_buttons == 3:
            gap = 60
            start_y = header_end_y + 55
        else: # 4 buttons
            gap = 50
            start_y = header_end_y + 35
            
        buttons_design = []
        mask_draws = [hl_draw, sel_draw]
        
        for idx, label in enumerate(button_labels):
            y_pos = start_y + idx * gap
            box = self._draw_text_button(draw, label, center_x, y_pos, btn_font, self.config.text_color, mask_draws)
            buttons_design.append(box)
        
        # Downscale images to coded DVD resolution (720x480)
        final_bg = bg_image.resize((self.MENU_WIDTH, self.MENU_HEIGHT), Image.Resampling.LANCZOS)
        final_hl = hl_image.resize((self.MENU_WIDTH, self.MENU_HEIGHT), Image.Resampling.NEAREST)
        final_sel = sel_image.resize((self.MENU_WIDTH, self.MENU_HEIGHT), Image.Resampling.NEAREST)
        
        # Save assets
        bg_path = self.output_dir / "menu_main_bg.png"
        hl_path = self.output_dir / "menu_main_highlight.png"
        sel_path = self.output_dir / "menu_main_select.png"
        
        final_bg.save(bg_path, "PNG")
        final_hl.save(hl_path, "PNG")
        final_sel.save(sel_path, "PNG")
        
        # Convert design-space coordinates to coded 720x480 coordinates
        coded_bounds = [self._scale_box_to_coded(box) for box in buttons_design]
        
        return bg_path, hl_path, sel_path, coded_bounds

    def generate_setup_menu(
        self,
        backdrop_path: Optional[Path] = None,
        logo_path: Optional[Path] = None
    ) -> tuple[Path, Path, Path, list[tuple[int, int, int, int]]]:
        """
        Generate the Setup Menu (toggle subtitles on/off).
        """
        bg_image = self._load_backdrop(backdrop_path)
        draw = ImageDraw.Draw(bg_image)
        bg_image = self._apply_style(bg_image)
        draw = ImageDraw.Draw(bg_image)
        
        hl_image = Image.new('RGB', (self.DESIGN_WIDTH, self.DESIGN_HEIGHT), (0, 0, 0))
        sel_image = Image.new('RGB', (self.DESIGN_WIDTH, self.DESIGN_HEIGHT), (0, 0, 0))
        hl_draw = ImageDraw.Draw(hl_image)
        sel_draw = ImageDraw.Draw(sel_image)
        
        header_end_y = self._draw_menu_header(bg_image, draw, logo_path)
        
        # Setup Title
        font_setup = self._get_font(22)
        setup_bbox = draw.textbbox((0, 0), "SUBTITLES SETUP", font=font_setup)
        setup_w = setup_bbox[2] - setup_bbox[0]
        draw.text(((self.DESIGN_WIDTH - setup_w) // 2, header_end_y + 10), "SUBTITLES SETUP", fill=self.config.subtitle_color, font=font_setup)
        
        btn_font = self._get_font(20)
        mask_draws = [hl_draw, sel_draw]
        buttons_design = []
        
        # Button 1: SUBTITLES ON
        box1 = self._draw_text_button(draw, "SUBTITLES ON", 300, header_end_y + 100, btn_font, self.config.text_color, mask_draws)
        buttons_design.append(box1)
        
        # Button 2: SUBTITLES OFF
        box2 = self._draw_text_button(draw, "SUBTITLES OFF", 553, header_end_y + 100, btn_font, self.config.text_color, mask_draws)
        buttons_design.append(box2)
        
        # Button 3: BACK
        box3 = self._draw_text_button(draw, "BACK TO MAIN", self.DESIGN_WIDTH // 2, header_end_y + 190, btn_font, self.config.subtitle_color, mask_draws)
        buttons_design.append(box3)
        
        # Downscale and save
        final_bg = bg_image.resize((self.MENU_WIDTH, self.MENU_HEIGHT), Image.Resampling.LANCZOS)
        final_hl = hl_image.resize((self.MENU_WIDTH, self.MENU_HEIGHT), Image.Resampling.NEAREST)
        final_sel = sel_image.resize((self.MENU_WIDTH, self.MENU_HEIGHT), Image.Resampling.NEAREST)
        
        bg_path = self.output_dir / "menu_setup_bg.png"
        hl_path = self.output_dir / "menu_setup_highlight.png"
        sel_path = self.output_dir / "menu_setup_select.png"
        
        final_bg.save(bg_path, "PNG")
        final_hl.save(hl_path, "PNG")
        final_sel.save(sel_path, "PNG")
        
        coded_bounds = [self._scale_box_to_coded(box) for box in buttons_design]
        return bg_path, hl_path, sel_path, coded_bounds

    def generate_cast_menu(
        self,
        backdrop_path: Optional[Path] = None,
        logo_path: Optional[Path] = None,
        overview: str = "",
        actors: list[str] = None
    ) -> tuple[Path, Path, Path, list[tuple[int, int, int, int]]]:
        """
        Generate the Cast & Show Info Menu background and highlights.
        """
        bg_image = self._load_backdrop(backdrop_path)
        draw = ImageDraw.Draw(bg_image)
        bg_image = self._apply_style(bg_image)
        draw = ImageDraw.Draw(bg_image)
        
        hl_image = Image.new('RGB', (self.DESIGN_WIDTH, self.DESIGN_HEIGHT), (0, 0, 0))
        sel_image = Image.new('RGB', (self.DESIGN_WIDTH, self.DESIGN_HEIGHT), (0, 0, 0))
        hl_draw = ImageDraw.Draw(hl_image)
        sel_draw = ImageDraw.Draw(sel_image)
        
        header_end_y = self._draw_menu_header(bg_image, draw, logo_path)
        
        # Cast Title Subtext
        font_sub = self._get_font(20)
        sub_text = "CAST & SHOW INFO"
        sub_bbox = draw.textbbox((0, 0), sub_text, font=font_sub)
        sub_x = (self.DESIGN_WIDTH - (sub_bbox[2] - sub_bbox[0])) // 2
        draw.text((sub_x, header_end_y + 5), sub_text, fill=self.config.subtitle_color, font=font_sub)
        
        content_y = header_end_y + 50
        
        # Draw Summary column (Left side)
        summary_title_font = self._get_font(16)
        draw.text((self.SAFE_MARGIN_X, content_y), "SHOW SUMMARY", fill=self.config.subtitle_color, font=summary_title_font)
        
        summary_font = self._get_font(11)
        summary_text = overview or "No show summary available."
        # Wrap summary text (approx 45 chars per line)
        wrapped_summary = textwrap.fill(summary_text, width=45)
        # Limit lines to prevent vertical overflow
        lines = wrapped_summary.split("\n")
        if len(lines) > 13:
            wrapped_summary = "\n".join(lines[:12]) + "\n..."
        draw.text((self.SAFE_MARGIN_X, content_y + 25), wrapped_summary, fill=self.config.text_color, font=summary_font)
        
        # Draw Cast column (Right side)
        cast_title_x = 480
        draw.text((cast_title_x, content_y), "STARRING CAST", fill=self.config.subtitle_color, font=summary_title_font)
        
        cast_font = self._get_font(14)
        actors_list = actors or self.config.actors
        if not actors_list:
            actors_list = ["Cast details not available."]
            
        cast_y = content_y + 25
        for actor in actors_list[:7]:  # Limit to 7 actors to fit vertically
            # Truncate long role descriptions to fit column
            if len(actor) > 35:
                actor = actor[:32] + "..."
            draw.text((cast_title_x, cast_y), f"• {actor}", fill=self.config.text_color, font=cast_font)
            cast_y += 26
            
        # Draw Back Button at the bottom
        nav_y = 435
        btn_font = self._get_font(18)
        mask_draws = [hl_draw, sel_draw]
        buttons_design = []
        
        box_back = self._draw_text_button(draw, "BACK TO MAIN", self.DESIGN_WIDTH // 2, nav_y, btn_font, self.config.subtitle_color, mask_draws)
        buttons_design.append(box_back)
        
        # Downscale and save
        final_bg = bg_image.resize((self.MENU_WIDTH, self.MENU_HEIGHT), Image.Resampling.LANCZOS)
        final_hl = hl_image.resize((self.MENU_WIDTH, self.MENU_HEIGHT), Image.Resampling.NEAREST)
        final_sel = sel_image.resize((self.MENU_WIDTH, self.MENU_HEIGHT), Image.Resampling.NEAREST)
        
        bg_path = self.output_dir / "menu_cast_bg.png"
        hl_path = self.output_dir / "menu_cast_highlight.png"
        sel_path = self.output_dir / "menu_cast_select.png"
        
        final_bg.save(bg_path, "PNG")
        final_hl.save(hl_path, "PNG")
        final_sel.save(sel_path, "PNG")
        
        coded_bounds = [self._scale_box_to_coded(box) for box in buttons_design]
        return bg_path, hl_path, sel_path, coded_bounds

    def generate_episode_menu(
        self,
        backdrop_path: Optional[Path] = None,
        logo_path: Optional[Path] = None,
        episodes: list[EpisodeThumbnail] = None,
        page_index: int = 0,
        total_pages: int = 1
    ) -> tuple[Path, Path, Path, list[tuple[int, int, int, int]]]:
        """
        Generate paginated Episode Selection Menu backgrounds and highlights.
        """
        bg_image = self._load_backdrop(backdrop_path)
        draw = ImageDraw.Draw(bg_image)
        bg_image = self._apply_style(bg_image)
        draw = ImageDraw.Draw(bg_image)
        
        hl_image = Image.new('RGB', (self.DESIGN_WIDTH, self.DESIGN_HEIGHT), (0, 0, 0))
        sel_image = Image.new('RGB', (self.DESIGN_WIDTH, self.DESIGN_HEIGHT), (0, 0, 0))
        hl_draw = ImageDraw.Draw(hl_image)
        sel_draw = ImageDraw.Draw(sel_image)
        
        header_end_y = self._draw_menu_header(bg_image, draw, logo_path)
        
        # Page Title Subtext
        font_sub = self._get_font(18)
        sub_text = f"SELECT EPISODE - PAGE {page_index+1} OF {total_pages}"
        sub_bbox = draw.textbbox((0, 0), sub_text, font=font_sub)
        sub_x = (self.DESIGN_WIDTH - (sub_bbox[2] - sub_bbox[0])) // 2
        draw.text((sub_x, header_end_y + 5), sub_text, fill=self.config.subtitle_color, font=font_sub)
        
        grid_start_y = header_end_y + 25
        
        # Grid parameters
        tw = self.config.thumbnail_width
        th = self.config.thumbnail_height
        padding = self.config.grid_padding
        cols = self.config.grid_columns
        grid_w = cols * tw + (cols - 1) * padding
        start_x = (self.DESIGN_WIDTH - grid_w) // 2
        
        episode_font = self._get_font(12)
        num_font = self._get_font(24)
        
        buttons_design = []
        
        # Slice episodes for this page
        page_episodes = episodes[page_index * 6 : (page_index + 1) * 6]
        
        for i, ep in enumerate(page_episodes):
            row = i // cols
            col = i % cols
            
            x = start_x + col * (tw + padding)
            y = grid_start_y + row * 135
            
            # Draw Thumbnail
            if ep.thumbnail_image:
                thumb = ep.thumbnail_image.copy()
                thumb = thumb.resize((tw, th), Image.Resampling.LANCZOS)
                bg_image.paste(thumb, (x, y))
            elif ep.thumbnail_path and ep.thumbnail_path.exists():
                try:
                    thumb = Image.open(ep.thumbnail_path)
                    thumb = thumb.resize((tw, th), Image.Resampling.LANCZOS)
                    bg_image.paste(thumb, (x, y))
                except Exception:
                    # Draw placeholder
                    draw.rectangle([x, y, x + tw, y + th], fill=(50, 50, 70), outline=(100, 100, 120))
            else:
                # Draw placeholder
                draw.rectangle([x, y, x + tw, y + th], fill=(50, 50, 70), outline=(100, 100, 120))
                num_text = f"E{ep.episode_index}"
                n_bbox = draw.textbbox((0, 0), num_text, font=num_font)
                nx = x + (tw - (n_bbox[2] - n_bbox[0])) // 2
                ny = y + (th - (n_bbox[3] - n_bbox[1])) // 2
                draw.text((nx, ny), num_text, fill=(150, 150, 150), font=num_font)
                
            # Draw episode label below
            lbl = f"E{ep.episode_index}. {ep.title}"
            if len(lbl) > 22:
                lbl = lbl[:19] + "..."
            l_bbox = draw.textbbox((0, 0), lbl, font=episode_font)
            lx = x + (tw - (l_bbox[2] - l_bbox[0])) // 2
            draw.text((lx, y + th + 2), lbl, fill=self.config.text_color, font=episode_font)
            
            # The button bounds matches the thumbnail exactly
            btn_box = (x, y, x + tw, y + th)
            buttons_design.append(btn_box)
            
            # Draw highlight outline on masks
            hl_draw.rectangle(btn_box, outline=self.config.highlight_color, width=4)
            sel_draw.rectangle(btn_box, outline=self.config.select_color, width=5)
            
        # Draw navigation buttons at the bottom
        nav_y = 435
        nav_font = self._get_font(18)
        mask_draws = [hl_draw, sel_draw]
        
        # Previous Page Button (if page > 0)
        if page_index > 0:
            box_prev = self._draw_text_button(draw, "PREV PAGE", 150, nav_y, nav_font, self.config.text_color, mask_draws)
            buttons_design.append(box_prev)
            
        # Back to Main Menu Button
        box_main = self._draw_text_button(draw, "MAIN MENU", self.DESIGN_WIDTH // 2, nav_y, nav_font, self.config.subtitle_color, mask_draws)
        buttons_design.append(box_main)
        
        # Next Page Button (if there are more pages)
        if page_index < total_pages - 1:
            box_next = self._draw_text_button(draw, "NEXT PAGE", 703, nav_y, nav_font, self.config.text_color, mask_draws)
            buttons_design.append(box_next)
            
        # Downscale and save
        final_bg = bg_image.resize((self.MENU_WIDTH, self.MENU_HEIGHT), Image.Resampling.LANCZOS)
        final_hl = hl_image.resize((self.MENU_WIDTH, self.MENU_HEIGHT), Image.Resampling.NEAREST)
        final_sel = sel_image.resize((self.MENU_WIDTH, self.MENU_HEIGHT), Image.Resampling.NEAREST)
        
        bg_path = self.output_dir / f"menu_episodes_bg_{page_index+1}.png"
        hl_path = self.output_dir / f"menu_episodes_highlight_{page_index+1}.png"
        sel_path = self.output_dir / f"menu_episodes_select_{page_index+1}.png"
        
        final_bg.save(bg_path, "PNG")
        final_hl.save(hl_path, "PNG")
        final_sel.save(sel_path, "PNG")
        
        coded_bounds = [self._scale_box_to_coded(box) for box in buttons_design]
        return bg_path, hl_path, sel_path, coded_bounds

    def generate_menu_video(
        self,
        background_path: Path,
        output_filename: str,
        audio_path: Optional[Path] = None,
        duration: int = 15
    ) -> Path:
        """
        Generate a looping menu video from background PNG, with optional theme audio.
        """
        output_path = self.output_dir / output_filename
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            raise MenuBuilderError("FFmpeg not found")
        
        cmd = [
            ffmpeg_path,
            "-y",
            "-loop", "1",
            "-i", str(background_path),
            "-t", str(duration),
        ]
        
        if audio_path and audio_path.exists():
            cmd.extend([
                "-i", str(audio_path),
                "-shortest",
                "-af", f"afade=t=out:st={duration-2}:d=2",
            ])
            
        cmd.extend([
            "-c:v", "mpeg2video",
            "-b:v", "6000k",
            "-maxrate", "8000k",
            "-bufsize", "2000k",
            "-s", f"{self.MENU_WIDTH}x{self.MENU_HEIGHT}",
            "-r", "29.97",
            "-aspect", "16:9",
            "-pix_fmt", "yuv420p",
            "-c:a", "ac3",
            "-b:a", "192k",
            "-ar", "48000",
            "-target", "ntsc-dvd",
            str(output_path)
        ])
        
        logger.debug(f"Running FFmpeg: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise MenuBuilderError(f"Failed to generate menu video: {result.stderr}")
            
        logger.info(f"Generated menu video: {output_path}")
        return output_path

    def compile_interactive_menu(
        self,
        menu_video_path: Path,
        highlight_path: Path,
        select_path: Path,
        buttons: list[tuple[int, int, int, int]],
        output_path: Path
    ) -> Path:
        """
        Runs spumux to multiplex highlight overlays directly into the menu video stream.
        """
        spumux_path = shutil.which("spumux")
        if not spumux_path:
            logger.warning("spumux not found. Highlight borders will be inactive.")
            shutil.copy(menu_video_path, output_path)
            return output_path
            
        spumux_xml = self.output_dir / f"spumux_{output_path.stem}.xml"
        
        buttons_xml = []
        for i, btn in enumerate(buttons):
            x0, y0, x1, y1 = btn
            buttons_xml.append(f'      <button name="button{i+1}" x0="{x0}" y0="{y0}" x1="{x1}" y1="{y1}" />')
            
        xml_content = f'''<subpictures>
  <stream>
    <spu start="00:00:00.00" end="00:00:00.00"
         image="{highlight_path}"
         select="{select_path}"
         transparent="000000"
         force="yes">
{chr(10).join(buttons_xml)}
    </spu>
  </stream>
</subpictures>
'''
        spumux_xml.write_text(xml_content)
        
        cmd = [spumux_path, str(spumux_xml)]
        logger.debug(f"Running spumux: {' '.join(cmd)}")
        try:
            with open(menu_video_path, 'rb') as stdin_file:
                with open(output_path, 'wb') as stdout_file:
                    result = subprocess.run(
                        cmd,
                        stdin=stdin_file,
                        stdout=stdout_file,
                        stderr=subprocess.PIPE,
                        timeout=300
                    )
            if result.returncode != 0:
                logger.error(f"spumux failed: {result.stderr.decode('utf-8', errors='ignore')}")
                shutil.copy(menu_video_path, output_path)
            else:
                logger.info(f"Successfully multiplexed highlights into {output_path}")
        except Exception as e:
            logger.error(f"Failed to run spumux: {e}")
            shutil.copy(menu_video_path, output_path)
            
        return output_path

    def generate_dvdauthor_xml(
        self,
        video_files: list[Path],
        menu_main_path: Path,
        menu_episode_paths: list[Path],
        menu_cast_path: Optional[Path] = None,
        menu_trailer_path: Optional[Path] = None,
        output_path: Optional[Path] = None
    ) -> Path:
        """
        Generate dvdauthor XML configuration with advanced VM state registers.
        """
        if output_path is None:
            output_path = self.output_dir / "dvdauthor.xml"
            
        # Build titleset menus PGCs
        menu_pgcs = []
        
        # PGC indexes:
        # PGC 1: Main Menu (Menu 1)
        # If cast menu exists:
        #   PGC 2: Cast Menu (Menu 2)
        #   PGC 3+: Episode Menu Pages
        # Else:
        #   PGC 2+: Episode Menu Pages
        
        has_cast = menu_cast_path is not None
        has_trailer = menu_trailer_path is not None
        ep_start_menu_num = 3 if has_cast else 2
        
        total_pages = len(menu_episode_paths)
        
        # 1. Main Menu PGC (PGC 1)
        redirects = []
        for p_idx in range(total_pages):
            menu_num = ep_start_menu_num + p_idx
            redirects.append(f"          if (g2 == {menu_num}) {{ g2 = 0; jump menu {menu_num}; }}")
        redirects_str = "\n".join(redirects)
        
        # Generate main menu buttons dynamically
        main_button_cmds = []
        btn_idx = 1
        
        # Play All (Jump to first episode: Title 2 if trailer is Title 1, else Title 1)
        play_title = 2 if has_trailer else 1
        main_button_cmds.append(f'        <button name="button{btn_idx}"> g1 = 1; jump title {play_title}; </button>')
        btn_idx += 1
        
        # Episode Select (only if we have episode sub-menus)
        if len(video_files) > 1 and total_pages > 0:
            main_button_cmds.append(f'        <button name="button{btn_idx}"> jump menu {ep_start_menu_num}; </button>')
            btn_idx += 1
            
        # Cast & Info (Menu 2)
        if has_cast:
            main_button_cmds.append(f'        <button name="button{btn_idx}"> jump menu 2; </button>')
            btn_idx += 1
            
        # Play Trailer (Title 1)
        if has_trailer:
            main_button_cmds.append(f'        <button name="button{btn_idx}"> jump title 1; </button>')
            btn_idx += 1
            
        main_buttons = "\n".join(main_button_cmds)
        
        menu_pgcs.append(f'''    <menus>
      <video format="ntsc" aspect="16:9" />
      
      <!-- Menu 1: Main Menu -->
      <pgc entry="root">
        <pre>
{redirects_str}
        </pre>
        <vob file="{menu_main_path}" pause="inf" />
{main_buttons}
      </pgc>''')
 
        # 2. Cast Menu PGC (PGC 2) - Optional
        if has_cast:
            menu_pgcs.append(f'''      <!-- Menu 2: Cast & Info Menu -->
      <pgc>
        <pre> g2 = 0; </pre>
        <vob file="{menu_cast_path}" pause="inf" />
        <button name="button1"> jump menu 1; </button>
      </pgc>''')
 
        # 3. Episode Selection Menus
        for p_idx, ep_menu_path in enumerate(menu_episode_paths):
            menu_num = ep_start_menu_num + p_idx
            
            buttons = []
            ep_start_idx = p_idx * 6
            eps_on_page = min(6, len(video_files) - ep_start_idx)
            
            btn_idx = 1
            for i in range(eps_on_page):
                title_num = ep_start_idx + i + 1
                if has_trailer:
                    title_num += 1
                buttons.append(f'        <button name="button{btn_idx}"> g1 = 0; g2 = {menu_num}; jump title {title_num}; </button>')
                btn_idx += 1
                
            if p_idx > 0:
                prev_menu_num = ep_start_menu_num + p_idx - 1
                buttons.append(f'        <button name="button{btn_idx}"> jump menu {prev_menu_num}; </button>')
                btn_idx += 1
                
            buttons.append(f'        <button name="button{btn_idx}"> jump menu 1; </button>')
            btn_idx += 1
            
            if p_idx < total_pages - 1:
                next_menu_num = ep_start_menu_num + p_idx + 1
                buttons.append(f'        <button name="button{btn_idx}"> jump menu {next_menu_num}; </button>')
                btn_idx += 1
                
            menu_pgcs.append(f'''      <!-- Menu {menu_num}: Episode Menu Page {p_idx+1} -->
      <pgc>
        <pre> g2 = 0; </pre>
        <vob file="{ep_menu_path}" pause="inf" />
{chr(10).join(buttons)}
      </pgc>''')
      
        menu_pgcs.append('    </menus>')
     
        # Build individual Title PGCs with Play All / Single Play branching
        title_pgcs = []
        
        # Trailer Title PGC (Title 1)
        if has_trailer:
            title_pgcs.append(f'''      <!-- Title 1: Trailer -->
      <pgc>
        <vob file="{menu_trailer_path}" />
        <post>
          call menu;
        </post>
      </pgc>''')
        
        # Episode Title PGCs
        for i, vf in enumerate(video_files):
            title_num = i + 2 if has_trailer else i + 1
            
            if i < len(video_files) - 1:
                next_title_num = title_num + 1
                post_cmd = f'''        <post>
          if (g1 == 1) jump title {next_title_num};
          else call menu;
        </post>'''
            else:
                post_cmd = '''        <post>
          g1 = 0;
          call menu;
        </post>'''
                
            title_pgcs.append(f'''      <!-- Title {title_num}: Episode {i+1} -->
      <pgc>
        <vob file="{vf}" />
{post_cmd}
      </pgc>''')
      
        xml_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<dvdauthor dest="{self.output_dir / 'DVD'}">
  <vmgm>
    <menus>
      <video format="ntsc" aspect="16:9" />
      <pgc>
        <pre> jump titleset 1 menu; </pre>
      </pgc>
    </menus>
  </vmgm>
  
  <titleset>
{chr(10).join(menu_pgcs)}
    
    <titles>
      <video format="ntsc" aspect="16:9" />
      <audio format="ac3" channels="2" />
{chr(10).join(title_pgcs)}
    </titles>
  </titleset>
</dvdauthor>
'''
        output_path.write_text(xml_content)
        logger.info(f"Generated advanced dvdauthor XML: {output_path}")
        return output_path

    def build_dvd_structure(
        self,
        dvdauthor_xml: Path,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Path:
        """
        Run dvdauthor to build the DVD file structure.
        """
        dvdauthor_path = shutil.which("dvdauthor")
        if not dvdauthor_path:
            raise DVDAuthorNotFoundError("dvdauthor not found.")
        
        dvd_dir = self.output_dir / "DVD"
        if dvd_dir.exists():
            try:
                shutil.rmtree(dvd_dir)
            except Exception as e:
                logger.warning(f"Could not remove existing DVD directory: {e}")
        dvd_dir.mkdir(parents=True, exist_ok=True)
        
        if progress_callback:
            progress_callback("Building DVD structure...")
        
        cmd = [dvdauthor_path, "-x", str(dvdauthor_xml)]
        logger.debug(f"Running dvdauthor: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=self.output_dir)
        if result.returncode != 0:
            raise MenuBuilderError(f"dvdauthor failed: {result.stderr}")
        
        if progress_callback:
            progress_callback("DVD structure complete")
            
        logger.info(f"Built DVD structure: {dvd_dir}")
        return dvd_dir


def check_menu_dependencies() -> dict[str, bool]:
    """Check for required dependencies for menu building."""
    return {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "dvdauthor": shutil.which("dvdauthor") is not None,
        "spumux": shutil.which("spumux") is not None,
        "pillow": True,
    }
