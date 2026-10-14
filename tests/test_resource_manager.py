import tempfile
import unittest
from pathlib import Path

from stellasora_toolkit.resource_manager import _safe_asset_path


class ResourceManagerTests(unittest.TestCase):
    def test_asset_path_stays_inside_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(_safe_asset_path(root, "travelers/133.png"), (root / "travelers/133.png").resolve())

    def test_asset_path_rejects_traversal_and_non_png(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(ValueError):
                _safe_asset_path(root, "../secret.png")
            with self.assertRaises(ValueError):
                _safe_asset_path(root, "travelers/133.jpg")


if __name__ == "__main__":
    unittest.main()
