import tempfile
import unittest
from pathlib import Path

from PIL import Image

from jellydisc.preview_renderer import DVDPreviewRenderer


class DVDPreviewRendererTests(unittest.TestCase):
    def test_renders_without_library_art(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "preview.png"
            DVDPreviewRenderer().render(
                output,
                series_name="Example Show",
                season_name="Season 1",
                poster_path=None,
                backdrop_path=None,
                logo_path=None,
                episode_count=8,
                disc_count=1,
            )

            with Image.open(output) as image:
                self.assertEqual(image.size, (1120, 650))
                self.assertEqual(image.mode, "RGB")

    def test_case_rotation_changes_the_render(self):
        with tempfile.TemporaryDirectory() as directory:
            left = Path(directory) / "left.png"
            right = Path(directory) / "right.png"
            renderer = DVDPreviewRenderer()
            arguments = {
                "series_name": "Example Show",
                "season_name": "Season 1",
                "poster_path": None,
                "backdrop_path": None,
                "logo_path": None,
                "episode_count": 8,
                "disc_count": 1,
            }
            renderer.render(left, case_angle=-60, **arguments)
            renderer.render(right, case_angle=60, **arguments)

            self.assertNotEqual(left.read_bytes(), right.read_bytes())

    def test_renders_half_open_case_with_print_art(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            cover = folder / "cover.png"
            booklet = folder / "booklet.png"
            disc = folder / "disc.png"
            Image.new("RGB", (900, 600), "navy").save(cover)
            Image.new("RGB", (600, 900), "ivory").save(booklet)
            Image.new("RGB", (700, 700), "teal").save(disc)
            output = folder / "open-case.png"

            DVDPreviewRenderer().render_open_case(
                output,
                series_name="Example Show",
                season_name="Season 1",
                cover_preview_path=cover,
                booklet_preview_path=booklet,
                disc_preview_path=disc,
            )

            with Image.open(output) as image:
                self.assertEqual(image.size, (1120, 650))
                self.assertEqual(image.mode, "RGB")


if __name__ == "__main__":
    unittest.main()
