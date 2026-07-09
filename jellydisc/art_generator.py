"""
Art Generator Module

This module generates printable DVD box cover art (front, spine, and back)
and an episode folio/booklet PDF with details for each episode.
Uses Pillow to layout high-resolution (300 DPI) templates.
"""

import logging
import textwrap
from pathlib import Path
from typing import Optional, List
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger(__name__)

# DVD Cover Dimensions at 300 DPI
# Standard DVD case: 273mm x 183mm
# Front cover: 129.5mm, Spine: 14mm, Back cover: 129.5mm
# Width: (273 / 25.4) * 300 = 3224 pixels
# Height: (183 / 25.4) * 300 = 2161 pixels
# Spine Width: (14 / 25.4) * 300 = 166 pixels
# Front/Back Width: (129.5 / 25.4) * 300 = 1529 pixels
COV_WIDTH = 3224
COV_HEIGHT = 2161
COV_SPINE = 166
COV_PAGE = 1529  # Back/Front cover width

# DVD Booklet / Folio Page Dimensions at 300 DPI
# Standard insert booklet: 120mm x 180mm
# Width: (120 / 25.4) * 300 = 1417 pixels
# Height: (180 / 25.4) * 300 = 2126 pixels
BK_WIDTH = 1417
BK_HEIGHT = 2126


class ArtGenerator:
    """Generates printable DVD box covers and episode booklet PDFs."""

    def __init__(self, assets_dir: Path):
        self.assets_dir = Path(assets_dir)
        self.font_bold_path = self._find_font(bold=True)
        self.font_reg_path = self._find_font(bold=False)

    def _find_font(self, bold: bool = False) -> Optional[str]:
        """Find a suitable system font."""
        # Check local assets folder first
        local_font = self.assets_dir / ("font.ttf" if bold else "font_reg.ttf")
        if local_font.exists():
            return str(local_font)
        
        # Check parent folder assets (standard fallback for menu builder)
        parent_font = self.assets_dir.parent / "assets" / "font.ttf"
        if parent_font.exists() and bold:
            return str(parent_font)

        if bold:
            font_paths = [
                "/System/Library/Fonts/Supplemental/HelveticaNeue-Bold.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
                "C:\\Windows\\Fonts\\arialbd.ttf",
                "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
            ]
        else:
            font_paths = [
                "/System/Library/Fonts/Supplemental/HelveticaNeue.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
                "C:\\Windows\\Fonts\\arial.ttf",
                "/usr/share/fonts/TTF/DejaVuSans.ttf",
            ]

        for path in font_paths:
            if Path(path).exists():
                return path
        return None

    def _get_font(self, bold: bool, size: int) -> ImageFont.FreeTypeFont:
        """Helper to load font at specific size with fallback."""
        path = self.font_bold_path if bold else self.font_reg_path
        try:
            if path:
                return ImageFont.truetype(path, size)
        except Exception as e:
            logger.warning(f"Could not load font {path}: {e}")
        return ImageFont.load_default()

    def _wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> List[str]:
        """Wrap text to fit within a maximum pixel width."""
        if not text:
            return []
        words = text.split(' ')
        lines = []
        current_line = []
        for word in words:
            # Handle manual newlines
            if '\n' in word:
                parts = word.split('\n')
                for idx, part in enumerate(parts):
                    test_line = ' '.join(current_line + [part])
                    try:
                        w = draw.textlength(test_line, font=font)
                    except AttributeError:
                        try:
                            w, _ = draw.textsize(test_line, font=font)
                        except AttributeError:
                            bbox = font.getbbox(test_line)
                            w = bbox[2] - bbox[0]
                    
                    if w <= max_width:
                        current_line.append(part)
                    else:
                        if current_line:
                            lines.append(' '.join(current_line))
                            current_line = [part]
                        else:
                            lines.append(part)
                    
                    if idx < len(parts) - 1:
                        if current_line:
                            lines.append(' '.join(current_line))
                            current_line = []
            else:
                test_line = ' '.join(current_line + [word])
                try:
                    w = draw.textlength(test_line, font=font)
                except AttributeError:
                    try:
                        w, _ = draw.textsize(test_line, font=font)
                    except AttributeError:
                        bbox = font.getbbox(test_line)
                        w = bbox[2] - bbox[0]
                
                if w <= max_width:
                    current_line.append(word)
                else:
                    if current_line:
                        lines.append(' '.join(current_line))
                        current_line = [word]
                    else:
                        lines.append(word)
                        
        if current_line:
            lines.append(' '.join(current_line))
        return lines

    def _resize_to_cover(self, img: Image.Image, target_w: int, target_h: int) -> Image.Image:
        """Resize and crop image to fill target dimensions (aspect cover)."""
        img_w, img_h = img.size
        aspect_target = target_w / target_h
        aspect_img = img_w / img_h

        if aspect_img > aspect_target:
            # Image is wider than target aspect ratio
            new_h = target_h
            new_w = int(img_w * (target_h / img_h))
            img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            # Crop horizontal sides
            start_x = (new_w - target_w) // 2
            return img_resized.crop((start_x, 0, start_x + target_w, target_h))
        else:
            # Image is taller than target aspect ratio
            new_w = target_w
            new_h = int(img_h * (target_w / img_w))
            img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            # Crop vertical top/bottom
            start_y = (new_h - target_h) // 2
            return img_resized.crop((0, start_y, target_w, start_y + target_h))

    def generate_dvd_wrap(self, 
                          series_name: str,
                          season_name: str,
                          overview: str,
                          episodes: list,
                          backdrop_path: Optional[Path],
                          logo_path: Optional[Path],
                          season_poster_path: Optional[Path],
                          output_path: Path) -> Path:
        """
        Generate a printable DVD case cover wrap (back, spine, and front).
        Saves as a high-quality PDF at 300 DPI.
        """
        logger.info(f"Generating DVD Cover Wrap for {series_name}...")
        
        # Base canvas (RGBA for transparency support)
        canvas = Image.new('RGBA', (COV_WIDTH, COV_HEIGHT), (15, 15, 25, 255))
        draw = ImageDraw.Draw(canvas)
        
        # 1. FRONT COVER (Right Side: x = 1695 to 3224)
        front_x = COV_PAGE + COV_SPINE
        if season_poster_path and season_poster_path.exists():
            try:
                poster = Image.open(season_poster_path)
                poster_resized = self._resize_to_cover(poster, COV_PAGE, COV_HEIGHT)
                canvas.paste(poster_resized, (front_x, 0))
            except Exception as e:
                logger.error(f"Failed to draw season poster on front cover: {e}")
        elif backdrop_path and backdrop_path.exists():
            try:
                # Fallback to cropped backdrop
                bd = Image.open(backdrop_path)
                bd_resized = self._resize_to_cover(bd, COV_PAGE, COV_HEIGHT)
                canvas.paste(bd_resized, (front_x, 0))
            except Exception as e:
                logger.error(f"Failed to draw backdrop on front cover: {e}")
                
        # Draw series logo or text title on front cover
        logo_drawn = False
        if logo_path and logo_path.exists():
            try:
                logo = Image.open(logo_path).convert('RGBA')
                # Scale logo to fit front cover nicely (max width 1000, max height 400)
                logo.thumbnail((1000, 400), Image.Resampling.LANCZOS)
                lw, lh = logo.size
                lx = front_x + (COV_PAGE - lw) // 2
                ly = 250
                canvas.paste(logo, (lx, ly), logo)
                logo_drawn = True
            except Exception as e:
                logger.error(f"Failed to paste logo on front cover: {e}")

        # Draw series name text if logo failed or doesn't exist
        if not logo_drawn:
            font_title = self._get_font(bold=True, size=80)
            title_lines = self._wrap_text(series_name.upper(), font_title, COV_PAGE - 200, draw)
            y_offset = 300
            for line in title_lines:
                try:
                    lw = draw.textlength(line, font=font_title)
                except AttributeError:
                    lw = draw.textsize(line, font=font_title)[0]
                lx = front_x + (COV_PAGE - int(lw)) // 2
                # Draw subtle shadow
                draw.text((lx + 4, y_offset + 4), line, fill=(0, 0, 0, 200), font=font_title)
                draw.text((lx, y_offset), line, fill=(255, 255, 255, 255), font=font_title)
                y_offset += 100

        # Draw season name on front cover (lower-middle)
        font_season = self._get_font(bold=True, size=55)
        season_str = season_name.upper()
        try:
            sw = draw.textlength(season_str, font=font_season)
        except AttributeError:
            sw = draw.textsize(season_str, font=font_season)[0]
        sx = front_x + (COV_PAGE - int(sw)) // 2
        sy = 1600
        
        # Transparent background band behind season title for readability
        band_h = 130
        band = Image.new('RGBA', (COV_PAGE, band_h), (0, 0, 0, 160))
        canvas.paste(band, (front_x, sy - 30), band)
        
        # Draw season text
        draw.text((sx + 3, sy + 3), season_str, fill=(0, 0, 0, 220), font=font_season)
        draw.text((sx, sy), season_str, fill=(255, 215, 0, 255), font=font_season)  # Gold

        # Small "DVD VIDEO" format badge at bottom
        font_badge = self._get_font(bold=True, size=24)
        badge_text = "DVD VIDEO"
        try:
            bw = draw.textlength(badge_text, font=font_badge)
        except AttributeError:
            bw = draw.textsize(badge_text, font=font_badge)[0]
        bx = front_x + (COV_PAGE - int(bw)) // 2
        draw.text((bx, 2000), badge_text, fill=(200, 200, 200, 255), font=font_badge)


        # 2. SPINE (Middle: x = 1529 to 1695)
        # Background: Grab vertical strip from backdrop (or use solid dark slate)
        spine_color = (25, 25, 38, 255)
        if backdrop_path and backdrop_path.exists():
            try:
                bd = Image.open(backdrop_path)
                bd_w, bd_h = bd.size
                # Crop a slice from center-left of backdrop
                slice_w = int(bd_h * (COV_SPINE / COV_HEIGHT))
                slice_x = max(0, (bd_w - slice_w) // 2)
                bd_slice = bd.crop((slice_x, 0, slice_x + slice_w, bd_h))
                bd_slice_resized = bd_slice.resize((COV_SPINE, COV_HEIGHT), Image.Resampling.LANCZOS)
                # Blur and darken
                bd_slice_blurred = bd_slice_resized.filter(ImageFilter.GaussianBlur(15))
                canvas.paste(bd_slice_blurred, (COV_PAGE, 0))
                # Semi-transparent overlay to darken
                overlay = Image.new('RGBA', (COV_SPINE, COV_HEIGHT), (0, 0, 0, 100))
                canvas.paste(overlay, (COV_PAGE, 0), overlay)
            except Exception as e:
                logger.error(f"Failed to generate textured spine background: {e}")
                draw.rectangle([(COV_PAGE, 0), (COV_PAGE + COV_SPINE, COV_HEIGHT)], fill=spine_color)
        else:
            draw.rectangle([(COV_PAGE, 0), (COV_PAGE + COV_SPINE, COV_HEIGHT)], fill=spine_color)

        # Draw rotated Spine Text (Series Name - Season Name)
        # Create separate image, draw text, rotate 270 deg (top-to-bottom)
        spine_font = self._get_font(bold=True, size=48)
        spine_text_str = f"{series_name.upper()}  —  {season_name.upper()}"
        
        # Temp image (width is length of spine text, height is spine thickness)
        text_img = Image.new('RGBA', (1600, COV_SPINE), (0, 0, 0, 0))
        text_draw = ImageDraw.Draw(text_img)
        try:
            tw = text_draw.textlength(spine_text_str, font=spine_font)
        except AttributeError:
            tw = text_draw.textsize(spine_text_str, font=spine_font)[0]
            
        # Draw centered
        tx = (1600 - int(tw)) // 2
        ty = (COV_SPINE - 60) // 2
        text_draw.text((tx, ty), spine_text_str, fill=(255, 255, 255, 240), font=spine_font)
        
        # Rotate 270 degrees
        rotated_text = text_img.rotate(270, expand=True)
        # Paste centered vertically on spine (y starts at (2161 - 1600)//2 = 280)
        canvas.paste(rotated_text, (COV_PAGE, 280), rotated_text)

        # Draw DVD format logo rotated at the bottom of spine
        dvd_badge_img = Image.new('RGBA', (200, COV_SPINE), (0, 0, 0, 0))
        dvd_badge_draw = ImageDraw.Draw(dvd_badge_img)
        dvd_badge_font = self._get_font(bold=True, size=24)
        try:
            dbw = dvd_badge_draw.textlength("DVD", font=dvd_badge_font)
        except AttributeError:
            dbw = dvd_badge_draw.textsize("DVD", font=dvd_badge_font)[0]
        dvd_badge_draw.text(((200 - int(dbw))//2, (COV_SPINE - 30)//2), "DVD", fill=(180, 180, 180, 255), font=dvd_badge_font)
        rotated_dvd = dvd_badge_img.rotate(270, expand=True)
        canvas.paste(rotated_dvd, (COV_PAGE, 1850), rotated_dvd)


        # 3. BACK COVER (Left Side: x = 0 to 1529)
        # Background: Heavy blurred backdrop with dark overlay
        if backdrop_path and backdrop_path.exists():
            try:
                bd = Image.open(backdrop_path)
                bd_resized = self._resize_to_cover(bd, COV_PAGE, COV_HEIGHT)
                bd_blurred = bd_resized.filter(ImageFilter.GaussianBlur(25))
                canvas.paste(bd_blurred, (0, 0))
            except Exception as e:
                logger.error(f"Failed to draw back cover blurred bg: {e}")
        
        # Darkening glass layer on back cover
        glass_overlay = Image.new('RGBA', (COV_PAGE, COV_HEIGHT), (12, 12, 20, 210))
        canvas.paste(glass_overlay, (0, 0), glass_overlay)
        
        # Safe margins for back cover
        margin = 100
        text_w = COV_PAGE - (2 * margin)
        
        # Draw Header (Title & Season)
        y_offset = 120
        font_back_title = self._get_font(bold=True, size=52)
        draw.text((margin, y_offset), series_name, fill=(255, 255, 255, 255), font=font_back_title)
        
        y_offset += 65
        font_back_season = self._get_font(bold=True, size=36)
        draw.text((margin, y_offset), season_name, fill=(255, 215, 0, 255), font=font_back_season)
        
        # Draw thin separator line
        y_offset += 60
        draw.line([(margin, y_offset), (COV_PAGE - margin, y_offset)], fill=(255, 255, 255, 40), width=3)
        
        # Draw Season Overview / Synopsis
        y_offset += 40
        font_overview = self._get_font(bold=False, size=24)
        overview_wrapped = self._wrap_text(overview, font_overview, text_w, draw)
        
        # Show up to 8 lines of overview
        for line in overview_wrapped[:8]:
            draw.text((margin, y_offset), line, fill=(230, 230, 240, 255), font=font_overview)
            y_offset += 32
            
        if len(overview_wrapped) > 8:
            draw.text((margin, y_offset), "...", fill=(230, 230, 240, 255), font=font_overview)
            y_offset += 32
            
        # Draw "EPISODE SELECTION" header
        y_offset += 50
        font_ep_header = self._get_font(bold=True, size=28)
        draw.text((margin, y_offset), "EPISODES", fill=(255, 255, 255, 255), font=font_ep_header)
        
        y_offset += 45
        font_ep_item = self._get_font(bold=False, size=22)
        
        # Layout episodes in columns
        max_per_col = 8
        col_w = text_w // 2
        
        for idx, ep in enumerate(episodes[:16]):  # Display up to 16 episodes on cover
            col = idx // max_per_col
            row = idx % max_per_col
            
            ex = margin + (col * col_w)
            ey = y_offset + (row * 36)
            
            runtime = f" ({int(ep.runtime_minutes)}m)" if getattr(ep, "runtime_minutes", 0) > 0 else ""
            ep_text = f"{ep.index_number:02d}. {ep.name}{runtime}"
            
            # Truncate episode text if too long
            try:
                ep_len = draw.textlength(ep_text, font=font_ep_item)
            except AttributeError:
                ep_len = draw.textsize(ep_text, font=font_ep_item)[0]
                
            if ep_len > col_w - 40:
                # Simple truncation
                while ep_len > col_w - 60 and len(ep_text) > 5:
                    ep_text = ep_text[:-2]
                    try:
                        ep_len = draw.textlength(ep_text + "...", font=font_ep_item)
                    except AttributeError:
                        ep_len = draw.textsize(ep_text + "...", font=font_ep_item)[0]
                ep_text += "..."
                
            draw.text((ex, ey), ep_text, fill=(200, 200, 205, 255), font=font_ep_item)
            
        # Draw 3 Episode Thumbnails in a nice strip (above tech specs)
        thumb_y = 1590
        thumb_w = 360
        thumb_h = 203  # 16:9 ratio
        
        # Gather thumb paths from assets if available
        thumbs_found = []
        for ep in episodes:
            t_path = self.assets_dir / f"ep_{ep.index_number}_thumb.jpg"
            if t_path.exists():
                thumbs_found.append(t_path)
            if len(thumbs_found) >= 3:
                break
                
        if len(thumbs_found) > 0:
            spacing = (text_w - (len(thumbs_found) * thumb_w)) // (len(thumbs_found) + 1)
            for t_idx, t_path in enumerate(thumbs_found):
                tx = margin + spacing + (t_idx * (thumb_w + spacing))
                try:
                    t_img = Image.open(t_path)
                    t_resized = self._resize_to_cover(t_img, thumb_w, thumb_h)
                    
                    # Draw a nice frame border
                    draw.rectangle([(tx - 4, thumb_y - 4), (tx + thumb_w + 4, thumb_y + thumb_h + 4)], outline=(255, 255, 255, 80), width=4)
                    canvas.paste(t_resized, (tx, thumb_y))
                except Exception as e:
                    logger.error(f"Failed to place back cover thumbnail {t_idx}: {e}")

        # Technical Specs Bar at bottom
        specs_y = 1910
        draw.rectangle([(margin, specs_y), (COV_PAGE - margin, specs_y + 100)], fill=(0, 0, 0, 100), outline=(255, 255, 255, 30), width=2)
        
        specs_text = "NTSC  |  MPEG-2  |  COLOR  |  DOLBY DIGITAL STEREO  |  16:9 ANAMORPHIC  |  REGION 0  |  DVD-9"
        font_specs = self._get_font(bold=True, size=20)
        try:
            spec_w = draw.textlength(specs_text, font=font_specs)
        except AttributeError:
            spec_w = draw.textsize(specs_text, font=font_specs)[0]
            
        sp_x = margin + (text_w - int(spec_w)) // 2
        sp_y = specs_y + 36
        draw.text((sp_x, sp_y), specs_text, fill=(150, 150, 160, 255), font=font_specs)
        
        # Save as single-page PDF
        # PDF format requires converting to RGB first
        final_pdf_path = output_path
        rgb_canvas = canvas.convert('RGB')
        
        # Save with DPI metadata for accurate physical printing
        rgb_canvas.save(final_pdf_path, 'PDF', resolution=300.0)
        logger.info(f"✓ DVD Cover Wrap PDF generated successfully at: {final_pdf_path}")
        return final_pdf_path

    def generate_episode_folio(self,
                               series_name: str,
                               season_name: str,
                               overview: str,
                               episodes: list,
                               backdrop_path: Optional[Path],
                               logo_path: Optional[Path],
                               output_path: Path,
                               actors: Optional[List[str]] = None) -> Path:
        """
        Generate a multi-page printable folio / insert booklet detailing each episode.
        Saves as a multi-page PDF at 300 DPI.
        """
        logger.info(f"Generating Episode Folio booklet for {series_name}...")
        pages = []
        
        # --- PAGE 1: COVER PAGE ---
        cov_img = Image.new('RGB', (BK_WIDTH, BK_HEIGHT), (15, 15, 25))
        c_draw = ImageDraw.Draw(cov_img)
        
        if backdrop_path and backdrop_path.exists():
            try:
                bd = Image.open(backdrop_path)
                bd_resized = self._resize_to_cover(bd, BK_WIDTH, BK_HEIGHT)
                # Apply blur
                bd_blur = bd_resized.filter(ImageFilter.GaussianBlur(15))
                cov_img.paste(bd_blur, (0, 0))
            except Exception as e:
                logger.error(f"Failed to load cover backdrop: {e}")
                
        # Draw transparent dark sheet on cover page
        sheet = Image.new('RGBA', (BK_WIDTH, BK_HEIGHT), (0, 0, 0, 160))
        cov_img.paste(sheet, (0, 0), sheet)
        
        # Cover Content
        # Logo or Title
        logo_drawn = False
        if logo_path and logo_path.exists():
            try:
                logo = Image.open(logo_path).convert('RGBA')
                logo.thumbnail((900, 350), Image.Resampling.LANCZOS)
                lw, lh = logo.size
                lx = (BK_WIDTH - lw) // 2
                ly = 350
                cov_img.paste(logo, (lx, ly), logo)
                logo_drawn = True
            except Exception as e:
                logger.error(f"Cover logo paste failed: {e}")
                
        if not logo_drawn:
            font_title = self._get_font(bold=True, size=75)
            lines = self._wrap_text(series_name.upper(), font_title, BK_WIDTH - 200, c_draw)
            y_off = 400
            for line in lines:
                try:
                    lw = c_draw.textlength(line, font=font_title)
                except AttributeError:
                    lw = c_draw.textsize(line, font=font_title)[0]
                lx = (BK_WIDTH - int(lw)) // 2
                c_draw.text((lx, y_off), line, fill=(255, 255, 255), font=font_title)
                y_off += 95
                
        # Season Name
        font_season = self._get_font(bold=True, size=48)
        season_str = season_name.upper()
        try:
            sw = c_draw.textlength(season_str, font=font_season)
        except AttributeError:
            sw = c_draw.textsize(season_str, font=font_season)[0]
        c_draw.text(((BK_WIDTH - int(sw)) // 2, 1000), season_str, fill=(255, 215, 0), font=font_season)
        
        # Subtitle: EPISODE GUIDE
        font_sub = self._get_font(bold=True, size=32)
        guide_text = "E P I S O D E   G U I D E"
        try:
            gw = c_draw.textlength(guide_text, font=font_sub)
        except AttributeError:
            gw = c_draw.textsize(guide_text, font=font_sub)[0]
        c_draw.text(((BK_WIDTH - int(gw)) // 2, 1120), guide_text, fill=(200, 200, 200), font=font_sub)
        
        # Draw a beautiful decorative frame outline
        c_draw.rectangle([(80, 80), (BK_WIDTH - 80, BK_HEIGHT - 80)], outline=(255, 215, 0, 100), width=4)
        c_draw.rectangle([(95, 95), (BK_WIDTH - 95, BK_HEIGHT - 95)], outline=(255, 255, 255, 30), width=1)
        
        # Bottom details
        bot_text = "JellyDisc DVD Authoring Suite"
        font_bot = self._get_font(bold=False, size=22)
        try:
            bw = c_draw.textlength(bot_text, font=font_bot)
        except AttributeError:
            bw = c_draw.textsize(bot_text, font=font_bot)[0]
        c_draw.text(((BK_WIDTH - int(bw)) // 2, 1850), bot_text, fill=(130, 130, 140), font=font_bot)
        
        pages.append(cov_img)
        
        # --- INSIDE PAGES: EPISODES (2 episodes per page) ---
        # Fonts for episode layouts
        font_ep_title = self._get_font(bold=True, size=32)
        font_ep_meta = self._get_font(bold=True, size=22)
        font_ep_desc = self._get_font(bold=False, size=22)
        
        ep_idx = 0
        total_eps = len(episodes)
        
        while ep_idx < total_eps:
            # Create a new inside page
            page_img = Image.new('RGB', (BK_WIDTH, BK_HEIGHT), (20, 20, 30))
            p_draw = ImageDraw.Draw(page_img)
            
            # Subtle top/bottom header/footer rule
            p_draw.line([(100, 100), (BK_WIDTH - 100, 100)], fill=(255, 255, 255, 30), width=2)
            p_draw.line([(100, BK_HEIGHT - 100), (BK_WIDTH - 100, BK_HEIGHT - 100)], fill=(255, 255, 255, 30), width=2)
            
            # Running header
            header_txt = f"{series_name.upper()}  |  {season_name.upper()}"
            font_hdr = self._get_font(bold=True, size=18)
            p_draw.text((100, 60), header_txt, fill=(150, 150, 160), font=font_hdr)
            
            # Page number
            p_num_txt = f"Page {len(pages) + 1}"
            try:
                pnw = p_draw.textlength(p_num_txt, font=font_hdr)
            except AttributeError:
                pnw = p_draw.textsize(p_num_txt, font=font_hdr)[0]
            p_draw.text((BK_WIDTH - 100 - int(pnw), 60), p_num_txt, fill=(150, 150, 160), font=font_hdr)
            
            # Process up to 2 episodes on this page
            # Episode 1 layout: y_start = 160, y_end = 1060
            # Episode 2 layout: y_start = 1110, y_end = 2010
            for slot in range(2):
                if ep_idx >= total_eps:
                    break
                    
                ep = episodes[ep_idx]
                y_start = 160 if slot == 0 else 1110
                
                # Draw Episode Thumbnail on the Left, details on the Right
                thumb_w = 400
                thumb_h = 225  # 16:9
                thumb_x = 100
                thumb_y = y_start + 40
                
                # Draw white frame border for thumbnail
                p_draw.rectangle([(thumb_x - 3, thumb_y - 3), (thumb_x + thumb_w + 3, thumb_y + thumb_h + 3)], outline=(255, 255, 255, 60), width=3)
                
                t_path = self.assets_dir / f"ep_{ep.index_number}_thumb.jpg"
                if t_path.exists():
                    try:
                        t_img = Image.open(t_path)
                        t_resized = self._resize_to_cover(t_img, thumb_w, thumb_h)
                        page_img.paste(t_resized, (thumb_x, thumb_y))
                    except Exception as e:
                        logger.error(f"Folio: failed to paste thumbnail for E{ep.index_number}: {e}")
                        p_draw.rectangle([(thumb_x, thumb_y), (thumb_x + thumb_w, thumb_y + thumb_h)], fill=(40, 40, 60))
                else:
                    # Draw a nice grey placeholder box
                    p_draw.rectangle([(thumb_x, thumb_y), (thumb_x + thumb_w, thumb_y + thumb_h)], fill=(40, 40, 60))
                    
                # Text Info on the Right of thumbnail
                info_x = thumb_x + thumb_w + 50
                info_w = BK_WIDTH - info_x - 100
                
                # Title: "E01. Pilot"
                title_str = f"E{ep.index_number:02d}. {ep.name}"
                title_lines = self._wrap_text(title_str, font_ep_title, info_w, p_draw)
                ty = y_offset = y_start + 35
                
                for line in title_lines[:2]: # Max 2 lines for title
                    p_draw.text((info_x, ty), line, fill=(255, 255, 255), font=font_ep_title)
                    ty += 40
                    
                # Metadata (Runtime)
                runtime = f"{int(ep.runtime_minutes)} minutes" if getattr(ep, "runtime_minutes", 0) > 0 else "N/A"
                meta_str = f"Runtime: {runtime}"
                p_draw.text((info_x, ty + 10), meta_str, fill=(255, 215, 0), font=font_ep_meta)
                
                # Description underneath
                desc_y = thumb_y + thumb_h + 40
                desc_w = BK_WIDTH - 200
                
                # Retrieve and clean overview
                ep_overview = ep.overview or "No episode description available."
                desc_wrapped = self._wrap_text(ep_overview, font_ep_desc, desc_w, p_draw)
                
                dy = desc_y
                max_desc_lines = 11 if slot == 0 else 11
                for line in desc_wrapped[:max_desc_lines]:
                    p_draw.text((100, dy), line, fill=(210, 210, 220), font=font_ep_desc)
                    dy += 32
                    
                if len(desc_wrapped) > max_desc_lines:
                    p_draw.text((100, dy), "...", fill=(210, 210, 220), font=font_ep_desc)
                
                # Draw separator line between slot 0 and slot 1
                if slot == 0 and ep_idx + 1 < total_eps:
                    p_draw.line([(150, 1080), (BK_WIDTH - 150, 1080)], fill=(255, 255, 255, 20), width=1)
                    
                ep_idx += 1
                
            pages.append(page_img)
            
        # --- LAST PAGE: CAST / CREDITS ---
        credit_img = Image.new('RGB', (BK_WIDTH, BK_HEIGHT), (15, 15, 25))
        cr_draw = ImageDraw.Draw(credit_img)
        
        # Frame border
        cr_draw.rectangle([(80, 80), (BK_WIDTH - 80, BK_HEIGHT - 80)], outline=(255, 255, 255, 20), width=2)
        
        y_off = 180
        font_c_title = self._get_font(bold=True, size=46)
        cr_draw.text((150, y_off), "CAST & CREW", fill=(255, 215, 0), font=font_c_title)
        
        y_off += 65
        cr_draw.line([(150, y_off), (BK_WIDTH - 150, y_off)], fill=(255, 255, 255, 30), width=2)
        
        y_off += 60
        font_c_item = self._get_font(bold=False, size=24)
        font_c_label = self._get_font(bold=True, size=24)
        
        if actors:
            # Layout cast in two columns
            cr_col_w = (BK_WIDTH - 300) // 2
            for a_idx, actor in enumerate(actors[:24]):  # Limit to 24 actors
                col = a_idx % 2
                row = a_idx // 2
                
                ax = 150 + (col * cr_col_w)
                ay = y_off + (row * 50)
                
                # Print actor
                actor_txt = f"•  {actor}"
                # Truncate if needed
                try:
                    al = cr_draw.textlength(actor_txt, font=font_c_item)
                except AttributeError:
                    al = cr_draw.textsize(actor_txt, font=font_c_item)[0]
                if al > cr_col_w - 30:
                    while al > cr_col_w - 50 and len(actor_txt) > 5:
                        actor_txt = actor_txt[:-2]
                        try:
                            al = cr_draw.textlength(actor_txt + "...", font=font_c_item)
                        except AttributeError:
                            al = cr_draw.textsize(actor_txt + "...", font=font_c_item)[0]
                    actor_txt += "..."
                cr_draw.text((ax, ay), actor_txt, fill=(230, 230, 240), font=font_c_item)
        else:
            cr_draw.text((150, y_off), "No cast information available.", fill=(180, 180, 180), font=font_c_item)
            
        # Draw a beautiful summary note at the bottom
        note_y = 1600
        cr_draw.line([(150, note_y), (BK_WIDTH - 150, note_y)], fill=(255, 255, 255, 20), width=1)
        
        note_str = "This season was compiled, transcoded, and authored using the JellyDisc DVD Authoring Suite. All titles, episode information, and cover artwork are sourced directly from your Jellyfin server library."
        font_note = self._get_font(bold=False, size=20)
        note_wrapped = self._wrap_text(note_str, font_note, BK_WIDTH - 300, cr_draw)
        
        ny = note_y + 40
        for line in note_wrapped:
            try:
                nw = cr_draw.textlength(line, font=font_note)
            except AttributeError:
                nw = cr_draw.textsize(line, font=font_note)[0]
            nx = (BK_WIDTH - int(nw)) // 2
            cr_draw.text((nx, ny), line, fill=(140, 140, 150), font=font_note)
            ny += 30
            
        pages.append(credit_img)
        
        # Save as multi-page PDF
        final_pdf_path = output_path
        # PDF format requires converting to RGB (they are already RGB, but safety check)
        rgb_pages = [p.convert('RGB') for p in pages]
        
        rgb_pages[0].save(
            final_pdf_path, 
            'PDF', 
            save_all=True, 
            append_images=rgb_pages[1:], 
            resolution=300.0
        )
        logger.info(f"✓ Episode Folio PDF generated successfully at: {final_pdf_path}")
        return final_pdf_path
