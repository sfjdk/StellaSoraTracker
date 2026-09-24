# -*- coding: utf-8 -*-
"""
官方限时卡池信息的自动获取。

StellaBase 公开接口 /api/stella/banners 提供全部卡池的最新信息:
    id / name / bannerType / startTime / endTime / rateUp.fiveStar.entries[].name

工具旧版本把卡池信息写在 ui/constants.py 的 OFFICIAL_LIMITED_POOL_INFO 静态表里,
每次游戏更新卡池都要手动编辑。本模块把它变成运行时自动拉取:

- fetch_banners()           拉取并解析为与静态表相同的 {gid: (名称, 开始, 结束, UP名)};
- save_banners/load_banners 落盘缓存到 output_dir/official_banners_<版本>.json, 离线也可用;
- official_pool_info(gid)  合成查询: 动态数据优先, 静态表兜底(网络完全不可用时仍有旧数据可用)。

语言: `lang` 参数取当前激活的游戏版本(server_config), 国服 cn / 国际服 en,
因此卡池名与 UP 名会与本机抽卡记录的名字语言一致。

软件运行时行为: 窗口启动后后台线程拉取一次并写缓存; 期间(以及离线时)查询均同步成功。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from . import server_config
from .ui.constants import OFFICIAL_LIMITED_POOL_INFO

BANNERS_API_URL = "https://stella.ennead.cc/api/stella/banners"


def cache_filename() -> str:
    """按当前版本区分缓存文件, 切换服务器时不会读到另一版本的卡池数据。"""
    return f"official_banners_{server_config.active().key}.json"

# 进程内动态表: gid -> (名称, 开始日期, 结束日期, UP名); None 表示尚未加载
_active: dict[int, tuple[str, str, str, str]] | None = None


def set_active_banners(banners: dict[int, tuple[str, str, str, str]]) -> None:
    global _active
    _active = banners


def _date_part(value: str) -> str:
    """'2026-09-08T12:00:00+08:00' -> '2026-09-08'(与静态表日期格式一致)。"""
    return str(value)[:10]


def _up_names(banner: dict[str, Any]) -> str:
    """rateUp.fiveStar.entries 里的第一个五星名字(UP 判定只需名字, 且旧版格式只有一个)。"""
    try:
        entries = banner.get("rateUp", {}).get("fiveStar", {}).get("entries") or []
        return str(entries[0].get("name", ""))
    except (AttributeError, IndexError, TypeError):
        return ""


def parse_banners(payload: list[dict]) -> dict[int, tuple[str, str, str, str]]:
    """API JSON -> {gid: (名称, 开始, 结束, UP名)}。空条目丢弃。"""
    result: dict[int, tuple[str, str, str, str]] = {}
    for banner in payload:
        try:
            gid = int(banner["id"])
        except (KeyError, TypeError, ValueError):
            continue
        btype = str(banner.get("bannerType") or "")
        # 只保留四个历史分类之外的说明: 常驻池(bannerType 含"常驻"/"Permanent")可以在 API 里,
        # 但静态表/界面只关心限时池; 这里全部收录由调用方按需使用。
        name = str(banner.get("name") or f"卡池 {gid}")
        start = _date_part(str(banner.get("startTime") or ""))
        end = _date_part(str(banner.get("endTime") or ""))
        if btype and ("常驻" in btype or "permanent" in btype.casefold()):
            continue  # 常驻池不走 UP 展示, 保持与静态表一致(兼容国服/国际服文案)
        result[gid] = (name, start, end, _up_names(banner))
    return result


def fetch_banners(timeout: float = 20.0, lang: str | None = None) -> dict[int, tuple[str, str, str, str]]:
    """联网拉取; 失败(超时/解析错误/网络不可用)抛 OSError, 调用方自行兜底。

    lang 默认取当前激活版本(server_config.api_lang()): 国服 cn / 国际服 en, 名称语言一致。
    """
    lang = lang or server_config.api_lang()
    request = Request(f"{BANNERS_API_URL}?lang={lang}", headers={"User-Agent": "StellaSoraToolkit/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or "current" not in payload:
        raise ValueError("banners API response is not a list")
    banners = parse_banners(payload["current"] + payload.get("upcoming", []) + payload.get("ended", []))
    return banners


def save_banners(banners: dict[int, tuple[str, str, str, str]], cache_path: Path) -> None:
    """把动态表写盘, 下次启动离线可用。"""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "banners": [
            {"gid": gid, "name": name, "start": start, "end": end, "up": up}
            for gid, (name, start, end, up) in sorted(banners.items())
        ],
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_banners(cache_path: Path) -> dict[int, tuple[str, str, str, str]]:
    """读缓存; 文件缺失/损坏返回空 dict(此时由静态表兜底)。"""
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return {
            int(row["gid"]): (str(row["name"]), str(row["start"]), str(row["end"]), str(row["up"]))
            for row in payload.get("banners", [])
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def official_pool_info(gid: int) -> tuple[str, str, str, str] | None:
    """视图层统一查询: 动态数据(本次拉取/缓存)优先, 静态表兜底。"""
    if _active is not None and gid in _active:
        return _active[gid]
    return OFFICIAL_LIMITED_POOL_INFO.get(gid)


def active_banners() -> dict[int, tuple[str, str, str, str]]:
    """当前生效的卡池表(动态优先; 未加载动态表时为内置静态表)。

    供**反向查询**使用 —— 例如截图 OCR 只拿到卡池名, 需要由名字反推 Gid。
    """
    return dict(_active) if _active else dict(OFFICIAL_LIMITED_POOL_INFO)


def refresh_from_network(cache_path: Path) -> bool:
    """后台线程用: 拉取 -> 写缓存 -> 更新进程内表。失败静默返回 False(静态表兜底)。"""
    try:
        banners = fetch_banners()
        save_banners(banners, cache_path)
        set_active_banners(banners)
        return True
    except (OSError, ValueError):
        return False
