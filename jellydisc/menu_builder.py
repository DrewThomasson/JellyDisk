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
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Callable
from io import BytesIO

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
    
    # Grid layout settings
    thumbnail_width: int = 160
    thumbnail_height: int = 90
    grid_columns: int = 3
    grid_padding: int = 20
    
    # Colors (RGBA)
    background_color: tuple = (20, 20, 30, 255)
    highlight_color: tuple = (255, 215, 0, 255)  # Gold
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
    
    Features:
    - Grid layout of episode thumbnails
    - Interactive highlight masks for DVD remote navigation
    - Season overview text display
    - Theme song audio loop
    - Modern/Retro visual styles
    """
    
    # DVD menu resolution (NTSC)
    MENU_WIDTH = 720
    MENU_HEIGHT = 480
    
    # Safe area margins (TV overscan)
    SAFE_MARGIN_X = 36
    SAFE_MARGIN_Y = 24
    
    def __init__(
        self,
        output_dir: Path,
        config: Optional[MenuConfig] = None
    ):
        """
        Initialize the menu builder.
        
        Args:
            output_dir: Directory to store generated menu assets
            config: Menu configuration options
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.config = config or MenuConfig()
        
        # Try to find a font
        self._font_path = self._find_font()
    
    def _find_font(self) -> Optional[str]:
        """Find a suitable font for text rendering."""
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "C:\\Windows\\Fonts\\arial.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        ]
        
        for path in font_paths:
            if Path(path).exists():
                return path
        
        return None
    
    def _get_font(self, size: int) -> ImageFont.FreeTypeFont:
        """Get a font at the specified size."""
        try:
            if self._font_path:
                return ImageFont.truetype(self._font_path, size)
        except Exception:
            pass
        
        # Fallback to default
        return ImageFont.load_default()
    
    def _apply_style(self, image: Image.Image) -> Image.Image:
        """Apply visual style effects to the menu background."""
        if self.config.style == MenuStyle.RETRO:
            # Add scanlines effect for retro look
            overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            
            for y in range(0, image.height, 2):
                draw.line([(0, y), (image.width, y)], fill=(0, 0, 0, 80), width=1)
            
            image = Image.alpha_composite(image.convert('RGBA'), overlay)
            
            # Add slight blur
            image = image.filter(ImageFilter.GaussianBlur(radius=0.5))
        else:
            # Modern style - add subtle vignette
            overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            
            # Create radial gradient vignette
            cx, cy = image.width // 2, image.height // 2
            max_dist = (cx ** 2 + cy ** 2) ** 0.5
            
            for y in range(image.height):
                for x in range(0, image.width, 4):  # Sample every 4 pixels for speed
                    dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                    alpha = int(min(80, (dist / max_dist) * 100))
                    draw.rectangle([x, y, x + 4, y + 1], fill=(0, 0, 0, alpha))
            
            image = Image.alpha_composite(image.convert('RGBA'), overlay)
        
        return image
    
    def generate_menu_background(
        self,
        backdrop_path: Optional[Path] = None,
        logo_path: Optional[Path] = None,
        episodes: Optional[list[EpisodeThumbnail]] = None
    ) -> Path:
        """
        Generate the main menu background image with episode thumbnail grid.
        
        Args:
            backdrop_path: Path to series backdrop image
            logo_path: Path to series logo image
            episodes: List of episode thumbnails to display
            
        Returns:
            Path to generated menu background PNG
        """
        # Create base image
        if backdrop_path and backdrop_path.exists():
            backdrop = Image.open(backdrop_path)
            backdrop = backdrop.resize((self.MENU_WIDTH, self.MENU_HEIGHT), Image.Resampling.LANCZOS)
            # Darken for better contrast
            backdrop = Image.blend(
                backdrop.convert('RGBA'),
                Image.new('RGBA', backdrop.size, (0, 0, 0, 180)),
                0.6
            )
            image = backdrop
        else:
            image = Image.new('RGBA', (self.MENU_WIDTH, self.MENU_HEIGHT), self.config.background_color)
        
        draw = ImageDraw.Draw(image)
        
        # Apply style
        image = self._apply_style(image)
        draw = ImageDraw.Draw(image)
        
        # Add logo or title at top
        title_y = self.SAFE_MARGIN_Y
        
        if logo_path and logo_path.exists():
            logo = Image.open(logo_path).convert('RGBA')
            # Scale logo to fit
            max_logo_width = self.MENU_WIDTH - 2 * self.SAFE_MARGIN_X
            max_logo_height = 80
            logo.thumbnail((max_logo_width, max_logo_height), Image.Resampling.LANCZOS)
            
            logo_x = (self.MENU_WIDTH - logo.width) // 2
            image.paste(logo, (logo_x, title_y), logo)
            title_y += logo.height + 10
        else:
            # Draw text title
            title_font = self._get_font(32)
            title_bbox = draw.textbbox((0, 0), self.config.title, font=title_font)
            title_width = title_bbox[2] - title_bbox[0]
            title_x = (self.MENU_WIDTH - title_width) // 2
            draw.text((title_x, title_y), self.config.title, fill=self.config.text_color, font=title_font)
            title_y += 40
        
        # Draw episode thumbnail grid
        if episodes:
            grid_start_y = title_y + 20
            self._draw_episode_grid(image, draw, episodes, grid_start_y)
        
        # Add season overview at bottom
        if self.config.season_overview:
            overview_y = self.MENU_HEIGHT - self.SAFE_MARGIN_Y - 60
            self._draw_overview(draw, overview_y)
        
        # Save the menu background
        output_path = self.output_dir / "menu_background.png"
        image.save(output_path, "PNG")
        
        logger.info(f"Generated menu background: {output_path}")
        return output_path
    
    def _draw_episode_grid(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        episodes: list[EpisodeThumbnail],
        start_y: int
    ) -> list[tuple[int, int, int, int]]:
        """
        Draw episode thumbnails in a grid layout.
        
        Returns list of button bounding boxes for highlight mask generation.
        """
        button_bounds = []
        
        tw = self.config.thumbnail_width
        th = self.config.thumbnail_height
        padding = self.config.grid_padding
        cols = self.config.grid_columns
        
        # Calculate grid dimensions
        grid_width = cols * tw + (cols - 1) * padding
        start_x = (self.MENU_WIDTH - grid_width) // 2
        
        episode_font = self._get_font(12)
        
        for i, ep in enumerate(episodes[:6]):  # Max 6 episodes per menu page
            row = i // cols
            col = i % cols
            
            x = start_x + col * (tw + padding)
            y = start_y + row * (th + padding + 20)  # Extra space for label
            
            # Draw thumbnail placeholder or actual image
            if ep.thumbnail_image:
                thumb = ep.thumbnail_image.copy()
                thumb = thumb.resize((tw, th), Image.Resampling.LANCZOS)
                image.paste(thumb, (x, y))
            elif ep.thumbnail_path and ep.thumbnail_path.exists():
                thumb = Image.open(ep.thumbnail_path)
                thumb = thumb.resize((tw, th), Image.Resampling.LANCZOS)
                image.paste(thumb, (x, y))
            else:
                # Draw placeholder
                draw.rectangle([x, y, x + tw, y + th], fill=(60, 60, 80), outline=(100, 100, 120))
                # Draw episode number
                num_font = self._get_font(24)
                num_text = f"E{ep.episode_index}"
                num_bbox = draw.textbbox((0, 0), num_text, font=num_font)
                num_x = x + (tw - (num_bbox[2] - num_bbox[0])) // 2
                num_y = y + (th - (num_bbox[3] - num_bbox[1])) // 2
                draw.text((num_x, num_y), num_text, fill=(150, 150, 150), font=num_font)
            
            # Draw episode title below thumbnail
            title_text = f"{ep.episode_index}. {ep.title}"
            if len(title_text) > 20:
                title_text = title_text[:17] + "..."
            
            title_bbox = draw.textbbox((0, 0), title_text, font=episode_font)
            title_width = title_bbox[2] - title_bbox[0]
            title_x = x + (tw - title_width) // 2
            title_y = y + th + 2
            
            draw.text((title_x, title_y), title_text, fill=self.config.text_color, font=episode_font)
            
            # Store button bounds for highlight mask
            button_bounds.append((x, y, x + tw, y + th))
        
        return button_bounds
    
    def _draw_overview(self, draw: ImageDraw.ImageDraw, y: int):
        """Draw season overview text at the bottom of the menu."""
        overview_font = self._get_font(11)
        
        # Wrap text to fit
        max_width = self.MENU_WIDTH - 2 * self.SAFE_MARGIN_X
        wrapped = textwrap.wrap(self.config.season_overview, width=80)
        
        # Only show first 2 lines
        text = '\n'.join(wrapped[:2])
        if len(wrapped) > 2:
            text = text.rstrip() + "..."
        
        draw.multiline_text(
            (self.SAFE_MARGIN_X, y),
            text,
            fill=self.config.subtitle_color,
            font=overview_font,
            spacing=2
        )
    
    def generate_highlight_mask(
        self,
        episodes: list[EpisodeThumbnail],
        start_y: int = 130
    ) -> Path:
        """
        Generate the highlight/selection mask for DVD button navigation.
        
        The highlight mask is a 2-bit indexed image that defines the
        "glow" effect when buttons are selected with a DVD remote.
        
        Args:
            episodes: List of episodes (for button positions)
            start_y: Y position where episode grid starts
            
        Returns:
            Path to generated highlight mask PNG
        """
        # Create transparent image for highlights
        image = Image.new('RGBA', (self.MENU_WIDTH, self.MENU_HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        tw = self.config.thumbnail_width
        th = self.config.thumbnail_height
        padding = self.config.grid_padding
        cols = self.config.grid_columns
        
        grid_width = cols * tw + (cols - 1) * padding
        start_x = (self.MENU_WIDTH - grid_width) // 2
        
        # Draw highlight frames around each episode thumbnail
        for i, ep in enumerate(episodes[:6]):
            row = i // cols
            col = i % cols
            
            x = start_x + col * (tw + padding)
            y = start_y + row * (th + padding + 20)
            
            # Draw highlight frame
            frame_width = 4
            highlight_color = self.config.highlight_color
            
            # Outer glow
            draw.rectangle(
                [x - frame_width, y - frame_width, x + tw + frame_width, y + th + frame_width],
                outline=highlight_color,
                width=frame_width
            )
        
        # Save highlight mask
        output_path = self.output_dir / "menu_highlight.png"
        image.save(output_path, "PNG")
        
        logger.info(f"Generated highlight mask: {output_path}")
        return output_path
    
    def generate_select_mask(
        self,
        episodes: list[EpisodeThumbnail],
        start_y: int = 130
    ) -> Path:
        """
        Generate the selection mask for DVD button press feedback.
        
        Args:
            episodes: List of episodes (for button positions)
            start_y: Y position where episode grid starts
            
        Returns:
            Path to generated select mask PNG
        """
        # Create transparent image for selection
        image = Image.new('RGBA', (self.MENU_WIDTH, self.MENU_HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        tw = self.config.thumbnail_width
        th = self.config.thumbnail_height
        padding = self.config.grid_padding
        cols = self.config.grid_columns
        
        grid_width = cols * tw + (cols - 1) * padding
        start_x = (self.MENU_WIDTH - grid_width) // 2
        
        # Draw selection highlight (brighter than highlight)
        select_color = (255, 255, 255, 255)
        
        for i, ep in enumerate(episodes[:6]):
            row = i // cols
            col = i % cols
            
            x = start_x + col * (tw + padding)
            y = start_y + row * (th + padding + 20)
            
            # Draw selection frame (thicker)
            frame_width = 6
            draw.rectangle(
                [x - frame_width, y - frame_width, x + tw + frame_width, y + th + frame_width],
                outline=select_color,
                width=frame_width
            )
        
        # Save select mask
        output_path = self.output_dir / "menu_select.png"
        image.save(output_path, "PNG")
        
        logger.info(f"Generated select mask: {output_path}")
        return output_path
    
    def generate_menu_video(
        self,
        background_path: Path,
        audio_path: Optional[Path] = None,
        duration: int = 30
    ) -> Path:
        """
        Generate a looping menu video with optional audio.
        
        Args:
            background_path: Path to menu background image
            audio_path: Path to theme song audio (optional)
            duration: Duration of menu loop in seconds
            
        Returns:
            Path to generated menu MPEG video
        """
        output_path = self.output_dir / "menu.mpg"
        
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
                "-af", f"afade=t=out:st={duration-2}:d=2",  # Fade out audio
            ])
        
        cmd.extend([
            "-c:v", "mpeg2video",
            "-b:v", "5000k",
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
        
        logger.debug(f"Running: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise MenuBuilderError(f"Failed to generate menu video: {result.stderr}")
        
        logger.info(f"Generated menu video: {output_path}")
        return output_path
    
    def generate_dvdauthor_xml(
        self,
        video_files: list[Path],
        menu_video_path: Path,
        highlight_path: Path,
        select_path: Path,
        output_path: Optional[Path] = None
    ) -> Path:
        """
        Generate dvdauthor XML configuration for DVD structure.
        
        Args:
            video_files: List of transcoded episode MPEG files
            menu_video_path: Path to menu video
            highlight_path: Path to highlight mask
            select_path: Path to select mask
            output_path: Output path for XML file
            
        Returns:
            Path to generated XML file
        """
        if output_path is None:
            output_path = self.output_dir / "dvdauthor.xml"
        
        # Generate button coordinates
        tw = self.config.thumbnail_width
        th = self.config.thumbnail_height
        padding = self.config.grid_padding
        cols = self.config.grid_columns
        start_y = 130
        
        grid_width = cols * tw + (cols - 1) * padding
        start_x = (self.MENU_WIDTH - grid_width) // 2
        
        buttons_xml = []
        num_episodes = min(len(video_files), 6)
        
        for i in range(num_episodes):
            row = i // cols
            col = i % cols
            
            x0 = start_x + col * (tw + padding)
            y0 = start_y + row * (th + padding + 20)
            x1 = x0 + tw
            y1 = y0 + th
            
            # Navigation: up, down, left, right
            up = i - cols if i >= cols else i
            down = i + cols if i + cols < num_episodes else i
            left = i - 1 if col > 0 else i
            right = i + 1 if col < cols - 1 and i + 1 < num_episodes else i
            
            buttons_xml.append(f'''      <button name="button{i+1}" x0="{x0}" y0="{y0}" x1="{x1}" y1="{y1}"
              up="button{up+1}" down="button{down+1}" left="button{left+1}" right="button{right+1}">
        jump title {i+1};
      </button>''')
        
        # Build video list for titleset
        vob_entries = []
        for i, vf in enumerate(video_files):
            chapters = "0"  # Chapter at start
            vob_entries.append(f'      <vob file="{vf}" chapters="{chapters}" />')
        
        xml_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<dvdauthor dest="{self.output_dir / 'DVD'}">
  <vmgm>
    <menus>
      <pgc>
        <vob file="{menu_video_path}" pause="inf" />
        <button name="button1">jump titleset 1 title 1;</button>
      </pgc>
    </menus>
  </vmgm>
  
  <titleset>
    <menus>
      <video format="ntsc" aspect="16:9" />
      <pgc>
        <vob file="{menu_video_path}" pause="inf" />
        <subpicture>
          <stream id="0" mode="highlight">
            <highlight file="{highlight_path}" />
            <select file="{select_path}" />
          </stream>
        </subpicture>
{chr(10).join(buttons_xml)}
      </pgc>
    </menus>
    
    <titles>
      <video format="ntsc" aspect="16:9" />
      <audio format="ac3" channels="2" />
      <pgc>
{chr(10).join(vob_entries)}
        <post>call vmgm menu;</post>
      </pgc>
    </titles>
  </titleset>
</dvdauthor>
'''
        
        output_path.write_text(xml_content)
        logger.info(f"Generated dvdauthor XML: {output_path}")
        return output_path
    
    def build_dvd_structure(
        self,
        dvdauthor_xml: Path,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Path:
        """
        Run dvdauthor to build the DVD file structure.
        
        Args:
            dvdauthor_xml: Path to dvdauthor XML configuration
            progress_callback: Optional callback for status updates
            
        Returns:
            Path to DVD structure directory
        """
        dvdauthor_path = shutil.which("dvdauthor")
        if not dvdauthor_path:
            raise DVDAuthorNotFoundError(
                "dvdauthor not found. Please install:\n"
                "  Ubuntu/Debian: sudo apt install dvdauthor\n"
                "  macOS: brew install dvdauthor"
            )
        
        dvd_dir = self.output_dir / "DVD"
        dvd_dir.mkdir(parents=True, exist_ok=True)
        
        if progress_callback:
            progress_callback("Building DVD structure...")
        
        # Run dvdauthor
        cmd = [dvdauthor_path, "-x", str(dvdauthor_xml)]
        
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
        "pillow": True,  # We've already imported it
    }


def main():
    """Test menu builder module."""
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    print("Checking menu builder dependencies...")
    deps = check_menu_dependencies()
    
    for dep, available in deps.items():
        status = "✓" if available else "✗"
        print(f"  {status} {dep}")
    
    # Create test menu
    print("\nGenerating test menu...")
    
    config = MenuConfig(
        style=MenuStyle.MODERN,
        title="Test Series - Season 1",
        season_overview="This is a test season overview that describes the plot of this season. "
                       "It should be displayed at the bottom of the menu."
    )
    
    builder = MenuBuilder(Path("/tmp/jellydisc_menu_test"), config)
    
    # Create test episodes
    episodes = [
        EpisodeThumbnail(1, "Pilot Episode"),
        EpisodeThumbnail(2, "The Second One"),
        EpisodeThumbnail(3, "Episode Three"),
        EpisodeThumbnail(4, "The Fourth Hour"),
        EpisodeThumbnail(5, "Five Alive"),
        EpisodeThumbnail(6, "Six of Hearts"),
    ]
    
    try:
        bg_path = builder.generate_menu_background(episodes=episodes)
        print(f"  Generated: {bg_path}")
        
        hl_path = builder.generate_highlight_mask(episodes)
        print(f"  Generated: {hl_path}")
        
        sel_path = builder.generate_select_mask(episodes)
        print(f"  Generated: {sel_path}")
        
        print("\nMenu assets generated successfully!")
        print(f"Output directory: {builder.output_dir}")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
