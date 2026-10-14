from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable, Iterable

from . import accounts, server_config
from .account_uid import UidSearch, find_account_uid
from .client_lang import detect_language
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

# 两个"增强功能"的时间预算(秒): 都不该让刷新无限等下去
UID_SEARCH_BUDGET = 20.0
LANG_DETECT_BUDGET = 12.0

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
    data_dir = _resolve_dir(Path(output_dir))          # uid.json 属于账号目录, 不是根目录
    with RemoteProcess(pid) as process:
        lua = Lua53Reader(process)
        discovery = LuaTableDiscovery(process, lua)
        try:
            search = find_account_uid(discovery, preferred=effective_uid(output_dir),
                                      field_hint=load_uid_field(data_dir))
        except Exception as err:                               # noqa: BLE001
            report(f"UID 探测中断: {err}")
            return UidSearch()
    if search.found:
        save_uid_field(data_dir, search.field_name)
    return search


def probe_running_keys() -> list[str]:
    """只探测: 当前正在运行的客户端版本 key 列表(探测失败/无客户端返回 [])。"""
    try:
        running_names = [name for name, _pid in running_processes()]
    except OSError:
        return []
    return server_config.resolve_running(running_names)[1]


def probe_running_groups() -> list[list[str]]:
    """按"客户端进程"分组的版本 key(国际服与日服共用 StellaSora.exe → 同一组)。

    界面用它判断"是不是两个客户端同时在跑": 用 key 个数会误判, 因为一个
    StellaSora.exe 就会给出 intl/jp 两个 key。
    """
    try:
        running_names = [name for name, _pid in running_processes()]
    except OSError:
        return []
    return server_config.running_client_groups(running_names)


def detect_and_apply(output_dir: Path | None = None) -> tuple[server_config.ServerProfile, str, list[str]]:
    """自动检测运行中的游戏客户端并确定读取版本(国服/国际服/日服)。

    规则:
    - 只有一个客户端在跑且只对应一个版本(国服) → 自动切换并持久化 server.json;
    - StellaSora.exe 在跑(国际服/日服共用): 设置页选过哪个就用哪个, 没选过用国际服,
      并提示可以在设置页切到日服 —— 进程名区分不出这两版, 只能由用户选一次;
    - 国服与 StellaSora.exe 同时在跑 → 保持当前(设置页所选/--server)版本并提示
      (界面在"刷新数据"时会事先弹窗让用户选定, 此路径是 CLI/兜底);
    - 没有客户端运行 → 保持当前版本, 返回空提示(后续按"未找到进程"正常报错)。

    返回 (生效版本, 状态提示(空串为无需显示), 匹配到的版本 key 列表)。
    """
    groups = probe_running_groups()
    keys = [key for group in groups for key in group]
    current = server_config.active()
    if len(groups) == 2:
        labels = " 与 ".join(server_config.PROFILES[group[0]].label for group in groups)
        return current, f"同时检测到 {labels} 客户端, 按设置页所选(或 --server)读取 {current.label}", keys
    if len(groups) != 1:
        return current, "", keys
    group = groups[0]
    fallback = server_config.PROFILES[group[0]]
    if len(group) > 1:
        chosen = current if current.key in group else fallback
        server_config.set_active(chosen.key)          # 幂等
        if chosen.key != current.key and output_dir is not None:
            server_config.save_key(server_config.config_path(output_dir), chosen.key)
        if chosen.key == current.key:
            return chosen, "", keys
        shared = " / ".join(server_config.PROFILES[key].label for key in group)
        return chosen, (
            f"检测到 {chosen.client_names[0]} 客户端（{shared} 共用该客户端）, "
            f"已使用 {chosen.label}；要读日服请在设置页切换"
        ), keys
    if fallback.key != current.key:
        server_config.set_active(fallback.key)
        if output_dir is not None:
            server_config.save_key(server_config.config_path(output_dir), fallback.key)
        return fallback, f"自动检测到 {fallback.label} 客户端（{fallback.client_names[0]}）, 已自动切换", keys
    server_config.set_active(fallback.key)  # 已在运行也应保持一致(幂等)
    return fallback, "", keys


def extract_snapshot(
    output_dir: Path,
    process_name: str | Iterable[str] | None = None,
    progress: ProgressCallback | None = None,
    verify_uid: bool = False,
) -> Snapshot:
    """读取当前游戏版本的招募快照。

    process_name 为 None 时自动检测运行中的客户端(国服 xtlr.exe / 国际服 StellaSora.exe):
    恰好一个客户端时自动切换版本; 两个客户端并存时沿用设置页所选版本。
    显式传入 process_name 时直接使用, 不做版本切换。Lua 字段名取自当前版本配置。

    记录写进**当前账号**的数据目录; 若从游戏内存读到 UID, 会按 UID 自动切到对应账号
    (没有就新建) —— 游戏里换账号后刷新一次就跟着换。
    """
    report = progress or (lambda _message: None)
    root = output_dir.resolve()
    accounts.ensure_ready(root)
    target = accounts.active_data_dir(root)
    payload = read_archive_payload(target)
    # UID 决定分享文件名: 设置页手填的优先, 其次是账号清单/归档里记着的
    uid = (load_manual_uid(target) or (accounts.active_account(root).uid if accounts.active_account(root) else "")
           or extract_uid(payload))
    uid_note = "沿用已保存的 UID" if uid else ""
    previous_uid = uid
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

        # 国际服/日服共用 StellaSora.exe, 进程名分不出来 —— 看内存里加载的是哪种语言。
        # 用户手动指定过版本时不覆盖他的选择, 只提示(否则"点了日服又被切回国际服")。
        if len(profile.client_names) and len(running_keys) > 1:
            lang, marker = detect_language(discovery, pinned=profile.api_lang,
                                           deadline=perf_counter() + LANG_DETECT_BUDGET)
            if lang:
                manual = server_config.load_manual(server_config.config_path(root))
                target_key, note = server_config.resolve_detected(profile.key, lang, manual)
                if note:
                    report(f"「{marker}」→ {note}")
                if target_key != profile.key and server_config.set_active(target_key):
                    profile = server_config.active()
                    server_config.save_key(server_config.config_path(root), profile.key,
                                           manual=False)

        if not uid or verify_uid:
            # 还不知道 UID 时才去内存里找(要额外扫描, 有成本);
            # field_hint 是上次学到的字段名: 命中就直接用, 不再全内存找"uid"。
            # 这是增强功能: 探测本身出任何问题都必须放过, 不能连累招募数据读取。
            # 另外给它一个时间预算 —— 扫描量随进程大小变化, 不能无限等。
            report("正在从游戏内存读取账号 UID")
            try:
                search = find_account_uid(discovery, field_hint=load_uid_field(target),
                                          deadline=perf_counter() + (UID_SEARCH_BUDGET if not uid else 2.0))
            except Exception:                                  # noqa: BLE001
                search = UidSearch()
            if search.found:
                uid = search.uid
                uid_note = (f"从游戏内存读取（字段 {search.field_name}）"
                            if uid != previous_uid else "UID 已核实")
                save_uid_field(target, search.field_name)
            elif search.budget_exceeded:
                uid_note = "UID 扫描超时，本次先按当前账号记录（下次刷新会再试）"
        raw_gacha = discovery.read_target_field(
            profile.gacha_field,
            set(profile.gacha_companions),
        )
    locate_seconds = perf_counter() - started
    report(f"招募数据读取完成（{locate_seconds:.1f}s），正在生成本地 JSON 和 CSV")

    if search.found:
        # 按游戏里的 UID 归位: 已有该账号就切过去, 没有就新建, 记录写进它自己的目录
        account = accounts.adopt_uid(root, uid)
        if account is not None:
            new_target = accounts.data_dir(root, account.key)
            if new_target != target:
                report(f"已切换到账号 {account.label}")
                target = new_target
                payload = read_archive_payload(target)
            save_uid_field(target, search.field_name)

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
    """当前账号的 UID: 手填的优先, 否则账号清单/归档里记着的。"""
    root = Path(output_dir)
    target = _resolve_dir(root)
    manual = load_manual_uid(target)
    if manual:
        return manual
    account_uid = _account_uid(root)
    if account_uid:
        return account_uid
    return extract_uid(read_archive_payload(target))


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
    """当前生效的 UID(当前账号): 手填 > 账号清单 > 归档。"""
    return load_archive_uid(output_dir)


def load_archive_categories(output_dir: Path) -> dict[int, list[dict]]:
    """当前账号的归档分类表(供界面直接使用)。"""
    return _categories_from_payload(read_archive_payload(_resolve_dir(Path(output_dir))))


def load_account_categories(output_dir: Path, key: str) -> dict[int, list[dict]]:
    """指定账号的归档分类表(导出时按 UID 找账号用)。"""
    return _categories_from_payload(read_archive_payload(accounts.data_dir(Path(output_dir), key)))


def refresh_share_file(output_dir: Path) -> Path | None:
    """按当前账号的归档与 UID 重新产出 <uid>.json(没 UID 或没记录时返回 None)。

    启动时与学到 UID 后都可以直接调用 —— 不用点按钮, 文件总是最新的。
    """
    root = Path(output_dir)
    target = _resolve_dir(root)
    categories = _categories_from_payload(read_archive_payload(target))
    if not categories:
        return None
    uid = effective_uid(root)
    if not uid:
        return None
    return write_share_file(target, categories, uid)


def export_share_for_uid(output_dir: Path, uid_text: str = "") -> Path:
    """按 UID 导出分享文件 —— **文件名与内容必须来自同一个账号**。

    - uid_text 为空: 导出当前账号;
    - uid_text 命中某个账号: 导出那一个(哪怕它不是当前账号);
    - 当前账号还没登记 UID 且 uid_text 谁都不命中: 让它认领这个 UID;
    - 其它(uid_text 属于别的账号、或是个不存在的号): 抛 ValueError, 界面弹文案。

    为什么这么严: 以前导出的文件名取"输入框里的 UID"、内容取"当前账号的归档",
    游戏换号后就会出现「308423356.json 里装着 100872990 的 653 组」这种
    张冠李戴的文件 —— 看起来就是"几个号的记录被合在一起了"。
    """
    root = Path(output_dir)
    accounts.ensure_ready(root)
    typed = normalize_uid(uid_text)
    account = accounts.active_account(root)
    if typed:
        if account is None or typed != account.uid:
            other = accounts.find_by_uid(root, typed)
            if other is not None:
                account = other
            elif account is not None and not account.uid:
                accounts.set_uid(root, account.key, typed)
                account = accounts.active_account(root)
            else:
                current = account.label if account else "无"
                raise ValueError(
                    f"UID {typed} 不对应任何账号（当前账号是 {current}）。\n"
                    "请先在账号下拉框切到要导出的账号, 或把 UID 改成当前账号的。")
    if account is None:
        raise ValueError("还没有账号, 先在设置页新建一个")
    uid = account.uid or typed
    if not uid:
        raise ValueError("还没有 UID：先填一个并保存, 或导入一次带 uid 的分享文件")
    data_dir = accounts.data_dir(root, account.key)
    categories = normalize_category_keys(_categories_from_payload(read_archive_payload(data_dir)))
    if not categories:
        raise ValueError(f"账号 {account.label} 还没有记录, 请先点「刷新游戏数据」")
    path = write_share_file(data_dir, categories, uid)
    if path is None:
        raise ValueError("UID 不合法，未能生成分享文件")
    return path


def write_share_file(output_dir: Path, categories: dict[int, list[dict]], uid: str) -> Path | None:
    """生成与网页版/分享文件完全同格式的 <uid>.json。

    键与顺序都和分享文件一致: version / uid / updatedAt / categories。
    UID 未知(没填过也没导入过带 uid 的文件)时不生成, 返回 None。

    传进来的是"账号根目录"(带 accounts.json)时, 落到当前账号目录里 —— 分享文件
    属于某个账号, 不该散在根目录里, 否则很容易和别的账号对上号。
    """
    uid = normalize_uid(uid)
    if not uid:
        return None
    output_dir = Path(output_dir)
    if (output_dir / accounts.ACCOUNTS_FILENAME).is_file():
        output_dir = accounts.active_data_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{uid}.json"
    _write_json_atomic(path, _archive_payload(categories, uid))
    return path


def _resolve_dir(output_dir: Path) -> Path:
    """把"用户看到的数据目录"解析成真正放归档的目录(只读, 不产生副作用)。

    规则:
    - 有账号清单 accounts.json(正常情况) → 当前账号目录 accounts/<key>/;
    - 该目录里直接躺着一份归档(老版本数据, 或调用方本来就按数据目录用) → 就用它;
    - 其它(全新目录) → 当前账号目录(读取方不需要先建账号)。
    """
    root = Path(output_dir)
    if (root / accounts.ACCOUNTS_FILENAME).is_file():
        return accounts.data_dir(root, (accounts.active_account(root) or accounts.Account("")).key or None)
    if (root / ARCHIVE_FILENAME).is_file():
        return root
    return accounts.data_dir(root)


def _account_uid(output_dir: Path) -> str:
    """账号清单里当前账号的 UID(没有账号清单时返回空串, 不触发迁移)。"""
    root = Path(output_dir)
    if not (root / accounts.ACCOUNTS_FILENAME).is_file():
        return ""
    account = accounts.active_account(root)
    return account.uid if account else ""


def active_data_dir(output_dir: Path) -> Path:
    """当前账号的数据目录(归档/分享文件都放这里; 供 server_upload 等调用方使用)。"""
    return _resolve_dir(Path(output_dir))


def count_pulls(categories: dict[int, list[dict]]) -> int:
    """分类表里的总抽数(Ids 个数)。"""
    return sum(len(group.get("Ids") or []) for groups in categories.values() for group in groups)


def merge_accounts(output_dir: Path, source_key: str, target_key: str) -> tuple[int, int]:
    """把 source 账号的记录并入 target 账号(按 (Gid,Time,Ids) 合并, 幂等)。

    用来收拾"记录被读进了另一个账号"的情况(比如那次刷新没读到 UID): 合并后
    source 目录改名保留(不删数据), 并切到 target。

    返回 (新增组数, 新增抽数)。
    """
    root = Path(output_dir)
    accounts.ensure_ready(root)
    source_key = str(source_key or "").strip()
    target_key = str(target_key or "").strip()
    if not source_key or not target_key or source_key == target_key:
        raise ValueError("需要选择两个不同的账号")
    source_payload = read_archive_payload(accounts.data_dir(root, source_key))
    target_payload = read_archive_payload(accounts.data_dir(root, target_key))
    target_categories = normalize_category_keys(_categories_from_payload(target_payload))
    source_categories = normalize_category_keys(_categories_from_payload(source_payload))
    merged = merge_gacha_categories(target_categories, source_categories)
    added_groups = (sum(len(groups) for groups in merged.values())
                    - sum(len(groups) for groups in target_categories.values()))
    added_pulls = count_pulls(merged) - count_pulls(target_categories)
    # UID 以 target 为准(它才是"正确"的那个账号), 其次 source 的
    uid = (extract_uid(target_payload)
           or next((a.uid for a in accounts.load_state(root).accounts if a.key == target_key), "")
           or extract_uid(source_payload))
    target_dir = accounts.data_dir(root, target_key)
    _write_archive(target_dir, merged, uid=uid)
    write_share_file(target_dir, merged, uid)
    accounts.remove(root, source_key)
    accounts.switch(root, target_key)
    return added_groups, added_pulls


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

    文件里带 uid 时按 uid 归位: 已有该账号就切过去, 没有就新建 —— 导入别人的/自己的
    另一份数据不会混进当前账号(垫抽与概率是按账号算的)。

    返回 ImportResult; 解析不出任何记录时抛 ValueError(界面直接弹这个文案)。
    """
    root = Path(output_dir)
    accounts.ensure_ready(root)
    text = read_import_text(Path(source))
    categories, uid = parse_import_text(text, Path(source).suffix)
    if not categories:
        raise ValueError(f"未能从 {Path(source).name} 中解析到抽卡记录，请选择网页版/桌面版导出的 JSON 或 CSV")
    if uid:
        account = accounts.adopt_uid(root, uid)
        if account is not None and not account.name:
            accounts.set_uid(root, account.key, uid)
    target = accounts.active_data_dir(root)
    payload = read_archive_payload(target)
    # 归档里历史上被拍平的分类先按 Gid 归位, 再合并 —— 否则同一批记录会因为
    # 归档在 key 1、导入文件在 key 3 而各存一份, 抽数直接翻倍。归位是幂等的。
    archived = normalize_category_keys(_categories_from_payload(payload))
    before = sum(len(groups) for groups in archived.values())
    merged = merge_gacha_categories(archived, categories)
    after = sum(len(groups) for groups in merged.values())
    # uid 以导入文件为准: 用户导进来的就是自己账号的数据, 空着就沿用当前账号已记录的
    uid = uid or effective_uid(root)
    _write_archive(target, merged, uid=uid)
    share = write_share_file(target, merged, uid)
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
    """当前账号最近一次导出/归档的快照(界面启动时用它显示上次数据)。"""
    target = _resolve_dir(Path(output_dir))
    # Imports update the canonical archive but do not rewrite older timestamped exports.
    # Prefer the complete merged archive on restart/account switch.
    archive = target / ARCHIVE_FILENAME
    if archive.is_file():
        try:
            payload = json.loads(archive.read_text(encoding="utf-8"))
            categories = _categories_from_payload(payload)
            gacha = [group for groups in categories.values() for group in groups]
            return Snapshot(gacha, [], (archive,), categories, uid=effective_uid(Path(output_dir)))
        except (OSError, ValueError, TypeError):
            pass
    gacha_files = sorted(
        (path for path in target.glob("stellasora_gacha_*.json") if path.name != ARCHIVE_FILENAME),
        key=lambda path: path.stat().st_mtime,
    )
    if not gacha_files:
        # 只有归档(没时间戳导出)时也要能显示
        categories = _categories_from_payload(read_archive_payload(target))
        if not categories:
            return None
        gacha = [group for groups in categories.values() for group in groups]
        return Snapshot(gacha, [], (), categories, uid=effective_uid(Path(output_dir)))
    gacha_file = gacha_files[-1]
    try:
        gacha_payload = json.loads(gacha_file.read_text(encoding="utf-8"))
        gacha = gacha_payload.get("groups", [])
        categories = {int(key): value for key, value in gacha_payload.get("categories", {"1": gacha}).items()}
    except (OSError, ValueError, AttributeError):
        return None
    return Snapshot(gacha, [], (gacha_file,), categories, uid=effective_uid(Path(output_dir)))
