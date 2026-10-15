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
    parser.add_argument("--dark", action="store_true", help="深色模式")
    parser.add_argument("--beta", choices=("orbit", "sky", "journal"), help="UI Beta 风格")
    parser.add_argument("--demo", action="store_true", help="仅在内存中展示演示记录，不读取游戏或写入归档")
    parser.add_argument("--server", choices=("cn","intl","jp"), help="游戏版本：国服、国际服、日服")
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


def _smoke_test() -> int:
    """Render all bundled themes/pages without touching user archives or the network."""
    import tempfile
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication
    from .catalog_sync import asset_root
    from .ui.window import StellaSoraApp

    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setStyle("Fusion")
    if QPixmap(str(asset_root() / "app_icon.ico")).isNull():
        raise RuntimeError("Bundled application icon could not be loaded")
    with tempfile.TemporaryDirectory(prefix="stellasora-smoke-") as directory:
        for variant in ("orbit", "sky", "journal"):
            window = StellaSoraApp(Path(directory), variant=variant, demo=True, online_sync=False)
            window.show()
            for page in range(5):
                window.navigate(page)
                app.processEvents()
                if window.grab().isNull() or window.stack.currentIndex() != page:
                    raise RuntimeError(f"Could not render {variant} page {page}")
            if window.refresh_button.text() != "抓取抽卡记录" or len(window.nav_buttons) != 5:
                raise RuntimeError(f"Incomplete navigation in {variant}")
            window.close()
            window.deleteLater()
            app.processEvents()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _install_crash_log()
    if args.smoke_test:
        return _smoke_test()
    if args.server:
        from . import server_config
        server_config.set_active(args.server)
        if not args.demo:
            server_config.save_key(server_config.config_path(args.output),args.server,manual=True)
    if not _ensure_admin():
        return 0  # 已请求提权重启, 原实例退出
    from .ui.window import run
    return run(args.output.resolve(), dark=args.dark, variant=args.beta, demo=args.demo)


def __getattr__(name):
    # Preserve the original import used by test_gui without eagerly loading Qt for CLI use.
    if name == "StellaSoraApp":
        from .ui.window import StellaSoraApp
        return StellaSoraApp
    raise AttributeError(name)


if __name__ == "__main__":
    raise SystemExit(main())
