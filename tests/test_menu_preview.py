import unittest
from pathlib import Path

from jellydisc.main import select_preview_menu_audio


class MenuPreviewAudioTests(unittest.TestCase):
    def test_uses_theme_music_only_on_main_menu(self):
        assets = {
            "_theme_path": Path("theme.mp3"),
            "_trivia_audio_path": Path("trivia.mp3"),
        }

        self.assertEqual(
            select_preview_menu_audio("main", assets), Path("theme.mp3")
        )
        self.assertIsNone(select_preview_menu_audio("episodes:0", assets))
        self.assertIsNone(select_preview_menu_audio("cast:0", assets))

    def test_uses_trivia_music_for_every_trivia_screen(self):
        assets = {"_trivia_audio_path": Path("trivia.mp3")}

        for screen in ("trivia:0", "trivia:wrong", "trivia:win"):
            self.assertEqual(
                select_preview_menu_audio(screen, assets), Path("trivia.mp3")
            )


if __name__ == "__main__":
    unittest.main()
