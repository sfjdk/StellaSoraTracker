"""星塔旅人数据工具 —— Qt (PySide6) 桌面界面入口。

用法(在项目根目录):
    python -m stellasora_toolkit.gui --output exports
可选项:
    --dark       深色模式启动
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _install_crash_log() -> None:
    """把未捕获的 Python 异常写入 exe 同级的 crash.log,便于 windowed 下排查。"""
    import traceback

    def hook(etype, value, tb) -> None:
        try:
            log = Path(sys.executable).resolve().parent / "crash.log"
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
                traceback.print_exception(etype, value, tb, file=f)
        except Exception:
            pass

    sys.excepthook = hook


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="星塔旅人数据工具桌面界面")
    default_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
    parser.add_argument("--output", type=Path, default=default_root / "exports")
    parser.add_argument("--server", choices=["cn", "intl"], default=None, help="游戏版本: cn 国服 / intl 国际服")
    parser.add_argument("--dark", action="store_true", help="深色模式")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    return parser


def _ensure_admin() -> bool:
    """打包版: 检测是否已具管理员权限; 若不是, 通过 UAC 提权重启自身并返回 False。

    源码运行或 --smoke-test 时不提权。
    """
    if not getattr(sys, "frozen", False):
        return True
    if "--smoke-test" in sys.argv:
        return True
    try:
        import ctypes
        if ctypes.windll.shell32.IsUserAnAdmin():
            return True
        params = subprocess.list2cmdline(sys.argv[1:]) if len(sys.argv) > 1 else None
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        return False
    except Exception:
        return True


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _install_crash_log()
    if args.smoke_test:
        from .ui import window, views, widgets, theme  # noqa: F401
        return 0
    # 游戏版本: 命令行 > server.json > 默认国服(环境变量优先, 见 server_config)
    from . import server_config
    if args.server is not None:
        server_config.set_active(args.server)
    else:
        server_config.init_from(args.output)
    if not _ensure_admin():
        return 0  # 已请求提权重启, 原实例退出
    from .ui.window import run
    return run(args.output.resolve(), dark=args.dark)


if __name__ == "__main__":
    raise SystemExit(main())
