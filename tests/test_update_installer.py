import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from stellasora_toolkit.update_installer import APP_EXE_NAME, apply_update, extract_update_package


class UpdateInstallerTests(unittest.TestCase):
    def _write_package(self, path: Path, files: dict[str, bytes]) -> None:
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)

    def test_applies_wrapped_portable_package_and_preserves_user_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "app"
            target.mkdir()
            (target / APP_EXE_NAME).write_bytes(b"old")
            (target / "_internal").mkdir()
            (target / "_internal" / "old.dll").write_bytes(b"old dll")
            (target / "exports").mkdir()
            (target / "exports" / "history.json").write_bytes(b"user data")
            package = root / "update.zip"
            self._write_package(
                package,
                {
                    f"StellaSoraGachaTool/{APP_EXE_NAME}": b"new",
                    "StellaSoraGachaTool/_internal/new.dll": b"new dll",
                },
            )

            apply_update(package, target)

            self.assertEqual((target / APP_EXE_NAME).read_bytes(), b"new")
            self.assertTrue((target / "_internal" / "new.dll").is_file())
            self.assertFalse((target / "_internal" / "old.dll").exists())
            self.assertEqual((target / "exports" / "history.json").read_bytes(), b"user data")

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "update.zip"
            self._write_package(package, {"../outside.txt": b"bad", APP_EXE_NAME: b"new"})
            destination = root / "extract"
            destination.mkdir()
            with self.assertRaises(ValueError):
                extract_update_package(package, destination)
            self.assertFalse((root / "outside.txt").exists())

    def test_rejects_packages_that_contain_user_data_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "update.zip"
            self._write_package(
                package,
                {
                    f"StellaSoraGachaTool/{APP_EXE_NAME}": b"new",
                    "StellaSoraGachaTool/exports/history.json": b"must not overwrite",
                },
            )
            destination = root / "extract"
            destination.mkdir()
            with self.assertRaises(ValueError):
                extract_update_package(package, destination)

    def test_rolls_back_when_installing_new_files_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "app"
            target.mkdir()
            original = target / APP_EXE_NAME
            original.write_bytes(b"old")
            package = root / "update.zip"
            self._write_package(package, {APP_EXE_NAME: b"new", "second.dat": b"new data"})

            real_move = __import__("shutil").move
            calls = 0

            def failing_move(source, destination, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise OSError("simulated failure")
                return real_move(source, destination, *args, **kwargs)

            with patch("stellasora_toolkit.update_installer.shutil.move", side_effect=failing_move):
                with self.assertRaises(OSError):
                    apply_update(package, target)

            self.assertEqual(original.read_bytes(), b"old")
            self.assertFalse((target / "second.dat").exists())


if __name__ == "__main__":
    unittest.main()
