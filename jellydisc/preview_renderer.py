"""Fast pre-authoring mockups for the desktop GUI."""

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


class DVDPreviewRenderer:
    """Render a lightweight DVD case and printed-disc mockup from library art."""

    WIDTH = 1120
    HEIGHT = 650

    def __init__(self, font_path: Optional[str] = None):
        self.font_path = font_path

    def _font(self, size: int, bold: bool = False):
        candidates = [
            self.font_path,
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return ImageFont.truetype(candidate, size)
        return ImageFont.load_default()

    @staticmethod
    def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
        return ImageOps.fit(image.convert("RGB"), size, Image.Resampling.LANCZOS)

    @staticmethod
    def _open(path: Optional[Path]) -> Optional[Image.Image]:
        try:
            return Image.open(path).convert("RGBA") if path and path.exists() else None
        except Exception:
            return None

    def render(
        self,
        output_path: Path,
        series_name: str,
        season_name: str,
        poster_path: Optional[Path],
        backdrop_path: Optional[Path],
        logo_path: Optional[Path],
        episode_count: int,
        disc_count: int,
        case_angle: int = 0,
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        canvas = Image.new("RGBA", (self.WIDTH, self.HEIGHT), (13, 16, 24, 255))
        backdrop = self._open(backdrop_path)
        poster = self._open(poster_path) or backdrop
        logo = self._open(logo_path)

        if backdrop:
            bg = self._cover(backdrop, canvas.size).filter(ImageFilter.GaussianBlur(24))
            bg = Image.blend(bg.convert("RGB"), Image.new("RGB", bg.size, (9, 13, 23)), 0.68)
            canvas.paste(bg.convert("RGBA"), (0, 0))

        # Ground glow and shadows make the flat artwork read as a product mockup.
        glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse((60, 510, 1060, 665), fill=(0, 0, 0, 150))
        glow = glow.filter(ImageFilter.GaussianBlur(22))
        canvas.alpha_composite(glow)

        # Printed disc, sitting behind the case.
        disc_size = 390
        disc = Image.new("RGBA", (disc_size, disc_size), (0, 0, 0, 0))
        disc_mask = Image.new("L", disc.size, 0)
        ImageDraw.Draw(disc_mask).ellipse((4, 4, disc_size - 4, disc_size - 4), fill=255)
        if backdrop:
            disc_art = self._cover(backdrop, disc.size)
        elif poster:
            disc_art = self._cover(poster, disc.size)
        else:
            disc_art = Image.new("RGB", disc.size, (37, 83, 112))
        disc.paste(disc_art, (0, 0), disc_mask)
        tint = Image.new("RGBA", disc.size, (18, 42, 64, 90))
        disc.alpha_composite(tint)
        dd = ImageDraw.Draw(disc)
        dd.ellipse((4, 4, disc_size - 4, disc_size - 4), outline=(218, 231, 240, 210), width=5)
        dd.ellipse((146, 146, 244, 244), fill=(14, 17, 25, 255), outline=(220, 230, 238, 210), width=4)
        dd.ellipse((178, 178, 212, 212), fill=(225, 230, 235, 255))
        if logo:
            logo_copy = logo.copy()
            logo_copy.thumbnail((230, 82), Image.Resampling.LANCZOS)
            disc.alpha_composite(
                logo_copy,
                ((disc_size - logo_copy.width) // 2, 62),
            )
        else:
            label_font = self._font(27, bold=True)
            text_box = dd.textbbox((0, 0), series_name, font=label_font)
            dd.text(
                ((disc_size - (text_box[2] - text_box[0])) // 2, 72),
                series_name,
                font=label_font,
                fill="white",
            )
        disc = disc.rotate(-8, Image.Resampling.BICUBIC, expand=True)
        canvas.alpha_composite(disc, (665, 148))

        # Case front artwork and subtle clear-plastic sleeve.
        case_w, case_h = 390, 548
        front = Image.new("RGBA", (case_w, case_h), (20, 24, 32, 255))
        if poster:
            front.paste(self._cover(poster, front.size), (0, 0))
        fd = ImageDraw.Draw(front)
        fd.rectangle((0, case_h - 108, case_w, case_h), fill=(5, 8, 14, 170))
        season_font = self._font(27, bold=True)
        meta_font = self._font(17)
        fd.text((24, case_h - 88), season_name.upper(), font=season_font, fill="white")
        fd.text(
            (24, case_h - 48),
            f"{episode_count} EPISODES  •  {disc_count} DISC{'S' if disc_count != 1 else ''}",
            font=meta_font,
            fill=(196, 210, 223),
        )
        if logo:
            logo_copy = logo.copy()
            logo_copy.thumbnail((320, 128), Image.Resampling.LANCZOS)
            front.alpha_composite(logo_copy, ((case_w - logo_copy.width) // 2, 38))
        elif not poster:
            title_font = self._font(39, bold=True)
            fd.multiline_text((28, 50), series_name, font=title_font, fill="white", spacing=4)
        sleeve = Image.new("RGBA", front.size, (255, 255, 255, 0))
        sd = ImageDraw.Draw(sleeve)
        sd.polygon(((0, 0), (72, 0), (250, case_h), (178, case_h)), fill=(255, 255, 255, 24))
        sd.rectangle((3, 3, case_w - 4, case_h - 4), outline=(235, 242, 248, 105), width=5)
        front.alpha_composite(sleeve)
        angle = max(-65, min(65, int(case_angle)))
        angle_ratio = abs(angle) / 65
        visible_w = max(170, int(case_w * (1 - angle_ratio * 0.48)))
        front = front.resize((visible_w, case_h), Image.Resampling.LANCZOS)
        side_w = 20 + int(62 * angle_ratio)
        case_x, case_y = 105, 45
        if angle < 0:
            case_x += side_w

        shadow = Image.new(
            "RGBA", (visible_w + side_w + 45, case_h + 45), (0, 0, 0, 0)
        )
        ImageDraw.Draw(shadow).rounded_rectangle(
            (15, 15, shadow.width - 4, shadow.height - 4),
            radius=10,
            fill=(0, 0, 0, 190),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(18))
        canvas.alpha_composite(shadow, (case_x + 5, case_y + 8))

        # Visible spine/hinge grows as the case rotates away from the viewer.
        draw = ImageDraw.Draw(canvas)
        if angle >= 0:
            spine = (
                (case_x, case_y + 8),
                (case_x + side_w, case_y),
                (case_x + side_w, case_y + case_h),
                (case_x, case_y + case_h - 8),
            )
            draw.polygon(spine, fill=(20, 25, 35, 255))
            canvas.alpha_composite(front, (case_x + side_w, case_y))
        else:
            canvas.alpha_composite(front, (case_x, case_y))
            spine = (
                (case_x + visible_w, case_y),
                (case_x + visible_w + side_w, case_y + 8),
                (case_x + visible_w + side_w, case_y + case_h - 8),
                (case_x + visible_w, case_y + case_h),
            )
            draw.polygon(spine, fill=(20, 25, 35, 255))
        draw.line(spine[:2], fill=(235, 241, 246, 95), width=2)

        title_font = self._font(30, bold=True)
        draw.text((600, 54), "PACKAGE PREVIEW", font=title_font, fill=(238, 242, 247))
        draw.text(
            (601, 96),
            "Built from your Jellyfin artwork",
            font=self._font(18),
            fill=(155, 172, 190),
        )

        canvas.convert("RGB").save(output_path, "PNG", optimize=True)
        return output_path

    def render_open_case(
        self,
        output_path: Path,
        series_name: str,
        season_name: str,
        cover_preview_path: Optional[Path],
        booklet_preview_path: Optional[Path],
        disc_preview_path: Optional[Path],
        backdrop_path: Optional[Path] = None,
        case_angle: int = 0,
    ) -> Path:
        """Render an open keep case with its booklet and disc in place."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas = Image.new("RGBA", (self.WIDTH, self.HEIGHT), (12, 15, 22, 255))
        backdrop = self._open(backdrop_path)
        if backdrop:
            bg = self._cover(backdrop, canvas.size).filter(ImageFilter.GaussianBlur(28))
            bg = Image.blend(bg.convert("RGB"), Image.new("RGB", bg.size, (8, 11, 18)), 0.76)
            canvas.paste(bg.convert("RGBA"), (0, 0))

        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).ellipse((90, 492, 1030, 625), fill=(0, 0, 0, 175))
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(23)))

        case = Image.new("RGBA", (940, 510), (0, 0, 0, 0))
        draw = ImageDraw.Draw(case)
        left = (18, 16, 465, 494)
        right = (475, 16, 922, 494)
        for box in (left, right):
            draw.rounded_rectangle(box, radius=25, fill=(24, 29, 39, 255),
                                   outline=(105, 117, 132, 255), width=7)
            inner = (box[0] + 15, box[1] + 15, box[2] - 15, box[3] - 15)
            draw.rounded_rectangle(inner, radius=17, fill=(14, 18, 26, 255),
                                   outline=(54, 64, 77, 255), width=3)
        draw.rounded_rectangle((455, 22, 485, 488), radius=12,
                               fill=(12, 16, 23, 255), outline=(91, 102, 116, 255), width=3)
        for y in (55, 430):
            draw.rounded_rectangle((459, y, 481, y + 42), radius=7,
                                   fill=(72, 82, 96, 255))

        # The wrap peeks through the clear sleeve around the outer edge.
        cover = self._open(cover_preview_path)
        if cover:
            sleeve = self._cover(cover, (418, 450))
            sleeve.putalpha(72)
            case.alpha_composite(sleeve, (32, 30))
        else:
            draw.rectangle((32, 30, 450, 480), fill=(27, 47, 67, 100))

        booklet = self._open(booklet_preview_path)
        if booklet:
            page = ImageOps.contain(booklet.convert("RGB"), (330, 410), Image.Resampling.LANCZOS)
        else:
            page = Image.new("RGB", (300, 400), (226, 223, 213))
            pd = ImageDraw.Draw(page)
            pd.text((25, 35), series_name, font=self._font(24, True), fill=(20, 25, 34))
            pd.text((25, 75), season_name, font=self._font(18), fill=(55, 61, 70))
        px = 241 - page.width // 2
        py = 254 - page.height // 2
        page_shadow = Image.new("RGBA", (page.width + 20, page.height + 20), (0, 0, 0, 0))
        ImageDraw.Draw(page_shadow).rounded_rectangle(
            (8, 8, page_shadow.width - 2, page_shadow.height - 2),
            radius=5, fill=(0, 0, 0, 125)
        )
        case.alpha_composite(page_shadow.filter(ImageFilter.GaussianBlur(7)), (px - 5, py - 3))
        case.alpha_composite(page.convert("RGBA"), (px, py))
        # Transparent retaining clips.
        for y in (105, 390):
            draw.rounded_rectangle((38, y, 87, y + 62), radius=10,
                                   fill=(210, 222, 235, 70), outline=(190, 205, 220, 125), width=2)

        disc_source = self._open(disc_preview_path)
        disc_size = 376
        disc = Image.new("RGBA", (disc_size, disc_size), (0, 0, 0, 0))
        mask = Image.new("L", disc.size, 0)
        md = ImageDraw.Draw(mask)
        md.ellipse((3, 3, disc_size - 3, disc_size - 3), fill=255)
        md.ellipse((151, 151, 225, 225), fill=0)
        if disc_source:
            art = self._cover(disc_source, disc.size)
        else:
            art = Image.new("RGB", disc.size, (38, 80, 104))
        disc.paste(art, (0, 0), mask)
        dd = ImageDraw.Draw(disc)
        dd.ellipse((3, 3, disc_size - 3, disc_size - 3),
                   outline=(215, 224, 232, 235), width=4)
        dd.ellipse((151, 151, 225, 225), outline=(190, 201, 211, 255), width=4)
        dx, dy = 699 - disc_size // 2, 255 - disc_size // 2
        case.alpha_composite(disc, (dx, dy))
        draw.ellipse((672, 228, 726, 282), fill=(31, 37, 48, 255),
                     outline=(135, 148, 162, 255), width=4)
        draw.ellipse((687, 243, 711, 267), fill=(15, 19, 27, 255))

        # Foreshorten the left door so the case reads as half-open rather than flat.
        left_door = case.crop((0, 0, 470, case.height)).resize(
            (350, 460), Image.Resampling.LANCZOS
        )
        right_door = case.crop((470, 0, case.width, case.height))
        half_open = Image.new("RGBA", (824, case.height), (0, 0, 0, 0))
        half_open.alpha_composite(left_door, (0, 25))
        half_open.alpha_composite(right_door, (350, 0))
        hinge_draw = ImageDraw.Draw(half_open)
        hinge_draw.polygon(
            ((340, 30), (365, 17), (365, 492), (340, 480)),
            fill=(10, 14, 21, 235),
        )
        hinge_draw.line((365, 20, 365, 488), fill=(137, 149, 163, 150), width=2)
        case = half_open

        # Shift and compress the open package to simulate rotating it on a turntable.
        angle = max(-60, min(60, int(case_angle)))
        scale = 1.0 - abs(angle) / 60 * 0.22
        rotated_w = int(case.width * scale)
        case = case.resize((rotated_w, case.height), Image.Resampling.LANCZOS)
        x = (self.WIDTH - rotated_w) // 2 + int(angle * 0.75)
        canvas.alpha_composite(case, (x, 80))

        label = ImageDraw.Draw(canvas)
        label.text((34, 24), "OPEN CASE PREVIEW", font=self._font(25, True),
                   fill=(238, 242, 247))
        label.text((35, 55), "Click the booklet, disc, or cover to inspect its PDF",
                   font=self._font(16), fill=(166, 180, 195))
        canvas.convert("RGB").save(output_path, "PNG", optimize=True)
        return output_path
