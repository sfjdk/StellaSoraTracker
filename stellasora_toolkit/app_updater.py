from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


# 更新渠道只有 GitHub 一个。
# 清单地址不写死在代码里, 由环境变量提供:
#   STELLASORA_UPDATE_MANIFEST_GITHUB : 更新清单完整 URL
# 未配置时更新检查视为"未配置", 直接提示而不会去请求任何地址。
UPDATE_MANIFEST_ENV_VAR = "STELLASORA_UPDATE_MANIFEST_GITHUB"


def update_urls() -> list[str]:
    """返回更新清单地址; 未配置时返回空列表。"""
    url = os.environ.get(UPDATE_MANIFEST_ENV_VAR, "").strip()
    return [url] if url else []


UPDATE_MANIFEST_URL = next(iter(update_urls()), "")

APP_EXE_NAME = "StellaSoraGachaTool.exe"
UPDATER_EXE_NAME = "StellaSoraUpdater.exe"
APP_INSTALL_FOLDER = "StellaSoraGachaTool"
APP_REGISTRY_KEY = r"Software\StellaSoraGachaTool"
ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class AppUpdate:
    version: str
    url: str
    sha256: str
    notes: str
    installer_url: str | None = None
    installer_sha256: str | None = None

    @property
    def has_installer(self) -> bool:
        return self.installer_url is not None and self.installer_sha256 is not None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _version_tuple(value: str) -> tuple[int, ...]:
    text = value.strip().lower().removeprefix("v")
    # 去掉预发布/build 元数据(如 1.2.17-beta.1 / 1.2.17+abc)后再比较
    core = text.split("-")[0].split("+")[0]
    parts = core.split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise ValueError(f"invalid version: {value}")
    return tuple(int(part) for part in parts)


def is_newer_version(candidate: str, current: str) -> bool:
    candidate_parts = _version_tuple(candidate)
    current_parts = _version_tuple(current)
    length = max(len(candidate_parts), len(current_parts))
    return candidate_parts + (0,) * (length - len(candidate_parts)) > current_parts + (0,) * (length - len(current_parts))


def parse_update_manifest(manifest: object) -> AppUpdate:
    if not isinstance(manifest, dict):
        raise ValueError("app update manifest format is invalid")
    installer_url = manifest.get("installer_url")
    installer_sha256 = manifest.get("installer_sha256")
    if (installer_url is None) != (installer_sha256 is None):
        raise ValueError("app installer update manifest is invalid")
    update = AppUpdate(
        version=str(manifest["version"]),
        url=str(manifest["url"]),
        sha256=str(manifest["sha256"]).lower(),
        notes=str(manifest.get("notes", "")),
        installer_url=str(installer_url) if installer_url is not None else None,
        installer_sha256=str(installer_sha256).lower() if installer_sha256 is not None else None,
    )
    if urlparse(update.url).scheme != "https" or len(update.sha256) != 64:
        raise ValueError("app update manifest is invalid")
    if update.has_installer and (
        urlparse(update.installer_url or "").scheme != "https" or len(update.installer_sha256 or "") != 64
    ):
        raise ValueError("app installer update manifest is invalid")
    return update


def check_for_update(manifest_urls, current_version: str) -> AppUpdate | None:
    """按优先级依次检查清单源; 某源正常(无论有无新版)即返回, 全部失败才抛错。"""
    if isinstance(manifest_urls, str):
        manifest_urls = [manifest_urls]
    last_error: Exception | None = None
    for manifest_url in manifest_urls:
        try:
            request = Request(manifest_url, headers={"User-Agent": "StellaSoraToolkit/1.0"})
            with urlopen(request, timeout=12) as response:
                manifest = json.loads(response.read().decode("utf-8"))
            update = parse_update_manifest(manifest)
            return update if is_newer_version(update.version, current_version) else None
        except Exception as err:
            last_error = err
            continue
    raise last_error if last_error is not None else RuntimeError("update check failed")


def is_installed_application(executable: Path) -> bool:
    executable = executable.resolve()
    if executable.name.casefold() != APP_EXE_NAME.casefold():
        return False
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_REGISTRY_KEY) as key:
                install_location, _ = winreg.QueryValueEx(key, "InstallLocation")
            if executable.parent == Path(str(install_location)).resolve():
                return True
        except OSError:
            pass
        if any(executable.parent.glob("unins*.exe")):
            return True
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        expected = Path(local_app_data) / APP_INSTALL_FOLDER / APP_EXE_NAME
        if executable == expected.resolve():
            return True
    # Older installers did not persist their selected directory. Preserve support
    # for their custom locations while keeping ordinary download folders portable.
    return executable.parent.name.casefold() == APP_INSTALL_FOLDER.casefold()


def download_update(
    update: AppUpdate,
    target_dir: Path,
    progress: ProgressCallback | None = None,
    *,
    installer: bool = False,
    retries: int = 3,
) -> Path:
    if installer and not update.has_installer:
        raise ValueError("installer update is unavailable")
    download_url = update.installer_url if installer else update.url
    expected_hash = update.installer_sha256 if installer else update.sha256
    assert download_url is not None and expected_hash is not None
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(urlparse(download_url).path).suffix or ".bin"
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        fd, temp_name = tempfile.mkstemp(prefix="stellasora-update-", suffix=suffix, dir=target_dir)
        digest = hashlib.sha256()
        try:
            request = Request(download_url, headers={"User-Agent": "StellaSoraToolkit/1.0"})
            with os.fdopen(fd, "wb") as output, urlopen(request, timeout=30) as response:
                total = int(response.headers.get("Content-Length", 0))
                received = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    if progress and total:
                        progress(f"正在下载软件更新 {received * 100 // total}%")
            if digest.hexdigest().lower() != expected_hash:
                raise ValueError("software update checksum mismatch")
            return Path(temp_name)
        except Exception as err:
            last_error = err
            if os.path.exists(temp_name):
                os.unlink(temp_name)
            if attempt < retries:
                if progress:
                    progress(f"下载失败，正在重试(第 {attempt} 次)")
                continue
    raise last_error if last_error is not None else RuntimeError("download failed")


def launch_update_installer(package: Path, executable: Path) -> None:
    if os.name != "nt":
        raise OSError("automatic software updates are only supported on Windows")
    executable = executable.resolve(strict=True)
    package = package.resolve(strict=True)
    bundled_updater = executable.parent / UPDATER_EXE_NAME
    helper_dir = Path(tempfile.mkdtemp(prefix="stellasora-updater-"))
    helper = helper_dir / UPDATER_EXE_NAME
    try:
        if bundled_updater.is_file():
            shutil.copy2(bundled_updater, helper)
        else:
            _extract_update_installer(package, helper)
    except Exception:
        shutil.rmtree(helper_dir, ignore_errors=True)
        raise
    args = [
        str(helper),
        "--package",
        str(package),
        "--target-dir",
        str(executable.parent),
        "--parent-pid",
        str(os.getpid()),
        "--executable",
        executable.name,
        "--cleanup-dir",
        str(helper_dir),
    ]

    if _directory_is_writable(executable.parent):
        subprocess.Popen(args, cwd=str(executable.parent))
        return

    parameters = subprocess.list2cmdline(args[1:])
    result = __import__("ctypes").windll.shell32.ShellExecuteW(
        None,
        "runas",
        str(helper),
        parameters,
        str(executable.parent),
        1,
    )
    if result <= 32:
        raise OSError(f"failed to start elevated updater: {result}")


def update_installer_available(executable: Path) -> bool:
    return (executable.resolve().parent / UPDATER_EXE_NAME).is_file()


def _extract_update_installer(package: Path, destination: Path) -> None:
    with zipfile.ZipFile(package, "r") as archive:
        candidates = [
            info
            for info in archive.infolist()
            if not info.is_dir() and Path(info.filename.replace("\\", "/")).name.casefold() == UPDATER_EXE_NAME.casefold()
        ]
        if len(candidates) != 1:
            raise FileNotFoundError(f"update package must contain exactly one {UPDATER_EXE_NAME}")
        with archive.open(candidates[0]) as source, destination.open("wb") as output:
            shutil.copyfileobj(source, output)


def _directory_is_writable(directory: Path) -> bool:
    try:
        fd, probe = tempfile.mkstemp(prefix=".stellasora-write-test-", dir=directory)
        os.close(fd)
        os.unlink(probe)
        return True
    except OSError:
        return False
