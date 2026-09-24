from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import server_config
from .service import extract_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="只读导出《星塔旅人》招募记录")
    parser.add_argument(
        "--server", choices=sorted(server_config.PROFILES), default=None,
        help="游戏版本: 国服 cn / 国际服 intl(默认: 读取输出目录下的 server.json, 无则国服)",
    )
    parser.add_argument(
        "--process", default=None,
        help="游戏进程名(默认: 按所选版本自动判断, 如 xtlr.exe / StellaSora.exe)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.cwd() / "exports",
        help="导出目录（默认：当前目录下 exports）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.server is not None:
        server_config.set_active(args.server)
    else:
        server_config.init_from(args.output)
    try:
        snapshot = extract_snapshot(args.output, args.process, progress=print)
        print(
            f"完成：{len(snapshot.gacha)} 组招募记录，共 {snapshot.pull_count} 个结果。"
        )
        for path in snapshot.files:
            print(path)
        return 0
    except (OSError, ValueError, LookupError, ProcessLookupError) as error:
        print(f"导出失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
