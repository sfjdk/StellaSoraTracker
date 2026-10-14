"""外部数据格式的适配测试。

被适配的是网页版/分享归档那种带外壳的文件:
    {"version": 1, "uid": "100872990", "updatedAt": "...", "categories": {...}}
修之前, version/uid/updatedAt 三个键会让整个 categories 被判成"无法识别的分类",
四类记录全部塌缩成第 1 类。
"""
import contextlib
import json
import shutil
import unittest
from pathlib import Path

from stellasora_toolkit import service
from stellasora_toolkit.exporter import (
    export_all,
    extract_uid,
    normalize_category_keys,
    parse_import_text,
    sanitize_gacha_categories,
)

# 官方外层分类 key(经实际归档核对): 1 旅人限时 / 2 旅人常驻 / 3 秘纹限时 / 4 秘纹常驻
# 常驻池的 Gid 固定就是 1(旅人)/ 2(秘纹), 所以一类里凑两组只能靠 Time 不同。
CATEGORY_GROUPS = {
    1: [(10130, 100), (10131, 200)],
    2: [(1, 300), (1, 400)],
    3: [(20130, 500), (20131, 600)],
    4: [(2, 700), (2, 800)],
}
GROUP_COUNT = sum(len(groups) for groups in CATEGORY_GROUPS.values())
GROUP_IDS = [212009, 132]

TEMP_ROOT = Path(__file__).resolve().parent.parent / ".testtmp"


@contextlib.contextmanager
def temp_workdir(name: str):
    """用例专用的临时目录。

    这里不用 tempfile.TemporaryDirectory: 它建出来的目录权限是 0o700, 在受限
    沙箱(以及部分企业安全策略)下连 scandir/chmod 都会被拒绝, 清理阶段抛
    WinError 5 —— 测试逻辑本身没问题, 结果却被染红。普通 mkdir 建出来的目录
    在同样环境下读写删除都正常。
    """
    directory = TEMP_ROOT / f"import_format_{name}"
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def group(gid: int, time: int, ids: list[int]) -> dict:
    return {"Time": time, "NextPackage": "", "Gid": gid, "Ids": ids}


def all_groups() -> list[dict]:
    return [group(gid, time, list(GROUP_IDS))
            for groups in CATEGORY_GROUPS.values() for gid, time in groups]


def categories_fixture() -> dict[int, list[dict]]:
    return {
        category: [group(gid, time, list(GROUP_IDS)) for gid, time in groups]
        for category, groups in CATEGORY_GROUPS.items()
    }


def wrapper_payload() -> dict:
    return {
        "version": 1,
        "uid": "100872990",
        "updatedAt": "2026-10-12T07:18:09.124641+00:00",
        "categories": {
            str(category): list(groups) for category, groups in categories_fixture().items()
        },
    }


class WrapperFormatTests(unittest.TestCase):
    def test_wrapper_keeps_four_categories(self):
        categories = sanitize_gacha_categories(wrapper_payload())
        self.assertEqual(sorted(categories), [1, 2, 3, 4])
        self.assertEqual([len(groups) for _, groups in sorted(categories.items())],
                         [2, 2, 2, 2])

    def test_uid_is_read_from_wrapper(self):
        self.assertEqual(extract_uid(wrapper_payload()), "100872990")

    def test_uid_absent_or_empty_is_tolerated(self):
        self.assertEqual(extract_uid({"categories": {"1": []}}), "")
        self.assertEqual(extract_uid({"uid": "  "}), "")
        self.assertEqual(extract_uid(None), "")

    def test_int_like_string_keys_are_categories(self):
        payload = {"1": [group(10130, 1, [1])], "2": [group(1, 2, [2])]}
        self.assertEqual(sorted(sanitize_gacha_categories(payload)), [1, 2])

    def test_desktop_export_prefers_categories_over_flat_groups(self):
        payload = {
            "groups": all_groups(),
            "categories": {str(k): v for k, v in categories_fixture().items()},
        }
        categories = sanitize_gacha_categories(payload)
        self.assertEqual(sorted(categories), [1, 2, 3, 4])
        self.assertEqual(sum(len(v) for v in categories.values()), GROUP_COUNT)

    def test_groups_only_export_still_parses(self):
        categories = sanitize_gacha_categories({"groups": [group(10130, 1, [1])]})
        self.assertEqual(categories[1][0]["Gid"], 10130)

    def test_metadata_keys_are_not_mistaken_for_categories(self):
        payload = {"version": 1, "uid": "42", "updatedAt": "x",
                   "categories": {"3": [group(20130, 1, [1])]}}
        self.assertEqual(sorted(sanitize_gacha_categories(payload)), [3])

    def test_original_lua_shape_is_unchanged(self):
        categories = {1: [[group(10130, 1, [1])]], 3: [[group(20130, 2, [2])]]}
        self.assertEqual(sorted(sanitize_gacha_categories(categories)), [1, 3])


class CategoryKeyTests(unittest.TestCase):
    def test_flat_data_is_rebucketed_by_gid(self):
        flat = {1: all_groups()}
        categories = normalize_category_keys(flat)
        self.assertEqual(sorted(categories), [1, 2, 3, 4])
        for category, groups in CATEGORY_GROUPS.items():
            self.assertEqual([g["Gid"] for g in categories[category]],
                             [gid for gid, _time in groups])

    def test_unknown_gid_stays_in_its_category(self):
        categories = normalize_category_keys({1: [group(999999, 1, [1])]})
        self.assertEqual(sorted(categories), [1])

    def test_already_correct_data_is_untouched(self):
        original = categories_fixture()
        self.assertEqual(normalize_category_keys(original), original)


class ImportParsingTests(unittest.TestCase):
    def test_parse_import_text_reads_wrapper_json(self):
        categories, uid = parse_import_text(json.dumps(wrapper_payload()), ".json")
        self.assertEqual(sorted(categories), [1, 2, 3, 4])
        self.assertEqual(uid, "100872990")

    def test_unknown_shape_falls_back_to_deep_scan(self):
        payload = {"result": {"data": [[group(10130, 1, [1, 2])]]}}
        categories, _uid = parse_import_text(json.dumps(payload), ".json")
        self.assertEqual(sum(len(v) for v in categories.values()), 1)
        self.assertEqual(categories[1][0]["Ids"], [1, 2])

    def test_own_csv_export_round_trips_categories(self):
        with temp_workdir("csv_round_trip") as directory:
            csv_path = export_all(directory, all_groups(), None, categories_fixture())[1]
            categories, uid = parse_import_text(service.read_import_text(csv_path), ".csv")
        self.assertEqual(sorted(categories), [1, 2, 3, 4])
        self.assertEqual(uid, "")
        self.assertEqual(categories, categories_fixture())

    def test_csv_without_category_column_is_rebucketed_by_gid(self):
        text = "Gid,Time,Id,NextPackage\n1,100,212009,\n10130,101,132,\n"
        categories, _uid = parse_import_text(text, ".csv")
        self.assertEqual(sorted(categories), [1, 2])
        self.assertEqual([g["Gid"] for g in categories[2]], [1])

    def test_csv_group_column_keeps_separate_pulls_apart(self):
        text = ("category,group,item,Gid,Time,Id,NextPackage\n"
                "1,1,1,10130,100,1,\n"
                "1,1,2,10130,100,2,\n"
                "1,2,1,10130,100,3,\n")
        categories, _uid = parse_import_text(text, ".csv")
        self.assertEqual(len(categories[1]), 2)
        self.assertEqual([g["Ids"] for g in categories[1]], [[1, 2], [3]])


class ImportPersistTests(unittest.TestCase):
    def test_import_merges_into_archive_and_keeps_uid(self):
        with temp_workdir("merge_uid") as directory:
            source = directory / "100872990.json"
            source.write_text(json.dumps(wrapper_payload()), encoding="utf-8")

            result = service.import_gacha_file(directory, source)

            self.assertEqual(result.added_groups, GROUP_COUNT)
            self.assertEqual(result.uid, "100872990")
            # 归档落在当前账号目录下(多账号), 通过公开 API 读回来校验
            archive = json.loads(
                (service.active_data_dir(directory) / service.ARCHIVE_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(archive["uid"], "100872990")
            self.assertEqual(archive["version"], 1)
            self.assertEqual(sorted(archive["categories"]), ["1", "2", "3", "4"])
            self.assertEqual(service.load_archive_uid(directory), "100872990")
            self.assertEqual(service.load_archive_categories(directory), result.categories)

    def test_reimporting_the_same_file_adds_nothing(self):
        with temp_workdir("reimport") as directory:
            source = directory / "share.json"
            source.write_text(json.dumps(wrapper_payload()), encoding="utf-8")

            service.import_gacha_file(directory, source)
            again = service.import_gacha_file(directory, source)

            self.assertEqual(again.added_groups, 0)
            self.assertEqual(again.added_pulls, 0)
            self.assertEqual(again.total_groups, GROUP_COUNT)

    def test_import_keeps_existing_history(self):
        with temp_workdir("keep_history") as directory:
            service._write_archive(directory, {1: [group(10130, 500, [7])]})
            source = directory / "share.json"
            source.write_text(json.dumps(wrapper_payload()), encoding="utf-8")

            result = service.import_gacha_file(directory, source)

            self.assertEqual(result.total_groups, GROUP_COUNT + 1)
            self.assertEqual(result.added_groups, GROUP_COUNT)
            self.assertIn(group(10130, 500, [7]), result.categories[1])

    def test_import_repairs_a_previously_flattened_archive(self):
        with temp_workdir("repair_flat") as directory:
            service._write_archive(directory, {1: all_groups()}, uid="100872990")
            source = directory / "share.json"
            source.write_text(json.dumps(wrapper_payload()), encoding="utf-8")

            service.import_gacha_file(directory, source)

            archived = service.load_archive_categories(directory)
            self.assertEqual(sorted(archived), [1, 2, 3, 4])
            self.assertEqual(sum(len(v) for v in archived.values()), GROUP_COUNT)

    def test_uid_survives_archive_rewrite(self):
        with temp_workdir("uid_rewrite") as directory:
            service._write_archive(directory, {1: [group(10130, 1, [1])]}, uid="100872990")
            payload = service.read_archive_payload(directory)
            archived = service._categories_from_payload(payload)
            # 刷新游戏数据时就是这么写的: 沿用当前账号已有的 uid
            service._write_archive(directory, archived, uid=service.load_archive_uid(directory))
            self.assertEqual(service.load_archive_uid(directory), "100872990")

    def test_uid_from_import_wins_over_an_older_one(self):
        with temp_workdir("uid_priority") as directory:
            service._write_archive(directory, {1: [group(10130, 1, [1])]}, uid="111")
            source = directory / "share.json"
            source.write_text(json.dumps(wrapper_payload()), encoding="utf-8")

            service.import_gacha_file(directory, source)

            self.assertEqual(service.load_archive_uid(directory), "100872990")

    def test_gbk_csv_is_readable(self):
        with temp_workdir("gbk_csv") as directory:
            source = directory / "老工具.csv"
            source.write_bytes("Gid,Time,Id,NextPackage\n10130,100,1,\n".encode("gb18030"))
            result = service.import_gacha_file(directory, source)
            self.assertEqual(result.added_groups, 1)

    def test_empty_file_raises_readable_error(self):
        with temp_workdir("empty") as directory:
            source = directory / "empty.json"
            source.write_text('{"version": 1, "uid": "1", "categories": {}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                service.import_gacha_file(directory, source)

    def test_export_all_writes_uid_and_round_trips(self):
        with temp_workdir("export_round_trip") as directory:
            json_path, csv_path = export_all(directory, all_groups(), None,
                                             categories_fixture(), uid="100872990")[:2]
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["uid"], "100872990")
            # groups 与 categories 同时保留: 老版本/网页版都读这个导出文件
            self.assertEqual(payload["groups"], [g for v in payload["categories"].values() for g in v])

            categories, uid = parse_import_text(json_path.read_text(encoding="utf-8"), ".json")
            self.assertEqual(uid, "100872990")
            self.assertEqual(categories, categories_fixture())
            self.assertTrue(csv_path.exists())

    def test_export_without_uid_omits_the_key(self):
        with temp_workdir("export_no_uid") as directory:
            json_path = export_all(directory, all_groups(), None, categories_fixture())[0]
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertNotIn("uid", payload)


if __name__ == "__main__":
    unittest.main()
