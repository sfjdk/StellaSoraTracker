# -*- coding: utf-8 -*-
"""网页版服务端的客户端：注册 / 登录 / 上传归档。

只用标准库 urllib，与项目其它网络模块（official_banners / resource_manager）
保持一致的写法：Request + urlopen + 超时，失败抛 OSError。

与它们不同的是这里有 POST 和鉴权 —— 项目里第一批带 body 的请求。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .account_config import normalize_server_url
from .service import ARCHIVE_FILENAME

USER_AGENT = "StellaSoraToolkit/1.0"

# 首次配置时给用户看的提示（不是默认值 —— 强制用户填自己的域名）
PLACEHOLDER_URL = "https://你的域名"


class UploadError(RuntimeError):
    """带用户可读文案的网络错误。

    服务端返回的 message 直接透传 —— 那是写给用户看的
    （"密码不正确"、"上传过于频繁，请 3 分钟后再试"）。
    """

    def __init__(self, message: str, *, status: int = 0):
        super().__init__(message)
        self.message = message
        self.status = status

    @property
    def is_auth_error(self) -> bool:
        return self.status in (401, 403)


def _request(method: str, url: str, *, payload: dict | None = None,
             token: str = "", timeout: float = 60.0) -> dict:
    """发一次请求，返回解析后的 JSON。

    失败一律抛 UploadError，且 message 是可以直接弹给用户看的中文。
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as err:
        raise UploadError(_error_message(err), status=err.code) from err
    except URLError as err:
        raise UploadError(f"连不上服务器：{err.reason}") from err
    except OSError as err:
        # 超时、连接重置等
        raise UploadError(f"网络错误：{err}") from err

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as err:
        # 服务端约定 /api/* 永远返回 JSON；返回了别的说明
        # 多半是被中间的代理/门户页拦截了
        raise UploadError("服务器返回了无法识别的内容，请检查地址是否正确") from err
    if not isinstance(parsed, dict):
        raise UploadError("服务器返回了无法识别的内容")
    return parsed


def _error_message(err: HTTPError) -> str:
    """从错误响应里取服务端给的中文文案，取不到就按状态码兜底。"""
    try:
        payload = json.loads(err.read().decode("utf-8"))
        if isinstance(payload, dict) and payload.get("message"):
            return str(payload["message"])
    except Exception:                       # noqa: BLE001
        pass
    return {
        400: "请求有误，请检查填写的内容",
        401: "登录已失效，请重新登录",
        403: "没有权限执行该操作",
        404: "服务器地址不对，或该账号不存在",
        409: "该用户名已被注册",
        413: "上传内容过大",
        429: "操作过于频繁，请稍后再试",
        500: "服务器内部错误，请稍后再试",
    }.get(err.code, f"服务器返回错误（HTTP {err.code}）")


def _url(server_url: str, path: str) -> str:
    return normalize_server_url(server_url) + path


# -- 接口 -------------------------------------------------------------------

def probe(server_url: str, *, timeout: float = 12.0) -> dict:
    """探测地址是否是一个能用的服务端。"""
    result = _request("GET", _url(server_url, "/healthz"), timeout=timeout)
    if not result.get("ok"):
        raise UploadError("该地址不是本工具的服务端")
    return result


def register(server_url: str, username: str, password: str) -> dict:
    return _request("POST", _url(server_url, "/api/register"),
                    payload={"username": username, "password": password})


def login(server_url: str, username: str, password: str) -> dict:
    """返回 {"token": ..., "username": ...}。"""
    result = _request("POST", _url(server_url, "/api/login"),
                      payload={"username": username, "password": password})
    if not result.get("token"):
        raise UploadError("登录失败：服务器没有返回凭证")
    return result


def logout(server_url: str, token: str) -> None:
    try:
        _request("POST", _url(server_url, "/api/logout"), token=token, timeout=12.0)
    except UploadError:
        # 退出登录失败不影响本地清凭据 —— 本地删掉就够了
        pass


def fetch_me(server_url: str, token: str) -> dict:
    return _request("GET", _url(server_url, "/api/me"), token=token, timeout=20.0)


def upload(server_url: str, token: str, categories: Any, *,
           mode: str = "merge", timeout: float = 120.0) -> dict:
    """上传抽卡数据。

    categories 就是本地归档里的那一坨：{外层key: [组, ...]}。
    服务器会按 Gid 重新归类、与库里的数据合并。

    返回 {"added": 新增组数, "groups": 总组数, "pulls": 总抽数}。
    """
    return _request("POST", _url(server_url, "/api/upload"),
                    payload={"categories": categories, "mode": mode},
                    token=token, timeout=timeout)


def change_password(server_url: str, token: str, old: str, new: str) -> dict:
    return _request("POST", _url(server_url, "/api/password"),
                    payload={"old": old, "new": new}, token=token)


def delete_account(server_url: str, token: str, password: str) -> dict:
    return _request("POST", _url(server_url, "/api/account/delete"),
                    payload={"password": password}, token=token)


# -- 本地归档 ---------------------------------------------------------------

def read_archive(output_dir: Path) -> dict:
    """读**当前账号**归档里的 categories。

    ⚠️ 上传的是【归档】而不是本次读取的快照：归档是与历史合并后的完整数据，
    而 snapshot.gacha_categories 只有本次读到的部分。用后者会把服务器上
    更早的历史越传越少。
    """
    from .service import active_data_dir  # 延迟导入: 避免 service ←→ server_upload 循环

    path = Path(active_data_dir(Path(output_dir))) / ARCHIVE_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise UploadError("读不到本地归档，请先点「抓取抽卡记录」读取一次") from err
    if not isinstance(payload, dict):
        raise UploadError("本地归档格式不对")
    categories = payload.get("categories")
    if not isinstance(categories, dict) or not categories:
        raise UploadError("本地归档里还没有抽卡记录，请先读取一次游戏数据")
    return categories


__all__ = [
    "UploadError", "PLACEHOLDER_URL", "probe", "register", "login", "logout",
    "fetch_me", "upload", "change_password", "delete_account", "read_archive",
]
