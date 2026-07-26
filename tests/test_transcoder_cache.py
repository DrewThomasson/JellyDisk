import tempfile
import unittest
from pathlib import Path

from jellydisc.transcoder import Transcoder


class TranscoderCacheVersionTests(unittest.TestCase):
    def test_unversioned_output_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "episode.mpg"
            output.write_bytes(b"old output")

            self.assertFalse(Transcoder.is_cached_output_current(output))

    def test_current_output_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "episode.mpg"
            output.write_bytes(b"new output")
            Transcoder._mark_output_current(output)

            self.assertTrue(Transcoder.is_cached_output_current(output))


if __name__ == "__main__":
    unittest.main()
