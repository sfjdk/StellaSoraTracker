from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .gacha_stats import history_category_key


GACHA_ALLOWED = {"Gid", "Time", "Ids", "NextPackage"}
EMBLEM_ALLOWED = {
    "nCharId",
    "nGemId",
    "nGenerateId",
    "nRefreshId",
    "nType",
    "sName",
    "sIcon",
    "bLock",
    "tbAffix",
    "tbRandomAttr",
    "tbAlterAffix",
    "tbUpgradeCount",
    "tbAlterUpgradeCount",
    "tbPotentialAffix",
    "tbSkillAffix",
    "tbEffect",
}


def _dict_values(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return []


def _int_key(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_group(value: Any) -> bool:
    return isinstance(value, dict) and "Gid" in value and "Ids" in value


def _is_group_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(_is_group(item) for item in value)


def unwrap_gacha_source(raw: Any) -> Any:
    """剥掉外层包装, 返回真正装着分类的那一层。

    需要兼容的几种真实形状:
        {"version":1,"uid":"...","updatedAt":"...","categories":{...}}  网页版/分享归档
        {"groups":[...],"categories":{...}}                            桌面版单次导出
        {"groups":[...]}                                               只存扁平记录的旧导出
        {"1":[...],"2":[...]}                                          归档读回来的字符串键
        {1:[...],2:[...]}                                              游戏 Lua 原始数据

    先认「键能转成整数」的那一层 —— 那是分类表本身, 不该再往下钻;
    否则依次尝试 categories / groups。元数据键(version/uid/updatedAt)不写死,
    靠值是不是分类表/记录列表判断, 免得以后多一个字段就解析不动。
    """
    node = raw
    for _ in range(6):
        if not isinstance(node, dict):
            return node
        if any(_int_key(key) is not None for key in node):
            return node
        nested: Any = None
        for key in ("categories", "groups"):
            value = node.get(key)
            if isinstance(value, dict) and value:
                nested = value
                break
            if _is_group_list(value):
                nested = value
                break
        if nested is None:
            return node
        node = nested
    return node


UID_KEYS = ("uid", "UID", "Uid")


def extract_uid(raw: Any) -> str:
    """取外壳里的 uid(网页版归档会带); 没有就返回空串。"""
    node = raw
    for _ in range(6):
        if not isinstance(node, dict):
            return ""
        for key in UID_KEYS:
            value = node.get(key)
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                continue
            text = str(value).strip()
            if text:
                return text
        node = node.get("categories")
    return ""


def normalize_category_keys(categories: dict[int, list[dict[str, Any]]]) -> dict[int, list[dict[str, Any]]]:
    """把记录放回官方的外层分类(1 旅人限时 / 2 旅人常驻 / 3 秘纹限时 / 4 秘纹常驻)。

    导入的数据可能压根没有分类信息(CSV、早期只存 groups 的导出), 也可能被
    拍平成一类。Gid 是唯一可靠的判据; 判不出来的记录留在原来的分类里, 不丢。
    对本来分类正确的归档来说这是一次空操作(幂等)。
    """
    result: dict[int, list[dict[str, Any]]] = {}
    for category, groups in categories.items():
        for group in groups:
            key = history_category_key([group])
            result.setdefault(category if key is None else key, []).append(group)
    for groups in result.values():
        groups.sort(key=lambda item: (item.get("Time") or 0, item.get("Gid") or 0))
    return {category: groups for category, groups in result.items() if groups}


def sanitize_gacha(raw: Any) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict) and "Gid" in value and "Ids" in value:
            item = {key: value.get(key) for key in GACHA_ALLOWED if key in value}
            ids = item.get("Ids")
            item["Ids"] = [int(v) for v in _dict_values(ids) if isinstance(v, (int, float))]
            groups.append(item)
            return
        for child in _dict_values(value):
            collect(child)

    collect(raw)
    groups.sort(key=lambda item: (item.get("Time") or 0, item.get("Gid") or 0))
    return groups


def sanitize_gacha_categories(raw: Any) -> dict[int, list[dict[str, Any]]]:
    """Keep the outer history category instead of flattening it away.

    带 version/uid/updatedAt 外壳的归档/分享文件会先被剥开 —— 否则那几个元数据键
    会让整个 categories 被当成"无法识别的分类"丢掉, 四类记录全部塌缩成第 1 类。
    """
    node = unwrap_gacha_source(raw)
    if isinstance(node, dict):
        pairs = node.items()
    elif _is_group_list(node):
        pairs = [(1, node)]
    else:
        pairs = enumerate(node if isinstance(node, list) else [], 1)
    categories: dict[int, list[dict[str, Any]]] = {}
    for key, value in pairs:
        try:
            category = int(key)
        except (TypeError, ValueError):
            continue
        groups = sanitize_gacha(value)
        if groups:
            categories[category] = groups
    return categories


def sanitize_emblems(raw: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for character_key, slots in (raw.items() if isinstance(raw, dict) else enumerate(_dict_values(raw), 1)):
        for slot_key, slot_value in (
            slots.items() if isinstance(slots, dict) else enumerate(_dict_values(slots), 1)
        ):
            for equipment in _dict_values(slot_value):
                if not isinstance(equipment, dict) or "nGemId" not in equipment:
                    continue
                sanitized = {key: equipment.get(key) for key in EMBLEM_ALLOWED if key in equipment}
                sanitized["characterKey"] = character_key
                sanitized["slotKey"] = slot_key
                result.append(sanitized)
    result.sort(
        key=lambda item: (
            item.get("nCharId") or item.get("characterKey") or 0,
            item.get("slotKey") or 0,
            item.get("nGemId") or 0,
        )
    )
    return result


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_gacha_csv(text: str) -> dict[int, list[dict[str, Any]]]:
    """读本工具导出的抽卡 CSV(也接受别的工具生成的同名列)。

    用 csv 模块而不是 split(",") —— 卡池名之类的字段一旦带引号/逗号,
    手写切分会把列错位。分类列存在时直接用它; 没有就全靠 Gid 反推。
    """
    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        return {}
    header = [cell.strip() for cell in rows[0]]

    def column(name: str) -> int | None:
        return header.index(name) if name in header else None

    columns = {
        "category": column("category"),
        "group": column("group"),
        "Gid": column("Gid"),
        "Time": column("Time"),
        "Id": column("Id"),
        "NextPackage": column("NextPackage"),
    }
    if columns["Gid"] is None or columns["Id"] is None:
        return {}

    def cell(row: list[str], name: str) -> str:
        index = columns[name]
        return row[index].strip() if index is not None and index < len(row) else ""

    def number(text_value: str, fallback: int = 0) -> int:
        try:
            return int(float(text_value))
        except (TypeError, ValueError):
            return fallback

    buckets: dict[tuple[int, str, int, int], dict[str, Any]] = {}
    for row in rows[1:]:
        item = cell(row, "Id")
        if not item.lstrip("-").isdigit():
            continue
        category = number(cell(row, "category"), 1) or 1
        gid = number(cell(row, "Gid"))
        time = number(cell(row, "Time"))
        # group 列就是同一次十连的编号; 没有 group 列(别的工具导的 CSV)时,
        # (Gid, Time) 才是区分两次抽取的依据 —— 两列都没有就会把整张表并成一组。
        bucket = buckets.setdefault(
            (category, cell(row, "group") or "0", gid, time),
            {
                "Gid": gid,
                "Time": time,
                "NextPackage": cell(row, "NextPackage"),
                "Ids": [],
            },
        )
        bucket["Ids"].append(int(item))

    categories: dict[int, list[dict[str, Any]]] = {}
    for (category, _group_key, _gid, _time), group in buckets.items():
        if group["Ids"]:
            categories.setdefault(category, []).append(group)
    for groups in categories.values():
        groups.sort(key=lambda item: (item.get("Time") or 0, item.get("Gid") or 0))
    return categories


def parse_import_text(text: str, suffix: str = "") -> tuple[dict[int, list[dict[str, Any]]], str]:
    """解析「导入数据」选中的文件内容 → (分类表, uid)。

    支持: 网页版/分享归档(带 uid 外壳)、桌面版导出的 JSON/CSV、只含扁平 groups
    的旧导出、以及游戏 Lua 原始结构。解析结果已经过 Gid 归位, 可以直接合并进归档。
    """
    if suffix.lower() == ".csv":
        return normalize_category_keys(_parse_gacha_csv(text)), ""
    data = json.loads(text)
    categories = sanitize_gacha_categories(data)
    if not categories:
        # 兜底: 形状完全陌生的 JSON, 仍然把能认出来的记录捞出来(不丢数据优先)
        groups = sanitize_gacha(data)
        categories = {1: groups} if groups else {}
    return normalize_category_keys(categories), extract_uid(data)


def export_all(
    output_dir: Path,
    gacha: list[dict[str, Any]],
    emblems: list[dict[str, Any]] | None = None,
    gacha_categories: dict[int, list[dict[str, Any]]] | None = None,
    uid: str = "",
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    gacha_json = output_dir / f"stellasora_gacha_{stamp}.json"
    gacha_csv = output_dir / f"stellasora_gacha_{stamp}.csv"
    payload: dict[str, Any] = {"version": 1}
    if uid:
        payload["uid"] = uid
    # 同时写 groups 与 categories: 老版本/网页版都读这个导出文件,
    # 去掉任何一个都可能让别处的导入读不到数据。
    payload["groups"] = gacha
    payload["categories"] = {
        str(key): value for key, value in (gacha_categories or {1: gacha}).items()
    }
    _write_json(gacha_json, payload)
    # gacha CSV 始终生成(即使不导出秘纹),避免返回未创建文件的路径
    with gacha_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["category", "group", "item", "Gid", "Time", "Id", "NextPackage"])
        writer.writeheader()
        categories = gacha_categories or {1: gacha}
        for category, category_groups in categories.items():
            for group_index, group in enumerate(category_groups, 1):
                for item_index, item_id in enumerate(group.get("Ids", []), 1):
                    writer.writerow(
                        {
                            "category": category,
                            "group": group_index,
                            "item": item_index,
                            "Gid": group.get("Gid"),
                            "Time": group.get("Time"),
                            "Id": item_id,
                            "NextPackage": group.get("NextPackage"),
                        }
                    )
    if emblems is None:
        return [gacha_json, gacha_csv]
    emblem_json = output_dir / f"stellasora_emblems_{stamp}.json"
    emblem_csv = output_dir / f"stellasora_emblems_{stamp}.csv"
    _write_json(emblem_json, {"emblems": emblems})

    with emblem_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = [
            "nCharId", "slotKey", "nGemId", "nGenerateId", "nRefreshId", "nType",
            "sName", "bLock", "AttrId", "CfgValue", "Value", "tbAffix",
            "tbPotentialAffix", "tbSkillAffix",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for emblem in emblems:
            attrs = _dict_values(emblem.get("tbRandomAttr")) or [{}]
            for attr in attrs:
                attr = attr if isinstance(attr, dict) else {}
                writer.writerow(
                    {
                        "nCharId": emblem.get("nCharId"),
                        "slotKey": emblem.get("slotKey"),
                        "nGemId": emblem.get("nGemId"),
                        "nGenerateId": emblem.get("nGenerateId"),
                        "nRefreshId": emblem.get("nRefreshId"),
                        "nType": emblem.get("nType"),
                        "sName": emblem.get("sName"),
                        "bLock": emblem.get("bLock"),
                        "AttrId": attr.get("AttrId"),
                        "CfgValue": attr.get("CfgValue"),
                        "Value": attr.get("Value"),
                        "tbAffix": json.dumps(emblem.get("tbAffix"), ensure_ascii=False),
                        "tbPotentialAffix": json.dumps(emblem.get("tbPotentialAffix"), ensure_ascii=False),
                        "tbSkillAffix": json.dumps(emblem.get("tbSkillAffix"), ensure_ascii=False),
                    }
                )
    return [gacha_json, gacha_csv, emblem_json, emblem_csv]
