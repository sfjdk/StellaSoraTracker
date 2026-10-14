"""UID 与「分享文件」格式(<uid>.json)测试。

用户的诉求: 工具要能产出与网页版/分享文件完全同格式的文件 ——
    {"version": 1, "uid": "100872990", "updatedAt": "...", "categories": {...}}
之前只有归档里恰好记着 uid 时才会出现该字段, 而且生成的文件名不叫 <uid>.json。
"""
import contextlib
import json
import shutil
import unittest
from pathlib import Path

from stellasora_toolkit import service

TEMP_ROOT = Path(__file__).resolve().parent.parent / ".testtmp"


@contextlib.contextmanager
def temp_workdir(name: str):
    """见 tests/test_import_format.py: 不用 tempfile(其 0o700 目录在受限沙箱里删不掉)。"""
    directory = TEMP_ROOT / f"share_{name}"
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def group(gid: int, time: int, ids: list[int]) -> dict:
    return {"Time": time, "NextPackage": "", "Gid": gid, "Ids": ids}


CATEGORIES = {
    1: [group(10139, 1770802631, [212007, 139])],
    2: [group(1, 1770802700, [110])],
}


class ShareFileFormatTests(unittest.TestCase):
    def test_share_file_has_exactly_the_exchange_shape(self):
        with temp_workdir("shape") as directory:
            path = service.write_share_file(directory, CATEGORIES, "100872990")
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(path.name, "100872990.json")
        self.assertEqual(list(payload), ["version", "uid", "updatedAt", "categories"])
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["uid"], "100872990")
        self.assertEqual(sorted(payload["categories"]), ["1", "2"])
        self.assertEqual(payload["categories"]["1"], CATEGORIES[1])

    def test_imported_uid_produces_the_share_file(self):
        with temp_workdir("from_import") as directory:
            source = directory / "100872990.json"
            source.write_text(json.dumps({
                "version": 1, "uid": "100872990",
                "updatedAt": "2026-10-12T07:18:09.124641+00:00",
                "categories": {str(k): v for k, v in CATEGORIES.items()},
            }, ensure_ascii=False), encoding="utf-8")

            result = service.import_gacha_file(directory, source)

            self.assertEqual(result.uid, "100872990")
            self.assertIsNotNone(result.share_file)
            self.assertEqual(result.share_file.name, "100872990.json")
            payload = json.loads(result.share_file.read_text(encoding="utf-8"))
            self.assertEqual(list(payload), ["version", "uid", "updatedAt", "categories"])
            self.assertEqual(payload["uid"], "100872990")

    def test_manual_uid_wins_over_archive_uid(self):
        with temp_workdir("manual_wins") as directory:
            service._write_archive(directory, CATEGORIES, uid="111")
            self.assertTrue(service.save_manual_uid(directory, "100872990"))
            self.assertEqual(service.effective_uid(directory), "100872990")

            # 刷新游戏数据走的就是这个取值顺序(手填 > 归档)
            path = service.write_share_file(directory, CATEGORIES, service.effective_uid(directory))
            self.assertEqual(path.name, "100872990.json")

    def test_no_uid_means_no_share_file(self):
        with temp_workdir("no_uid") as directory:
            self.assertIsNone(service.write_share_file(directory, CATEGORIES, ""))
            self.assertEqual(list(directory.glob("*.json")), [])

    def test_uid_is_sanitised_before_becoming_a_filename(self):
        with temp_workdir("sanitise") as directory:
            self.assertEqual(service.normalize_uid(" 100872990 "), "100872990")
            for bad in ("../evil", "a/b", "a\\b", "", "x" * 65, "uid.json"):
                with self.subTest(bad=bad):
                    self.assertEqual(service.normalize_uid(bad), "")
                    self.assertIsNone(service.write_share_file(directory, CATEGORIES, bad))

    def test_manual_uid_file_round_trips_and_clears(self):
        with temp_workdir("uid_file") as directory:
            self.assertEqual(service.load_manual_uid(directory), "")
            self.assertTrue(service.save_manual_uid(directory, "100872990"))
            self.assertEqual(service.load_manual_uid(directory), "100872990")
            self.assertTrue(service.save_manual_uid(directory, ""))
            self.assertEqual(service.load_manual_uid(directory), "")

    def test_broken_uid_file_is_ignored(self):
        with temp_workdir("broken_uid") as directory:
            (directory / service.UID_FILENAME).write_text("{not json", encoding="utf-8")
            self.assertEqual(service.load_manual_uid(directory), "")
            # 归档里的 uid 仍然可用
            service._write_archive(directory, CATEGORIES, uid="100872990")
            self.assertEqual(service.effective_uid(directory), "100872990")

    def test_archive_and_share_file_are_separate_files(self):
        with temp_workdir("both") as directory:
            service._write_archive(directory, CATEGORIES, uid="100872990")
            share = service.write_share_file(directory, CATEGORIES, "100872990")
            names = sorted(path.name for path in directory.glob("*.json"))
        self.assertEqual(names, ["100872990.json", service.ARCHIVE_FILENAME])
        self.assertEqual(share.name, "100872990.json")

    def test_load_archive_categories_matches_the_archive(self):
        with temp_workdir("categories") as directory:
            service._write_archive(directory, CATEGORIES, uid="100872990")
            loaded = service.load_archive_categories(directory)
        self.assertEqual(sorted(loaded), [1, 2])
        self.assertEqual(loaded[1], CATEGORIES[1])


if __name__ == "__main__":
    unittest.main()
