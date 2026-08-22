# -*- coding: utf-8 -*-
"""
澳彩收单软件 - 核心结算逻辑（已按最新规则更新）

规则说明：
1. 中奖金额 = 押注金额 × 47
2. 个人客户不计算佣金
3. 应收/应付 = 总押注金额 - 总中奖金额
   - 正数 → 应收（客户需支付给庄家）
   - 负数 → 应付（庄家需支付给客户）
4. 开奖后显示：对应号码、押注金额、中奖金额
"""

from __future__ import annotations
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime


# ============================================================
# 常量与默认映射（2026 马年）
# ============================================================

PAYOUT_MULTIPLIER = 47          # 中奖倍数

# 波色（固定）
COLOR_MAP: Dict[str, List[int]] = {
    "红": [1, 2, 7, 8, 12, 13, 18, 19, 23, 24, 29, 30, 34, 35, 40, 45, 46],
    "蓝": [3, 4, 9, 10, 14, 15, 20, 25, 26, 31, 36, 37, 41, 42, 47, 48],
    "绿": [5, 6, 11, 16, 17, 21, 22, 27, 28, 32, 33, 38, 39, 43, 44, 49],
}

# 2026 年生肖映射（马年）
ZODIAC_MAP_2026: Dict[str, List[int]] = {
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

# 2026 年五行示例
ELEMENT_MAP_2026: Dict[str, List[int]] = {
    "金": [4, 5, 12, 13, 26, 27, 34, 35, 42, 43],
    "木": [8, 9, 16, 17, 24, 25, 38, 39, 46, 47],
    "水": [1, 14, 15, 22, 23, 30, 31, 44, 45],
    "火": [2, 3, 10, 11, 18, 19, 32, 33, 40, 41, 48, 49],
    "土": [6, 7, 20, 21, 28, 29, 36, 37],
}


# ============================================================
# 数据结构
# ============================================================

@dataclass
class Bet:
    id: int
    customer_id: int
    period_id: int
    bet_type: str          # 'number' | 'zodiac' | 'color' | 'element'
    bet_value: str         # 号码 / 生肖名 / 波色 / 五行
    amount: float
    win_amount: float = 0.0
    is_win: int = 0


@dataclass
class DrawResult:
    period_id: int
    special_num: int                 # 特码 1-49
    normal_nums: List[int] = field(default_factory=list)


@dataclass
class CustomerSettlement:
    """个人客户结算（不计算佣金）"""
    customer_id: int
    period_id: int
    total_bet: float = 0.0          # 本期总押注
    total_win: float = 0.0          # 本期总中奖
    net_amount: float = 0.0         # 应收/应付 = total_bet - total_win
                                    # 正数=应收，负数=应付
    win_details: List[dict] = field(default_factory=list)  # 中奖明细


# ============================================================
# 核心判断函数
# ============================================================

def get_color(num: int) -> Optional[str]:
    for color, nums in COLOR_MAP.items():
        if num in nums:
            return color
    return None


def get_zodiac(num: int, zodiac_map: Dict[str, List[int]] = None) -> Optional[str]:
    mapping = zodiac_map or ZODIAC_MAP_2026
    for name, nums in mapping.items():
        if num in nums:
            return name
    return None


def get_element(num: int, element_map: Dict[str, List[int]] = None) -> Optional[str]:
    mapping = element_map or ELEMENT_MAP_2026
    for name, nums in mapping.items():
        if num in nums:
            return name
    return None


def is_bet_win(bet: Bet, draw: DrawResult,
               zodiac_map: Dict[str, List[int]] = None,
               element_map: Dict[str, List[int]] = None) -> bool:
    """
    判断单笔押注是否中奖（以特码为准）
    - number  : 押注号码 == 特码
    - zodiac  : 特码属于该生肖
    - color   : 特码属于该波色
    - element : 特码属于该五行
    """
    special = draw.special_num
    if not (1 <= special <= 49):
        return False

    bet_type = bet.bet_type.lower()
    value = str(bet.bet_value).strip()

    if bet_type == "number":
        try:
            return int(value) == special
        except ValueError:
            return False
    elif bet_type == "zodiac":
        return get_zodiac(special, zodiac_map) == value
    elif bet_type == "color":
        return get_color(special) == value
    elif bet_type == "element":
        return get_element(special, element_map) == value
    return False


def calc_win_amount(amount: float, is_win: bool, multiplier: float = PAYOUT_MULTIPLIER) -> float:
    """中奖金额 = 押注金额 × 47"""
    if is_win:
        return round(amount * multiplier, 2)
    return 0.0


# ============================================================
# 结算主流程（个人不计算佣金）
# ============================================================

def settle_period(
    bets: List[Bet],
    draw: DrawResult,
    multiplier: float = PAYOUT_MULTIPLIER,
    zodiac_map: Dict[str, List[int]] = None,
    element_map: Dict[str, List[int]] = None,
) -> Tuple[List[Bet], List[CustomerSettlement]]:
    """
    对某一期所有押注进行结算

    返回：
        updated_bets     : 更新了 win_amount / is_win 的押注列表
        settlements      : 每位客户的结算汇总（含中奖明细，不含佣金）
    """
    updated_bets: List[Bet] = []
    customer_data: Dict[int, CustomerSettlement] = {}

    for bet in bets:
        if bet.period_id != draw.period_id:
            updated_bets.append(bet)
            continue

        win = is_bet_win(bet, draw, zodiac_map, element_map)
        win_amt = calc_win_amount(bet.amount, win, multiplier)

        new_bet = Bet(
            id=bet.id,
            customer_id=bet.customer_id,
            period_id=bet.period_id,
            bet_type=bet.bet_type,
            bet_value=bet.bet_value,
            amount=bet.amount,
            win_amount=win_amt,
            is_win=1 if win else 0,
        )
        updated_bets.append(new_bet)

        # 累计客户数据
        cid = bet.customer_id
        if cid not in customer_data:
            customer_data[cid] = CustomerSettlement(
                customer_id=cid,
                period_id=draw.period_id,
            )
        cs = customer_data[cid]
        cs.total_bet += bet.amount
        cs.total_win += win_amt

        # 记录中奖明细（开奖时需要显示）
        if win:
            cs.win_details.append({
                "bet_type": bet.bet_type,
                "bet_value": bet.bet_value,
                "amount": bet.amount,
                "win_amount": win_amt,
            })

    # 计算应收/应付 = 总押注 - 总中奖
    settlements: List[CustomerSettlement] = []
    for cs in customer_data.values():
        cs.total_bet = round(cs.total_bet, 2)
        cs.total_win = round(cs.total_win, 2)
        cs.net_amount = round(cs.total_bet - cs.total_win, 2)  # 正=应收，负=应付
        settlements.append(cs)

    return updated_bets, settlements


def calc_global_stats(settlements: List[CustomerSettlement],
                      commission_rate: float = 0.03) -> Dict[str, float]:
    """
    全局汇总
    佣金只在全局计算（个人客户不计算佣金）
    """
    total_bet = sum(s.total_bet for s in settlements)
    total_win = sum(s.total_win for s in settlements)
    total_net = sum(s.net_amount for s in settlements)  # 正=总应收，负=总应付
    total_commission = round(total_bet * commission_rate, 2)

    return {
        "总押注": round(total_bet, 2),
        "总中奖": round(total_win, 2),
        "总应收应付": round(total_net, 2),   # 正数应收，负数应付
        "总佣金": total_commission,           # 仅全局计算
        "客户数": len(settlements),
    }


def format_settlement_report(settlements: List[CustomerSettlement],
                             customer_names: Dict[int, str] = None) -> str:
    """
    生成开奖结算报告文本
    显示：客户、总押注、中奖明细（号码+押注金额+中奖金额）、应收/应付
    """
    customer_names = customer_names or {}
    lines = []
    lines.append("=" * 60)
    lines.append("开奖结算报告")
    lines.append("=" * 60)

    for s in settlements:
        name = customer_names.get(s.customer_id, f"客户{s.customer_id}")
        net_label = "应收" if s.net_amount >= 0 else "应付"
        net_abs = abs(s.net_amount)

        lines.append(f"\n【{name}】")
        lines.append(f"  本期总押注：¥{s.total_bet:.2f}")
        lines.append(f"  本期总中奖：¥{s.total_win:.2f}")
        lines.append(f"  {net_label}金额：¥{net_abs:.2f}")

        if s.win_details:
            lines.append("  中奖明细：")
            for d in s.win_details:
                type_name = {"number": "号码", "zodiac": "生肖", "color": "波色", "element": "五行"}.get(d["bet_type"], d["bet_type"])
                lines.append(f"    · {type_name} {d['bet_value']}  押注¥{d['amount']:.2f} → 中奖¥{d['win_amount']:.2f}")
        else:
            lines.append("  中奖明细：无")

    return "\n".join(lines)


# ============================================================
# 数据库集成辅助函数
# ============================================================

def load_bets_from_db(conn: sqlite3.Connection, period_id: int) -> List[Bet]:
    cur = conn.execute(
        """
        SELECT id, customer_id, period_id, bet_type, bet_value, amount, win_amount, is_win
        FROM bets WHERE period_id = ?
        """,
        (period_id,),
    )
    return [
        Bet(id=r[0], customer_id=r[1], period_id=r[2], bet_type=r[3],
            bet_value=r[4], amount=r[5], win_amount=r[6] or 0.0, is_win=r[7] or 0)
        for r in cur.fetchall()
    ]


def save_settlement_to_db(
    conn: sqlite3.Connection,
    updated_bets: List[Bet],
    settlements: List[CustomerSettlement],
    period_id: int,
) -> None:
    """写回数据库（settlements 表不再存 commission 字段，或存 0）"""
    cur = conn.cursor()

    for bet in updated_bets:
        if bet.period_id != period_id:
            continue
        cur.execute(
            "UPDATE bets SET win_amount = ?, is_win = ? WHERE id = ?",
            (bet.win_amount, bet.is_win, bet.id),
        )

    for s in settlements:
        cur.execute(
            """
            INSERT INTO settlements (customer_id, period_id, total_bet, total_win, net_amount, commission, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            ON CONFLICT(customer_id, period_id) DO UPDATE SET
                total_bet = excluded.total_bet,
                total_win = excluded.total_win,
                net_amount = excluded.net_amount,
                commission = 0,
                updated_at = excluded.updated_at
            """,
            (
                s.customer_id, s.period_id,
                s.total_bet, s.total_win, s.net_amount,
                datetime.now().isoformat(sep=" ", timespec="seconds"),
            ),
        )

    cur.execute(
        "UPDATE periods SET status = 'settled', settled_at = ? WHERE id = ?",
        (datetime.now().isoformat(sep=" ", timespec="seconds"), period_id),
    )
    conn.commit()


def run_settlement(conn: sqlite3.Connection, period_id: int, special_num: int,
                   normal_nums: List[int] = None,
                   commission_rate: float = 0.03) -> Dict[str, Any]:
    """一键结算入口"""
    draw = DrawResult(period_id=period_id, special_num=special_num, normal_nums=normal_nums or [])
    bets = load_bets_from_db(conn, period_id)
    updated_bets, settlements = settle_period(bets, draw)
    save_settlement_to_db(conn, updated_bets, settlements, period_id)
    global_stats = calc_global_stats(settlements, commission_rate)

    return {
        "period_id": period_id,
        "special_num": special_num,
        "bets_updated": len([b for b in updated_bets if b.period_id == period_id]),
        "customers": len(settlements),
        "global": global_stats,
        "settlements": [
            {
                "customer_id": s.customer_id,
                "total_bet": s.total_bet,
                "total_win": s.total_win,
                "net_amount": s.net_amount,          # 正=应收，负=应付
                "net_label": "应收" if s.net_amount >= 0 else "应付",
                "win_details": s.win_details,
            }
            for s in settlements
        ],
    }


# ============================================================
# 纯内存演示（按您给的例子验证）
# ============================================================

def demo():
    print("=" * 60)
    print("澳彩收单 - 核心结算逻辑演示（最新规则）")
    print("=" * 60)

    # 例子：开奖号码 07
    draw = DrawResult(period_id=1, special_num=7)
    print(f"\n开奖特码：{draw.special_num}  "
          f"({get_color(draw.special_num)}波 · {get_zodiac(draw.special_num)})")

    # 张三共押注 1000（其中号码07押了20）
    bets = [
        Bet(1, 1, 1, "number", "07", 20),    # 中奖 20×47=940
        Bet(2, 1, 1, "number", "12", 300),   # 未中
        Bet(3, 1, 1, "zodiac", "马", 400),   # 未中（07是鼠）
        Bet(4, 1, 1, "number", "25", 280),   # 未中
        # 合计押注 1000

        # 再加一个其他客户方便对比
        Bet(5, 2, 1, "zodiac", "鼠", 100),   # 中奖 100×47=4700
        Bet(6, 2, 1, "number", "15", 50),    # 未中
    ]

    updated_bets, settlements = settle_period(bets, draw)

    print("\n----- 每笔押注结算结果 -----")
    for b in updated_bets:
        status = "✅ 中奖" if b.is_win else "❌ 未中"
        print(f"  客户{b.customer_id} | {b.bet_type:7s} {b.bet_value:4s} | "
              f"押注 ¥{b.amount:7.2f} → 中奖 ¥{b.win_amount:8.2f}  {status}")

    print("\n----- 客户汇总（个人不计算佣金） -----")
    for s in settlements:
        label = "应收" if s.net_amount >= 0 else "应付"
        print(f"  客户{s.customer_id} | 总押注 ¥{s.total_bet:8.2f} | "
              f"总中奖 ¥{s.total_win:8.2f} | {label} ¥{abs(s.net_amount):8.2f}")
        if s.win_details:
            for d in s.win_details:
                print(f"           中奖明细：{d['bet_type']} {d['bet_value']}  "
                      f"押注¥{d['amount']:.2f} → 中奖¥{d['win_amount']:.2f}")

    stats = calc_global_stats(settlements)
    print("\n----- 全局统计（佣金仅全局计算） -----")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # 使用报告格式输出
    print("\n" + format_settlement_report(settlements, {1: "张三", 2: "李四"}))


if __name__ == "__main__":
    demo()
