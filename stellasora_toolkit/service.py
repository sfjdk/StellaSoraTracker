from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable, Iterable

from . import server_config
from .account_uid import UidSearch, find_account_uid
from .discovery import LuaTableDiscovery
from .exporter import (
    export_all,
    extract_uid,
    normalize_category_keys,
    parse_import_text,
    sanitize_gacha_categories,
)
from .lua53 import Lua53Reader
from .process import RemoteProcess, find_process_id, running_processes


ProgressCallback = Callable[[str], None]
ARCHIVE_FILENAME = "stellasora_gacha_archive.json"
UID_FILENAME = "uid.json"

# UID 只用来命名分享文件, 必须挡掉路径穿越等奇怪输入
UID_ALLOWED = set("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_-")


@dataclass(frozen=True)
class Snapshot:
    gacha: list[dict]
    emblems: list[dict] = field(default_factory=list)
    files: tuple[Path, ...] = ()
    gacha_categories: dict[int, list[dict]] = field(default_factory=dict)
    uid: str = ""
    uid_note: str = ""
    share_file: Path | None = None

    @property
    def pull_count(self) -> int:
        return sum(len(group.get("Ids", [])) for group in self.gacha)

    @property
    def character_count(self) -> int:
        return len({item.get("nCharId") for item in self.emblems if item.get("nCharId") is not None})


def read_game_uid(
    output_dir: Path,
    progress: ProgressCallback | None = None,
    process_name: str | Iterable[str] | None = None,
) -> UidSearch:
    """只读探测: 从游戏内存里找账号 UID(设置页「从游戏读取 UID」按钮用)。

    除 uid.json 里记下学到的字段名(下次直接走快速通道)外不做任何写入 ——
    是否采信这个 UID 由界面决定(歧义时让用户确认)。
    """
    report = progress or (lambda _message: None)
    profile, note, running_keys = detect_and_apply(output_dir)
    if note:
        report(note)
    if process_name is not None:
        names = process_name
    elif not running_keys:
        names = [n for prof in server_config.PROFILES.values() for n in prof.client_names]
    else:
        names = profile.client_names
    pid = find_process_id(names)
    report(f"已连接游戏进程 PID {pid}，正在扫描账号 UID")
    with RemoteProcess(pid) as process:
        lua = Lua53Reader(process)
        discovery = LuaTableDiscovery(process, lua)
        try:
            search = find_account_uid(discovery, preferred=effective_uid(output_dir),
                                      field_hint=load_uid_field(output_dir))
        except Exception as err:                               # noqa: BLE001
            report(f"UID 探测中断: {err}")
            return UidSearch()
    if search.found:
        save_uid_field(output_dir, search.field_name)
    return search


def probe_running_keys() -> list[str]:
    """只探测: 当前正在运行的客户端版本 key 列表(探测失败/无客户端返回 [])。"""
    try:
        running_names = [name for name, _pid in running_processes()]
    except OSError:
        return []
    return server_config.resolve_running(running_names)[1]


def detect_and_apply(output_dir: Path | None = None) -> tuple[server_config.ServerProfile, str, list[str]]:
    """自动检测运行中的游戏客户端并确定读取版本(国服/国际服)。

    规则("一个自动选, 两个手动选"):
    - 恰好一种客户端在运行 → 自动切换为该版本并持久化到 server.json;
    - 两者都运行 → 保持当前(设置页所选/--server)版本, 返回提示(界面在"刷新数据"时
      会事先弹窗让用户选定, 此路径是 CLI/兜底);
    - 没有客户端运行 → 保持当前版本, 返回空提示(后续按"未找到进程"正常报错)。

    返回 (生效版本, 状态提示(空串为无需显示), 正在运行的版本 key 列表)。
    """
    running_keys = probe_running_keys()
    profile = server_config.PROFILES[running_keys[0]] if len(running_keys) == 1 else None
    if profile is None:
        if len(running_keys) == 2:
            labels = " 与 ".join(server_config.PROFILES[k].label for k in running_keys)
            current = server_config.active()
            return current, (
                f"同时检测到 {labels} 客户端, 按设置页所选(或 --server)读取 {current.label}"
            ), running_keys
        return server_config.active(), "", running_keys
    if profile.key != server_config.active().key:
        server_config.set_active(profile.key)
        if output_dir is not None:
            server_config.save_key(server_config.config_path(output_dir), profile.key)
        return profile, f"自动检测到 {profile.label} 客户端（{profile.client_names[0]}）, 已自动切换", running_keys
    server_config.set_active(profile.key)  # 已在运行也应保持一致(幂等)
    return profile, "", running_keys


def extract_snapshot(
    output_dir: Path,
    process_name: str | Iterable[str] | None = None,
    progress: ProgressCallback | None = None,
) -> Snapshot:
    """读取当前游戏版本的招募快照。

    process_name 为 None 时自动检测运行中的客户端(国服 xtlr.exe / 国际服 StellaSora.exe):
    恰好一个客户端时自动切换版本; 两个客户端并存时沿用设置页所选版本。
    显式传入 process_name 时直接使用, 不做版本切换。Lua 字段名取自当前版本配置。
    """
    report = progress or (lambda _message: None)
    target = output_dir.resolve()
    payload = read_archive_payload(target)
    # UID 决定分享文件名: 设置页手填的优先, 其次是归档里记着的(导入时学到的)
    uid = load_manual_uid(target) or extract_uid(payload)
    uid_note = "沿用已保存的 UID" if uid else ""
    search = UidSearch()

    profile, note, running_keys = detect_and_apply(output_dir)
    if note:
        report(note)
    if process_name is not None:
        names = process_name
    elif not running_keys:
        # 没有任何客户端在运行: 报错信息列出两版全部候选, 更便于提示
        names = [n for prof in server_config.PROFILES.values() for n in prof.client_names]
    else:
        names = profile.client_names
    pid = find_process_id(names)
    report(f"已连接游戏进程 PID {pid}，正在定位招募数据")
    started = perf_counter()
    with RemoteProcess(pid) as process:
        lua = Lua53Reader(process)
        discovery = LuaTableDiscovery(process, lua)
        if not uid:
            # 还不知道 UID 时才去内存里找(要额外扫描, 有成本);
            # field_hint 是上次学到的字段名: 命中就直接用, 不再全内存找"uid"。
            # 这是增强功能: 探测本身出任何问题都必须放过, 不能连累招募数据读取。
            report("正在从游戏内存读取账号 UID")
            try:
                search = find_account_uid(discovery, field_hint=load_uid_field(target))
            except Exception:                                  # noqa: BLE001
                search = UidSearch()
            if search.found:
                uid = search.uid
                uid_note = f"从游戏内存读取（字段 {search.field_name}）"
                save_uid_field(target, search.field_name)
        raw_gacha = discovery.read_target_field(
            profile.gacha_field,
            set(profile.gacha_companions),
        )
    locate_seconds = perf_counter() - started
    report(f"招募数据读取完成（{locate_seconds:.1f}s），正在生成本地 JSON 和 CSV")
    current_categories = sanitize_gacha_categories(raw_gacha)
    categories = merge_gacha_categories(_categories_from_payload(payload), current_categories)
    gacha = [group for groups in categories.values() for group in groups]
    files = list(export_all(target, gacha, None, categories, uid=uid))
    _write_archive(target, categories, uid=uid)
    # 每次刷新都产出与分享文件同格式的 <uid>.json
    share = write_share_file(target, categories, uid)
    if share is not None:
        files.append(share)
    if not uid_note and share is not None:
        uid_note = "沿用已保存的 UID"
    if not uid and search.ambiguous:
        uid_note = search.summary()
    return Snapshot(gacha, [], tuple(files), categories,
                    uid=uid, uid_note=uid_note, share_file=share)


def _group_key(group: dict) -> tuple:
    ids = group.get("Ids", [])
    if isinstance(ids, dict):
        ids = list(ids.values())
    return (
        group.get("Gid"),
        group.get("Time"),
        tuple(ids) if isinstance(ids, list) else str(ids),
    )


def merge_gacha_categories(
    archived: dict[int, list[dict]],
    current: dict[int, list[dict]],
) -> dict[int, list[dict]]:
    merged: dict[int, list[dict]] = {}
    for category in sorted(set(archived) | set(current)):
        by_key = {_group_key(group): group for group in archived.get(category, [])}
        by_key.update({_group_key(group): group for group in current.get(category, [])})
        merged[category] = sorted(
            by_key.values(),
            key=lambda group: (int(group.get("Time") or 0), int(group.get("Gid") or 0)),
        )
    return {category: groups for category, groups in merged.items() if groups}


def read_archive_payload(output_dir: Path) -> dict:
    """读归档的完整 payload(version / uid / updatedAt / categories)。

    归档不存在或读坏时退回最近一次带时间戳的导出 —— 老用户是从
    stellasora_gacha_*.json 升上来的, 不该因为少一个归档文件名就丢数据。
    读不到任何东西返回 {}。
    """
    archive = output_dir / ARCHIVE_FILENAME
    try:
        payload = json.loads(archive.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        files = sorted(
            (path for path in output_dir.glob("stellasora_gacha_*.json") if path.name != ARCHIVE_FILENAME),
            key=lambda path: path.stat().st_mtime,
        )
        if not files:
            return {}
        try:
            payload = json.loads(files[-1].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return payload if isinstance(payload, dict) else {}


def _categories_from_payload(payload: dict) -> dict[int, list[dict]]:
    categories = payload.get("categories", {}) if isinstance(payload, dict) else {}
    if not isinstance(categories, dict) or not categories:
        return {}
    return {int(key): value for key, value in categories.items() if isinstance(value, list)}


def load_archive_uid(output_dir: Path) -> str:
    """归档里记着的 uid; 没记过返回空串。"""
    return extract_uid(read_archive_payload(output_dir))


def normalize_uid(value: Any) -> str:
    """校验/规整 UID; 含非法字符返回空串(它会被拿去当文件名)。"""
    text = str(value or "").strip()
    if not text or len(text) > 64 or any(ch not in UID_ALLOWED for ch in text):
        return ""
    return text


def _read_uid_config(output_dir: Path) -> dict:
    """uid.json: {"uid": 手填的 UID, "field": 内存里学到的字段名}。"""
    try:
        payload = json.loads((Path(output_dir) / UID_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_uid_config(output_dir: Path, payload: dict) -> bool:
    path = Path(output_dir) / UID_FILENAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(path, payload)
        return True
    except OSError:
        return False


def load_manual_uid(output_dir: Path) -> str:
    """设置页手填的 UID(uid.json); 没有/损坏返回空串。"""
    return normalize_uid(_read_uid_config(output_dir).get("uid"))


def save_manual_uid(output_dir: Path, uid: str) -> bool:
    """写 uid.json 的 uid(空串表示清除), 保留已学到的字段名。写盘失败返回 False。"""
    payload = _read_uid_config(output_dir)
    payload["uid"] = normalize_uid(uid)
    return _write_uid_config(output_dir, payload)


def load_uid_field(output_dir: Path) -> str:
    """上次在游戏内存里学到的 UID 字段名(下次直接走快速通道); 没有返回空串。"""
    text = str(_read_uid_config(output_dir).get("field") or "").strip()
    if not text or len(text) > 32 or not text.replace("_", "").isalnum():
        return ""
    return text


def save_uid_field(output_dir: Path, field_name: str) -> bool:
    """记住 UID 字段名(保留手填的 uid)。名字非法返回 False。"""
    text = str(field_name or "").strip()
    if not text or len(text) > 32 or not text.replace("_", "").isalnum():
        return False
    payload = _read_uid_config(output_dir)
    if payload.get("field") == text:
        return True
    payload["field"] = text
    return _write_uid_config(output_dir, payload)


def effective_uid(output_dir: Path) -> str:
    """当前生效的 UID: 设置页手填的优先, 否则用归档里记着的(导入分享文件时学到的)。"""
    return load_manual_uid(output_dir) or load_archive_uid(output_dir)


def load_archive_categories(output_dir: Path) -> dict[int, list[dict]]:
    """本地归档的分类表(供界面直接使用)。"""
    return _categories_from_payload(read_archive_payload(output_dir))


def refresh_share_file(output_dir: Path) -> Path | None:
    """按当前归档与 UID 重新产出 <uid>.json(没 UID 或没记录时返回 None)。

    启动时与学到 UID 后都可以直接调用 —— 不用点按钮, 文件总是最新的。
    """
    output_dir = Path(output_dir)
    categories = load_archive_categories(output_dir)
    if not categories:
        return None
    uid = effective_uid(output_dir)
    if not uid:
        return None
    return write_share_file(output_dir, categories, uid)


def write_share_file(output_dir: Path, categories: dict[int, list[dict]], uid: str) -> Path | None:
    """生成与网页版/分享文件完全同格式的 <uid>.json。

    键与顺序都和分享文件一致: version / uid / updatedAt / categories。
    UID 未知(没填过也没导入过带 uid 的文件)时不生成, 返回 None。
    """
    uid = normalize_uid(uid)
    if not uid:
        return None
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{uid}.json"
    _write_json_atomic(path, _archive_payload(categories, uid))
    return path


def count_pulls(categories: dict[int, list[dict]]) -> int:
    """分类表里的总抽数(Ids 个数)。"""
    return sum(len(group.get("Ids") or []) for groups in categories.values() for group in groups)


def _write_json_atomic(path: Path, payload: dict) -> None:
    """临时文件 + 原子替换: 中途崩溃不会留下半截 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _archive_payload(categories: dict[int, list[dict]], uid: str = "") -> dict:
    """归档/分享文件的统一外壳(键与顺序: version / uid / updatedAt / categories)。"""
    payload: dict = {"version": 1}
    if uid:
        payload["uid"] = uid
    payload["updatedAt"] = datetime.now(timezone.utc).isoformat()
    payload["categories"] = {str(key): value for key, value in categories.items()}
    return payload


def _write_archive(output_dir: Path, categories: dict[int, list[dict]], uid: str = "") -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(output_dir / ARCHIVE_FILENAME, _archive_payload(categories, uid))


@dataclass(frozen=True)
class ImportResult:
    categories: dict[int, list[dict]]
    added_groups: int
    added_pulls: int
    total_groups: int
    total_pulls: int
    uid: str
    source: Path
    share_file: Path | None = None


def import_gacha_file(output_dir: Path, source: Path) -> ImportResult:
    """把外部抽卡数据文件合并进本地归档并落盘。

    能读的文件: 网页版/分享归档({"version","uid","updatedAt","categories"})、
    本工具导出的 JSON/CSV、只含扁平 groups 的老导出。合并键是 (Gid, Time, Ids),
    所以同一个文件反复导入不会重复计数。

    返回 ImportResult; 解析不出任何记录时抛 ValueError(界面直接弹这个文案)。
    """
    output_dir = Path(output_dir)
    text = read_import_text(Path(source))
    categories, uid = parse_import_text(text, Path(source).suffix)
    if not categories:
        raise ValueError(f"未能从 {Path(source).name} 中解析到抽卡记录，请选择网页版/桌面版导出的 JSON 或 CSV")
    payload = read_archive_payload(output_dir)
    # 归档里历史上被拍平的分类先按 Gid 归位, 再合并 —— 否则同一批记录会因为
    # 归档在 key 1、导入文件在 key 3 而各存一份, 抽数直接翻倍。归位是幂等的。
    archived = normalize_category_keys(_categories_from_payload(payload))
    before = sum(len(groups) for groups in archived.values())
    merged = merge_gacha_categories(archived, categories)
    after = sum(len(groups) for groups in merged.values())
    # uid 以导入文件为准: 用户导进来的就是自己账号的数据, 空着就沿用已设置/归档里的
    uid = uid or effective_uid(output_dir)
    _write_archive(output_dir, merged, uid=uid)
    share = write_share_file(output_dir, merged, uid)
    return ImportResult(
        categories=merged,
        added_groups=after - before,
        added_pulls=count_pulls(merged) - count_pulls(archived),
        total_groups=after,
        total_pulls=count_pulls(merged),
        uid=uid,
        source=Path(source),
        share_file=share,
    )


def read_import_text(source: Path) -> str:
    """按 UTF-8(含 BOM) 读; 中文 Excel/老工具存出来的 CSV 常是 GB18030。"""
    raw = source.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def load_latest_snapshot(output_dir: Path) -> Snapshot | None:
    gacha_files = sorted(
        (path for path in output_dir.glob("stellasora_gacha_*.json") if path.name != ARCHIVE_FILENAME),
        key=lambda path: path.stat().st_mtime,
    )
    if not gacha_files:
        return None
    gacha_file = gacha_files[-1]
    try:
        gacha_payload = json.loads(gacha_file.read_text(encoding="utf-8"))
        gacha = gacha_payload.get("groups", [])
        categories = {int(key): value for key, value in gacha_payload.get("categories", {"1": gacha}).items()}
    except (OSError, ValueError, AttributeError):
        return None
    return Snapshot(gacha, [], (gacha_file,), categories)
