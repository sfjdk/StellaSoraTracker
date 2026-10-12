# -*- coding: utf-8 -*-
"""诊断脚本: 找出游戏内存里的账号 UID 到底存在哪个字段 + 各阶段耗时。

用法(游戏要开着并已登录, **必须用管理员身份运行**):
    python tools/probe_game_uid.py                          # 全量扫描(扫所有含 uid 的字段名)
    python tools/probe_game_uid.py --uid 100872990          # 再按这个值反查真实字段名
    python tools/probe_game_uid.py --name _roleId           # 只试指定字段名(快速通道)
    python tools/probe_game_uid.py --uid 100872990 --json   # 机器可读输出(便于粘贴)

输出三段: [1] 名字含 uid 的字段 → 值  [2] 按值反查到的字段  [3] 结论与耗时。
只读: 不写任何文件、不改游戏内存(只会把学到的字段名记进 exports/uid.json 供下次加速)。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stellasora_toolkit import server_config  # noqa: E402
from stellasora_toolkit.account_uid import find_account_uid, is_plausible_uid  # noqa: E402
from stellasora_toolkit.discovery import LuaTableDiscovery  # noqa: E402
from stellasora_toolkit.lua53 import Lua53Reader  # noqa: E402
from stellasora_toolkit.process import (  # noqa: E402
    RemoteProcess, find_process_id, running_processes,
)
from stellasora_toolkit.service import effective_uid, load_uid_field, save_uid_field  # noqa: E402


def _timed(function, *args, **kwargs):
    start = time.perf_counter()
    value = function(*args, **kwargs)
    return value, time.perf_counter() - start


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="探测游戏内存里的账号 UID 字段")
    parser.add_argument("--uid", default="", help="已知 UID(不填则从 exports 里读)")
    parser.add_argument("--name", default="", help="只试这个字段名(快速通道)")
    parser.add_argument("--output", type=Path, default=ROOT / "exports", help="数据目录")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出(便于粘贴)")
    args = parser.parse_args(argv)
    try:
        return _probe(args)
    except ProcessLookupError as err:
        print(f"\n找不到游戏进程: {err}")
        print("请确认: 1) 游戏已启动并登录进主界面; 2) 客户端是国服 xtlr.exe / 国际服 StellaSora.exe。")
        return 2
    except OSError as err:
        print(f"\n打不开游戏进程: {err}")
        print("最常见的原因是没有管理员权限(或游戏有反作弊保护)。")
        print("请用【管理员身份】打开 PowerShell, 再跑一次:")
        print("    python tools\\probe_game_uid.py --uid 100872990")
        return 3


def _probe(args) -> int:

    known = str(args.uid).strip() or effective_uid(args.output)
    hint = str(args.name).strip() or load_uid_field(args.output)
    timings: dict[str, float] = {}

    running = [name for name, _pid in running_processes()]
    profile, _keys = server_config.resolve_running(running)
    names = (profile.client_names if profile else
             [n for prof in server_config.PROFILES.values() for n in prof.client_names])
    pid = find_process_id(names)
    if not args.json:
        print(f"已知 UID: {known or '(无 —— 只能按字段名扫)'}")
        print(f"字段提示: {hint or '(无 —— 走全量扫描)'}")
        print(f"运行中的客户端: {running or '(没有)'} → 连接 PID {pid}"
              f"（{profile.label if profile else '按当前设置版本'}）")

    with RemoteProcess(pid) as process:
        lua = Lua53Reader(process)
        discovery = LuaTableDiscovery(process, lua)

        if hint:
            by_name, timings["hint_scan"] = _timed(
                discovery.find_uid_candidates, is_plausible_uid, names=[hint])
        else:
            by_name, timings["hint_scan"] = {}, 0.0
        if not by_name:
            by_name, timings["broad_scan"] = _timed(
                discovery.find_uid_candidates, is_plausible_uid)
        else:
            timings["broad_scan"] = 0.0

        if known:
            by_value, timings["value_lookup"] = _timed(
                discovery.find_fields_with_value, known)
        else:
            by_value, timings["value_lookup"] = {}, 0.0

        search, timings["full_search"] = _timed(
            find_account_uid, discovery, preferred=known, field_hint=hint)

    resolved = {}
    if search.found:
        resolved = {"uid": search.uid, "field": search.field_name}
        save_uid_field(args.output, search.field_name)

    if args.json:
        print(json.dumps({
            "pid": pid,
            "client": profile.label if profile else "",
            "known_uid": known,
            "field_hint": hint,
            "by_name": {str(k): str(v) for k, v in by_name.items()},
            "by_value": {str(k): str(v) for k, v in by_value.items()},
            "candidates": [[n, v] for n, v in search.candidates],
            "resolved": resolved,
            "ambiguous": search.ambiguous,
            "verdict": search.summary(),
            "elapsed": {k: round(v, 2) for k, v in timings.items()},
        }, ensure_ascii=False, indent=2))
    else:
        print("\n[1] 名字含 uid 的字段（值通过 6-15 位纯数字校验）")
        print("    " + ("\n    ".join(f"{k} = {v}" for k, v in sorted(by_name.items())) or "（无）"))
        if known:
            print(f"\n[2] 按值 {known} 反查字段名")
            print("    " + ("\n    ".join(f"{k} = {v}" for k, v in sorted(by_value.items()))
                            or "（没找到 —— 该值可能不在 Lua 表里）"))
        print("\n[3] 结论")
        print(f"    {search.summary()}")
        if search.candidates:
            print("    全部候选: " + "、".join(f"{n}={v}" for n, v in search.candidates))
        if search.found:
            print(f"    → 工具采用 {search.uid}（字段 {search.field_name}）, 导出 {search.uid}.json")
            print(f"    → 字段名已记进 {args.output.name}/uid.json, 之后刷新走快速通道")
        elif search.ambiguous:
            print("    → 多候选: 工具不会自动选, 请在设置页手填 UID 后点「保存 UID」")
        else:
            print("    → 没扫到: 把这段输出发我, 我把真实字段名加进候选")
        print("\n耗时(秒): " + ", ".join(f"{k}={v:.2f}" for k, v in timings.items())
              + f" | 合计 {sum(timings.values()):.2f}s")
    return 0 if (search.found or by_name or by_value) else 1


if __name__ == "__main__":
    raise SystemExit(main())
