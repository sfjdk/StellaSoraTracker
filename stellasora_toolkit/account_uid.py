# -*- coding: utf-8 -*-
"""从游戏内存里读账号 UID。

为什么需要它: <uid>.json 这种分享文件的名字与 uid 字段都要求先知道账号 UID,
而 UID 之前只能"导入一次带 uid 的文件"才能学到 —— 全新安装永远导不出这个格式。
这里直接从游戏进程的内存里把它读出来。

做法不写死字段名: 扫描内存里所有"名字含 uid"的 Lua 短字符串, 在包含该键的表里
取值, 只接受"纯数字、长度 6-15"的值。判不出来、或者同时出现多个不同值时**不猜** ——
宁可留空让用户手填, 也不能把别人的/错误的 UID 写进导出文件。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .discovery import LuaTableDiscovery

# UID 是纯数字账号号(实测形如 100872990)。判据放宽到 6-15 位, 兼容其它区服。
UID_MIN_DIGITS = 6
UID_MAX_DIGITS = 15

# 已知/更可能的字段名: 命中多个不同值时用它排序, 先给用户看最像的那个。
PREFERRED_FIELDS = (
    "_uid", "_sUid", "_nUid", "uid", "_userUid", "_accountUid",
    "_playerUid", "_roleUid", "_uidStr", "_userId", "_sUserId",
)

# 快速通道先单独试的字段名(每个名字 = 一遍"找名字" + 一遍"找引用"),
# 实测 _uid 这类字段一次就命中, 于是省掉"扫描所有含 uid 的字符串"那一大圈。
QUICK_FIELDS = ("_uid", "_sUid", "_nUid", "uid")


def is_plausible_uid(value: object) -> bool:
    """像不像账号 UID: 纯数字、长度 6-15(布尔不算)。"""
    if isinstance(value, bool):
        return False
    if not isinstance(value, (str, int)):
        return False
    text = str(value).strip()
    return text.isdigit() and UID_MIN_DIGITS <= len(text) <= UID_MAX_DIGITS


def _preference(field_name: str) -> int:
    try:
        return PREFERRED_FIELDS.index(field_name)
    except ValueError:
        return len(PREFERRED_FIELDS)


@dataclass(frozen=True)
class UidSearch:
    """一次 UID 探测的结果。

    uid         最终采用的 UID(没找到或存在歧义时为空串 —— 不猜)
    field_name  采用的字段名(不能叫 field: 会和 dataclasses.field 撞名)
    candidates  (字段名, 值) 列表, 按可信度排序, 用于给用户看/手选
    ambiguous   探测到多个不同值(此时 uid 为空, 交给用户确认)
    """

    uid: str = ""
    field_name: str = ""
    candidates: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    ambiguous: bool = False

    @property
    def found(self) -> bool:
        return bool(self.uid)

    def summary(self) -> str:
        if self.found:
            return f"UID {self.uid}（游戏内存字段 {self.field_name}）"
        if self.ambiguous:
            pairs = "、".join(f"{name}={value}" for name, value in self.candidates[:4])
            return f"检测到多个候选 UID，需要手动确认：{pairs}"
        return "游戏内存里没有找到账号 UID"


def find_account_uid(
    discovery: LuaTableDiscovery,
    *,
    preferred: str = "",
    field_hint: str = "",
) -> UidSearch:
    """在游戏内存里找账号 UID。

    preferred  已知的 UID(手填/归档里记着的)。作用有两层:
               1. 候选里有它就优先采信它 —— "多候选"场景也能自动选对;
               2. 名字里带 uid 的字段一个都没命中时, 按这个值反查真实字段名
                  (游戏里的字段可能叫 _roleId 之类, 光靠名字扫不到)。
    field_hint 上次学到的字段名: 先只试它(精确匹配, 便宜很多), 命中就直接返回,
               不再做"扫描全部含 uid 的字符串"那一步。

    两者都没有则返回空结果, 由调用方兜底(手填或导入)。
    """
    if field_hint:
        hint_values: list[str] = []
        for value in discovery.find_uid_candidates(is_plausible_uid, names=[field_hint]).values():
            hint_values.append(str(value).strip())
        if hint_values and (not preferred or preferred in hint_values):
            uid = preferred if preferred in hint_values else hint_values[0]
            return UidSearch(uid=uid, field_name=field_hint,
                             candidates=tuple((field_hint, value) for value in hint_values))

    # 快速通道: 逐个试最可能的字段名, 命中就收工(通常只花一两遍扫描)。
    # 两个快速字段给出的值不一致时视为歧义 —— 宁可让用户确认, 也不要写错 UID。
    quick: dict[str, str] = {}
    for name in QUICK_FIELDS:
        for value in discovery.find_uid_candidates(is_plausible_uid, names=[name]).values():
            quick[str(name)] = str(value).strip()
    if quick:
        values = set(quick.values())
        if len(values) == 1:
            uid = preferred if preferred in values else next(iter(values))
            if not preferred or uid == preferred:
                field_name = next(name for name, value in quick.items() if value == uid)
                return UidSearch(uid=uid, field_name=field_name, candidates=tuple(quick.items()))
        elif not preferred:
            ordered = tuple(sorted(quick.items(), key=lambda item: _preference(item[0])))
            return UidSearch("", "", ordered, True)

    raw = discovery.find_uid_candidates(is_plausible_uid)
    pairs = {str(name): str(value).strip() for name, value in raw.items()}
    if preferred and preferred not in pairs.values():
        pairs.update(discovery.find_fields_with_value(preferred))
    if not pairs:
        return UidSearch()
    ordered = tuple(sorted(pairs.items(), key=lambda item: (_preference(item[0]), len(item[0]), item[0])))
    values = {value for _name, value in ordered}

    if preferred and preferred in values:
        field_name = next(name for name, value in ordered if value == preferred)
        return UidSearch(preferred, field_name, ordered, len(values) > 1)
    if len(values) == 1:
        field_name, value = ordered[0]
        return UidSearch(value, field_name, ordered, False)
    # 多个不同值: 不猜, 把候选交给用户确认
    return UidSearch("", "", ordered, True)
