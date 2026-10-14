"""多账号测试: 每个 UID 一份独立归档, 可切换/新建/删除, 老数据自动迁移。

为什么要分开: 垫抽/保底/五星概率都是按账号算的, 两个账号混在一个归档里全错。
"""
import contextlib
import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stellasora_toolkit import accounts, service  # noqa: E402

TEMP_ROOT = Path(__file__).resolve().parent.parent / ".testtmp"


@contextlib.contextmanager
def temp_workdir(name: str):
    directory = TEMP_ROOT / f"multi_{name}"
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def group(gid: int, time: int, ids: list[int]) -> dict:
    return {"Time": time, "NextPackage": "", "Gid": gid, "Ids": ids}


CATEGORIES_A = {1: [group(10139, 100, [212007, 139])]}
CATEGORIES_B = {1: [group(10140, 200, [140])], 3: [group(20140, 300, [214001])]}


class AccountStateTests(unittest.TestCase):
    def test_first_use_creates_a_default_account(self):
        with temp_workdir("first") as directory:
            state = accounts.ensure_ready(directory)
            state_file = directory / accounts.ACCOUNTS_FILENAME
            self.assertTrue(state_file.is_file())
            saved = json.loads(state_file.read_text(encoding="utf-8"))
        self.assertEqual(len(state.accounts), 1)
        self.assertEqual(state.active, accounts.DEFAULT_KEY)
        self.assertEqual(saved["active"], accounts.DEFAULT_KEY)

    def test_create_switch_rename_remove(self):
        with temp_workdir("crud") as directory:
            accounts.ensure_ready(directory)
            a = accounts.create(directory, uid="100872990", name="大号")
            b = accounts.create(directory, uid="200000001", name="小号")
            self.assertEqual(accounts.active_account(directory).key, b.key)

            self.assertTrue(accounts.switch(directory, a.key))
            self.assertEqual(accounts.active_account(directory).uid, "100872990")

            self.assertTrue(accounts.rename(directory, a.key, "主号"))
            self.assertEqual(accounts.active_account(directory).label, "主号")

            self.assertTrue(accounts.remove(directory, a.key))
            remaining = accounts.load_state(directory).accounts
            self.assertNotIn(a.key, [account.key for account in remaining])
            # 删除是改名保留, 不是真删
            kept = [p.name for p in (directory / accounts.ACCOUNTS_DIRNAME).iterdir()]
            self.assertTrue(any(name.startswith(f"{a.key}.deleted_") for name in kept), kept)

    def test_create_is_idempotent_per_uid(self):
        with temp_workdir("dup") as directory:
            first = accounts.create(directory, uid="100872990")
            again = accounts.create(directory, uid="100872990")
        self.assertEqual(first.key, again.key)

    def test_adopt_uid_switches_or_creates(self):
        with temp_workdir("adopt") as directory:
            accounts.ensure_ready(directory)
            a = accounts.create(directory, uid="100872990")
            b = accounts.create(directory, uid="200000001")
            self.assertEqual(accounts.active_account(directory).key, b.key)

            adopted = accounts.adopt_uid(directory, "100872990")   # 已有 → 切过去
            self.assertEqual(adopted.key, a.key)
            self.assertEqual(accounts.active_account(directory).key, a.key)

            fresh = accounts.adopt_uid(directory, "300000003")      # 没有 → 新建并切
            self.assertEqual(accounts.active_account(directory).key, fresh.key)
            self.assertEqual(fresh.uid, "300000003")

    def test_directory_names_are_sanitised(self):
        with temp_workdir("safe") as directory:
            account = accounts.create(directory, uid="../../evil")
            key = account.key if account else ""
            target = accounts.data_dir(directory, key)
        self.assertNotIn("..", target.parts)
        self.assertTrue(str(target.resolve()).startswith(str(TEMP_ROOT.resolve())))


class ShareExportTests(unittest.TestCase):
    """导出分享文件: 文件名与内容必须来自同一个账号。

    事故复盘: 游戏里换号后输入框先变成新 UID(308423356), 当前账号还是 100872990,
    于是导出的 308423356.json 里装着 100872990 的 653 组 —— 用户看到的就是
    "导出/查看记录时几个号的记录被合在一起了"。
    """

    @staticmethod
    def _two_accounts(directory: Path):
        accounts.ensure_ready(directory)
        big = accounts.create(directory, uid="100872990", name="大号")
        small = accounts.create(directory, uid="308423356", name="小号")
        service._write_archive(accounts.data_dir(directory, big.key), CATEGORIES_A,
                               uid="100872990")
        service._write_archive(accounts.data_dir(directory, small.key), CATEGORIES_B,
                               uid="308423356")
        return big, small

    def test_exports_the_account_matching_the_typed_uid(self):
        with temp_workdir("export_match") as directory:
            big, small = self._two_accounts(directory)
            accounts.switch(directory, big.key)              # 当前是大号

            path = service.export_share_for_uid(directory, "308423356")   # 框里是小号

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(path.name, "308423356.json")
            self.assertEqual(payload["uid"], "308423356")
            # 内容必须是小号的(2 组), 不能是大号的
            self.assertEqual(sum(len(v) for v in payload["categories"].values()),
                             sum(len(v) for v in CATEGORIES_B.values()))
            self.assertEqual(payload["categories"]["1"][0], CATEGORIES_B[1][0])

    def test_export_lands_in_that_accounts_directory(self):
        with temp_workdir("export_dir") as directory:
            big, small = self._two_accounts(directory)
            path = service.export_share_for_uid(directory, "100872990")
            self.assertEqual(path.parent, accounts.data_dir(directory, big.key))
            self.assertFalse((directory / path.name).exists(), "不该散在账号根目录里")

    def test_unknown_uid_is_refused(self):
        with temp_workdir("export_unknown") as directory:
            self._two_accounts(directory)
            with self.assertRaises(ValueError):
                service.export_share_for_uid(directory, "999999999")

    def test_current_account_is_used_when_uid_is_blank(self):
        with temp_workdir("export_blank") as directory:
            big, small = self._two_accounts(directory)
            accounts.switch(directory, small.key)
            path = service.export_share_for_uid(directory, "")
        self.assertEqual(path.name, "308423356.json")

    def test_account_without_uid_claims_the_typed_one(self):
        """还没登记 UID 的账号: 填进去就认领, 而不是导出失败。"""
        with temp_workdir("export_claim") as directory:
            accounts.ensure_ready(directory)
            blank = accounts.create(directory, uid="", name="")
            service._write_archive(accounts.data_dir(directory, blank.key), CATEGORIES_B)

            path = service.export_share_for_uid(directory, "308423356")

            self.assertEqual(path.name, "308423356.json")
            self.assertEqual(accounts.active_account(directory).uid, "308423356")
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["uid"], "308423356")

    def test_write_share_file_redirects_root_to_active_account(self):
        """万一还有代码把账号根目录传进来, 也不能把文件散在根目录。"""
        with temp_workdir("export_root") as directory:
            big, _small = self._two_accounts(directory)
            accounts.switch(directory, big.key)          # 底层函数只能按"当前账号"兜底
            path = service.write_share_file(directory, CATEGORIES_A, "100872990")
        self.assertEqual(path.parent, accounts.data_dir(directory, big.key))
        self.assertFalse((directory / path.name).exists())

    def test_no_records_is_refused_with_a_clear_message(self):
        with temp_workdir("export_empty") as directory:
            accounts.ensure_ready(directory)
            accounts.create(directory, uid="308423356")
            with self.assertRaises(ValueError) as ctx:
                service.export_share_for_uid(directory, "308423356")
        self.assertIn("还没有记录", str(ctx.exception))


class MergeAccountTests(unittest.TestCase):
    """合并账号: 收拾"记录读进了另一个账号"(那次刷新没读到 UID)。"""

    def test_merge_adds_records_and_keeps_source(self):
        with temp_workdir("merge") as directory:
            accounts.ensure_ready(directory)
            main = accounts.create(directory, uid="100872990")
            stray = accounts.create(directory, uid="", name="")
            service._write_archive(accounts.data_dir(directory, main.key), CATEGORIES_A,
                                   uid="100872990")
            service._write_archive(accounts.data_dir(directory, stray.key), CATEGORIES_B)

            added_groups, added_pulls = service.merge_accounts(directory, stray.key, main.key)

            merged = service.load_archive_categories(directory)
            self.assertEqual(added_groups, len(CATEGORIES_B[1]) + len(CATEGORIES_B[3]))
            self.assertGreater(added_pulls, 0)
            self.assertIn(CATEGORIES_A[1][0], merged[1])
            self.assertIn(CATEGORIES_B[1][0], merged[1])
            self.assertIn(CATEGORIES_B[3][0], merged[3])
            self.assertEqual(accounts.active_account(directory).key, main.key)
            self.assertEqual(service.effective_uid(directory), "100872990")
            keys = [a.key for a in accounts.load_state(directory).accounts]
            self.assertNotIn(stray.key, keys)
            # 源目录只是改名保留, 数据还在
            kept = list((directory / accounts.ACCOUNTS_DIRNAME).glob(f"{stray.key}.deleted_*"))
            self.assertEqual(len(kept), 1, "合并后源账号目录应当改名保留")
            self.assertTrue((kept[0] / service.ARCHIVE_FILENAME).is_file())

    def test_merge_is_idempotent(self):
        """重复合并同一批记录不该翻倍(真实场景: 用户连点两次)。"""
        with temp_workdir("merge_twice") as directory:
            accounts.ensure_ready(directory)
            main = accounts.create(directory, uid="100872990")
            first = accounts.create(directory, uid="", name="")
            service._write_archive(accounts.data_dir(directory, main.key), CATEGORIES_A,
                                   uid="100872990")
            service._write_archive(accounts.data_dir(directory, first.key), CATEGORIES_B)
            service.merge_accounts(directory, first.key, main.key)
            before = service.load_archive_categories(directory)

            second = accounts.create(directory, uid="", name="")
            service._write_archive(accounts.data_dir(directory, second.key), CATEGORIES_B)
            added_groups, added_pulls = service.merge_accounts(directory, second.key, main.key)

            self.assertEqual((added_groups, added_pulls), (0, 0), "同一批记录不该再计一次")
            self.assertEqual(service.load_archive_categories(directory), before)

    def test_merge_rejects_same_or_missing_keys(self):
        with temp_workdir("merge_bad") as directory:
            accounts.ensure_ready(directory)
            account = accounts.active_account(directory)
            for source, target in ((account.key, account.key), ("", account.key), (account.key, "")):
                with self.subTest(source=source, target=target):
                    with self.assertRaises(ValueError):
                        service.merge_accounts(directory, source, target)


class RepairTests(unittest.TestCase):
    """界面事故复盘: 用户点「新建账号」留空 UID 后停在空账号上, 看着像数据没了。"""

    def test_blank_uid_account_is_not_called_default(self):
        with temp_workdir("blank_key") as directory:
            accounts.ensure_ready(directory)              # 迁移出的 "default"
            first = accounts.create(directory, uid="100872990")
            blank = accounts.create(directory, uid="", name="")
        self.assertNotEqual(blank.key, accounts.DEFAULT_KEY, "不能和迁移用的默认账号重名")
        self.assertNotEqual(blank.key, first.key)
        self.assertEqual(blank.label, "默认账号" if blank.uid == "" and blank.name else blank.label)

    def test_repair_learns_uid_from_archive(self):
        with temp_workdir("repair_uid") as directory:
            accounts.ensure_ready(directory)              # account = default(无 uid)
            service._write_archive(accounts.active_data_dir(directory), CATEGORIES_A, uid="100872990")

            note = accounts.repair(directory)

            account = accounts.active_account(directory)
        self.assertEqual(account.uid, "100872990")
        self.assertIn("100872990", note)

    def test_repair_leaves_an_empty_account_for_one_with_records(self):
        with temp_workdir("repair_empty") as directory:
            accounts.ensure_ready(directory)
            with_data = accounts.create(directory, uid="100872990")
            service._write_archive(accounts.data_dir(directory, with_data.key), CATEGORIES_A,
                                   uid="100872990")
            blank = accounts.create(directory, uid="", name="")   # 留空 UID 的新账号(当前)

            self.assertEqual(accounts.active_account(directory).key, blank.key)
            note = accounts.repair(directory)

            self.assertEqual(accounts.active_account(directory).key, with_data.key)
            self.assertIn("已自动切到", note)

    def test_repair_is_quiet_when_everything_is_fine(self):
        with temp_workdir("repair_quiet") as directory:
            accounts.ensure_ready(directory)
            account = accounts.create(directory, uid="100872990")
            service._write_archive(accounts.data_dir(directory, account.key), CATEGORIES_A,
                                   uid="100872990")
            self.assertEqual(accounts.repair(directory), "")

    def test_repair_keeps_a_blank_account_when_it_has_records(self):
        """空 UID 但已有记录(比如还没读出 UID 就导入了)时不要乱切走。"""
        with temp_workdir("repair_keep") as directory:
            accounts.ensure_ready(directory)
            blank = accounts.create(directory, uid="", name="")
            service._write_archive(accounts.data_dir(directory, blank.key), CATEGORIES_A)
            self.assertEqual(accounts.active_account(directory).key, blank.key)
            accounts.repair(directory)
            self.assertEqual(accounts.active_account(directory).key, blank.key)

    def test_archive_group_count(self):
        with temp_workdir("counts") as directory:
            accounts.ensure_ready(directory)
            account = accounts.active_account(directory)
            self.assertEqual(accounts.archive_group_count(directory, account.key), -1)  # 还没有归档
            service._write_archive(accounts.data_dir(directory, account.key), CATEGORIES_B)
            self.assertEqual(accounts.archive_group_count(directory, account.key), 2)


class LegacyMigrationTests(unittest.TestCase):
    def test_old_archive_becomes_the_first_account(self):
        with temp_workdir("legacy") as directory:
            service._write_archive(directory, CATEGORIES_A, uid="100872990")
            service.write_share_file(directory, CATEGORIES_A, "100872990")

            state = accounts.ensure_ready(directory)

            account = state.active_account
            self.assertEqual(account.uid, "100872990")
            self.assertEqual(account.key, "100872990")
            data_dir = accounts.data_dir(directory, account.key)
            self.assertTrue((data_dir / service.ARCHIVE_FILENAME).is_file())
            self.assertTrue((data_dir / "100872990.json").is_file())
            # 老文件保留(不删任何东西), 当作备份
            self.assertTrue((directory / service.ARCHIVE_FILENAME).is_file())
            self.assertEqual(service.load_archive_categories(directory), CATEGORIES_A)

    def test_migration_without_uid_uses_default_key(self):
        with temp_workdir("legacy_nouid") as directory:
            service._write_archive(directory, CATEGORIES_A)
            state = accounts.ensure_ready(directory)
        self.assertEqual(state.active_account.key, accounts.DEFAULT_KEY)
        self.assertEqual(state.active_account.uid, "")

    def test_migration_is_idempotent(self):
        with temp_workdir("legacy_twice") as directory:
            service._write_archive(directory, CATEGORIES_A, uid="100872990")
            first = accounts.ensure_ready(directory)
            second = accounts.ensure_ready(directory)
        self.assertEqual([a.key for a in first.accounts], [a.key for a in second.accounts])


class PerAccountDataTests(unittest.TestCase):
    def test_two_accounts_do_not_share_records(self):
        with temp_workdir("isolate") as directory:
            accounts.ensure_ready(directory)
            a = accounts.create(directory, uid="100872990", name="大号")
            b = accounts.create(directory, uid="200000001", name="小号")

            accounts.switch(directory, a.key)
            service._write_archive(accounts.active_data_dir(directory), CATEGORIES_A, uid=a.uid)
            accounts.switch(directory, b.key)
            service._write_archive(accounts.active_data_dir(directory), CATEGORIES_B, uid=b.uid)

            accounts.switch(directory, a.key)
            self.assertEqual(service.load_archive_categories(directory), CATEGORIES_A)
            accounts.switch(directory, b.key)
            self.assertEqual(service.load_archive_categories(directory), CATEGORIES_B)

    def test_uid_and_share_file_follow_the_active_account(self):
        with temp_workdir("uid_follow") as directory:
            accounts.ensure_ready(directory)
            a = accounts.create(directory, uid="100872990")
            b = accounts.create(directory, uid="200000001")
            for account, categories in ((a, CATEGORIES_A), (b, CATEGORIES_B)):
                accounts.switch(directory, account.key)
                service._write_archive(accounts.active_data_dir(directory), categories, uid=account.uid)

            accounts.switch(directory, a.key)
            self.assertEqual(service.effective_uid(directory), "100872990")
            share = service.refresh_share_file(directory)
            self.assertEqual(share.name, "100872990.json")
            self.assertEqual(
                json.loads(share.read_text(encoding="utf-8"))["categories"],
                {str(k): v for k, v in CATEGORIES_A.items()})

            accounts.switch(directory, b.key)
            self.assertEqual(service.effective_uid(directory), "200000001")
            self.assertEqual(service.refresh_share_file(directory).name, "200000001.json")

    def test_import_switches_to_the_files_uid(self):
        with temp_workdir("import_uid") as directory:
            accounts.ensure_ready(directory)
            accounts.create(directory, uid="200000001", name="小号")     # 当前是 200000001

            source = directory / "100872990.json"
            source.write_text(json.dumps({
                "version": 1, "uid": "100872990",
                "updatedAt": "2026-10-12T07:18:09+00:00",
                "categories": {str(k): v for k, v in CATEGORIES_A.items()},
            }, ensure_ascii=False), encoding="utf-8")

            result = service.import_gacha_file(directory, source)

            self.assertEqual(result.uid, "100872990")
            self.assertEqual(accounts.active_account(directory).uid, "100872990")
            self.assertEqual(service.load_archive_categories(directory), CATEGORIES_A)
            # 小号那份没被污染
            small = accounts.find_by_uid(directory, "200000001")
            self.assertEqual(
                service._categories_from_payload(service.read_archive_payload(
                    accounts.data_dir(directory, small.key))), {})

    def test_upload_reads_the_active_account(self):
        with temp_workdir("upload") as directory:
            accounts.ensure_ready(directory)
            a = accounts.create(directory, uid="100872990")
            accounts.create(directory, uid="200000001")
            accounts.switch(directory, a.key)
            service._write_archive(accounts.active_data_dir(directory), CATEGORIES_A, uid=a.uid)

            from stellasora_toolkit import server_upload
            categories = server_upload.read_archive(directory)
        self.assertEqual(sorted(categories), ["1"])


if __name__ == "__main__":
    unittest.main()
