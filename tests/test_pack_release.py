import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools import pack_release


class ReleasePackagingTests(unittest.TestCase):
    def test_excludes_personal_data_but_keeps_program_and_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            files = (
                "StellaSoraGachaTool.exe", "StellaSoraUpdater.exe",
                "_internal/assets/travelers/133.png", "_internal/catalog.json",
                "exports/accounts/100123456/100123456.json", "UID.JSON",
                "accounts.json", "ui_settings.json", "fortune.json", "100123456.json",
                "crash.log", "logs/session.log", "stellasora_gacha_archive.json",
            )
            for name in files:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
            with patch.object(pack_release, "RELEASE_DIR", root / "release"):
                result = pack_release.build_zip("1.2.26", source)
            with zipfile.ZipFile(result) as archive:
                self.assertEqual(set(archive.namelist()), {
                    "StellaSoraGachaTool/StellaSoraGachaTool.exe",
                    "StellaSoraGachaTool/StellaSoraUpdater.exe",
                    "StellaSoraGachaTool/_internal/assets/travelers/133.png",
                    "StellaSoraGachaTool/_internal/catalog.json",
                })

    def test_failed_rebuild_preserves_existing_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "app.exe").write_bytes(b"program")
            prior = root / "StellaSoraGachaTool-1.2.25-win64.zip"
            current = root / "StellaSoraGachaTool-1.2.26-win64.zip"
            prior.write_bytes(b"prior release")
            current.write_bytes(b"current release")
            with patch.object(pack_release, "RELEASE_DIR", root), patch.object(
                zipfile.ZipFile, "write", side_effect=OSError("disk full")
            ):
                with self.assertRaises(OSError):
                    pack_release.build_zip("1.2.26", source)
            self.assertEqual(prior.read_bytes(), b"prior release")
            self.assertEqual(current.read_bytes(), b"current release")
            self.assertEqual(list(root.glob("*.part")), [])
