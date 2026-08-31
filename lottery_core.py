# -*- coding: utf-8 -*-
"""
澳彩规则
- 特码命中：该号码押注金额 × 47
- 各字：该生肖下每个号码都押这个金额
- 各包：该生肖一共押这个金额，再平均分到该生肖每个号码
- 同一号码多处出现：金额自动相加
"""
from __future__ import annotations
import re
from typing import Dict, List, Optional, Tuple

PAYOUT = 47
COMMISSION_RATE = 0.03

COLOR_MAP: Dict[str, List[int]] = {
    "红": [1, 2, 7, 8, 12, 13, 18, 19, 23, 24, 29, 30, 34, 35, 40, 45, 46],
    "蓝": [3, 4, 9, 10, 14, 15, 20, 25, 26, 31, 36, 37, 41, 42, 47, 48],
    "绿": [5, 6, 11, 16, 17, 21, 22, 27, 28, 32, 33, 38, 39, 43, 44, 49],
}

ZODIAC_MAP: Dict[str, List[int]] = {
    "马": [1, 13, 25, 37, 49],
    "蛇": [2, 14, 26, 38],
    "龙": [3, 15, 27, 39],
    "兔": [4, 16, 28, 40],
    "虎": [5, 17, 29, 41],
    "牛": [6, 18, 30, 42],
    "鼠": [7, 19, 31, 43],
    "猪": [8, 20, 32, 44],
    "狗": [9, 21, 33, 45],
    "鸡": [10, 22, 34, 46],
    "猴": [11, 23, 35, 47],
    "羊": [12, 24, 36, 48],
}
ZODIAC_ORDER = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]
ZODIAC_CHARS = "".join(ZODIAC_ORDER)


def pad2(n: int) -> str:
    return f"{n:02d}"


def get_color(n: int) -> Optional[str]:
    for c, nums in COLOR_MAP.items():
        if n in nums:
            return c
    return None


def get_zodiac(n: int) -> Optional[str]:
    for z, nums in ZODIAC_MAP.items():
        if n in nums:
            return z
    return None


def group_size(bet_type: str, value: str) -> int:
    if bet_type == "zodiac":
        return len(ZODIAC_MAP.get(value, []))
    if bet_type == "color":
        return len(COLOR_MAP.get(value, []))
    return 1


def evaluate_bet(bet_type: str, bet_value: str, amount: float, special: int) -> Tuple[bool, float]:
    if not (1 <= special <= 49):
        return False, 0.0
    if bet_type == "number":
        n = int(bet_value)
        if n == special:
            return True, round(amount * PAYOUT, 2)
        return False, 0.0
    hit = False
    if bet_type == "zodiac":
        hit = get_zodiac(special) == bet_value
    elif bet_type == "color":
        hit = get_color(special) == bet_value
    if not hit:
        return False, 0.0
    n = group_size(bet_type, bet_value)
    if n <= 0:
        return False, 0.0
    return True, round((amount / n) * PAYOUT, 2)


def stake_on_special(bet_type: str, bet_value: str, amount: float, special: Optional[int]) -> float:
    """该注在开奖号码上的押注金额（生肖/波色按平均到每个号码）。"""
    if not special or not (1 <= int(special) <= 49):
        return 0.0
    special = int(special)
    if bet_type == "number":
        try:
            return float(amount) if int(bet_value) == special else 0.0
        except ValueError:
            return 0.0
    if bet_type == "zodiac" and get_zodiac(special) == bet_value:
        n = group_size("zodiac", bet_value)
        return round(float(amount) / n, 2) if n else 0.0
    if bet_type == "color" and get_color(special) == bet_value:
        n = group_size("color", bet_value)
        return round(float(amount) / n, 2) if n else 0.0
    return 0.0


def _normalize_line(text: str) -> str:
    t = text.replace("\u3000", " ")
    t = t.replace(" ", "")
    t = t.replace("＝", "=").replace("：", "=").replace(":", "=")
    t = t.replace("／", "/").replace("。", ".")
    t = t.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    t = t.replace("每个", "各字").replace("每只", "各字").replace("各子", "各字")
    return t


def extract_numbers(blob: str) -> List[int]:
    """从 32/34/02/2818 这类串取出 1–49。连续数字按两位切（2818 → 28,18）。"""
    s = blob.replace("，", ".").replace(",", ".").replace("、", ".").replace("/", ".")
    s = re.sub(r"[^\d.]", ".", s)
    out: List[int] = []
    for part in s.split("."):
        if not part:
            continue
        if part.isdigit() and 1 <= len(part) <= 2:
            n = int(part)
            if 1 <= n <= 49:
                out.append(n)
            continue
        i = 0
        while i < len(part):
            if i + 2 <= len(part):
                n = int(part[i : i + 2])
                if 1 <= n <= 49:
                    out.append(n)
                    i += 2
                    continue
            n = int(part[i])
            if 1 <= n <= 9:
                out.append(n)
            i += 1
    return out


def _pack_amounts(nums: List[int], total: float) -> List[Tuple[int, float]]:
    n = len(nums)
    if n <= 0 or total <= 0:
        return []
    per = round(total / n, 2)
    parts = [per] * n
    parts[-1] = round(total - per * (n - 1), 2)
    return list(zip(nums, parts))


def parse_slip(text: str) -> List[dict]:
    items: List[dict] = []
    for raw in text.splitlines():
        line = _normalize_line(raw)
        if not line:
            continue
        items.extend(_parse_line(line))
    merged: Dict[str, dict] = {}
    order: List[str] = []
    for it in items:
        k = f"{it['bet_type']}:{it['bet_value']}"
        if k not in merged:
            merged[k] = dict(it)
            order.append(k)
        else:
            merged[k]["amount"] = round(merged[k]["amount"] + it["amount"], 2)
    return [merged[k] for k in order]


def _parse_line(line: str) -> List[dict]:
    out: List[dict] = []
    used = [False] * len(line)

    def mark(a: int, b: int):
        for i in range(a, b):
            used[i] = True

    # 生肖各字 / 各包（允许逗号分隔：鼠，兔，猴各字40）
    # 各/买/× 三者等价，如：鼠买30、猴×50
    zre = re.compile(
        rf"([{ZODIAC_CHARS},，、]+)[各买×](?:字|包)?(\d+(?:\.\d+)?)"
    )
    for m in zre.finditer(line):
        mark(m.start(), m.end())
        amt = float(m.group(3))
        mode = m.group(2) or "字"
        if amt <= 0:
            continue
        for ch in m.group(1):
            nums = ZODIAC_MAP.get(ch)
            if not nums:
                continue
            if mode == "包":
                for n, a in _pack_amounts(nums, amt):
                    out.append({"bet_type": "number", "bet_value": pad2(n), "amount": a})
            else:
                for n in nums:
                    out.append({"bet_type": "number", "bet_value": pad2(n), "amount": amt})

    # 号码各字 / 各（30.35.40.45各30 或 32/34/2818各20）
    # 各/买/× 三者等价，如：05.18买20、16.28.39×10、03.04.45各30
    nre = re.compile(r"([\d./]+)[各买×](?:字|包)?(\d+(?:\.\d+)?)")
    for m in nre.finditer(line):
        if any(used[i] for i in range(m.start(), m.end())):
            continue
        mark(m.start(), m.end())
        amt = float(m.group(2))
        if amt <= 0:
            continue
        for n in extract_numbers(m.group(1)):
            out.append({"bet_type": "number", "bet_value": pad2(n), "amount": amt})

    # 剩余：01=20 / 马=40 / 红波50 / 39买60 / 25×50
    rest = "".join(ch if not used[i] else " " for i, ch in enumerate(line))
    for m in re.finditer(
        rf"(\d{{1,2}}|[{ZODIAC_CHARS}]|红波?|蓝波?|绿波?)[=/\-买×](\d+(?:\.\d+)?)",
        rest.replace(" ", ""),
    ):
        amt = float(m.group(2))
        if amt <= 0:
            continue
        key = m.group(1)
        if key.isdigit():
            n = int(key)
            if 1 <= n <= 49:
                out.append({"bet_type": "number", "bet_value": pad2(n), "amount": amt})
        elif key in ZODIAC_MAP:
            for n in ZODIAC_MAP[key]:
                out.append({"bet_type": "number", "bet_value": pad2(n), "amount": amt})
        elif key.startswith("红"):
            out.append({"bet_type": "color", "bet_value": "红", "amount": amt})
        elif key.startswith("蓝"):
            out.append({"bet_type": "color", "bet_value": "蓝", "amount": amt})
        elif key.startswith("绿"):
            out.append({"bet_type": "color", "bet_value": "绿", "amount": amt})
    return out
