# -*- coding: utf-8 -*-
"""
从 StellaBase (https://stella.ennead.cc) 抓取《星塔旅人》5星秘纹与5星角色的数据与图片。

数据源（反向分析站点前端 JS 得出）：
    GET https://stella.ennead.cc/api/stella/discs?lang=cn     -- 秘纹（disc）全量数据
    GET https://stella.ennead.cc/api/stella/characters?lang=cn -- 角色（trekker）全量数据
    （中文语言参数必须是 lang=cn，zh / zh-CN 会返回 404）

图片为相对路径（如 /stella/assets/outfit_1001.png），需要拼上站点域名下载。

输出目录（相对本项目根目录）：
    assets/stellabase_5star/
        discs.json            5星秘纹元数据（含 story 全文）
        travelers.json        5星角色元数据
        discs/<id>.png        5星秘纹大图（base）
        discs/icons/<id>.png  5星秘纹小图标（icon）
        travelers/<id>.png    5星角色立绘/头像（portrait）
        travelers/icons/<id>.png 5星角色小头像（icon）

零第三方依赖（仅标准库）。当前 Python 3.14，直接运行即可。
"""

from __future__ import annotations

import json
import sys
import time

# Windows 控制台默认 GBK，直接 print 非 ASCII 字符（如 ✓）会抛 UnicodeEncodeError。
# 允许替换字符而不是崩溃（UTF-8 终端下正常显示，GBK 终端下显示为 ?）。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# 配置区
# ---------------------------------------------------------------------------

SITE = "https://stella.ennead.cc"
API_BASE = f"{SITE}/api/stella"
LANG = "cn"                       # 站点自定义语言名：cn 为简体中文
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
TARGET_STAR = 5                   # 只保留 5 星的秘纹/角色
RETRIES = 3                       # 单次请求失败重试次数
RETRY_DELAY = 2.0                 # 重试间隔（秒）

# 输出目录：tools/stellabase_cache（JSON 供 rebuild_resource_manifest 回填元数据；图片为中间产物）
OUT_DIR = Path(__file__).resolve().parent / "stellabase_cache"


# ---------------------------------------------------------------------------
# 网络层
# ---------------------------------------------------------------------------

def _headers() -> dict[str, str]:
    return {"Accept": "application/json", "User-Agent": USER_AGENT}


def fetch_json(url: str) -> object:
    """GET + JSON 解析，带重试。失败抛出最后一次的异常。"""
    last_err: Exception | None = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=_headers())
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
            last_err = err
            print(f"  ! 第 {attempt + 1} 次请求失败: {err}")
            if attempt < RETRIES - 1:
                time.sleep(RETRY_DELAY)
    raise RuntimeError(f"请求失败（重试 {RETRIES} 次）: {url}") from last_err


def download_image(url: str, dest: Path) -> bool:
    """下载图片到 dest（自动建目录）。返回是否成功。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return True  # 已存在，跳过
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=_headers())
            with urllib.request.urlopen(req, timeout=60) as resp:
                dest.write_bytes(resp.read())
            return True
        except Exception as err:  # noqa: BLE001 - 图片失败直接重试
            if attempt == RETRIES - 1:
                print(f"  ! 下载失败: {url} -> {err}")
                return False
            time.sleep(RETRY_DELAY)
    return False


def resolve_asset(path: str) -> str:
    """
    把接口返回的相对路径拼成可下载的完整 URL。

    /stella/assets/ 开头的资源不能直连主域（返回 520），必须经过
    /api/asset 代理（站点 JS 里的 kp() 函数，反向分析得出）：
        /stella/assets/outfit_1001.png -> https://stella.ennead.cc/api/asset/stella/assets/outfit_1001.png
    """
    if path.startswith("http"):
        return path
    return f"{SITE}/api/asset{path}"


# ---------------------------------------------------------------------------
# 过滤与保存
# ---------------------------------------------------------------------------

def filter_five_star(items: list[dict], star_field: str) -> list[dict]:
    """按 star_field（discs 用 star，角色用 grade）过滤出 TARGET_STAR。"""
    return [it for it in items if (it.get(star_field) or 0) >= TARGET_STAR]


def save_json(data: object, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / name
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ {out.relative_to(OUT_DIR.parent.parent)}")


def scrape_discs() -> None:
    print("[1/2] 抓取秘纹数据 ...")
    discs = fetch_json(f"{API_BASE}/discs?lang={LANG}")
    five_star = filter_five_star(discs, "star")
    print(f"  共 {len(discs)} 个秘纹，5星 {len(five_star)} 个")
    save_json(five_star, "discs.json")

    ok = 0
    for i, d in enumerate(five_star, 1):
        img = d.get("base") or d.get("icon")
        if not img:
            continue
        if download_image(resolve_asset(img), OUT_DIR / "discs" / f"{d['id']}.png"):
            ok += 1
        d.get("icon") and download_image(
            resolve_asset(d["icon"]),
            OUT_DIR / "discs" / "icons" / f"{d['id']}.png",
        )
        print(f"  下载图纸 {i}/{len(five_star)}: {d['name']}")
    print(f"  秘纹图片下载完成 {ok}/{len(five_star)}")


def scrape_travelers() -> None:
    print("[2/2] 抓取角色数据 ...")
    chars = fetch_json(f"{API_BASE}/characters?lang={LANG}")
    five_star = filter_five_star(chars, "grade")
    print(f"  共 {len(chars)} 个角色，5星 {len(five_star)} 个")
    save_json(five_star, "travelers.json")

    ok = 0
    for i, c in enumerate(five_star, 1):
        img = c.get("portrait") or c.get("icon")
        if not img:
            continue
        if download_image(resolve_asset(img), OUT_DIR / "travelers" / f"{c['id']}.png"):
            ok += 1
        c.get("icon") and download_image(
            resolve_asset(c["icon"]),
            OUT_DIR / "travelers" / "icons" / f"{c['id']}.png",
        )
        print(f"  下载 角色 {i}/{len(five_star)}: {c['name']}")
    print(f"  角色图片下载完成 {ok}/{len(five_star)}")


def main() -> int:
    print(f"输出目录: {OUT_DIR}")
    try:
        scrape_discs()
        scrape_travelers()
    except Exception as err:  # noqa: BLE001
        print(f"\n失败: {err}", file=sys.stderr)
        return 1
    print("\n全部完成 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
