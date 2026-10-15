# -*- coding: utf-8 -*-
"""把 release/github/StellaSoraGachaTool 打成发行 zip, 并同步更新更新清单。

用法(在项目根目录, 先跑 build_release.ps1 或 PyInstaller 产出目录):
    python tools/pack_release.py
    python tools/pack_release.py --notes "本次更新说明"

约定:
- 版本号只认 stellasora_toolkit/ui/constants.py 的 APP_VERSION, 不再手抄;
- zip 名与 GitHub 资产名一致: StellaSoraGachaTool-<版本>-win64.zip;
- **绝不**把运行时数据打进包: exports/、uid.json、account.json 一律排除, 并二次校验;
- 更新清单的 url 指向对应 tag 的 GitHub 资产。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stellasora_toolkit.ui.constants import APP_VERSION  # noqa: E402

SRC = ROOT / "release" / "github" / "StellaSoraGachaTool"
RELEASE_DIR = ROOT / "release"
MANIFESTS = (ROOT / "app_update.json", ROOT / "app_update_github.json")
REPO = "sfjdk/StellaSoraTracker"
EXCLUDED_PARTS = {"exports", "accounts", "backups", "logs", "__pycache__"}
EXCLUDED_NAMES = {
    "uid.json", "account.json", "accounts.json", "ui_settings.json", "fortune.json",
    "server.json", "stellasora_gacha_archive.json", "crash.log",
}


def is_runtime_data(path: Path) -> bool:
    parts = {part.casefold() for part in path.parts}
    return bool(EXCLUDED_PARTS & parts) or path.name.casefold() in EXCLUDED_NAMES or (
        path.suffix.casefold() == ".json" and path.stem.isdecimal()
    )


def build_zip(version: str, src: Path) -> Path:
    if not src.is_dir():
        raise SystemExit(f"未找到构建输出: {src}（先跑 build_release.ps1）")
    zip_path = RELEASE_DIR / f"StellaSoraGachaTool-{version}-win64.zip"
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=RELEASE_DIR, suffix=".zip.part")
    os.close(descriptor)
    temporary = Path(temporary_name)
    # zip 内顶层目录固定叫 StellaSoraGachaTool(无论构建输出放在哪个目录)
    top = "StellaSoraGachaTool"
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(src.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(src)
                if is_runtime_data(relative):
                    continue
                archive.write(path, f"{top}/{relative.as_posix()}")
        with zipfile.ZipFile(temporary) as archive:
            leaked = [n for n in archive.namelist() if is_runtime_data(Path(n))]
        if leaked:
            raise SystemExit(f"发行包里混入了运行时数据: {leaked[:5]}")
        temporary.replace(zip_path)
    finally:
        temporary.unlink(missing_ok=True)
    return zip_path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def update_manifest(path: Path, version: str, asset: str, sha: str, notes: str | None) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["version"] = version
    payload["url"] = f"https://github.com/{REPO}/releases/download/v{version}/{asset}"
    payload["sha256"] = sha
    if notes:
        payload["notes"] = notes
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="打包发行 zip 并更新清单")
    parser.add_argument("--notes", default="", help="更新说明(不填则保留清单里原有的)")
    parser.add_argument("--src", type=Path, default=SRC,
                        help="构建输出目录(默认 release/github/StellaSoraGachaTool)")
    args = parser.parse_args(argv)

    zip_path = build_zip(APP_VERSION, args.src)
    sha = sha256_file(zip_path)
    for manifest in MANIFESTS:
        update_manifest(manifest, APP_VERSION, zip_path.name, sha, args.notes or None)

    with zipfile.ZipFile(zip_path) as archive:
        entries = len(archive.namelist())
    print(json.dumps({
        "version": APP_VERSION,
        "zip": zip_path.name,
        "zip_mb": round(zip_path.stat().st_size / 1024 / 1024, 1),
        "entries": entries,
        "sha256": sha,
        "manifests": [m.name for m in MANIFESTS],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
