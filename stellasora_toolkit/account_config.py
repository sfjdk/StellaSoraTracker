# -*- coding: utf-8 -*-
"""账户配置持久化：服务器地址 + 登录 token + 用户名。

## 为什么单独一个文件，不并进 server.json

`server_config.save_key()` 是**整体覆写** —— 它只写 `{"server": "cn"}` 这一个
键，不是读改写。把 token 塞进去的话，用户每次切服（设置页手动切、启动时
自动检测、双客户端弹窗选择都会调它）token 就被**静默抹掉**，表现为
"明明刚登录过，下次打开又让我登录"，而且没有任何错误提示。

单独一个 account.json 就没这个问题，也顺带避免了"敏感凭据混在偏好设置里"
被随手分享出去。

风险声明：token 存在 exports 目录下，和归档放在一起。导出归档给别人时
注意别把这个文件也带上（导出功能只写归档和 CSV，不会碰它）。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

ACCOUNT_FILENAME = "account.json"


@dataclass(frozen=True)
class Account:
    server_url: str = ""
    token: str = ""
    username: str = ""

    @property
    def logged_in(self) -> bool:
        return bool(self.server_url and self.token)


def config_path(output_dir: Path) -> Path:
    return Path(output_dir) / ACCOUNT_FILENAME


def load(output_dir: Path) -> Account | None:
    """读账户配置。缺失/损坏/字段非法一律返回 None —— 与 server_config 的
    "损坏即降级"风格一致，坏文件不该让程序起不来。"""
    path = config_path(output_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    server_url = payload.get("serverUrl")
    token = payload.get("token")
    username = payload.get("username")
    if not isinstance(server_url, str) or not isinstance(token, str):
        return None
    if not server_url.strip() or not token.strip():
        return None
    return Account(server_url=server_url.strip(), token=token.strip(),
                   username=username.strip() if isinstance(username, str) else "")


def save(output_dir: Path, account: Account) -> bool:
    """原子写。中途崩溃不会留下半截文件 —— 那会让下次启动读到损坏的 token。"""
    path = config_path(output_dir)
    payload = {
        "serverUrl": account.server_url,
        "token": account.token,
        "username": account.username,
    }
    temp: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        temp = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temp, path)
        return True
    except OSError:
        if temp is not None:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
        return False


def clear(output_dir: Path) -> bool:
    """退出登录：只删文件，不报错。"""
    try:
        config_path(output_dir).unlink(missing_ok=True)
        return True
    except OSError:
        return False


def normalize_server_url(url: str) -> str:
    """统一成 "https://host[:port]" 形态。

    用户可能粘贴 "https://x.com/"、带路径的分享链接、或者忘了协议头。
    这里只做最小规整：补协议、去尾部斜杠。
    """
    text = (url or "").strip()
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        # 公网服务必须是 https，本地调试允许 http://127.0.0.1
        host = text.split("/")[0]
        scheme = "http://" if host.split(":")[0] in ("127.0.0.1", "localhost") else "https://"
        text = scheme + text
    return text.rstrip("/")


def split_share_url(url: str) -> str:
    """从分享链接里抽出服务器地址。

    用户拿到的可能是一条 "/s/xxxx" 分享链接，粘贴进来时应该只取站点根。
    """
    text = normalize_server_url(url)
    marker = "/s/"
    index = text.find(marker)
    return text[:index] if index > 0 else text


__all__ = ["Account", "ACCOUNT_FILENAME", "config_path", "load", "save", "clear",
           "normalize_server_url", "split_share_url"]
