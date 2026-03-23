import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xhs_downloader.infra.utils import (
    build_note_output_dir,
    build_run_root,
    guess_extension_from_url,
    normalize_count,
    safe_filename,
)


class PathUtilsTests(unittest.TestCase):
    def test_safe_filename_removes_windows_invalid_chars(self) -> None:
        self.assertEqual("穿搭_春夏_推荐", safe_filename("穿搭:春夏/推荐"))

    def test_normalize_count_supports_wan_unit(self) -> None:
        self.assertEqual(12000, normalize_count("1.2万"))
        self.assertEqual(530, normalize_count("530"))

    def test_output_directory_helpers(self) -> None:
        root = build_run_root(Path("downloads"), "穿搭合集", "20260323_demo")
        note_dir = build_note_output_dir(root, "note:001")
        self.assertEqual(Path("downloads") / "穿搭合集" / "20260323_demo", root)
        self.assertEqual(root / "note_001", note_dir)

    def test_guess_extension_from_url(self) -> None:
        self.assertEqual(".png", guess_extension_from_url("https://a.com/1.png?x=1"))
        self.assertEqual(".jpg", guess_extension_from_url("https://a.com/noext"))


if __name__ == "__main__":
    unittest.main()
