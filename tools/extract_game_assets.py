# -*- coding: utf-8 -*-
"""从《星塔旅人》客户端 Unity AssetBundle 提取角色头像与秘纹图片。

设计要点
--------
1. 只读游戏文件 —— 从不写入游戏目录, 不修改任何游戏数据;
2. Patch_Store 与 Persistent_Store 合并, 后扫的 Patch_Store 覆盖同名精灵
   (新版本新增/更新的资源优先以 Patch 为准);
3. 输出命名与工具资产目录对齐:
       travelers/<玩家ID>.png   <- head_<玩家ID*100+1>01_XL  如 head_11001_XL -> 110.png
       discs/<秘纹ID>.png       <- DiscSkill_<秘纹ID>_S       如 DiscSkill_214001_S -> 214001.png
4. 每类资源写一份 JSON 清单(来源 bundle、原始精灵名), 便于回溯与打包。

用法::

    python tools/extract_game_assets.py [游戏根目录] [--output DIR]

    # 默认游戏根目录: F:\\YostarGames\\StellaSora_CN
    # 默认输出目录:   tools/out/
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

try:
    import UnityPy
except ImportError:  # pragma: no cover
    raise SystemExit("缺少依赖: pip install UnityPy")

# ---------------------------------------------------------------------------
# 匹配规则
# ---------------------------------------------------------------------------
# 游戏内部精灵名(icon-*.unity3d 中的 Sprite 名) -> 工具 ID:
#
#   head_11001_XL  玩家头像: 内部 ID "11001" // 100 = 玩家 110 (翡冷翠)
#                  尾部两位 01 = 原皮本体, 02/03/04 与 _SK = 换装/皮肤
#   DiscSkill_214001_S   秘纹技能图标: 直接为秘纹 ID
#
# 剔除: head_npc*/head_anonymity/head_group、4 位系统头像(head_9100_*)、
#       弃用的怪物头像等。

# 头像变体优先级: 游戏内同一角色有多个精灵, 内容并不等价!
#   _S (208x208) 圆形纯头像(无背景)  —— 本工具 assets/travelers 用的就是这种
#   _SS (106x106) 小号纯头像, 画质更低
#   _XL/_XXL/_L   半身立绘(带背景)    —— 旧版本脚本误选此档
#   _SK           皮肤立绘(带背景), 仅无 _S 时兜底(如 head_10001_SK)
#   其余 _Q/_QM/_QS/_QSS 为 Q 版头像, _GC/_GD/_GOODS 为商店/徽章用途, 不用.
HEAD_SIZE_ORDER = ("S", "SS", "XL", "XXL", "L", "SK")
# 头像中 5 位内部 ID 的玩家号段: 100xx ~ 160xx
PLAYER_BASE_PREFIXES = ("100", "101", "102", "103", "104", "105", "106",
                        "107", "108", "109", "110", "111", "112", "113",
                        "114", "115", "116", "117", "118", "119", "120",
                        "121", "122", "123", "124", "125", "126", "127",
                        "128", "129", "130", "131", "132", "133", "134",
                        "135", "136", "137", "138", "139", "140", "141",
                        "142", "143", "144", "145", "146", "147", "148",
                        "149", "150", "151", "152", "153", "154", "155",
                        "156", "157", "158", "159", "160", "161")
HEAD_EXCLUDES = ("npc", "anonymity", "group")
DISC_PREFIX = "DiscSkill_"


def parse_head(name: str) -> tuple[int, str] | None:
    """'head_11001_XL' -> (玩家 ID, 是否本体); 非玩家头像返回 None."""
    if not name.startswith("head_"):
        return None
    if any(name.startswith(f"head_{p}") for p in HEAD_EXCLUDES):
        return None
    body = name[5:].split("_")[0]
    if not body.isdigit() or len(body) not in (4, 5):
        return None
    if len(body) == 4:  # 系统/占位头像
        return None
    base, variant = body[:3], body[3:5]
    if base not in PLAYER_BASE_PREFIXES:
        return None
    return int(base), variant == "01"


def parse_disc(name: str) -> int | None:
    """'DiscSkill_214001_S' -> 秘纹 ID; 非秘纹返回 None."""
    if not name.startswith(DISC_PREFIX):
        return None
    body = name[len(DISC_PREFIX):].split("_")[0]
    if body.isdigit() and len(body) == 6 and body.startswith("21"):
        return int(body)
    return None


# ---------------------------------------------------------------------------
# 扫描
# ---------------------------------------------------------------------------

def iter_bundles(game_root: Path):
    """Persistent_Store 在前, Patch_Store 在后(后者可覆盖)."""
    for store in ("Persistent_Store", "Patch_Store"):
        ab = game_root / store / "AssetBundles"
        if ab.is_dir():
            yield from sorted(ab.glob("*.unity3d"))


def collect(game_root: Path, progress=None):
    """扫描全部 bundles, 返回:

    travelers: {(玩家ID, 尺寸): (PIL.Image, bundle名, 精灵名)}
    discs:     {秘纹ID: (PIL.Image, bundle名, 精灵名)}

    注意: 必须在此解码图片. UnityPy 的 Object 引用绑定在其 Environment 上,
          循环结束后 env 被回收, 之后再取 .image 会静默失败.
    """
    travelers: dict = {}
    discs: dict = {}
    for bundle_path in iter_bundles(game_root):
        try:
            # UnityPy.load 只接受 str, Path 会抛 TypeError
            env = UnityPy.load(str(bundle_path))
        except Exception:
            continue  # 跳过损坏/加密的包
        for obj in env.objects:
            if obj.type.name != "Sprite":
                continue
            name = obj.read().m_Name
            hit = parse_head(name)
            if hit is not None:
                player_id, is_base = hit
                if not is_base:
                    continue  # 只取原皮本体, 换装暂不入库
                # 按 "_" 分段精确匹配变体, 避免 _XXLS/_SK 等复合后缀误判
                parts = name.split("_")
                size = next((s for s in HEAD_SIZE_ORDER if s in parts), "X")
                try:
                    img = obj.read().image
                except Exception:
                    img = None
                if img is not None:
                    travelers[(player_id, size)] = (img, bundle_path.name, name)
            did = parse_disc(name)
            if did is not None:
                try:
                    img = obj.read().image
                except Exception:
                    img = None
                if img is not None:
                    discs[did] = (img, bundle_path.name, name)
        if progress:
            progress(bundle_path)
    return travelers, discs


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------

def save_png(img, dest: Path) -> bool:
    """将 PIL Image 存盘. 成功返回 True."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest)
        return True
    except Exception:
        return False


def run(game_root: Path, out_root: Path, progress=None) -> dict:
    travelers, discs = collect(game_root, progress)

    # 同一玩家同尺寸可能选中多个包(persistent + patch), 后者覆盖前者已在 collect 内完成.
    # 同名精灵在多个尺寸择优; "X" 为无已知变体后缀时的兜底键
    PICK_ORDER = HEAD_SIZE_ORDER + ("X",)

    def pick_size(by_id: dict, key_id):
        for size in PICK_ORDER:
            if (key_id, size) in by_id:
                return by_id[(key_id, size)]
        return None

    t_items = {}
    for (pid, _size), _ in travelers.items():
        hit = pick_size(travelers, pid)
        if hit is not None:
            t_items[pid] = hit

    t_manifest = []
    for pid in sorted(t_items):
        img, src, raw = t_items[pid]
        dest = out_root / "travelers" / f"{pid}.png"
        if save_png(img, dest):
            t_manifest.append({"id": pid, "file": f"travelers/{pid}.png",
                               "source": src, "sprite": raw})

    d_manifest = []
    for did in sorted(discs):
        img, src, raw = discs[did]
        dest = out_root / "discs" / f"{did}.png"
        if save_png(img, dest):
            d_manifest.append({"id": did, "file": f"discs/{did}.png",
                               "source": src, "sprite": raw})

    manifest = {
        "game_root": str(game_root),
        "date": date.today().isoformat(),
        "travelers": t_manifest,
        "discs": d_manifest,
    }
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("game_root", nargs="?", default=r"F:\YostarGames\StellaSora_CN",
                    help="游戏安装目录(默认 F:\\YostarGames\\StellaSora_CN)")
    ap.add_argument("--output", default=None, help="输出目录(默认 tools/out)")
    args = ap.parse_args()

    out = Path(args.output) if args.output else Path(__file__).parent / "out"

    def progress(p: Path):
        print(f"  读取 {p.name}", end="\r", flush=True)

    print(f"扫描: {args.game_root}")
    manifest = run(Path(args.game_root), out, progress)
    print("\n" + "=" * 40)
    print(f"输出: {out}")
    print(f"  角色头像  {len(manifest['travelers'])} 张")
    print(f"  秘纹图标  {len(manifest['discs'])} 张")
    print(f"清单:       {out / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
