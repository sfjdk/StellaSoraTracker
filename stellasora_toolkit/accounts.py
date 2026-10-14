# -*- coding: utf-8 -*-
"""多账号: 一个工具管理多份抽卡记录, 每份一个 UID, 由用户选择当前账号。

为什么要按账号分开: 垫抽/保底/五星概率都是**按账号**算的。两个账号的记录混在
一个归档里, 五星间隔和概率就全错了。

目录结构(输出目录 = exports):
    accounts.json                     账号清单 + 当前账号
    accounts/<key>/stellasora_gacha_archive.json    该账号的归档
    accounts/<key>/<uid>.json                       该账号的分享文件
    accounts/<key>/stellasora_gacha_*.json/csv      该账号的导出
    official_banners_*.json / catalog_sync_state.json  这些缓存与账号无关, 留在根目录

老数据迁移: 根目录已有的 stellasora_gacha_archive.json(以及同名 <uid>.json)会
**复制**成第一个账号(有 uid 就用 uid 当 key, 否则 default), 原文件保留不动。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import time

ACCOUNTS_FILENAME = "accounts.json"
ACCOUNTS_DIRNAME = "accounts"
DEFAULT_KEY = "default"
ARCHIVE_FILENAME = "stellasora_gacha_archive.json"

KEY_ALLOWED = re.compile(r"[^0-9A-Za-z_-]")


@dataclass(frozen=True)
class Account:
    key: str                 # 目录名(稳定, 不随 uid 变化)
    uid: str = ""            # 已知 UID(可能为空)
    name: str = ""           # 显示名

    @property
    def label(self) -> str:
        if self.name:
            return self.name
        return f"UID {self.uid}" if self.uid else "默认账号"


@dataclass(frozen=True)
class AccountState:
    accounts: tuple[Account, ...] = ()
    active: str = ""

    @property
    def active_account(self) -> Account | None:
        for account in self.accounts:
            if account.key == self.active:
                return account
        return self.accounts[0] if self.accounts else None


def normalize_key(value: str, fallback: str = DEFAULT_KEY) -> str:
    """把 UID/名字变成安全的目录名。"""
    text = KEY_ALLOWED.sub("_", str(value or "").strip())[:64]
    return text or fallback


def accounts_root(output_dir: Path) -> Path:
    return Path(output_dir) / ACCOUNTS_DIRNAME


def data_dir(output_dir: Path, key: str | None = None) -> Path:
    """某个账号的数据目录; key 为空时用当前账号。"""
    target = normalize_key(key) if key else (active_account(output_dir).key
                                             if active_account(output_dir) else DEFAULT_KEY)
    return accounts_root(output_dir) / target


def _state_path(output_dir: Path) -> Path:
    return Path(output_dir) / ACCOUNTS_FILENAME


def _write_json_atomic(path: Path, payload: dict) -> bool:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        temporary = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
        return True
    except OSError:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        return False


def save_state(output_dir: Path, state: AccountState) -> bool:
    payload = {
        "active": state.active,
        "accounts": [
            {"key": account.key, "uid": account.uid, "name": account.name}
            for account in state.accounts
        ],
    }
    return _write_json_atomic(_state_path(output_dir), payload)


def _parse_state(raw: object) -> AccountState:
    if not isinstance(raw, dict):
        return AccountState()
    accounts: list[Account] = []
    for row in raw.get("accounts", []) or []:
        if not isinstance(row, dict) or not row.get("key"):
            continue
        accounts.append(Account(
            key=normalize_key(row.get("key")),
            uid=str(row.get("uid") or "").strip(),
            name=str(row.get("name") or "").strip(),
        ))
    return AccountState(tuple(accounts), normalize_key(raw.get("active") or "", ""))


def _migrate_legacy(output_dir: Path, key: str, uid: str) -> None:
    """把根目录的老归档/分享文件复制进账号目录(原文件保留, 不删任何东西)。"""
    target = accounts_root(output_dir) / key
    target.mkdir(parents=True, exist_ok=True)
    sources = [output_dir / ARCHIVE_FILENAME]
    if uid:
        sources.append(output_dir / f"{uid}.json")
    for source in sources:
        if not source.is_file():
            continue
        destination = target / source.name
        if destination.exists():
            continue
        try:
            shutil.copy2(source, destination)
        except OSError:
            pass


def load_state(output_dir: Path) -> AccountState:
    """读账号清单; 缺失(老数据)时先迁移出一个账号。"""
    output_dir = Path(output_dir)
    path = _state_path(output_dir)
    if path.is_file():
        try:
            state = _parse_state(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            state = AccountState()
        if state.accounts:
            # 目录被手工删掉时兜底: 至少保证当前账号目录存在
            data_dir(output_dir, state.active or state.accounts[0].key).mkdir(parents=True, exist_ok=True)
            return state

    legacy = output_dir / ARCHIVE_FILENAME
    uid = ""
    if legacy.is_file():
        try:
            payload = json.loads(legacy.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                uid = str(payload.get("uid") or "").strip()
        except (OSError, ValueError):
            uid = ""
    key = normalize_key(uid, DEFAULT_KEY)
    _migrate_legacy(output_dir, key, uid)
    state = AccountState((Account(key=key, uid=uid, name=""),), key)
    save_state(output_dir, state)
    return state


def ensure_ready(output_dir: Path) -> AccountState:
    """启动/读写前调用: 保证账号清单存在且当前账号目录可用。"""
    state = load_state(output_dir)
    data_dir(output_dir, state.active or state.accounts[0].key).mkdir(parents=True, exist_ok=True)
    return state


def active_account(output_dir: Path) -> Account | None:
    return load_state(output_dir).active_account


def active_data_dir(output_dir: Path) -> Path:
    """当前账号的数据目录(归档/分享文件都放这里)。"""
    state = ensure_ready(output_dir)
    account = state.active_account
    return data_dir(output_dir, account.key if account else DEFAULT_KEY)


def find_by_uid(output_dir: Path, uid: str) -> Account | None:
    uid = str(uid or "").strip()
    if not uid:
        return None
    for account in load_state(output_dir).accounts:
        if account.uid == uid:
            return account
    return None


def switch(output_dir: Path, key: str) -> bool:
    state = load_state(output_dir)
    if not any(account.key == key for account in state.accounts):
        return False
    return save_state(output_dir, AccountState(state.accounts, key))


def create(output_dir: Path, *, uid: str = "", name: str = "") -> Account | None:
    """新建账号(同 UID 已存在则直接返回它)。

    UID 留空时不会占用 DEFAULT_KEY("默认账号" 是给老数据迁移用的名字) ——
    否则界面上会出现两个都叫"默认账号"的项, 或者用户以为自己新建的账号
    把老记录顶掉了。
    """
    uid = str(uid or "").strip()
    state = load_state(output_dir)
    if uid:
        existing = next((a for a in state.accounts if a.uid == uid), None)
        if existing is not None:
            return existing
    if uid:
        key = normalize_key(uid)
    else:
        index = 1
        while normalize_key(f"account_{index}") in {a.key for a in state.accounts}:
            index += 1
        key = normalize_key(f"account_{index}")
    if any(account.key == key for account in state.accounts):
        key = normalize_key(f"{key}_{int(time())}")
    account = Account(key=key, uid=uid, name=name.strip())
    data_dir(output_dir, key).mkdir(parents=True, exist_ok=True)
    save_state(output_dir, AccountState(state.accounts + (account,), key))
    return account


def archive_group_count(output_dir: Path, key: str) -> int:
    """该账号归档里的记录组数(-1 表示还没有归档文件)。

    只读一眼 JSON, 给界面显示"哪个账号有数据"用。
    """
    path = data_dir(output_dir, key) / ARCHIVE_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return -1
    categories = payload.get("categories") if isinstance(payload, dict) else None
    if not isinstance(categories, dict):
        return 0
    return sum(len(v) for v in categories.values() if isinstance(v, list))


def repair(output_dir: Path) -> str:
    """启动时的小修小补, 返回给用户看的一句话(空串表示无事发生)。

    做两件事:
    1. 账号清单里没登记 UID、但归档里带着 uid 的 → 补登记(标签就从"默认账号"变成 UID);
    2. 当前账号是空的、又没有 UID, 而另一个账号有记录 → 自动切过去。
       (用户点「新建账号」留空 UID 后很容易停在这种空账号上, 看着像数据没了。)
    """
    output_dir = Path(output_dir)
    state = ensure_ready(output_dir)
    notes: list[str] = []

    known = {account.uid for account in state.accounts if account.uid}
    for account in state.accounts:
        if account.uid:
            continue
        try:
            payload = json.loads((data_dir(output_dir, account.key) / ARCHIVE_FILENAME).read_text("utf-8"))
        except (OSError, ValueError):
            continue
        uid = str(payload.get("uid") or "").strip() if isinstance(payload, dict) else ""
        if uid and uid not in known:
            set_uid(output_dir, account.key, uid)
            known.add(uid)
            notes.append(f"账号 {account.label} 补登记为 UID {uid}")

    state = load_state(output_dir)
    current = state.active_account
    if current is not None and not current.uid and archive_group_count(output_dir, current.key) <= 0:
        with_data = [a for a in state.accounts if archive_group_count(output_dir, a.key) > 0]
        if len(with_data) == 1:
            switch(output_dir, with_data[0].key)
            notes.append(
                f"当前账号（{current.label}）还没有记录, 已自动切到有记录的 {with_data[0].label}")
    return "；".join(notes)


def rename(output_dir: Path, key: str, name: str) -> bool:
    state = load_state(output_dir)
    accounts = tuple(
        Account(a.key, a.uid, name.strip()) if a.key == key else a for a in state.accounts
    )
    if accounts == state.accounts:
        return False
    return save_state(output_dir, AccountState(accounts, state.active))


def set_uid(output_dir: Path, key: str, uid: str) -> bool:
    """给某个账号登记 UID(手填或从游戏读到的)。"""
    uid = str(uid or "").strip()
    state = load_state(output_dir)
    accounts = tuple(
        Account(a.key, uid, a.name) if a.key == key else a for a in state.accounts
    )
    return save_state(output_dir, AccountState(accounts, state.active))


def remove(output_dir: Path, key: str) -> bool:
    """删除账号(目录改名为 <key>.deleted_<时间> 保留数据, 不真删)。"""
    state = load_state(output_dir)
    remaining = tuple(account for account in state.accounts if account.key != key)
    if len(remaining) == len(state.accounts):
        return False
    target = accounts_root(output_dir) / normalize_key(key)
    if target.exists():
        try:
            target.rename(target.with_name(f"{target.name}.deleted_{int(time())}"))
        except OSError:
            pass
    active = state.active if state.active != key else (remaining[0].key if remaining else "")
    return save_state(output_dir, AccountState(remaining, active))


def adopt_uid(output_dir: Path, uid: str) -> Account | None:
    """按 UID 找账号; 没有就把它记到当前账号头上(当前账号还没 UID 时), 否则新建。

    游戏里换账号后, 刷新时读到的 UID 会把人自动带到对应账号的记录上。
    注意"当前账号还没有 UID"这一档: 老数据迁移出来的账号本来就没登记 UID,
    这时应该**认领**这个 UID(否则用户会看到老记录像换了账号一样消失)。
    """
    uid = str(uid or "").strip()
    if not uid:
        return None
    existing = find_by_uid(output_dir, uid)
    if existing is not None:
        switch(output_dir, existing.key)
        return existing
    current = active_account(output_dir)
    if current is not None and not current.uid:
        if set_uid(output_dir, current.key, uid):
            return Account(current.key, uid, current.name)
    account = create(output_dir, uid=uid)
    if account is not None:
        switch(output_dir, account.key)
    return account
