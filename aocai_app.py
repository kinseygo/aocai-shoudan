# -*- coding: utf-8 -*-
"""
澳彩收单软件 - 简易可运行 Web 原型
Flask + SQLite
运行方式：python3 aocai_app.py
然后浏览器打开 http://127.0.0.1:5000
"""

from __future__ import annotations
import os
import json
import sqlite3
import shutil
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, render_template_string, g, redirect, url_for

# 导入结算核心（同目录）
from settlement_core import (
    PAYOUT_MULTIPLIER, COLOR_MAP, ZODIAC_MAP_2026,
    get_color, get_zodiac, settle_period, calc_global_stats,
    Bet, DrawResult, format_settlement_report
)

app = Flask(__name__)
app.config["SECRET_KEY"] = "aocai-demo-2026"
DB_PATH = os.path.join("/tmp", "aocai.db")
BACKUP_DIR = os.path.join("/tmp", "aocai_backups")

os.makedirs(BACKUP_DIR, exist_ok=True)


# ============================================================
# 数据库
# ============================================================

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        phone TEXT,
        note TEXT,
        is_active INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS periods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        period_no TEXT NOT NULL UNIQUE,
        draw_date DATE,
        special_num INTEGER,
        normal_nums TEXT,
        status TEXT DEFAULT 'open' CHECK(status IN ('open','closed','settled')),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        settled_at DATETIME
    );

    CREATE TABLE IF NOT EXISTS bets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        period_id INTEGER NOT NULL,
        bet_type TEXT NOT NULL CHECK(bet_type IN ('number','zodiac','color','element')),
        bet_value TEXT NOT NULL,
        amount REAL NOT NULL CHECK(amount > 0),
        win_amount REAL DEFAULT 0,
        is_win INTEGER DEFAULT 0,
        note TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
        FOREIGN KEY (period_id) REFERENCES periods(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS settlements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        period_id INTEGER NOT NULL,
        total_bet REAL DEFAULT 0,
        total_win REAL DEFAULT 0,
        net_amount REAL DEFAULT 0,
        commission REAL DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(customer_id, period_id),
        FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
        FOREIGN KEY (period_id) REFERENCES periods(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_bets_cp ON bets(customer_id, period_id);
    CREATE INDEX IF NOT EXISTS idx_bets_period ON bets(period_id);
    """)
    # 初始数据
    cur = db.execute("SELECT COUNT(*) FROM customers")
    if cur.fetchone()[0] == 0:
        db.execute("INSERT INTO customers (name, phone, note) VALUES ('张三', '13800138001', '老客户')")
        db.execute("INSERT INTO customers (name, phone, note) VALUES ('李四', '13900139002', '新客户')")
        db.execute("INSERT INTO customers (name, note) VALUES ('王五', '只玩生肖')")
        db.execute("INSERT INTO periods (period_no, draw_date, status) VALUES ('2026229', date('now'), 'open')")
        db.commit()
    db.close()


# ============================================================
# 页面模板（单文件内嵌）
# ============================================================

BASE_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>澳彩收单系统</title>
<style>
:root {
  --primary:#1a56db; --success:#059669; --danger:#dc2626; --warning:#d97706;
  --bg:#f1f5f9; --card:#fff; --text:#1e293b; --muted:#64748b; --border:#e2e8f0;
  --red:#ef4444; --blue:#3b82f6; --green:#22c55e;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
.navbar{background:linear-gradient(135deg,#1e3a8a,#1e40af);color:#fff;padding:0 20px;height:52px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:50}
.navbar .logo{font-weight:700;font-size:16px}
.nav a{color:rgba(255,255,255,.85);text-decoration:none;padding:6px 12px;border-radius:6px;font-size:13px;margin-left:4px}
.nav a:hover,.nav a.active{background:rgba(255,255,255,.2);color:#fff}
.container{max-width:1200px;margin:0 auto;padding:16px}
.card{background:var(--card);border-radius:10px;border:1px solid var(--border);box-shadow:0 1px 3px rgba(0,0,0,.06);margin-bottom:16px;overflow:hidden}
.card-h{padding:12px 16px;border-bottom:1px solid var(--border);font-weight:600;font-size:14px;background:#f8fafc;display:flex;justify-content:space-between;align-items:center}
.card-b{padding:14px 16px}
.btn{padding:7px 14px;border-radius:6px;border:none;cursor:pointer;font-size:13px;font-weight:500;display:inline-flex;align-items:center;gap:4px}
.btn-p{background:var(--primary);color:#fff}.btn-p:hover{background:#1e40af}
.btn-s{background:var(--success);color:#fff}.btn-d{background:var(--danger);color:#fff}
.btn-o{background:#fff;border:1px solid var(--border);color:var(--text)}.btn-o:hover{background:#f8fafc}
.btn-sm{padding:4px 10px;font-size:12px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--border)}
th{background:#f8fafc;color:var(--muted);font-weight:600}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
.badge-s{background:#d1fae5;color:#065f46}.badge-d{background:#fee2e2;color:#991b1b}.badge-i{background:#dbeafe;color:#1e40af}
.stat-row{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}
.stat{background:#fff;border:1px solid var(--border);border-radius:10px;padding:16px;text-align:center}
.stat .l{font-size:12px;color:var(--muted);margin-bottom:6px}.stat .v{font-size:24px;font-weight:700}
.num-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:6px}
.num-btn{aspect-ratio:1;border:2px solid var(--border);border-radius:8px;background:#fff;cursor:pointer;font-size:13px;font-weight:600;display:flex;flex-direction:column;align-items:center;justify-content:center;transition:.15s}
.num-btn:hover{border-color:var(--primary);transform:scale(1.05)}
.num-btn.has{border-color:var(--primary);background:#eff6ff}
.num-btn .amt{font-size:9px;color:var(--primary);font-weight:700}
.num-btn.r{border-bottom:3px solid var(--red)}.num-btn.b{border-bottom:3px solid var(--blue)}.num-btn.g{border-bottom:3px solid var(--green)}
.zod-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:6px;margin-top:10px}
.zod-btn{padding:8px 4px;border:2px solid var(--border);border-radius:8px;background:#fff;cursor:pointer;text-align:center;font-size:13px}
.zod-btn:hover{border-color:var(--primary)}.zod-btn.has{border-color:var(--success);background:#ecfdf5}
.zod-btn .n{font-size:10px;color:var(--muted)}.zod-btn .a{font-size:11px;color:var(--success);font-weight:700}
.layout3{display:grid;grid-template-columns:220px 1fr 280px;gap:14px}
@media(max-width:1000px){.layout3{grid-template-columns:1fr}.stat-row{grid-template-columns:repeat(2,1fr)}}
.cust-item{padding:10px 12px;border-bottom:1px solid var(--border);cursor:pointer}.cust-item:hover{background:#f1f5f9}.cust-item.on{background:#eff6ff;border-left:3px solid var(--primary)}
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:100;align-items:center;justify-content:center}
.modal-bg.show{display:flex}.modal{background:#fff;border-radius:12px;padding:20px;width:300px}
.modal h3{margin-bottom:12px;font-size:15px}.modal input{width:100%;padding:10px;border:2px solid var(--border);border-radius:8px;font-size:16px;text-align:center;margin-bottom:12px}
.modal input:focus{outline:none;border-color:var(--primary)}
.tip{background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:8px 12px;font-size:12px;color:#92400e;margin-bottom:12px}
.ball{width:42px;height:42px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-weight:700;color:#fff;font-size:14px;margin:2px}
.ball.r{background:var(--red)}.ball.b{background:var(--blue)}.ball.g{background:var(--green)}.ball.sp{box-shadow:0 0 0 3px #fbbf24}
input[type=text],input[type=number],select{padding:7px 10px;border:1px solid var(--border);border-radius:6px;font-size:13px}
</style>
</head>
<body>
<nav class="navbar">
  <div class="logo">🎱 澳彩收单系统 <small style="opacity:.7;font-weight:400">v1.0</small></div>
  <div class="nav">
    <a href="/" class="{{ 'active' if page=='bet' else '' }}">押注入录</a>
    <a href="/customers" class="{{ 'active' if page=='customers' else '' }}">客户管理</a>
    <a href="/stats" class="{{ 'active' if page=='stats' else '' }}">汇总统计</a>
    <a href="/draw" class="{{ 'active' if page=='draw' else '' }}">开奖结算</a>
    <a href="/backup" class="{{ 'active' if page=='backup' else '' }}">备份恢复</a>
  </div>
  <div style="font-size:12px;opacity:.9">第 {{ period.period_no if period else '-' }} 期 · {{ period.status if period else '' }}</div>
</nav>
<div class="container">
  {% if msg %}<div class="tip">{{ msg }}</div>{% endif %}
  {{ content|safe }}
</div>
</body>
</html>
"""


def render(page, content, **kwargs):
    db = get_db()
    period = db.execute("SELECT * FROM periods ORDER BY id DESC LIMIT 1").fetchone()
    kwargs.setdefault("msg", None)
    return render_template_string(
        BASE_HTML, page=page, content=content, period=period, **kwargs
    )


# ============================================================
# 路由
# ============================================================

@app.route("/")
def index():
    db = get_db()
    period = db.execute("SELECT * FROM periods ORDER BY id DESC LIMIT 1").fetchone()
    customers = db.execute("SELECT * FROM customers WHERE is_active=1 ORDER BY id").fetchall()
    cid = request.args.get("cid", type=int)
    if not cid and customers:
        cid = customers[0]["id"]

    bets = []
    bet_map = {}  # number/zodiac -> amount
    total = 0
    if cid and period:
        bets = db.execute(
            "SELECT * FROM bets WHERE customer_id=? AND period_id=? ORDER BY id",
            (cid, period["id"])
        ).fetchall()
        for b in bets:
            key = f"{b['bet_type']}:{b['bet_value']}"
            bet_map[key] = bet_map.get(key, 0) + b["amount"]
            total += b["amount"]

    # 数字网格
    red = set(COLOR_MAP["红"]); blue = set(COLOR_MAP["蓝"]); green = set(COLOR_MAP["绿"])
    nums_html = ""
    for i in range(1, 50):
        n = f"{i:02d}"
        cls = "r" if i in red else ("b" if i in blue else "g")
        amt = bet_map.get(f"number:{n}", 0)
        has = " has" if amt else ""
        amt_html = f'<span class="amt">¥{int(amt)}</span>' if amt else ""
        nums_html += f'<button class="num-btn {cls}{has}" onclick="openAmt(\'number\',\'{n}\')">{n}{amt_html}</button>'

    # 生肖
    zod_html = ""
    for name, nums in ZODIAC_MAP_2026.items():
        ns = " ".join(f"{x:02d}" for x in nums)
        amt = bet_map.get(f"zodiac:{name}", 0)
        has = " has" if amt else ""
        amt_html = f'<div class="a">¥{int(amt)}</div>' if amt else ""
        zod_html += f'<button class="zod-btn{has}" onclick="openAmt(\'zodiac\',\'{name}\')"><div>{name}</div><div class="n">{ns}</div>{amt_html}</button>'

    # 客户列表
    cust_html = ""
    for c in customers:
        on = " on" if c["id"] == cid else ""
        # 本期已押
        t = db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM bets WHERE customer_id=? AND period_id=?",
            (c["id"], period["id"] if period else 0)
        ).fetchone()[0]
        cust_html += f'''<div class="cust-item{on}" onclick="location.href='/?cid={c["id"]}'">
          <div style="font-weight:500">{c["name"]}</div>
          <div style="font-size:11px;color:var(--muted)">本期已押 ¥{t:.0f}</div>
        </div>'''

    # 当前押注列表
    bet_list = ""
    for b in bets:
        tn = {"number": "号码", "zodiac": "生肖", "color": "波色"}.get(b["bet_type"], b["bet_type"])
        bet_list += f'''<div style="display:flex;justify-content:space-between;padding:6px 8px;background:#f8fafc;border-radius:6px;margin-bottom:4px;font-size:12px">
          <span><span class="badge badge-i">{tn}</span> {b["bet_value"]}</span>
          <span>¥{b["amount"]:.0f} <a href="/del_bet/{b["id"]}?cid={cid}" style="color:var(--danger);margin-left:6px" onclick="return confirm('删除?')">删</a></span>
        </div>'''

    content = f'''
    <div class="tip">点击数字或生肖输入金额。中奖 = 押注 × 47；应收/应付 = 总押注 − 总中奖（正数应收，负数应付）。个人不计算佣金。</div>
    <div class="layout3">
      <div class="card">
        <div class="card-h">客户 <a href="/customers" class="btn btn-o btn-sm">管理</a></div>
        <div>{cust_html or "<div style='padding:20px;color:#94a3b8;text-align:center'>暂无客户</div>"}</div>
      </div>
      <div>
        <div class="card" style="margin-bottom:12px">
          <div class="card-h">数字押注 01-49</div>
          <div class="card-b"><div class="num-grid">{nums_html}</div></div>
        </div>
        <div class="card">
          <div class="card-h">生肖押注（2026马年）</div>
          <div class="card-b"><div class="zod-grid">{zod_html}</div>
            <div style="display:flex;gap:8px;margin-top:10px">
              <button class="btn" style="flex:1;background:var(--red);color:#fff" onclick="openAmt('color','红')">红波</button>
              <button class="btn" style="flex:1;background:var(--blue);color:#fff" onclick="openAmt('color','蓝')">蓝波</button>
              <button class="btn" style="flex:1;background:var(--green);color:#fff" onclick="openAmt('color','绿')">绿波</button>
            </div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-h">当前客户押注</div>
        <div class="card-b">
          <div style="max-height:300px;overflow-y:auto;margin-bottom:10px">{bet_list or "<div style='color:#94a3b8;text-align:center;padding:20px'>暂无押注</div>"}</div>
          <div style="display:flex;justify-content:space-between;padding:8px 0;border-top:1px solid var(--border);font-size:14px">
            <span>本期合计</span><strong style="color:var(--primary)">¥{total:.2f}</strong>
          </div>
        </div>
      </div>
    </div>

    <div class="modal-bg" id="amtModal">
      <div class="modal">
        <h3 id="modalTitle">输入金额</h3>
        <form method="POST" action="/add_bet">
          <input type="hidden" name="cid" value="{cid or ''}">
          <input type="hidden" name="period_id" value="{period['id'] if period else ''}">
          <input type="hidden" name="bet_type" id="betType">
          <input type="hidden" name="bet_value" id="betValue">
          <input type="number" name="amount" id="amtInput" placeholder="请输入金额" min="1" step="1" required autofocus>
          <div style="display:flex;gap:8px">
            <button type="button" class="btn btn-o" style="flex:1" onclick="closeModal()">取消</button>
            <button type="submit" class="btn btn-p" style="flex:1">确认</button>
          </div>
        </form>
      </div>
    </div>
    <script>
    function openAmt(type, val) {{
      document.getElementById('betType').value = type;
      document.getElementById('betValue').value = val;
      const names = {{number:'号码',zodiac:'生肖',color:'波色'}};
      document.getElementById('modalTitle').textContent = '输入金额 - ' + (names[type]||type) + ' ' + val;
      document.getElementById('amtModal').classList.add('show');
      document.getElementById('amtInput').value = '';
      document.getElementById('amtInput').focus();
    }}
    function closeModal() {{ document.getElementById('amtModal').classList.remove('show'); }}
    document.getElementById('amtInput')?.addEventListener('keydown', e => {{ if(e.key==='Enter') e.target.form.submit(); }});
    </script>
    '''
    return render("bet", content)


@app.route("/add_bet", methods=["POST"])
def add_bet():
    db = get_db()
    cid = request.form.get("cid", type=int)
    pid = request.form.get("period_id", type=int)
    btype = request.form.get("bet_type")
    bval = request.form.get("bet_value")
    amount = request.form.get("amount", type=float)
    if cid and pid and btype and bval and amount and amount > 0:
        db.execute(
            "INSERT INTO bets (customer_id, period_id, bet_type, bet_value, amount) VALUES (?,?,?,?,?)",
            (cid, pid, btype, bval, amount)
        )
        db.commit()
    return redirect(f"/?cid={cid}")


@app.route("/del_bet/<int:bid>")
def del_bet(bid):
    db = get_db()
    cid = request.args.get("cid", type=int)
    db.execute("DELETE FROM bets WHERE id=?", (bid,))
    db.commit()
    return redirect(f"/?cid={cid}" if cid else "/")


@app.route("/customers", methods=["GET", "POST"])
def customers():
    db = get_db()
    msg = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        note = request.form.get("note", "").strip()
        if name:
            try:
                db.execute("INSERT INTO customers (name, phone, note) VALUES (?,?,?)", (name, phone or None, note or None))
                db.commit()
                msg = f"已添加客户：{name}"
            except sqlite3.IntegrityError:
                msg = f"客户「{name}」已存在"
    customers = db.execute("SELECT * FROM customers ORDER BY id").fetchall()
    period = db.execute("SELECT * FROM periods ORDER BY id DESC LIMIT 1").fetchone()

    rows = ""
    for c in customers:
        t_bet = 0
        t_win = 0
        net = 0
        if period:
            s = db.execute(
                "SELECT total_bet, total_win, net_amount FROM settlements WHERE customer_id=? AND period_id=?",
                (c["id"], period["id"])
            ).fetchone()
            if s:
                t_bet, t_win, net = s["total_bet"], s["total_win"], s["net_amount"]
            else:
                t_bet = db.execute(
                    "SELECT COALESCE(SUM(amount),0) FROM bets WHERE customer_id=? AND period_id=?",
                    (c["id"], period["id"])
                ).fetchone()[0]
        net_str = f"+¥{net:.0f}" if net > 0 else (f"-¥{abs(net):.0f}" if net < 0 else "¥0")
        net_color = "color:var(--success)" if net > 0 else ("color:var(--danger)" if net < 0 else "")
        rows += f'''<tr>
          <td><strong>{c["name"]}</strong></td>
          <td>{c["phone"] or "-"}</td>
          <td>¥{t_bet:.0f}</td>
          <td>¥{t_win:.0f}</td>
          <td style="{net_color};font-weight:600">{net_str}</td>
          <td>{c["note"] or "-"}</td>
        </tr>'''

    content = f'''
    <div class="card" style="margin-bottom:16px">
      <div class="card-h">新增客户</div>
      <div class="card-b">
        <form method="POST" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
          <div><label style="font-size:12px;color:var(--muted)">姓名 *</label><br><input type="text" name="name" required style="width:120px"></div>
          <div><label style="font-size:12px;color:var(--muted)">电话</label><br><input type="text" name="phone" style="width:140px"></div>
          <div><label style="font-size:12px;color:var(--muted)">备注</label><br><input type="text" name="note" style="width:160px"></div>
          <button type="submit" class="btn btn-p">添加</button>
        </form>
      </div>
    </div>
    <div class="card">
      <div class="card-h">客户列表</div>
      <div class="card-b" style="padding:0">
        <table>
          <thead><tr><th>客户</th><th>电话</th><th>本期押注</th><th>本期中奖</th><th>应收/应付</th><th>备注</th></tr></thead>
          <tbody>{rows or "<tr><td colspan=6 style='text-align:center;color:#94a3b8'>暂无客户</td></tr>"}</tbody>
        </table>
      </div>
    </div>
    '''
    return render("customers", content, msg=msg)


@app.route("/stats")
def stats():
    db = get_db()
    period = db.execute("SELECT * FROM periods ORDER BY id DESC LIMIT 1").fetchone()
    if not period:
        return render("stats", "<div class='tip'>暂无期数</div>")

    settlements = db.execute(
        """SELECT s.*, c.name FROM settlements s
           JOIN customers c ON s.customer_id=c.id
           WHERE s.period_id=? ORDER BY s.net_amount DESC""",
        (period["id"],)
    ).fetchall()

    # 如果还没结算，用当前押注估算
    if not settlements:
        customers = db.execute("SELECT id, name FROM customers WHERE is_active=1").fetchall()
        total_bet = 0
        rows = ""
        for c in customers:
            t = db.execute(
                "SELECT COALESCE(SUM(amount),0) FROM bets WHERE customer_id=? AND period_id=?",
                (c["id"], period["id"])
            ).fetchone()[0]
            total_bet += t
            if t > 0:
                rows += f"<tr><td>{c['name']}</td><td>¥{t:.0f}</td><td>-</td><td>-</td><td><span class='badge badge-i'>未结算</span></td></tr>"
        content = f'''
        <div class="stat-row">
          <div class="stat"><div class="l">本期总押注</div><div class="v" style="color:var(--primary)">¥{total_bet:.0f}</div></div>
          <div class="stat"><div class="l">本期总中奖</div><div class="v">-</div></div>
          <div class="stat"><div class="l">总应收/应付</div><div class="v">-</div></div>
          <div class="stat"><div class="l">状态</div><div class="v" style="font-size:16px">未结算</div></div>
        </div>
        <div class="card"><div class="card-h">客户明细（未结算）</div>
        <div class="card-b" style="padding:0"><table>
          <thead><tr><th>客户</th><th>总押注</th><th>总中奖</th><th>应收/应付</th><th>状态</th></tr></thead>
          <tbody>{rows or "<tr><td colspan=5 style='text-align:center;color:#94a3b8'>暂无押注</td></tr>"}</tbody>
        </table></div></div>
        '''
        return render("stats", content)

    total_bet = sum(s["total_bet"] for s in settlements)
    total_win = sum(s["total_win"] for s in settlements)
    total_net = sum(s["net_amount"] for s in settlements)
    net_label = "总应收" if total_net >= 0 else "总应付"
    net_color = "var(--success)" if total_net >= 0 else "var(--danger)"

    rows = ""
    for s in settlements:
        label = "应收" if s["net_amount"] >= 0 else "应付"
        color = "var(--success)" if s["net_amount"] >= 0 else "var(--danger)"
        rows += f'''<tr>
          <td><strong>{s["name"]}</strong></td>
          <td>¥{s["total_bet"]:.0f}</td>
          <td>¥{s["total_win"]:.0f}</td>
          <td style="color:{color};font-weight:600">{label} ¥{abs(s["net_amount"]):.0f}</td>
          <td><span class="badge badge-s">已结算</span></td>
        </tr>'''

    content = f'''
    <div class="stat-row">
      <div class="stat"><div class="l">本期总押注</div><div class="v" style="color:var(--primary)">¥{total_bet:.0f}</div></div>
      <div class="stat"><div class="l">本期总中奖</div><div class="v" style="color:var(--success)">¥{total_win:.0f}</div></div>
      <div class="stat"><div class="l">{net_label}</div><div class="v" style="color:{net_color}">¥{abs(total_net):.0f}</div></div>
      <div class="stat"><div class="l">全局佣金(3%)</div><div class="v" style="color:var(--warning)">¥{total_bet*0.03:.1f}</div></div>
    </div>
    <div class="card">
      <div class="card-h">客户明细汇总（第 {period["period_no"]} 期）</div>
      <div class="card-b" style="padding:0">
        <table>
          <thead><tr><th>客户</th><th>总押注</th><th>总中奖</th><th>应收/应付</th><th>状态</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>
    '''
    return render("stats", content)


@app.route("/draw", methods=["GET", "POST"])
def draw():
    db = get_db()
    period = db.execute("SELECT * FROM periods ORDER BY id DESC LIMIT 1").fetchone()
    msg = None
    report = ""

    if request.method == "POST" and period:
        action = request.form.get("action")
        if action == "save_draw":
            special = request.form.get("special", type=int)
            normals = []
            for i in range(1, 7):
                n = request.form.get(f"n{i}", type=int)
                if n:
                    normals.append(n)
            if special and 1 <= special <= 49:
                db.execute(
                    "UPDATE periods SET special_num=?, normal_nums=?, status='closed' WHERE id=?",
                    (special, json.dumps(normals), period["id"])
                )
                db.commit()
                msg = f"已保存开奖号码：特码 {special:02d}"
                period = db.execute("SELECT * FROM periods WHERE id=?", (period["id"],)).fetchone()
            else:
                msg = "请输入有效特码（1-49）"

        elif action == "settle" and period["special_num"]:
            # 执行结算
            rows = db.execute(
                "SELECT id, customer_id, period_id, bet_type, bet_value, amount, win_amount, is_win FROM bets WHERE period_id=?",
                (period["id"],)
            ).fetchall()
            bets = [Bet(r["id"], r["customer_id"], r["period_id"], r["bet_type"], r["bet_value"],
                        r["amount"], r["win_amount"] or 0, r["is_win"] or 0) for r in rows]
            draw_obj = DrawResult(period["id"], period["special_num"],
                                  json.loads(period["normal_nums"] or "[]"))
            updated, settlements = settle_period(bets, draw_obj)

            # 写回
            for b in updated:
                db.execute("UPDATE bets SET win_amount=?, is_win=? WHERE id=?",
                           (b.win_amount, b.is_win, b.id))
            for s in settlements:
                db.execute("""
                    INSERT INTO settlements (customer_id, period_id, total_bet, total_win, net_amount, commission, updated_at)
                    VALUES (?,?,?,?,?,0,?)
                    ON CONFLICT(customer_id, period_id) DO UPDATE SET
                      total_bet=excluded.total_bet, total_win=excluded.total_win,
                      net_amount=excluded.net_amount, commission=0, updated_at=excluded.updated_at
                """, (s.customer_id, s.period_id, s.total_bet, s.total_win, s.net_amount,
                      datetime.now().isoformat(sep=" ", timespec="seconds")))
            db.execute("UPDATE periods SET status='settled', settled_at=? WHERE id=?",
                       (datetime.now().isoformat(sep=" ", timespec="seconds"), period["id"]))
            db.commit()

            # 生成报告
            names = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM customers").fetchall()}
            report = format_settlement_report(settlements, names)
            msg = "结算完成！"
            period = db.execute("SELECT * FROM periods WHERE id=?", (period["id"],)).fetchone()

    # 显示开奖球
    special = period["special_num"] if period else None
    normals = json.loads(period["normal_nums"] or "[]") if period else []

    def ball_cls(n):
        if n in COLOR_MAP["红"]: return "r"
        if n in COLOR_MAP["蓝"]: return "b"
        return "g"

    balls_html = ""
    if normals:
        for n in normals:
            balls_html += f'<span class="ball {ball_cls(n)}">{n:02d}</span>'
        if special:
            balls_html += f' <span style="color:#94a3b8">+</span> <span class="ball {ball_cls(special)} sp">{special:02d}</span>'
            z = get_zodiac(special) or ""
            c = get_color(special) or ""
            balls_html += f'<span style="margin-left:10px;font-size:13px;color:var(--muted)">特码 {special:02d}（{c}波 · {z}）</span>'

    # 输入表单
    inputs = ""
    for i in range(1, 7):
        val = normals[i-1] if i <= len(normals) else ""
        inputs += f'<input type="number" name="n{i}" min="1" max="49" placeholder="正{i}" value="{val}" style="width:56px;text-align:center">'
    inputs += f' <strong>+</strong> <input type="number" name="special" min="1" max="49" placeholder="特码" value="{special or ""}" style="width:64px;text-align:center;border-color:#fbbf24;border-width:2px" required>'

    content = f'''
    <div class="card" style="margin-bottom:14px">
      <div class="card-h">录入开奖号码 · 第 {period["period_no"] if period else "-"} 期
        <span class="badge {"badge-s" if period and period["status"]=="settled" else "badge-i"}">{period["status"] if period else ""}</span>
      </div>
      <div class="card-b">
        <form method="POST">
          <input type="hidden" name="action" value="save_draw">
          <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:12px">{inputs}</div>
          <button type="submit" class="btn btn-p">保存开奖号码</button>
        </form>
        {"<div style='margin-top:14px'>" + balls_html + "</div>" if balls_html else ""}
        {f"""<form method="POST" style="margin-top:14px">
          <input type="hidden" name="action" value="settle">
          <button type="submit" class="btn btn-s" onclick="return confirm('确认对所有客户进行自动结算？')">🎯 一键自动结算</button>
        </form>""" if special and period and period["status"] != "settled" else ""}
      </div>
    </div>
    {"<div class='card'><div class='card-h'>结算报告</div><div class='card-b'><pre style='font-size:12px;white-space:pre-wrap;line-height:1.6'>" + report + "</pre></div></div>" if report else ""}
    '''
    return render("draw", content, msg=msg)


@app.route("/backup", methods=["GET", "POST"])
def backup():
    msg = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "backup":
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = os.path.join(BACKUP_DIR, f"aocai_{ts}.db")
            shutil.copy2(DB_PATH, dest)
            msg = f"备份成功：{os.path.basename(dest)}"
        elif action == "restore":
            f = request.files.get("file")
            if f and f.filename.endswith(".db"):
                # 先备份当前
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.copy2(DB_PATH, os.path.join(BACKUP_DIR, f"before_restore_{ts}.db"))
                f.save(DB_PATH)
                msg = "恢复成功！页面将刷新。"
            else:
                msg = "请上传 .db 备份文件"

    files = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")], reverse=True)[:10]
    file_list = "".join(f'<div style="padding:6px 0;border-bottom:1px solid var(--border);font-size:13px">{f}</div>' for f in files) or "<div style='color:#94a3b8'>暂无备份</div>"

    content = f'''
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
      <div class="card">
        <div class="card-h">数据备份</div>
        <div class="card-b" style="text-align:center;padding:30px">
          <div style="font-size:36px;margin-bottom:10px">💾</div>
          <p style="color:var(--muted);font-size:13px;margin-bottom:16px">导出当前所有数据为 SQLite 文件</p>
          <form method="POST"><input type="hidden" name="action" value="backup">
            <button type="submit" class="btn btn-p">立即备份</button>
          </form>
          <div style="margin-top:20px;text-align:left">
            <div style="font-size:13px;font-weight:600;margin-bottom:8px">最近备份</div>
            {file_list}
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-h">数据恢复</div>
        <div class="card-b" style="text-align:center;padding:30px">
          <div style="font-size:36px;margin-bottom:10px">📂</div>
          <p style="color:var(--danger);font-size:13px;margin-bottom:16px">恢复会覆盖当前数据，请先备份！</p>
          <form method="POST" enctype="multipart/form-data">
            <input type="hidden" name="action" value="restore">
            <input type="file" name="file" accept=".db" required style="margin-bottom:12px">
            <br><button type="submit" class="btn btn-o" onclick="return confirm('确认恢复？当前数据将被覆盖！')">选择文件并恢复</button>
          </form>
        </div>
      </div>
    </div>
    '''
    return render("backup", content, msg=msg)


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    init_db()
    print("=" * 50)
    print("澳彩收单系统 已启动")
    print("请在浏览器打开： http://127.0.0.1:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)
