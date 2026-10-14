"""Presentation data shared by the three UI betas; no archive writes."""
from dataclasses import dataclass
from datetime import datetime

from ..catalog import gacha_item_name, same_item_name
from ..gacha_stats import build_category_stat, build_banner_stats_with_shared_pity, classify_history_category
from ..service import Snapshot
from ..official_banners import official_pool_info
from .constants import GACHA_CATEGORY_ORDER, OFFICIAL_LIMITED_POOL_INFO


def is_up(gid: int, item_id: int) -> bool:
    info = official_pool_info(gid)
    # Unknown future banners retain normal five-star resets until metadata exists.
    return info is None or same_item_name(gacha_item_name(item_id), info[3])


@dataclass
class Overview:
    category_stats: dict
    total_pulls: int
    total_five: int
    well_banners: dict


def categories(records):
    result = {key: [] for key in GACHA_CATEGORY_ORDER}
    for record in records:
        key = classify_history_category([record])
        if key in result:
            result[key].append(record)
    return result


def overview(records) -> Overview:
    grouped = categories(records)
    stats = {
        key: build_category_stat(groups, is_up=is_up if 'limited' in key else None)
        for key, groups in grouped.items()
    }
    wells = {
        pool.gid: pool.total_pulls
        for pool in build_banner_stats_with_shared_pity(grouped[GACHA_CATEGORY_ORDER[0]])
        if pool.total_pulls >= 120
    }
    return Overview(stats, sum(len(r.get('Ids', [])) for r in records),
                    sum(len(s.five_stars) for s in stats.values() if s), wells)


def demo_snapshot() -> Snapshot:
    """Deterministic illustrative records kept entirely in memory."""
    specs = [
        (10160, '2026-07-28', [(42, 160), (27, 110), (64, 160)], 18),
        (11133, '2026-08-08', [(36, 133)], 0),
        (10157, '2026-08-20', [(53, 157), (24, 157)], 23),
        (20160, '2026-07-29', [(38, 214055)], 0),
        (20157, '2026-08-22', [(46, 214057), (31, 214057)], 14),
        (1, '2026-06-10', [(59, 125), (32, 134), (46, 145)], 41),
        (2, '2026-06-11', [(34, 214015), (52, 214004)], 9),
    ]
    data = {}
    for gid, date, hits, trailing in specs:
        cat = 1 if 10000 <= gid < 20000 else 3 if gid >= 20000 else 2 if gid == 1 else 4
        filler = 103 if cat in (1,2) else 211001
        base = int(datetime.fromisoformat(date).timestamp())
        groups = data.setdefault(cat, [])
        for offset, (interval, item) in enumerate(hits):
            groups.append({'Gid': gid, 'Time': base + offset * 3600,
                           'Ids': [filler] * (interval - 1) + [item]})
        if trailing:
            groups.append({'Gid': gid, 'Time': base + len(hits) * 3600,
                           'Ids': [filler] * trailing})
    return Snapshot([g for groups in data.values() for g in groups], gacha_categories=data)
