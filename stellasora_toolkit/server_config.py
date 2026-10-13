# -*- coding: utf-8 -*-
"""游戏发行版本(国服 / 国际服 / 日服)的差异配置。

《星塔旅人》各发行版是同一款游戏。经 StellaBase 验证, 各版的角色/秘纹/卡池
API 返回同一套 ID, 只是文本语言的差异(lang=cn / en / jp;例如 ID 137:
埃莉诺 / Eleanor / エレノア)。

因此工具与版本无关的部分(内存读取、ID 判定、概率统计、归档合并)无需改动,
真正差异的只有三点:
    1. 客户端进程名: 国服 xtlr.exe; 国际服与**日服共用 StellaSora.exe**;
    2. 名称语言: 工具从 StellaBase 拉取的名称表用哪个 lang 参数
       (cn / en / jp;tw 繁体也能用, 但没做进界面);
    3. 若某版游戏更新后 Lua 字段名变化, 在这里调整即可(默认各版一致)。

国际服与日服共用同一个进程名, 所以**无法靠进程名区分二者** ——
检测到 StellaSora.exe 时保持设置页所选(未选过则默认国际服), 想用日服就在
设置页切一次, 会持久化到 server.json。

配置持久化: 输出目录下 server.json; 未设置时默认国服。
命令行/环境变量可用 STELLASORA_SERVER=cn|intl|jp 覆盖(优先级: 环境变量 > server.json > 国服)。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

SERVER_CN = "cn"
SERVER_INTL = "intl"
SERVER_JP = "jp"

# 语言 → 版本 key(内存识别用; 放在这里避免 client_lang ←→ server_config 循环导入)
LANG_TO_SERVER = {"cn": SERVER_CN, "en": SERVER_INTL, "jp": SERVER_JP}

CONFIG_FILENAME = "server.json"
ENV_KEY = "STELLASORA_SERVER"


@dataclass(frozen=True)
class ServerProfile:
    key: str
    label: str                 # 界面显示名
    client_names: tuple[str, ...]   # 候选进程名, 按优先级排序
    api_lang: str              # StellaBase 的 lang 参数
    gacha_field: str = "_mapGachaHistory"
    gacha_companions: tuple[str, ...] = (
        "_mapGachaCount", "_mapGachaTotalTimes", "_mapTotalGachaTimes", "_openedPool",
    )


PROFILES: dict[str, ServerProfile] = {
    SERVER_CN: ServerProfile(
        key=SERVER_CN, label="国服",
        client_names=("xtlr.exe",), api_lang="cn",
    ),
    SERVER_INTL: ServerProfile(
        key=SERVER_INTL, label="国际服",
        client_names=("StellaSora.exe",), api_lang="en",
    ),
    # 日服与国际服共用 StellaSora.exe: 进程名区分不出来, 只能靠设置页选择
    SERVER_JP: ServerProfile(
        key=SERVER_JP, label="日服",
        client_names=("StellaSora.exe",), api_lang="jp",
    ),
}

_active: ServerProfile = PROFILES[SERVER_CN]


def active() -> ServerProfile:
    """当前激活的版本配置。"""
    return _active


def api_lang() -> str:
    """当前版本对应的 StellaBase 名称语言(cn/en)。"""
    return _active.api_lang


def set_active(key: str) -> bool:
    """切换激活版本; 非法 key 返回 False 并保持原样。"""
    global _active
    profile = PROFILES.get(str(key).strip().lower())
    if profile is None:
        return False
    _active = profile
    return True


def _parse_key(value: str | None) -> str | None:
    key = (value or "").strip().lower()
    return key if key in PROFILES else None


def running_client_groups(running_names: list[str]) -> list[list[str]]:
    """把在跑的进程按"客户端"分组: 每个 exe → 支持它的版本 key 列表。

    国际服与日服都是 StellaSora.exe, 所以它们落在**同一组** ——
    一组里有多个版本 ≠ 两个客户端在跑, 不能因此弹选择框。
    """
    names = {name.casefold() for name in running_names}
    by_client: dict[str, list[str]] = {}
    for key, profile in PROFILES.items():
        for client in profile.client_names:
            if client.casefold() in names:
                by_client.setdefault(client.casefold(), []).append(key)
    return [keys for _client, keys in sorted(by_client.items())]


def resolve_running(running_names: list[str]) -> tuple[ServerProfile | None, list[str]]:
    """根据运行中的客户端进程名推断版本(纯逻辑, 供自动检测使用)。

    返回 (选中的版本配置, 匹配到的版本 key 列表):
    - 只有一个客户端在跑, 且它只对应一个版本(国服) → 返回该配置;
    - 只有一个客户端在跑, 但它对应多个版本(StellaSora.exe = 国际服/日服):
      当前设置在这个组里就沿用它, 否则用组内第一个(国际服)兜底 —— 不弹框;
    - 两个客户端都在跑 / 都没跑 → 返回 (None, [...])。
    """
    groups = running_client_groups(running_names)
    keys = [key for group in groups for key in group]
    if len(groups) != 1:
        return None, keys
    group = groups[0]
    if len(group) == 1:
        return PROFILES[group[0]], keys
    current = active()
    return PROFILES[current.key if current.key in group else group[0]], keys


def init_from(output_dir: Path | None) -> ServerProfile:
    """启动时调用一次: 环境变量 > server.json > 默认国服。返回激活的配置。"""
    env_key = _parse_key(os.environ.get(ENV_KEY))
    if env_key is not None:
        set_active(env_key)
        return _active
    if output_dir is not None:
        key = load_key(config_path(output_dir))
        if key is not None:
            set_active(key)
            return _active
    set_active(SERVER_CN)
    return _active


def config_path(output_dir: Path) -> Path:
    return output_dir / CONFIG_FILENAME


def load_key(path: Path) -> str | None:
    """读 server.json; 缺失/损坏/未知 key 返回 None(调用方用默认值)。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _parse_key(str(payload.get("server") or ""))
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def load_manual(path: Path) -> bool:
    """server.json 里是否标记为"用户手动指定"。

    手动指定后, 内存语言识别只能提示、不再自动覆盖 —— 否则用户在设置页点了
    「日服」, 下次刷新又被自动判回国际服, 看起来就是"按钮没用"。
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return bool(payload.get("manual"))
    except (OSError, ValueError, AttributeError, TypeError):
        return False


def save_key(path: Path, key: str, *, manual: bool = True) -> bool:
    """写 server.json; 非法 key 或写盘失败返回 False。

    manual=True 表示"这是用户点选的结果", 自动识别不会覆盖它;
    自动识别自己写回时传 manual=False。
    """
    profile = PROFILES.get(str(key).strip().lower())
    if profile is None:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"server": profile.key, "manual": bool(manual)},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def resolve_detected(pinned_key: str, detected_lang: str, manual: bool) -> tuple[str, str]:
    """按"内存里识别出的语言"决定是否换版本 → (采用的 key, 给用户看的一句话)。

    - 没识别出来 → 维持原样;
    - 用户手动指定过 → 一律不覆盖, 只在识别结果不同的时候提示;
    - 没手动指定(自动模式) → 识别到哪版就用哪版。
    """
    pinned = PROFILES.get(str(pinned_key).strip().lower())
    if pinned is None:
        return str(pinned_key), ""
    target_key = LANG_TO_SERVER.get(str(detected_lang or "").strip().lower(), "")
    if not target_key or target_key not in PROFILES:
        return pinned.key, ""
    target = PROFILES[target_key]
    if target.key == pinned.key:
        return pinned.key, ""
    if manual:
        return pinned.key, (f"内存里的文本看起来是 {target.label}，但已手动指定 {pinned.label}，"
                            f"保持 {pinned.label}（要跟随识别请点「自动识别」）")
    return target.key, f"按内存里的文本判断这是 {target.label}，已自动切换"
