# -*- coding: utf-8 -*-
"""
自动检测并注册新五星角色/秘纹(查询缺失 -> 自动补全 -> 对应 -> 对齐校验)。

背景: catalog.py 的静态表 (TRAVELER_NAMES / FIVE_STAR_TRAVELERS / FIVE_STAR_DISCS)
跟随软件版本内置更新, 但游戏更新新池子时, 新五星的 ID/名称在清单发布前是未知的。
例如 139 艾蕾(限时池 10139)上线时静态表里没有它, is_five_star_item 会把它的
五星结果当成普通记录 —— register_gacha_resource() 就是为这种在线补登记准备的。
(静态表本身也要跟得上: 漏登记的 id 在离线时没有任何补救手段, 见
tests/test_catalog_alignment.py 的离线对齐校验。)

通路一(启动后台): sync_catalog() —— 静默增强, 任何失败都退回"内置清单"的旧行为;
通路二(手动同步): sync_with_report() —— 返回结构化报告, 由界面弹窗展示:
    查询缺失(未注册五星) -> 自动补全(注册名称/下载头像) -> 对应(按 ID 回填)
    -> 对齐校验 audit_alignment()(序号回显 / 五星判定错位 / ID 冲突)。
两者共用 _sync_once() 一次真实执行。

下载失败/网络异常全部静默 —— 这是增强功能, 任何失败都退回"内置清单"的旧行为。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

from . import server_config
from .catalog import (
    DISC_NAMES, TRAVELER_NAMES, gacha_item_name, is_five_star_item, is_gacha_item,
    register_gacha_resource,
)
from .resource_manager import STELLABASE_API, STELLABASE_ASSET_API

ProgressCallback = Callable[[str], None]

# characters/discs 的返回体很大(秘纹连剧情全文一起返回), 实测同一台机器上 20 秒经常
# 读不完、直接得到 0 字节。以前只试一次且失败静默返回空, 界面于是显示"资源库无缺失",
# 用户完全看不出自动更新其实没跑起来 —— 这里改成带重试的较长超时。
READ_TIMEOUT = 60.0
READ_ATTEMPTS = 3
CATALOG_CACHE_FILENAME = "stellasora_catalog_cache.json"

# 最近一次五星目录查询失败了几路(0/1/2); 供界面区分"没有缺失"与"根本没查到"。
_fetch_failures = 0


def fetch_failures() -> int:
    """最近一次五星目录查询失败的端点数(0 = 全部成功)。"""
    return _fetch_failures


def _read_url(url: str, progress: ProgressCallback | None = None,
              timeout: float = READ_TIMEOUT, attempts: int = READ_ATTEMPTS) -> bytes:
    """读一个 URL, 失败重试; 全部失败返回 b""(调用方按"查询失败"处理)。"""
    request = Request(url, headers={"User-Agent": "StellaSoraToolkit/1.0", "Accept": "application/json"})
    for attempt in range(max(1, attempts)):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except OSError:
            if attempt + 1 < attempts:
                if progress:
                    progress(f"资源查询超时，正在重试 {attempt + 2}/{attempts}")
                time.sleep(1.5 * (attempt + 1))
    return b""


def _catalog_cache_path(state_path: Path | None) -> Path | None:
    """五星目录缓存与同步状态同目录(exports/)。"""
    return Path(state_path).with_name(CATALOG_CACHE_FILENAME) if state_path else None


def _save_catalog_cache(path: Path | None, items: list[dict]) -> None:
    if path is None or not items:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _load_catalog_cache(path: Path | None) -> list[dict]:
    """上次成功查到的五星目录; 缺失/损坏返回 []。"""
    if path is None:
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and "id" in item and "kind" in item]


def _fetch_five_star_catalog(progress: ProgressCallback | None = None) -> list[dict]:
    """拉取 characters + discs, 只保留五星。返回条目: id/kind/name/icon(相对路径)。

    lang 取当前激活版本(server_config), 因此注册进名称表的名称语言与游戏一致。
    那一路查询失败时记进 fetch_failures() —— 空的目录不代表"没有新五星"。
    """
    global _fetch_failures
    items: list[dict] = []
    _fetch_failures = 0
    lang = server_config.api_lang()
    for endpoint, kind, rarity_key in (
        (f"characters?lang={lang}", "traveler", "grade"),
        (f"discs?lang={lang}", "disc", "star"),
    ):
        payload = _read_url(f"{STELLABASE_API}/{endpoint}", progress)
        if not payload:
            _fetch_failures += 1
            continue
        try:
            rows = json.loads(payload.decode("utf-8"))
        except ValueError:
            _fetch_failures += 1
            continue
        if not isinstance(rows, list):
            _fetch_failures += 1
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                item_id = int(row["id"])
                rarity = int(row.get(rarity_key, 0))
            except (KeyError, TypeError, ValueError):
                continue
            icon = str(row.get("icon") or "")
            portrait = str(row.get("portrait") or "")
            # icon(圆形小图标)优先, 缺失时回退 portrait(半身立绘), 两者都没有才丢弃
            if rarity < 5:
                continue
            # BOSS/剧情单位(魔侍巨像等)在角色接口里也是 grade=5, 但抽不到, 不能注册
            if not is_gacha_item(item_id):
                continue
            if not (icon.startswith("/stella/assets/") or portrait.startswith("/stella/assets/")):
                continue
            items.append({
                "id": item_id,
                "kind": kind,
                "name": str(row.get("name") or f"{kind} #{item_id}"),
                "icon": icon or portrait,
            })
    return items


def asset_root() -> Path:
    """与 widgets.AvatarLabel 读取路径保持一致, 保证下载的图立即可显示。

    本模块位于 stellasora_toolkit/ 下, 项目根需要两级 parent
    (widgets.py 是三级, 因为它多了一层 ui/ —— 别拿它当模板)。

    可用环境变量 SSTEMU_ASSETS_DIR 覆盖 —— 安卓上 APK 内的路径只读，
    下载的图必须落到应用私有目录。
    """
    import os
    import sys
    override = os.environ.get("SSTEMU_ASSETS_DIR")
    if override:
        return Path(override)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


def _download_icon(source_url: str, target: Path, progress: ProgressCallback | None = None) -> bool:
    """下载单张图到 target; 已存在/校验失败/目标扩展名不合法都返回 False。

    校验 PNG 魔数: 站点代理失败时可能返回错误页/HTML, 不能写入 .png 文件
    (否则界面永远读不出头像)。

    落盘用"临时文件 + 原子替换": 直接 write_bytes 的话, 后台同步线程与
    请求线程并发时, 读图的那一方会拿到半张 PNG; 更糟的是上面的
    "已存在即跳过"守卫只看 size>0, 会把半写文件当成完整的图【永久缓存】。
    """
    if target.exists() and target.stat().st_size > 0:
        return False
    payload = _read_url(source_url, progress)
    if not payload.startswith(b"\x89PNG"):
        return False
    temp: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=target.parent, suffix=".part")
        temp = Path(name)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(temp, target)
        return True
    except OSError:
        if temp is not None:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
        return False


def _load_seen(state_path: Path | None) -> set[int]:
    if state_path is None:
        return set()
    try:
        import json as _json
        payload = _json.loads(state_path.read_text(encoding="utf-8"))
        return {int(i) for i in payload.get("seen", [])}
    except (OSError, ValueError, TypeError, KeyError):
        return set()


def _save_seen(state_path: Path | None, seen: set[int]) -> None:
    if state_path is None:
        return
    import json as _json
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            _json.dumps({"seen": sorted(seen)}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def audit_alignment(fetched: list[dict], record_ids: list[int]) -> dict:
    """
    对齐校验: 序号(物品 ID) <-> 角色(名称/星级/类别) 是否一一对应。

    校验口径:
    1. 序号回显 —— 抽卡记录里的每个序号都必须能回显名称,
       "旅人 #137"/"物品 #137" 这类占位符 = 未对齐;
    2. 星级错位 —— API 确认五星的条目, is_five_star_item() 必须为 True,
       否则该五星结果会被当成普通记录(概率/保底统计错位);
    3. ID 冲突 —— 同一序号不得同时出现在角色表与秘纹表(对应关系必须唯一)。

    返回:
        {"unresolved": [id...], "misjudged": [{id, kind, name}...], "clash": [{id, kind, name}...]}
    """
    unresolved: list[int] = []
    for row_id in record_ids:
        if "#" in gacha_item_name(row_id):
            unresolved.append(row_id)
    misjudged: list[dict] = []
    clash: list[dict] = []
    for item in fetched:
        if not is_five_star_item(item["id"]):
            misjudged.append(dict(item))
        other = DISC_NAMES if item["kind"] == "traveler" else TRAVELER_NAMES
        if item["id"] in other:
            clash.append(dict(item))
    return {"unresolved": unresolved, "misjudged": misjudged, "clash": clash}


def needs_online_lookup(record_ids) -> bool:
    """记录里还有没有"不认识"的序号 —— 有才值得联网查五星目录。

    判据: 这个序号显示出来还是占位符("旅人 #137" / "物品 #999" / "秘纹 #214999")。
    全是已认识的序号时, 在线查询不可能带来新信息, 直接跳过 —— 这是刷新速度的
    主要优化: 省掉两个大接口(实测单次就可能几十秒)与超时重试。

    启动时的后台同步(不带 record_ids)仍会正常联网, 所以"发现新五星角色"
    这条通路不受影响。
    """
    for row_id in record_ids:
        try:
            item_id = int(row_id)
        except (TypeError, ValueError):
            continue
        if "#" in gacha_item_name(item_id):
            return True
    return False


def _sync_once(
    state_path: Path | None,
    progress: ProgressCallback | None,
    record_ids: list[int] | tuple[int, ...] = (),
) -> dict:
    """执行一次完整同步(查询缺失 -> 注册补全 -> 下载头像), 返回结构化报告。

    报告字段:
        fetched_travelers/fetched_discs  API 五星目录规模(查询);
        missing_before                  名称表缺失的五星条目(查询: 缺什么);
        registered                      本次注册条目的 (id, kind, name);
        downloaded                      本次新下载的头像 PNG;
        existing                       已存在于本地资源目录的头像(如游戏内提取);
        icon_failed                     注册成功但头像下载失败的条目;
        appeared                        首次发现(state 文件从未记录过);
        record_count                    参与对齐校验的抽卡记录序号数;
        audit_before/audit_after        注册前后各一次对齐校验, 前后对比即"是否自动对齐";
        skipped_online                  序号都认识, 本次跳过了在线查询。
    """
    seen = _load_seen(state_path)
    ids = [int(row_id) for row_id in record_ids if str(row_id).lstrip("-").isdigit()]
    skip_online = bool(ids) and not needs_online_lookup(ids)
    cache_path = _catalog_cache_path(state_path)
    from_cache = False
    if skip_online:
        if progress:
            progress("记录的序号都已认识，跳过在线查询")
        fetched: list[dict] = []
        failures = 0
        audit_before = audit_alignment(fetched, ids)
    else:
        if progress:
            progress("正在查询五星目录...")
        fetched = _fetch_five_star_catalog(progress)
        failures = fetch_failures()
    if fetched:
        _save_catalog_cache(cache_path, fetched)
    elif not skip_online:
        # 一路都没查到(离线/超时): 用上次成功的目录, 至少把缺的头像补齐,
        # 而不是把"没查到"当成"没有缺失"。
        cached = _load_catalog_cache(cache_path)
        if cached:
            fetched = cached
            from_cache = True
            if progress:
                progress(f"在线查询失败，改用上次缓存的五星目录（{len(cached)} 项）")
    if not skip_online:
        audit_before = audit_alignment(fetched, ids)

    names_by_kind = {"traveler": TRAVELER_NAMES, "disc": DISC_NAMES}
    missing_before = [dict(it) for it in fetched if it["id"] not in names_by_kind[it["kind"]]]
    registered: list[dict] = []
    downloaded: list[dict] = []
    existing: list[dict] = []
    icon_failed: list[dict] = []
    appeared: list[dict] = []
    for item in fetched:
        item_id, kind = item["id"], item["kind"]
        is_new = item_id not in seen
        seen.add(item_id)
        was_missing = item_id not in names_by_kind[kind]
        # 名称始终以本版 API 语言覆盖注册: 切换国服/国际服后, 下一次同步即换语言
        # (同语言重复写入为幂等操作); 报告里的 "registered" 仍只统计真正缺失的条目。
        register_gacha_resource(item_id, kind, item["name"], rarity=5)
        if was_missing:
            registered.append(dict(item))
            if is_new:
                appeared.append(dict(item))
        # 图片自动补全: 与注册解耦 —— 名称已注册但本地缺 PNG 的五星同样会下载,
        # 已存在(如游戏内提取/内置打包)则记入 existing, 不重复下载。
        target = asset_root() / ("travelers" if kind == "traveler" else "discs") / f"{item_id}.png"
        if target.exists() and target.stat().st_size > 0:
            existing.append(dict(item))
            continue
        if _download_icon(f"{STELLABASE_ASSET_API}{item['icon']}", target, progress):
            downloaded.append(dict(item))
        else:
            icon_failed.append(dict(item))
    _save_seen(state_path, seen)
    audit_after = audit_alignment(fetched, ids)
    return {
        "fetched_total": len(fetched),
        "fetched_travelers": sum(1 for it in fetched if it["kind"] == "traveler"),
        "fetched_discs": sum(1 for it in fetched if it["kind"] == "disc"),
        "record_count": len(ids),
        "skipped_online": skip_online,
        "fetch_failed": failures,
        "catalog_from_cache": from_cache,
        "missing_before": missing_before,
        "registered": registered,
        "downloaded": downloaded,
        "existing": existing,
        "icon_failed": icon_failed,
        "appeared": appeared,
        "audit_before": audit_before,
        "audit_after": audit_after,
    }


def sync_catalog(
    state_path: Path | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    同步一次(启动后台静默调用), 返回 (新出现条目, 新下载图片条目)。

    语义:
    - 新出现: 名称表(TRAVELER_NAMES/DISC_NAMES)里没有、且上次同步 state 里也没见过的五星条目
      → 仅用于"首次发现提示", 不会每次启动都弹框;
    - 注册: 凡名称表缺失的五星条目都会注册(幂等, 修复 is_five_star_item 漏判);
    - 新下载: 资源目录中不存在的头像 PNG。
    """
    report = _sync_once(state_path, progress)
    return report["appeared"], report["downloaded"]


def sync_with_report(
    state_path: Path | None = None,
    record_ids: list[int] | tuple[int, ...] | None = None,
    progress: ProgressCallback | None = None,
) -> dict:
    """手动同步入口: 同 sync_catalog 的执行逻辑, 但返回完整报告(含对齐校验前后对比)。"""
    return _sync_once(state_path, progress, record_ids or ())
