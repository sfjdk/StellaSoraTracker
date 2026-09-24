from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


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
    """Keep the outer history category instead of flattening it away."""
    if isinstance(raw, dict):
        pairs = raw.items()
    elif isinstance(raw, list) and raw and all(isinstance(value, dict) and "Gid" in value for value in raw):
        pairs = [(1, raw)]
    else:
        pairs = enumerate(raw if isinstance(raw, list) else [], 1)
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


def export_all(
    output_dir: Path,
    gacha: list[dict[str, Any]],
    emblems: list[dict[str, Any]] | None = None,
    gacha_categories: dict[int, list[dict[str, Any]]] | None = None,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    gacha_json = output_dir / f"stellasora_gacha_{stamp}.json"
    gacha_csv = output_dir / f"stellasora_gacha_{stamp}.csv"
    _write_json(
        gacha_json,
        {
            "groups": gacha,
            "categories": {str(key): value for key, value in (gacha_categories or {1: gacha}).items()},
        },
    )
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
