# -*- coding: utf-8 -*-
"""
重建 assets 资源清单与资源包（发布前的最后一步）。

做什么：
1. 扫描 assets/travelers/ 与 assets/discs/ 的全部 PNG，重算 sha256；
2. 用 assets/stellabase_5star/*.json（StellaBase 抓取数据）补齐清单里缺失条目的
   name / rarity —— 即本次新增的 5 星角色和秘纹；
3. 更新两份清单（resource_manifest.json / _github.json），
   resources.zip 与 archive_sha256 一并重建。

用法::

    python tools/rebuild_resource_manifest.py
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FETCH_DIR = Path(__file__).resolve().parent / "stellabase_cache"  # 抓取元数据缓存(由 fetch_stellabase.py 重新生成)
MANIFESTS = [
    ROOT / "resource_manifest.json",
    ROOT / "resource_manifest_github.json",
]
ZIP_PATH = ROOT / "resources.zip"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def scan_assets(folders: dict[str, str]) -> list[dict[str, object]]:
    """folders: {'travelers': 'traveler', 'discs': 'disc'} -> 全部 PNG 的清单条目（不含 name/rarity 回填）。"""
    items: list[dict[str, object]] = []
    for folder, kind in folders.items():
        for png in sorted((ASSETS / folder).glob("*.png")):
            item_id = int(png.stem)
            content = png.read_bytes()
            items.append({
                "id": item_id,
                "kind": kind,
                "path": f"{folder}/{png.name}",
                "sha256": sha256(content),
            })
    return items


def backfill_metadata(items: list[dict[str, object]]) -> None:
    """从抓取的 StellaBase 数据回填 name/rarity（仅对缺失的新条目）。"""
    fetched: dict[str, dict[str, dict]] = {
        "traveler": {row["id"]: row for row in json.loads((FETCH_DIR / "travelers.json").read_text("utf-8"))},
        "disc": {row["id"]: row for row in json.loads((FETCH_DIR / "discs.json").read_text("utf-8"))},
    }
    for item in items:
        kind, item_id = str(item["kind"]), int(item["id"])
        row = fetched.get(kind, {}).get(item_id)
        if row:
            item["name"] = row["name"]
            item["rarity"] = row.get("grade" if kind == "traveler" else "star", 5)
        else:
            item.setdefault("rarity", 5)


def build_zip() -> bytes:
    """打包 travelers/ 与 discs/（update_resources 按 'travelers/110.png' 逐一读取）。"""
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder in ("travelers", "discs"):
            for png in sorted((ASSETS / folder).glob("*.png")):
                zf.write(png, f"{folder}/{png.name}")
    return ZIP_PATH.read_bytes()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    # 1) 扫描 + 回填元数据
    items = scan_assets({"travelers": "traveler", "discs": "disc"})
    backfill_metadata(items)
    print(f"资源盘点: {len(items)} 个 PNG")

    # 2) 更新三份清单（保留原 base_url / archive_url）
    archive_sha = sha256(build_zip())
    print(f"resources.zip 已重建 ({ZIP_PATH.stat().st_size} bytes)")

    for path in MANIFESTS:
        manifest = json.loads(path.read_text("utf-8"))
        manifest["items"] = items
        manifest["archive_url"] = manifest.get("archive_url")
        manifest["archive_sha256"] = archive_sha
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
        print(f"  ✓ {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
