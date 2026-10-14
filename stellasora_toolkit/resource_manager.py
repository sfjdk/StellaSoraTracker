from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from . import server_config
from .app_updater import UPDATE_MANIFEST_ENV_VAR
from .catalog import is_gacha_item


# 资源清单与更新清单共用同一环境变量(STELLASORA_UPDATE_MANIFEST_GITHUB),
# 代码内不写死任何仓库地址; 未配置时更新流程视为"未配置"。
STELLABASE_API = "https://stella.ennead.cc/api/stella"
STELLABASE_ASSET_API = "https://stella.ennead.cc/api/asset"
DEFAULT_MANIFEST_URL = os.environ.get(UPDATE_MANIFEST_ENV_VAR, "").strip()
ProgressCallback = Callable[[str], None]


def _read_url(url: str, progress: ProgressCallback | None = None) -> bytes:
    request = Request(url, headers={"User-Agent": "StellaSoraToolkit/1.0"})
    last_error: OSError | None = None
    for attempt in range(2):
        try:
            with urlopen(request, timeout=15) as response:
                return response.read()
        except OSError as error:
            last_error = error
            if attempt == 0:
                if progress:
                    progress("资源连接超时，正在重试")
                time.sleep(1)
    raise OSError(f"resource download failed: {url}") from last_error


def _scrape_stellabase_items(progress: ProgressCallback | None = None) -> list[dict]:
    """Read current five-star portraits from StellaBase's public JSON API.

    lang 取当前激活版本(server_config), 名称语言与游戏一致。
    """
    discovered: list[dict] = []
    lang = server_config.api_lang()
    for endpoint, kind, folder, rarity_key in (
        (f"characters?lang={lang}", "traveler", "travelers", "grade"),
        (f"discs?lang={lang}", "disc", "discs", "star"),
    ):
        try:
            payload = json.loads(_read_url(f"{STELLABASE_API}/{endpoint}", progress).decode("utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, list):
            continue
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            try:
                item_id = int(entry["id"])
                rarity = int(entry.get(rarity_key, 0))
            except (KeyError, TypeError, ValueError):
                continue
            image_path = str(entry.get("icon") or "")
            if rarity < 5 or not image_path.startswith("/stella/assets/"):
                continue
            # 与 catalog_sync 同口径: BOSS/剧情单位不是抽卡产出物, 不该进头像库
            if not is_gacha_item(item_id):
                continue
            discovered.append(
                {
                    "id": item_id,
                    "kind": kind,
                    "name": str(entry.get("name") or f"{kind} #{item_id}"),
                    "rarity": rarity,
                    "path": f"{folder}/{item_id}.png",
                    "source_url": f"{STELLABASE_ASSET_API}{image_path}",
                }
            )
    return discovered


def _safe_asset_path(root: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".png":
        raise ValueError(f"invalid resource path: {relative_path}")
    resolved = (root / path).resolve()
    if root.resolve() not in resolved.parents:
        raise ValueError(f"resource path escapes asset directory: {relative_path}")
    return resolved


def update_resources(
    manifest_url: str,
    asset_root: Path,
    progress: ProgressCallback | None = None,
) -> tuple[list[dict], int]:
    if progress:
        progress("正在下载资源清单")
    manifest = json.loads(_read_url(manifest_url, progress).decode("utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("items"), list):
        raise ValueError("resource manifest format is invalid")
    base_url = urljoin(manifest_url, str(manifest.get("base_url", "./")))
    if urlparse(base_url).scheme not in {"http", "https"}:
        raise ValueError("resource manifest base URL is invalid")

    asset_root.mkdir(parents=True, exist_ok=True)
    items = [item for item in manifest["items"] if isinstance(item, dict)]
    scraped_items = _scrape_stellabase_items(progress)
    by_id: dict[tuple[str, int], dict] = {}
    for item in items:
        try:
            by_id[(str(item.get("kind")), int(item["id"]))] = item
        except (KeyError, TypeError, ValueError):
            continue
    for item in scraped_items:
        key = (str(item["kind"]), int(item["id"]))
        if key not in by_id:
            items.append(item)
            by_id[key] = item
        else:
            by_id[key].update({"name": item["name"]})
    pending: list[tuple[dict, str, Path, str]] = []
    for item in items:
        relative_path = str(item.get("path", ""))
        target = _safe_asset_path(asset_root, relative_path)
        expected_hash = str(item.get("sha256", "")).lower()
        if target.exists() and expected_hash:
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if digest == expected_hash:
                continue
        pending.append((item, relative_path, target, expected_hash))
    if not pending:
        if progress:
            progress("角色资源已是最新")
        return items, 0

    if progress:
        progress(f"正在下载角色资源包（{len(pending)} 个待更新）")
    archive_url = manifest.get("archive_url")
    archive_data: zipfile.ZipFile | None = None
    if archive_url:
        payload = _read_url(str(archive_url), progress)
        expected_archive_hash = str(manifest.get("archive_sha256", "")).lower()
        if expected_archive_hash and hashlib.sha256(payload).hexdigest().lower() != expected_archive_hash:
            raise ValueError("resource archive checksum mismatch")
        archive_data = zipfile.ZipFile(io.BytesIO(payload))
    if progress:
        progress("正在校验并写入角色资源")
    try:
        for _item, relative_path, target, expected_hash in pending:
            source_url = str(_item.get("source_url") or "")
            payload = archive_data.read(relative_path) if archive_data and not source_url else _read_url(
                source_url or urljoin(base_url, relative_path), progress
            )
            if expected_hash and hashlib.sha256(payload).hexdigest().lower() != expected_hash:
                raise ValueError(f"resource checksum mismatch: {relative_path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix="stella-resource-", suffix=".tmp", dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as temp_file:
                    temp_file.write(payload)
                os.replace(temp_name, target)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
    finally:
        if archive_data:
            archive_data.close()
    return items, len(pending)
