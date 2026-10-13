"""从游戏内存读账号 UID 的测试 —— 用合成 Lua 内存镜像, 不依赖真实游戏。

构造和方法与 lua53/discovery 的真实期望一致:
- 表对象: +8 字节 tt_=5, +11 是 lsize_node, +24 是节点数组指针;
- 哈希节点(32 字节): +0 值 TValue, +16 键 TValue;
- 短字符串对象: +8 gc_tag=4, +11 长度, +24 起是内容。
"""
import struct
import unittest

from stellasora_toolkit.account_uid import (
    UidSearch,
    find_account_uid,
    is_plausible_uid,
)
from stellasora_toolkit.discovery import LuaTableDiscovery
from stellasora_toolkit.lua53 import TAG_INTEGER, TAG_SHORT_STRING, Lua53Reader
from stellasora_toolkit.memory import MemoryRegion


class FakeProcess:
    """把整块内存当作一段连续可读区间; scan 就是在这段 bytes 里找子串。"""

    def __init__(self, data: bytearray, base: int = 0x1000):
        self.data = data
        self.base = base

    def read(self, address, size):
        if not self.is_readable(address, size):
            raise OSError("outside buffer")
        offset = address - self.base
        return bytes(self.data[offset:offset + size])

    def try_read(self, address, size):
        try:
            return self.read(address, size)
        except OSError:
            return None

    def is_readable(self, address, size=1):
        return self.base <= address and address + size <= self.base + len(self.data)

    def scan(self, needle, regions=None):
        """regions 参数与 RemoteProcess.scan 对齐(单区间假内存里忽略它)。"""
        hits, start = [], 0
        while True:
            index = self.data.find(needle, start)
            if index < 0:
                return hits
            hits.append(self.base + index)
            start = index + 1

    def regions(self):
        return [MemoryRegion(base=self.base, size=len(self.data))]

    def scan_any(self, needles, regions=None):
        """一次遍历找多个 pattern —— 与 RemoteProcess.scan_any 同语义。"""
        for needle in needles:
            for address in self.scan(needle):
                yield address, needle


class LuaImage:
    """按需往内存里塞 Lua 表/字符串, 尽量贴近真实布局。"""

    def __init__(self, size: int = 0x4000):
        self.process = FakeProcess(bytearray(size))
        self.lua = Lua53Reader(self.process)
        self.discovery = LuaTableDiscovery(self.process, self.lua)
        self._next = 0x1000 + 0x100

    def _alloc(self, size: int) -> int:
        address = self._next
        self._next += (size + 15) // 16 * 16
        return address

    def string_object(self, text: str) -> int:
        address = self._alloc(24 + len(text) + 1)
        offset = address - self.process.base
        self.process.data[offset + 8] = 4           # gc_tag: 短字符串
        self.process.data[offset + 11] = len(text)  # 长度
        self.process.data[offset + 24:offset + 24 + len(text)] = text.encode("utf-8")
        return address

    def table(self, fields: dict[str, object]) -> int:
        count = max(1, len(fields))
        lsize = 1
        while (1 << lsize) < count:
            lsize += 1
        table = self._alloc(48)
        nodes = self._alloc((1 << lsize) * 32)
        offset = table - self.process.base
        self.process.data[offset + 8] = 5           # tt_: 表
        self.process.data[offset + 11] = lsize
        struct.pack_into("<Q", self.process.data, offset + 24, nodes)
        node_offsets = [nodes + index * 32 - self.process.base for index in range(1 << lsize)]
        for index, (name, value) in enumerate(fields.items()):
            node = node_offsets[index]
            if isinstance(value, str):
                struct.pack_into("<Qi", self.process.data, node,
                                 self.string_object(value), TAG_SHORT_STRING)
            else:
                struct.pack_into("<Qi", self.process.data, node, int(value), TAG_INTEGER)
            struct.pack_into("<Qi", self.process.data, node + 16,
                             self.string_object(name), TAG_SHORT_STRING)
        return table


class FindAccountUidTests(unittest.TestCase):
    def test_finds_uid_stored_as_string(self):
        image = LuaImage()
        image.table({"_uid": "100872990", "_level": 42})
        result = find_account_uid(image.discovery)
        self.assertTrue(result.found)
        self.assertEqual(result.uid, "100872990")
        self.assertEqual(result.field_name, "_uid")
        self.assertIn("100872990", result.summary())

    def test_finds_uid_stored_as_integer(self):
        image = LuaImage()
        image.table({"_sUid": 100872990})
        result = find_account_uid(image.discovery)
        self.assertEqual(result.uid, "100872990")
        self.assertEqual(result.field_name, "_sUid")

    def test_ignores_implausible_values(self):
        image = LuaImage()
        image.table({"_uid": "12"})                 # 太短
        image.table({"_uid_len": "0123456789012345678"})  # 太长
        image.table({"_guid": "not-a-number"})      # 非数字
        result = find_account_uid(image.discovery)
        self.assertFalse(result.found)
        self.assertFalse(result.ambiguous)

    def test_ignores_non_uid_named_fields(self):
        image = LuaImage()
        image.table({"_level": "100872990"})        # 名字不含 uid
        self.assertFalse(find_account_uid(image.discovery).found)

    def test_prefers_the_uid_we_already_know(self):
        image = LuaImage()
        image.table({"_uid": "100872990"})
        image.table({"_sessionUid": "555000111"})   # 另一个看起来也像 UID 的值
        result = find_account_uid(image.discovery, preferred="100872990")
        self.assertEqual(result.uid, "100872990")
        self.assertEqual(result.field_name, "_uid")

    def test_quick_field_short_circuits_the_broad_scan(self):
        """_uid 这类最可能的字段名会先被单独试: 命中就直接采信(性能取舍)。

        代价: 名字不在"快速名单"里的其它字段(比如 _sessionUid)不会再被列出来参与
        歧义判断 —— 所以界面会显示 UID 来自哪个字段, 设置页也允许手动改。
        """
        image = LuaImage()
        image.table({"_uid": "100872990"})
        image.table({"_sessionUid": "555000111"})
        result = find_account_uid(image.discovery)
        self.assertEqual(result.uid, "100872990")
        self.assertEqual(result.field_name, "_uid")
        self.assertFalse(result.ambiguous, "快速通道命中即返回, 不再扫描其它名字")

    def test_quick_fields_disagreeing_is_still_reported_as_ambiguous(self):
        image = LuaImage()
        image.table({"_uid": "555000111"})
        image.table({"_nUid": "100872990"})
        result = find_account_uid(image.discovery)
        self.assertFalse(result.found, "两个快速字段打架时必须让用户确认")
        self.assertTrue(result.ambiguous)

    def test_empty_memory_is_reported_as_not_found(self):
        image = LuaImage()
        result = find_account_uid(image.discovery)
        self.assertFalse(result.found)
        self.assertEqual(result.candidates, ())
        self.assertIn("没有找到", result.summary())


class ReverseLookupTests(unittest.TestCase):
    """字段名不含 uid 时(比如叫 _roleId), 靠已知的 UID 值反查真实字段名。"""

    def test_learns_the_field_name_from_a_string_value(self):
        image = LuaImage()
        image.table({"_roleId": "100872990", "_nickname": "旅人"})
        # 先确认: 光靠名字扫不到任何候选
        self.assertFalse(find_account_uid(image.discovery).found)

        result = find_account_uid(image.discovery, preferred="100872990")

        self.assertTrue(result.found)
        self.assertEqual(result.uid, "100872990")
        self.assertEqual(result.field_name, "_roleId")

    def test_learns_the_field_name_from_an_integer_value(self):
        image = LuaImage()
        image.table({"_account": 100872990})
        result = find_account_uid(image.discovery, preferred="100872990")
        self.assertEqual(result.uid, "100872990")
        self.assertEqual(result.field_name, "_account")

    def test_does_not_match_a_longer_string_containing_the_digits(self):
        image = LuaImage()
        image.table({"_roleId": "x1008729900"})     # 更长的字符串, 不该被当成 UID
        result = find_account_uid(image.discovery, preferred="100872990")
        self.assertFalse(result.found)

    def test_preferred_value_wins_over_a_uid_named_lookalike(self):
        image = LuaImage()
        image.table({"_uid": "555000111"})
        image.table({"_roleId": "100872990"})
        result = find_account_uid(image.discovery, preferred="100872990")
        self.assertEqual(result.uid, "100872990")
        self.assertEqual(result.field_name, "_roleId")
        self.assertIn(result.field_name, {name for name, _ in result.candidates})


class BogusTableTests(unittest.TestCase):
    """内存扫描是启发式的: 候选里必然混着"看着像表头、其实是别的数据"的地址。

    真实事故: 用户点「刷新游戏数据」→ 本地还没存 UID → 走进 UID 扫描 →
    在假表上 table_header() 抛 ValueError("unreasonable Lua table size") →
    整个刷新失败(界面弹"读取失败")。探测必须把这些异常吞掉。
    """

    @staticmethod
    def _add_bogus_table(image: LuaImage, address: int, lsize: int = 0, size_array: int = 0) -> None:
        offset = address - image.process.base
        image.process.data[offset + 8] = 5                 # tt_: 看着是表
        image.process.data[offset + 11] = lsize            # lsize_node 离谱
        image.process.data[offset + 12:offset + 16] = size_array.to_bytes(4, "little")

    def test_bogus_tables_do_not_break_the_uid_scan(self):
        image = LuaImage()
        image.table({"_uid": "100872990"})
        self._add_bogus_table(image, 0x3000, lsize=40)          # lsize 超上限
        self._add_bogus_table(image, 0x3200, size_array=0xFFFFFF)  # 数组长度超上限

        result = find_account_uid(image.discovery)              # 关键: 不该抛异常
        self.assertTrue(result.found)
        self.assertEqual(result.uid, "100872990")

    def test_bogus_tables_do_not_break_the_reverse_lookup(self):
        image = LuaImage()
        image.table({"_roleId": "100872990"})
        self._add_bogus_table(image, 0x3000, lsize=40)
        result = find_account_uid(image.discovery, preferred="100872990")
        self.assertEqual(result.uid, "100872990")
        self.assertEqual(result.field_name, "_roleId")

    def test_only_bogus_tables_means_not_found_not_crash(self):
        image = LuaImage()
        self._add_bogus_table(image, 0x3000, size_array=0xFFFFFF)
        result = find_account_uid(image.discovery)
        self.assertFalse(result.found)


class PlausibleUidTests(unittest.TestCase):
    def test_accepts_real_shapes(self):
        self.assertTrue(is_plausible_uid("100872990"))
        self.assertTrue(is_plausible_uid(100872990))
        self.assertTrue(is_plausible_uid(" 123456 "))

    def test_rejects_other_shapes(self):
        for value in (True, None, 3.14, "12345", "1" * 16, "abc123456", "12 3456", ""):
            with self.subTest(value=value):
                self.assertFalse(is_plausible_uid(value))


class UidSearchSummaryTests(unittest.TestCase):
    def test_summary_texts(self):
        self.assertIn("100872990", UidSearch(uid="100872990", field_name="_uid").summary())
        self.assertIn("手动确认", UidSearch(ambiguous=True, candidates=(("_uid", "1"),)).summary())
        self.assertIn("没有找到", UidSearch().summary())


if __name__ == "__main__":
    unittest.main()
