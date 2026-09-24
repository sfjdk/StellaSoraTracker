from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from . import server_config
from .discovery import LuaTableDiscovery
from .exporter import export_all, sanitize_gacha_categories
from .lua53 import Lua53Reader
from .process import RemoteProcess, find_process_id, running_processes


ProgressCallback = Callable[[str], None]
ARCHIVE_FILENAME = "stellasora_gacha_archive.json"


@dataclass(frozen=True)
class Snapshot:
    gacha: list[dict]
    emblems: list[dict] = field(default_factory=list)
    files: tuple[Path, ...] = ()
    gacha_categories: dict[int, list[dict]] = field(default_factory=dict)

    @property
    def pull_count(self) -> int:
        return sum(len(group.get("Ids", [])) for group in self.gacha)

    @property
    def character_count(self) -> int:
        return len({item.get("nCharId") for item in self.emblems if item.get("nCharId") is not None})


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
    with RemoteProcess(pid) as process:
        lua = Lua53Reader(process)
        discovery = LuaTableDiscovery(process, lua)
        raw_gacha = discovery.read_target_field(
            profile.gacha_field,
            set(profile.gacha_companions),
        )
    report("招募数据读取完成，正在生成本地 JSON 和 CSV")
    current_categories = sanitize_gacha_categories(raw_gacha)
    categories = merge_gacha_categories(_load_archive(output_dir.resolve()), current_categories)
    gacha = [group for groups in categories.values() for group in groups]
    files = tuple(export_all(output_dir.resolve(), gacha, None, categories))
    _write_archive(output_dir.resolve(), categories)
    return Snapshot(gacha, [], files, categories)


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


def _load_archive(output_dir: Path) -> dict[int, list[dict]]:
    archive = output_dir / ARCHIVE_FILENAME
    payload: dict = {}
    try:
        payload = json.loads(archive.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Upgrade an existing timestamped export into the persistent archive.
        files = sorted(output_dir.glob("stellasora_gacha_*.json"), key=lambda path: path.stat().st_mtime)
        if files:
            try:
                payload = json.loads(files[-1].read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = {}
    categories = payload.get("categories", {}) if isinstance(payload, dict) else {}
    return {int(key): value for key, value in categories.items() if isinstance(value, list)}


def _write_archive(output_dir: Path, categories: dict[int, list[dict]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / ARCHIVE_FILENAME
    temporary = output_dir / f".{ARCHIVE_FILENAME}.tmp"
    payload = {
        "version": 1,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "categories": {str(key): value for key, value in categories.items()},
    }
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(archive)


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
