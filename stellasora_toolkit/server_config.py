# -*- coding: utf-8 -*-
"""游戏发行版本(国服 / 国际服)的差异配置。

《星塔旅人》国服与国际服是同一款游戏的两种发行版本。经 StellaBase 验证,
两版的角色/秘纹/卡池 API 返回同一套 ID,只是文本语言的差异
(land=cn / lang=en;例如 ID 137: 埃莉诺 / Eleanor)。

因此工具与版本无关的部分(内存读取、ID 判定、概率统计、归档合并)无需改动,
真正差异的只有三点:
    1. 客户端进程名: 国服 xtlr.exe / 国际服 StellaSora.exe;
    2. 名称语言: 工具从 StellaBase 拉取的名称表用哪个 lang 参数;
    3. 若某版游戏更新后 Lua 字段名变化, 在这里调整即可(默认两版一致)。

配置持久化: 输出目录下 server.json; 未设置时默认国服。
命令行/环境变量可用 STELLASORA_SERVER=cn|intl 覆盖(优先级: 环境变量 > server.json > 国服)。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

SERVER_CN = "cn"
SERVER_INTL = "intl"

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


def resolve_running(running_names: list[str]) -> tuple[ServerProfile | None, list[str]]:
    """根据运行中的客户端进程名推断服务器版本(纯逻辑, 供自动检测使用)。

    返回 (选中的版本配置, 正在运行的版本 key 列表):
    - 恰好一种客户端在运行 → 返回该配置;
    - 两者都运行 / 都没有 → 返回 (None, [...]) —— 两种客户端并存时必须由用户手动
      选择(调用方沿用当前激活版本并提示), 都没运行则按正常"未找到"流程报错。
    """
    names = {name.casefold() for name in running_names}
    running_keys = [
        key for key, prof in PROFILES.items()
        if any(client.casefold() in names for client in prof.client_names)
    ]
    if len(running_keys) == 1:
        return PROFILES[running_keys[0]], running_keys
    return None, running_keys


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


def save_key(path: Path, key: str) -> bool:
    """写 server.json; 非法 key 或写盘失败返回 False。"""
    profile = PROFILES.get(str(key).strip().lower())
    if profile is None:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"server": profile.key}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False
