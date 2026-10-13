from __future__ import annotations

import struct
from collections.abc import Iterable

from .lua53 import TAG_INTEGER, TAG_SHORT_STRING, TAG_TABLE, STRING_TAGS, Lua53Reader
from .memory import MemoryRegion


class LuaTableDiscovery:
    """在"某个可读的地址空间"里定位 Lua 表。

    process 只需要实现 read / try_read / regions 三个方法 —— 不绑定任何
    平台 API。Windows 端传 RemoteProcess，安卓端传 sstemulator 的后端。
    （注解在 `from __future__ import annotations` 下不求值，故不引入依赖。）
    """

    def __init__(self, process, lua: Lua53Reader):
        self.process = process
        self.lua = lua
        # 表头扫描是全内存遍历里最贵的一步: 一次 discovery 内缓存复用(同一次读取里
        # 内存不会变), 免得 UID 探测和招募数据定位各扫一遍。
        self._headers: list[tuple[int, int, int, int]] | None = None
        # regions() 要遍历整个地址空间(VirtualQueryEx), 一次 discovery 内也只算一次
        self._scan_regions: list[MemoryRegion] | None = None

    def _find_tstrings(self, text: str) -> list[int]:
        encoded = text.encode("utf-8")
        result: list[int] = []
        for data_address in self.process.scan(encoded):
            object_address = data_address - 24
            header = self.process.try_read(object_address, 24)
            if header is None or header[8] != 4 or header[11] != len(encoded):
                continue
            if self.process.try_read(data_address, len(encoded) + 1) != encoded + b"\0":
                continue
            result.append(object_address)
        return result

    def _find_key_nodes(self, string_addresses: Iterable[int]) -> list[int]:
        nodes: list[int] = []
        for string_address in string_addresses:
            pointer = struct.pack("<Q", string_address)
            for reference in self.process.scan(pointer):
                tag_raw = self.process.try_read(reference + 8, 4)
                if tag_raw is None or struct.unpack("<i", tag_raw)[0] != TAG_SHORT_STRING:
                    continue
                node_address = reference - 16
                if node_address % 8 == 0:
                    nodes.append(node_address)
        return nodes

    @staticmethod
    def _nearby_regions(regions: list[MemoryRegion], address: int, radius: int) -> list[MemoryRegion]:
        low, high = max(0, address - radius), address + radius
        return [region for region in regions if region.end > low and region.base < high]

    def _scan_many(self, needles: list[bytes]) -> Iterable[tuple[int, bytes]]:
        """一次遍历找多个 pattern; 后端没有 scan_any(如安卓)时退回逐个扫描。"""
        scan_any = getattr(self.process, "scan_any", None)
        if scan_any is not None:
            yield from scan_any(needles, self._scannable_regions())
            return
        regions = self._scannable_regions()
        for needle in needles:
            for address in self.process.scan(needle, regions):
                yield address, needle

    def _uid_like_string_objects(self, limit: int = 6) -> list[tuple[str, int]]:
        """扫描内存, 找出"名字里带 uid"的短字符串对象 → [(名字, 字符串对象地址)]。

        这里不写死字段名: 游戏里叫 _uid / _sUid / _roleUid 都能命中, 只要求
        名字含 uid(不分大小写)、是纯标识符、长度合理。名字短的优先(更像主字段)。

        性能: 三种大小写写法用**一次**遍历一起找(以前三种各扫一遍), 且只保留最像的
        前 limit 个 —— 每多一个候选就多一遍"找引用该字符串的指针"的遍历。
        """
        found: dict[str, int] = {}
        needles = [b"uid", b"UID", b"Uid"]
        for hit, needle in self._scan_many(needles):
            # 命中点可能在名字中间("_uid" 的 "uid" 在第 2 个字符), 所以要往回
            # 退几个字节去找真正的字符串对象头; 退多少由对象头里的长度决定。
            for back in range(0, 9):
                object_address = hit - 24 - back
                header = self.process.try_read(object_address, 24)
                if header is None or header[8] != 4:      # 只认短字符串
                    continue
                length = header[11]
                if not 2 <= length <= 32 or back + len(needle) > length:
                    continue
                raw = self.process.try_read(object_address + 24, length)
                if raw is None:
                    continue
                try:
                    name = raw.decode("ascii")
                except UnicodeDecodeError:
                    continue
                if name[back:back + len(needle)] != needle.decode("ascii"):
                    continue
                if "uid" not in name.lower() or not name.replace("_", "").isalnum():
                    continue
                found.setdefault(name, object_address)
                break
        ordered = sorted(found.items(), key=lambda item: (len(item[0]), item[0]))
        return ordered[:limit]

    def find_fields_with_value(self, value: str, limit: int = 8) -> dict[str, str]:
        """按值反查字段名: 哪些 Lua 字段的值正好是 value → {字段名: value}。

        为什么需要: 字段名不一定含 uid(可能叫 _roleId 之类), 光靠名字扫不到。
        已知 UID(手填/归档/导入学到)时用它能确认并学到真实字段名。

        值的两种存法都试:
        - 短字符串: 先扫内容定位字符串对象, 再扫"指向该对象的 TValue" → 那些就是值槽;
        - 整数: 把 数值 + tag(0x13) 一起当模式扫, 命中处就是值槽。
        """
        text = str(value).strip()
        if not text:
            return {}
        slots: list[int] = []

        for content_address in self.process.scan(text.encode("utf-8")):
            object_address = content_address - 24
            header = self.process.try_read(object_address, 24)
            if header is None or header[8] != 4 or header[11] != len(text):
                continue                      # 长度必须正好相等: 排除"更长的字符串里含这几个数字"
            for reference in self.process.scan(struct.pack("<Q", object_address)):
                tag_raw = self.process.try_read(reference + 8, 4)
                if tag_raw is None:
                    continue
                if struct.unpack("<i", tag_raw)[0] in STRING_TAGS:
                    slots.append(reference)

        if text.isdigit() and int(text) < 2 ** 63:
            needle = struct.pack("<q", int(text)) + struct.pack("<i", TAG_INTEGER)
            slots.extend(self.process.scan(needle))

        if not slots:
            return {}
        headers = self._scan_table_headers()
        found: dict[str, str] = {}
        for slot in slots:
            for table in self._tables_containing_node(slot, headers):
                try:
                    key = self.lua.read_tvalue(slot + 16)
                    if key.tag not in STRING_TAGS:
                        continue
                    name = self.lua.read_string(struct.unpack("<Q", key.raw_value)[0])
                except (OSError, ValueError, struct.error):
                    continue                      # 假表/坏数据: 跳过即可
                if 1 <= len(name) <= 64 and name.replace("_", "").isalnum():
                    found.setdefault(name, text)
                    if len(found) >= limit:
                        return found
        return found

    def find_uid_candidates(self, validator, names: list[str] | None = None) -> dict[str, object]:
        """找出"名字像 uid、值通过 validator"的字段 → {字段名: 值}。

        names 给定时只试这些字段名(精确匹配, 先找字符串对象再找引用它的表) ——
        这是"上次已经学到字段名"后的快速通道, 省掉全部"uid"子串扫描;
        names 为 None 时扫描内存里所有名字含 uid 的短字符串(首次探测的通用通路)。

        用"名字模式 + 取值校验"而不是固定字段名, 是因为游戏改字段名时工具不该整条失效;
        同时它只做只读扫描, 判不出来就返回空, 由调用方决定退回哪种兜底。
        """
        if names:
            targets: list[tuple[str, int]] = []
            for name in names:
                for string_address in self._find_tstrings(name):
                    targets.append((name, string_address))
        else:
            targets = self._uid_like_string_objects()
        if not targets:
            return {}
        # 表头只扫一次(且本次 discovery 内缓存), 所有候选共用
        headers = self._scan_table_headers()
        result: dict[str, object] = {}
        for name, string_address in targets:
            for node in self._find_key_nodes([string_address]):
                for table in self._tables_containing_node(node, headers):
                    # 扫描是启发式的: 候选表里必然混着"看起来像表头、其实是别的数据"的地址,
                    # 读它会抛 unreasonable Lua table size 之类 —— 跳过就好, 绝不能让
                    # 整个"刷新游戏数据"失败。
                    try:
                        value = self.lua.get_table_field_tvalue(table, name)
                        if value is None:
                            continue
                        decoded = self.lua.decode_tvalue(value)
                    except (OSError, ValueError, struct.error):
                        continue
                    if validator(decoded):
                        result[name] = decoded
                        break
                if name in result:
                    break
        return result

    def _scan_table_headers(self) -> list[tuple[int, int, int, int]]:
        """cached 版: 同一个 discovery 内只真扫一次。"""
        if self._headers is None:
            self._headers = self._scan_table_headers_uncached()
        return self._headers

    def _scannable_regions(self) -> list[MemoryRegion]:
        """优先只扫堆(排除几百 MB 的模块映像); 结果缓存, regions() 本身也很贵。

        Lua 表/字符串都在 MEM_PRIVATE 堆上, 模块映像里不可能有 —— 这一步能省掉
        相当一部分读取量。为了不因为平台差异(某些环境不填 Type)而漏掉数据,
        过滤后一无所获时调用方会用全部区域重扫。
        """
        if self._scan_regions is None:
            regions = self.process.regions()
            heap = [region for region in regions if not region.is_image]
            self._scan_regions = heap if heap and len(heap) < len(regions) else regions
        return self._scan_regions

    def _scan_table_headers_uncached(self) -> list[tuple[int, int, int, int]]:
        """一次全内存扫描, 收集所有 8 对齐、tt_==5 的表头。

        返回 [(表地址, lsize_node, node_ptr, node_count), ...]。
        新版本游戏里表头可能离节点数组很远(实测 ~117MB), 必须在堆区域里全扫;
        先只扫堆(跳过模块映像), 一个都没扫到再用全部区域兜底。
        """
        regions = self._scannable_regions()
        headers = self._collect_headers(regions)
        if not headers and len(regions) < len(self.process.regions()):
            headers = self._collect_headers(self.process.regions())
        return headers

    def _collect_headers(self, regions: list[MemoryRegion]) -> list[tuple[int, int, int, int]]:
        headers: list[tuple[int, int, int, int]] = []
        for region in regions:
            offset = 0
            while offset < region.size:
                take = min(4 * 1024 * 1024, region.size - offset)
                block = self.process.try_read(region.base + offset, take)
                if block is None:
                    offset += take
                    continue
                start = (-(region.base + offset)) % 8
                if start + 8 <= len(block):
                    strided = block[start + 8::8]
                    i = strided.find(b"\x05")
                    while i != -1:
                        rel = start + i * 8
                        if rel + 32 > len(block):
                            i = strided.find(b"\x05", i + 1)
                            continue
                        lsize_node = block[rel + 11]
                        if lsize_node <= 24:
                            node_ptr = struct.unpack_from("<Q", block, rel + 24)[0]
                            headers.append((region.base + offset + rel, lsize_node,
                                            node_ptr, 1 << lsize_node))
                        i = strided.find(b"\x05", i + 1)
                offset += take
        return headers

    def _tables_containing_node(
        self, node_address: int, headers: list[tuple[int, int, int, int]] | None = None,
    ) -> list[int]:
        """用一次扫描出的表头列表, 找出 node_ptr 覆盖该节点的表。"""
        if headers is None:
            headers = self._scan_table_headers()
        candidates: list[int] = []
        for addr, _lsize, node_ptr, node_count in headers:
            delta = node_address - node_ptr
            if 0 <= delta < node_count * 32 and delta % 32 == 0:
                candidates.append(addr)
        return candidates

    def find_instance_table(self, field: str, companion_fields: set[str]) -> int:
        strings = self._find_tstrings(field)
        if not strings:
            raise LookupError(f"未找到 Lua 字段字符串 {field}")
        nodes = self._find_key_nodes(strings)
        # 全内存只扫一次, 4 类/所有节点共用同一份表头数据
        headers = self._scan_table_headers()
        checked: set[int] = set()
        candidates_with_field = 0
        max_matches = 0
        best = None
        best_matches = -1
        for node in nodes:
            for table in self._tables_containing_node(node, headers):
                if table in checked:
                    continue
                checked.add(table)
                try:
                    field_value = self.lua.get_table_field_tvalue(table, field)
                    if field_value is None or field_value.tag != TAG_TABLE:
                        continue
                    candidates_with_field += 1
                    matches = sum(
                        self.lua.get_table_field_tvalue(table, name) is not None
                        for name in companion_fields
                    )
                    max_matches = max(max_matches, matches)
                    if matches > best_matches:
                        best_matches = matches
                        best = table
                    # 伴随字段为空时不应静默信任单一匹配
                    required = min(2, len(companion_fields))
                    if companion_fields and matches >= required:
                        return table
                except (OSError, ValueError):
                    continue
        # 宽松回退: 即便伴随字段匹配不足, 只要某个表确实以该字段为表值, 也采用匹配最佳的那个
        if best is not None:
            return best
        raise LookupError(
            f"找到字段 {field}，但无法确认所属的 Lua 实例表。\n\n"
            f"[诊断] 字段字符串 {len(strings)} 个 · 键节点 {len(nodes)} 个 · 候选表 {len(checked)} 个 · "
            f"其中含该字段且为表的有 {candidates_with_field} 个 · 伴随字段最高匹配 {max_matches}/{len(companion_fields)}\n\n"
            "若“含字段为表”>0，说明命中了表但伴随字段校验没通过(可能在游戏里还没打开对应的记录页)；"
            "若为 0，说明定位到的候选表都不含该字段——通常是游戏数据结构/字段名变化。\n\n"
            "请按顺序操作后再试：\n"
            "1. 登录《星塔旅人》并进入游戏主界面；\n"
            "2. 在游戏内依次打开「旅人限时 / 秘纹限时 / 旅人常驻 / 秘纹常驻」四类招募记录页面，"
            "并等待每个列表完整显示；\n"
            "3. 回到本工具点击“刷新游戏数据”。\n\n"
            "若已按上述步骤仍失败，很可能是游戏更新导致 Lua 数据结构变化，"
            "该工具需要匹配新版本后才能读取。")

    def read_target_field(self, field: str, companion_fields: set[str]):
        instance = self.find_instance_table(field, companion_fields)
        value = self.lua.get_table_field_tvalue(instance, field)
        if value is None or value.tag != TAG_TABLE:
            raise LookupError(f"Lua 字段 {field} 不是表")
        try:
            return self.lua.decode_tvalue(value)
        except (OSError, ValueError, struct.error) as err:
            raise LookupError(
                f"Lua 字段 {field} 数据格式异常，可能是游戏版本/内存布局变化"
            ) from err

