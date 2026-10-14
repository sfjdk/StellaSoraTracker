# -*- coding: utf-8 -*-
"""判断正在运行的客户端是哪个语言版本(国服 / 国际服 / 日服)。

为什么需要: 国际服与日服都用 `StellaSora.exe`, 进程名分不出来。但游戏内存里
一定加载着**当前语言的文本**(角色名/秘纹名), 而这几种语言的写法完全不同 ——
在内存里找一找就知道跑的是哪一版:

    110 号旅人: 翡冷翠(cn) / Firenze(en) / フィレン(jp)
    214001 秘纹: 猫神降歌(cn) / Meowing Cat God(en) / 在りし日の記憶(jp)

标记只用**长期不变的角色/秘纹名**(卡池名会换, 不能用)。先把当前设置的语言试一遍,
常见情况一遍扫描就能确认; 命中即返回, 不做多余扫描。
"""

from __future__ import annotations

from time import perf_counter

from .server_config import LANG_TO_SERVER  # 单一来源: 语言 ↔ 版本 key 的映射

# 每种语言取几个稳定名称(角色+秘纹各若干), 命中即可判定
LANG_MARKERS: dict[str, tuple[str, ...]] = {
    "cn": ("翡冷翠", "花原", "埃莉诺", "猫神降歌", "空与花与诗", "你与我相似"),
    "en": ("Firenze", "Nanoha", "Eleanor", "Meowing Cat God", "Sky, Flowers, Poem", "Seed Alike"),
    "jp": ("フィレン", "ナノハ", "エレノア", "在りし日の記憶", "空と花の詩", "似たもの同士"),
}

# 判定力的差别: 假名(日)/汉字(中)在别的语言客户端里基本不会出现, 而英文名是纯
# ASCII —— 资源文件名、调试串里到处都可能有 "Firenze", 所以英文证据最弱:
# 先找中日文证据, 都没有才认英文, 且要求命中 2 个标记。
STRONG_LANGS = ("jp", "cn")
WEAK_LANG = "en"
WEAK_MIN_HITS = 2


def language_markers(lang: str) -> tuple[str, ...]:
    return LANG_MARKERS.get(str(lang or "").strip().lower(), ())


def _hits_for(discovery, lang: str, limit: int, deadline: float | None) -> int:
    hits = 0
    for marker in language_markers(lang)[:limit]:
        if deadline is not None and perf_counter() > deadline:
            return hits
        encoded = marker.encode("utf-8")
        for _address in discovery.process.scan(encoded, discovery._scannable_regions()):
            hits += 1
            break                      # 一个标记命中一次就够, 继续数下一个
    return hits


def detect_language(
    discovery,
    *,
    pinned: str = "",
    deadline: float | None = None,
    markers_per_lang: int = 3,
) -> tuple[str, str]:
    """在游戏内存里判断客户端语言 → (语言 key, 命中的标记)。

    判不出来返回 ("", "")。pinned 是当前设置的语言, 会先试它。
    deadline 是 perf_counter() 的绝对时间上限: 超时就不再继续试其它语言
    (宁可保持当前设置, 也不让刷新卡在这儿)。
    """
    pinned = str(pinned or "").strip().lower()
    strong_order = ([pinned] if pinned in STRONG_LANGS else []) + \
        [lang for lang in STRONG_LANGS if lang != pinned]
    weak_first = pinned == WEAK_LANG
    if weak_first and deadline is not None and perf_counter() > deadline:
        return "", ""
    if weak_first and _hits_for(discovery, WEAK_LANG, WEAK_MIN_HITS, deadline) >= WEAK_MIN_HITS:
        return WEAK_LANG, language_markers(WEAK_LANG)[0]
    for lang in strong_order:
        if deadline is not None and perf_counter() > deadline:
            return "", ""
        if _hits_for(discovery, lang, markers_per_lang, deadline):
            return lang, language_markers(lang)[0]
    if not weak_first:
        if deadline is not None and perf_counter() > deadline:
            return "", ""
        if _hits_for(discovery, WEAK_LANG, WEAK_MIN_HITS, deadline) >= WEAK_MIN_HITS:
            return WEAK_LANG, language_markers(WEAK_LANG)[0]
    return "", ""
