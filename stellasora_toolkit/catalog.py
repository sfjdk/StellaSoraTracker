from __future__ import annotations

from typing import Any


TRAVELER_NAMES = {
    103: "琥珀",
    107: "缇莉娅",
    108: "卡西米拉",
    110: "翡冷翠",
    111: "鸢尾",
    112: "尘沙",
    113: "师渺",
    114: "猫眼",
    115: "火垂",
    116: "岭川",
    117: "璟麟",
    118: "科洛妮丝",
    119: "花原",
    120: "卡娜丝",
    123: "杏子",
    125: "苍兰",
    126: "紫槿",
    127: "特丽莎",
    130: "多娜",
    132: "密涅瓦",
    133: "夏花",
    134: "冬香",
    135: "雾语",
    137: "埃莉诺",
    139: "艾蕾",
    140: "斯帕克拉",
    141: "赤霞",
    142: "珂赛特",
    143: "风影",
    144: "千都世",
    145: "乙叶",
    147: "焦糖",
    149: "格芮",
    150: "菈露",
    155: "希娅",
    156: "小禾",
    158: "菈露（圣夜）",
    159: "科洛妮丝（新春）",
    160: "薇洛（盛夏）",
    157: "花铃",
}

GEM_TYPE_NAMES = {1: "尖章", 2: "方菱章", 3: "星闪章"}

FIVE_STAR_TRAVELERS = {
    110,
    114,
    115,
    119,
    125,
    130,
    132,
    133,
    134,
    135,
    137,
    139,
    140,
    141,
    143,
    144,
    145,
    149,
    155,
    156,
    158,
    159,
    160,
    157,
}

FIVE_STAR_DISCS = {
    214001: "猫神降歌", 214002: "空与花与诗", 214003: "你与我相似", 214004: "仙踪良梦",
    214005: "晴之花", 214006: "魔女的秋千", 214007: "午夜，堕天使", 214008: "飞越青空",
    214009: "“空白”的序章", 214010: "沐光祷告", 214011: "夏日午后的雨", 214012: "狼贪虎视",
    214013: "远航蓝图", 214014: "甜言蜜果", 214015: "鹿鸣", 214016: "春日纪事",
    214017: "花火", 214018: "冰柠与红茶", 214019: "一发破的", 214020: "闪光之时",
    214021: "因缘而聚", 214022: "午夜喵铃", 214023: "涂鸦彩虹", 214024: "一二三，跳！",
    214026: "潋滟故池水", 214027: "龙飞凤舞", 214028: "白日花园", 214029: "猫之珍藏",
    214030: "午后间隙", 214031: "刀与斧的铮鸣", 214032: "真相☆梦工厂", 214033: "与骨共舞",
    214036: "迷途的朝圣者", 214037: "抓住传说", 214038: "波光漫游", 214039: "夏日栖息地",
    214040: "勇气之拳", 214041: "启程的礼物", 214042: "酒暖灯明时", 214043: "革新的萌芽",
    214044: "罗帷春染岁朝新", 214045: "繁花幻梦", 214046: "冬夜后的黎明", 214047: "信笺乘风而去",
    214048: "雪夜惊喜", 214049: "星光的印记", 214050: "夜宴谜影", 214051: "星之所向",
    214052: "奇迹一触", 214053: "欢聚时刻", 214054: "微小的乐园", 214055: "浮光掠影",
    214056: "斑驳夏影",
    214057: "伴我航行",
    214058: "夏日进行曲",
    214059: "飞吧，笼中鸟",
    214060: "荣誉时刻",
    214061: "睡前童话",
    214062: "美好，尽在昨日",
}
FIVE_STAR_ITEMS = set(FIVE_STAR_TRAVELERS) | set(FIVE_STAR_DISCS)

# 非抽取单位: StellaBase 的角色接口把 BOSS/剧情单位(魔侍巨像, grade=5)也算作五星角色,
# 但它们不会出现在抽卡记录里。若当成可抽取五星注册, 会去下载 BOSS 头像, 并让
# 对齐校验永远报"星级错位"。这些 id 明确排除。
NON_GACHA_ITEM_IDS = frozenset({997, 998, 999})


def is_gacha_item(item_id: int) -> bool:
    """是否可能是抽卡产出物(排除 BOSS/剧情单位)。"""
    return int(item_id) not in NON_GACHA_ITEM_IDS


def is_five_star_item(value: Any) -> bool:
    """Return whether an item is a five-star gacha result.

    The game adds new IDs before the bundled resource manifest is updated. Disc
    five-stars use the 214xxx range, while new traveler IDs continue after the
    current catalog. Keep the static sets authoritative, but recognize those
    forward-compatible IDs so a new pull is not silently discarded.
    """
    try:
        item_id = int(value)
    except (TypeError, ValueError):
        return False
    return item_id in FIVE_STAR_ITEMS or item_id >= 161 and item_id < 200 or 214000 <= item_id < 215000
DISC_NAMES = {
    211001: "朝霭", 211002: "和煦", 211003: "晚霞", 211004: "粉梦", 211005: "孤烟",
    211006: "甘露", 211007: "希冀", 211008: "归途",
    212001: "盛宴", 212002: "喧哗", 212003: "极乐", 212005: "情热", 212006: "吉光",
    212007: "乘风", 212008: "泡沫", 212009: "黯灭", 212010: "坚韧",
    213001: "柠柚好奇", 213002: "季节波形", 213003: "热夜的结束", 213004: "双月怪盗",
    213005: "★~嘭嘭少女~★", 213006: "晚安", 213007: "翡翠隙境", 213008: "小憩片刻",
    213009: "“雨中”曲", 213010: "水蒸汽症候群", 213011: "喵律动", 213012: "问候星空",
    213013: "秋日絮语", 213014: "骑士的铁匠", 213015: "未闻芳名", 213016: "樊笼蔷薇",
    213017: "★~转转人生~★", 213018: "饮料采购日", 213019: "妄语", 213020: "闪灵",
    213021: "灵验颂歌", 213022: "诅咒爱河", 213023: "纯白", 213024: "假日泡影",
    213025: "甜蜜邀约", 213026: "清扫时间DA♥YO",
    **FIVE_STAR_DISCS,
}


def register_gacha_resource(item_id: int, kind: str, name: str, rarity: int = 5) -> None:
    """Register names and rarity metadata downloaded from the public resource manifest."""
    item_id = int(item_id)
    if kind == "traveler":
        TRAVELER_NAMES[item_id] = name
        if rarity >= 5:
            FIVE_STAR_TRAVELERS.add(item_id)
    elif kind == "disc":
        DISC_NAMES[item_id] = name
        if rarity >= 5:
            FIVE_STAR_DISCS[item_id] = name
    if rarity >= 5:
        FIVE_STAR_ITEMS.add(item_id)


def traveler_name(value: Any) -> str:
    try:
        traveler_id = int(value)
    except (TypeError, ValueError):
        return "未知旅人"
    return TRAVELER_NAMES.get(traveler_id, f"旅人 #{traveler_id}")


def gacha_item_name(value: Any) -> str:
    try:
        item_id = int(value)
    except (TypeError, ValueError):
        return str(value)
    if item_id in TRAVELER_NAMES:
        return TRAVELER_NAMES[item_id]
    if item_id in DISC_NAMES:
        return DISC_NAMES[item_id]
    if 161 <= item_id < 200:
        return f"旅人 #{item_id}"
    if 214000 <= item_id < 215000:
        return f"秘纹 #{item_id}"
    return f"物品 #{item_id}"


def gacha_item_kind(value: Any) -> str:
    try:
        item_id = int(value)
    except (TypeError, ValueError):
        return "unknown"
    if item_id in FIVE_STAR_TRAVELERS:
        return "traveler"
    if item_id in FIVE_STAR_DISCS:
        return "disc"
    if 214000 <= item_id < 215000:
        return "disc"
    if 161 <= item_id < 200:
        return "traveler"
    return "unknown"


def gem_type_name(value: Any) -> str:
    try:
        return GEM_TYPE_NAMES.get(int(value), f"类型 {value}")
    except (TypeError, ValueError):
        return f"类型 {value}"


def format_attr_value(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-" if value is None else str(value)
    if isinstance(value, float) and abs(value) < 1:
        return f"{value * 100:g}%"
    return f"{value:g}"


def format_random_attr(attr: Any) -> str:
    if not isinstance(attr, dict):
        return str(attr)
    attr_id = attr.get("AttrId", "?")
    return f"词条 #{attr_id}  {format_attr_value(attr.get('Value'))}"


def table_values(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return []


def _normalize(value: str) -> str:
    return (
        str(value)
        .replace("（", "(")
        .replace("）", ")")
        .replace(" ", "")
        .casefold()
    )


def same_item_name(actual: str, expected: str) -> bool:
    """归一化后比较两个名称是否相同(用于 UP/歪 判定)。"""
    return _normalize(actual) == _normalize(expected)
