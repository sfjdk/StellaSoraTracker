from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath


APP_EXE_NAME = "StellaSoraGachaTool.exe"
UPDATER_EXE_NAME = "StellaSoraUpdater.exe"
WAIT_TIMEOUT_SECONDS = 180
PRESERVED_TOP_LEVELS = {"exports", "updates", "backups"}


def _log_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "StellaSoraGachaTool" / "logs"
    root.mkdir(parents=True, exist_ok=True)
    return root / "updater.log"


def log(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with _log_path().open("a", encoding="utf-8") as output:
        output.write(f"[{timestamp}] {message}\n")


def wait_for_process_exit(pid: int, timeout: float = WAIT_TIMEOUT_SECONDS) -> None:
    if pid <= 0 or os.name != "nt":
        return
    synchronize = 0x00100000
    wait_object_0 = 0
    wait_timeout = 0x00000102
    handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return
    try:
        result = ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        if result == wait_timeout:
            raise TimeoutError("等待主程序退出超时")
        if result != wait_object_0:
            raise OSError(f"等待主程序退出失败：{result}")
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _safe_member_path(name: str) -> PurePosixPath:
    member = PurePosixPath(name.replace("\\", "/"))
    if member.is_absolute() or not member.parts:
        raise ValueError(f"更新包包含非法路径：{name}")
    if any(part in {"", ".", ".."} for part in member.parts):
        raise ValueError(f"更新包包含非法路径：{name}")
    if ":" in member.parts[0]:
        raise ValueError(f"更新包包含非法路径：{name}")
    return member


def extract_update_package(package: Path, destination: Path) -> Path:
    with zipfile.ZipFile(package, "r") as archive:
        members = [(info, _safe_member_path(info.filename)) for info in archive.infolist()]
        for info, member in members:
            target = destination.joinpath(*member.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)

    candidates = [destination]
    top_levels = {member.parts[0] for _, member in members}
    if len(top_levels) == 1:
        candidates.insert(0, destination / next(iter(top_levels)))
    for candidate in candidates:
        if (candidate / APP_EXE_NAME).is_file():
            forbidden = PRESERVED_TOP_LEVELS.intersection(path.name.casefold() for path in candidate.iterdir())
            if forbidden:
                names = "、".join(sorted(forbidden))
                raise ValueError(f"更新包不应包含用户数据目录：{names}")
            return candidate
    raise ValueError(f"更新包中未找到 {APP_EXE_NAME}")


def replace_program_files(payload_root: Path, target_dir: Path, backup_dir: Path) -> None:
    entries = list(payload_root.iterdir())
    if not entries:
        raise ValueError("更新包内容为空")

    moved_old: list[tuple[Path, Path]] = []
    installed_new: list[Path] = []
    try:
        for source in entries:
            target = target_dir / source.name
            if target.exists():
                backup = backup_dir / source.name
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(backup))
                moved_old.append((target, backup))

        for source in entries:
            target = target_dir / source.name
            shutil.move(str(source), str(target))
            installed_new.append(target)
    except Exception:
        for target in reversed(installed_new):
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
        for target, backup in reversed(moved_old):
            if backup.exists():
                shutil.move(str(backup), str(target))
        raise


def apply_update(package: Path, target_dir: Path) -> Path:
    """替换程序文件, 成功后返回 work_dir(含旧程序备份)。

    备份由调用方在「重启成功」后再删除; 替换失败时 replace_program_files 内部会回滚。
    """
    package = package.resolve(strict=True)
    target_dir = target_dir.resolve(strict=True)
    work_dir = Path(tempfile.mkdtemp(prefix="stellasora-update-work-"))
    extract_dir = work_dir / "new"
    backup_dir = work_dir / "backup"
    extract_dir.mkdir()
    backup_dir.mkdir()
    log(f"开始解压更新包：{package}")
    payload_root = extract_update_package(package, extract_dir)
    log(f"开始替换程序文件：{target_dir}")
    replace_program_files(payload_root, target_dir, backup_dir)
    if not (target_dir / APP_EXE_NAME).is_file():
        raise RuntimeError("更新后主程序不存在")
    log("程序文件替换完成")
    return work_dir


def restart_application(target_dir: Path, executable_name: str) -> None:
    executable = target_dir / executable_name
    if not executable.is_file():
        raise FileNotFoundError(f"无法重新启动，文件不存在：{executable}")
    subprocess.Popen([str(executable)], cwd=str(target_dir))


def schedule_self_cleanup(helper_dir: Path | None) -> None:
    if os.name != "nt" or not getattr(sys, "frozen", False) or helper_dir is None:
        return
    helper_dir = helper_dir.resolve()
    if not helper_dir.name.startswith("stellasora-updater-"):
        log(f"跳过不安全的更新器清理路径：{helper_dir}")
        return
    quoted_helper_dir = str(helper_dir).replace("'", "''")
    command = (
        f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue; "
        f"Remove-Item -LiteralPath '{quoted_helper_dir}' -Recurse -Force -ErrorAction SilentlyContinue"
    )
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", command],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def show_error(message: str) -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, message, "星塔旅人数据工具更新失败", 0x10)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="星塔旅人数据工具更新程序")
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--executable", default=APP_EXE_NAME)
    parser.add_argument("--cleanup-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        log(f"更新程序启动，等待主程序 PID {args.parent_pid} 退出")
        wait_for_process_exit(args.parent_pid)
        work_dir = apply_update(args.package, args.target_dir)
        args.package.unlink(missing_ok=True)
        restart_application(args.target_dir.resolve(), args.executable)
        log("更新成功，已重新启动主程序")
        # 重启成功后再删除备份目录(失败时保留以便回滚)
        shutil.rmtree(work_dir, ignore_errors=True)
        schedule_self_cleanup(args.cleanup_dir)
        return 0
    except Exception as error:
        log(f"更新失败：{type(error).__name__}: {error}")
        show_error(f"自动更新未完成，原程序文件已尽量恢复。\n\n{error}\n\n日志：{_log_path()}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
