# -*- coding: utf-8 -*-
"""
明澳彩收单系统 · 独立版
运行：python aocai_app.py
浏览器打开 http://127.0.0.1:9000
超级用户：admin   密码：gjxing1111
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import webbrowser
from datetime import date, datetime
from functools import wraps
from flask import Flask, g, redirect, render_template_string, request, send_file, session, url_for

from lottery_core import (
    COLOR_MAP, COMMISSION_RATE, PAYOUT, ZODIAC_MAP, ZODIAC_ORDER,
    evaluate_bet, get_color, get_zodiac, pad2, parse_slip, stake_on_special,
)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
# 云端部署时可指定持久化数据目录（如 Railway/Render 挂载卷）
DATA_DIR = os.environ.get("AOCAI_DATA_DIR", APP_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "aocai.db")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = "aocai-standalone-2026-gjxing"

# ---------- 工具 ----------
def today_iso():
    return date.today().isoformat()

def day_of_year(iso: str) -> int:
    d = datetime.strptime(iso, "%Y-%m-%d").date()
    return d.timetuple().tm_yday

def period_no(iso: str) -> str:
    d = datetime.strptime(iso, "%Y-%m-%d").date()
    return f"{d.year}{day_of_year(iso):03d}"

def hash_pw(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120000)
    return f"{salt}${dk.hex()}"

def check_pw(pw: str, stored: str) -> bool:
    try:
        salt, hx = stored.split("$", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120000)
    return hmac.compare_digest(dk.hex(), hx)

def money(n) -> str:
    return f"{float(n or 0):,.2f}".rstrip("0").rstrip(".")

def type_label(t: str) -> str:
    return {"number": "号码", "zodiac": "生肖", "color": "波色", "element": "五行"}.get(t, t)


# ---------- 数据库 ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(_=None):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        phone TEXT, note TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS periods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        period_no TEXT NOT NULL UNIQUE,
        draw_date TEXT NOT NULL,
        special_num INTEGER,
        normal_nums TEXT,
        status TEXT DEFAULT 'open'
    );
    CREATE TABLE IF NOT EXISTS bets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        period_id INTEGER NOT NULL,
        bet_type TEXT NOT NULL,
        bet_value TEXT NOT NULL,
        amount REAL NOT NULL,
        win_amount REAL DEFAULT 0,
        is_win INTEGER DEFAULT 0,
        FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
        FOREIGN KEY(period_id) REFERENCES periods(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS settlements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        period_id INTEGER NOT NULL,
        total_bet REAL, total_win REAL, net_amount REAL,
        UNIQUE(customer_id, period_id)
    );
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        db.execute("INSERT INTO users (username, password) VALUES (?,?)",
                   ("admin", hash_pw("gjxing1111")))
    if db.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
        db.execute("INSERT INTO customers (name, note) VALUES ('张三','示例客户')")
        db.execute("INSERT INTO customers (name, note) VALUES ('李四','示例客户')")
    if db.execute("SELECT COUNT(*) FROM settings WHERE key='invite_code'").fetchone()[0] == 0:
        db.execute("INSERT INTO settings (key, value) VALUES ('invite_code', 'aocai2026')")
    db.commit()
    db.close()

def login_required(fn):
    @wraps(fn)
    def wrap(*a, **k):
        if not session.get("uid"):
            return redirect(url_for("login"))
        return fn(*a, **k)
    return wrap

def ensure_period(iso: str):
    db = get_db()
    no = period_no(iso)
    row = db.execute("SELECT * FROM periods WHERE period_no=?", (no,)).fetchone()
    if row:
        return row
    db.execute("INSERT INTO periods (period_no, draw_date, status) VALUES (?,?, 'open')", (no, iso))
    db.commit()
    return db.execute("SELECT * FROM periods WHERE period_no=?", (no,)).fetchone()

@app.route("/save-now")
@login_required
def save_now():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    get_db().commit()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"aocai_{ts}.db")
    shutil.copy2(DB_PATH, dest)
    session["flash"] = f"已保存数据（{os.path.basename(dest)}）"
    ref = request.referrer or "/"
    return redirect(ref)


# ---------- 样式 ----------
CSS = """
:root{--bg:#f2f2f7;--surface:#ffffff;--elev:#fff;--ink:#1c1c1e;--muted:#8e8e93;--line:rgba(60,60,67,.14);
--accent:#007aff;--ok:#34c759;--bad:#ff3b30;--warn:#ff9500;--red:#ff3b30;--blue:#007aff;--green:#34c759;
--r:14px;--shadow:0 1px 3px rgba(0,0,0,.05),0 8px 24px rgba(0,0,0,.04)}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display","PingFang SC","Helvetica Neue","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--ink);min-height:100vh;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
h1{font-size:28px;margin-bottom:4px;font-weight:700;letter-spacing:-.02em}
h2{font-size:22px;font-weight:700;letter-spacing:-.02em}
nav{position:sticky;top:0;z-index:40;display:flex;align-items:center;gap:2px;padding:8px 14px;background:rgba(250,238,190,.92);backdrop-filter:saturate(180%) blur(20px);-webkit-backdrop-filter:saturate(180%) blur(20px);border-bottom:1px solid #e8d98f;overflow-x:auto;scrollbar-width:none}
nav::-webkit-scrollbar{display:none}
nav a,nav span{flex-shrink:0;white-space:nowrap}
nav a{color:var(--ink);padding:8px 13px;border-radius:999px;font-size:14px;font-weight:500;transition:background .15s}
nav a.on{background:var(--accent);color:#fff;font-weight:600}
nav a:not(.on):hover{background:rgba(0,0,0,.05)}
nav .logo{font-weight:700;font-size:17px;margin-right:8px;letter-spacing:-.02em}
.nav-save{background:var(--accent);color:#fff!important;border-radius:999px;padding:7px 14px;font-size:13px;font-weight:600}
.nav-save:hover{opacity:.9}
.wrap{max-width:1180px;margin:0 auto;padding:16px 14px 40px}
.card{background:var(--surface);border-radius:var(--r);padding:16px;margin-bottom:14px;box-shadow:var(--shadow)}
.btn{height:40px;padding:0 16px;border:none;border-radius:10px;cursor:pointer;font-size:14px;font-weight:600;display:inline-flex;align-items:center;justify-content:center;transition:opacity .15s,transform .05s}
.btn:active{opacity:.85;transform:scale(.98)}
.btn-p{background:var(--accent);color:#fff}
.btn-d{background:var(--bad);color:#fff}
.btn-o{background:#fff;border:1px solid var(--line);color:var(--ink)}
.btn-s{background:var(--ok);color:#fff}
.btn-batch-on{background:#e08600;color:#fff;box-shadow:0 0 0 2px rgba(224,134,0,.35)}
.pick{display:inline-flex;align-items:center;gap:4px;background:var(--accent);color:#fff;border-radius:8px;padding:4px 9px;font-size:13px;font-weight:600;animation:pickIn .25s ease}
.pick.has{background:var(--warn)}
.pick a{color:#fff;text-decoration:none;font-weight:700;margin-left:2px;opacity:.85}
.pick a:hover{opacity:1}
@keyframes pickIn{0%{transform:scale(.6);opacity:0}100%{transform:scale(1);opacity:1}}
input,select,textarea{height:40px;padding:0 12px;border:1px solid var(--line);border-radius:10px;font-size:15px;background:#fff;font-family:inherit;color:var(--ink);outline:none;transition:border-color .15s}
input:focus,select:focus,textarea:focus{border-color:var(--accent)}
textarea{height:auto;padding:10px 12px;width:100%}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);color:var(--ink)}
th{color:var(--muted);font-weight:500;font-size:12px}
tr:last-child td{border-bottom:none}
.grid7{display:grid;grid-template-columns:repeat(7,1fr);gap:6px}
.nb{aspect-ratio:1;border:1.5px solid var(--line);border-radius:10px;background:#fff;cursor:pointer;font-size:13px;font-weight:600;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--ink);transition:transform .05s,box-shadow .15s;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.nb:active{transform:scale(.94)}
.nb.sel{border-color:var(--accent);background:#e8f1ff;box-shadow:0 0 0 2px rgba(0,122,255,.15)}
.nb.has{border-color:var(--accent);background:#f0f6ff}
.nb.flash{animation:nbFlash .5s ease}
@keyframes nbFlash{0%{box-shadow:0 0 0 0 rgba(255,165,0,.75);background:#fff3d6}40%{transform:scale(1.12);box-shadow:0 0 0 6px rgba(255,165,0,.35);background:#ffe9b8;border-color:#f0a020}100%{box-shadow:0 0 0 0 rgba(255,165,0,0);transform:scale(1)}}
.nb.r{border-bottom:3px solid var(--red)}.nb.b{border-bottom:3px solid var(--blue)}.nb.g{border-bottom:3px solid var(--green)}
.layout{display:grid;grid-template-columns:200px 1fr 280px;gap:14px;align-items:start}
.cust{display:block;width:100%;text-align:left;padding:10px 12px;border:none;background:none;cursor:pointer;border-radius:10px;color:var(--ink);font-size:15px;margin-bottom:2px}
.cust:hover{background:rgba(0,0,0,.04)}
.cust.on{background:var(--accent);color:#fff}
.stat{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:14px 0}
.stat .b{background:var(--surface);border-radius:var(--r);padding:18px 14px;text-align:center;box-shadow:var(--shadow)}
.stat .l{font-size:12px;color:var(--muted)}.stat .v{font-size:26px;font-weight:700;margin-top:6px;letter-spacing:-.02em}
.tip{background:#fff7e6;border:none;border-radius:10px;padding:10px 14px;font-size:13px;margin-bottom:12px;color:#8a5a00}
.login-box{max-width:380px;margin:12vh auto;background:var(--surface);border-radius:20px;padding:32px 28px;box-shadow:0 20px 60px rgba(0,0,0,.08)}
.muted{color:var(--muted);font-size:13px}
.ocr2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:12px;align-items:start}
.betrow{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:#fff;border:1px solid var(--line);border-radius:10px;margin-bottom:6px;font-size:14px;color:var(--ink)}
.betrow a{color:var(--accent);font-weight:600}
@media(max-width:900px){
  .layout{grid-template-columns:1fr}
  .stat{grid-template-columns:1fr 1fr!important}
  .ocr2{grid-template-columns:1fr!important}
}
@media(max-width:480px){
  h1{font-size:24px}
  .stat .v{font-size:22px}
  .grid7{gap:4px}
  .nb{font-size:12px;border-radius:8px}
  .btn{height:44px;font-size:15px}
  input,select,textarea{height:44px;font-size:16px}
  .wrap{padding:12px 10px 32px}
}
@media print{nav,.noprint{display:none!important}body{background:#fff}.card{box-shadow:none;border:1px solid #ccc}}
"""

def page(title, body, active=""):
    iso = today_iso()
    day = day_of_year(iso)
    nav = [
        ("/", "押注入录", "bet"),
        ("/customers", "客户", "cust"),
        ("/draw", "开奖", "draw"),
        ("/ocr", "文字录入", "ocr"),
        ("/history", "历史查询", "hist"),
        ("/print", "打印对账单", "print"),
        ("/backup", "备份恢复", "bak"),
        ("/account", "账户", "acc"),
    ]
    links = "".join(
        f'<a href="{u}" class="{"on" if active==k else ""}">{n}</a>' for u, n, k in nav
    )
    user = session.get("user", "")
    flash = session.pop("flash", "")
    flash_html = f'<div class="tip noprint">{flash}</div>' if flash else ""
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · 明澳彩收单</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Noto+Sans+SC:wght@400;500;600&display=swap">
<style>{CSS}</style></head><body>
<nav class="noprint"><span class="logo"><svg viewBox="0 0 24 24" width="21" height="21" style="vertical-align:-4px;margin-right:6px" aria-hidden="true"><defs><linearGradient id="lgg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f7b733"/><stop offset="1" stop-color="#e0432e"/></linearGradient></defs><circle cx="12" cy="12" r="11" fill="url(#lgg)"/><circle cx="12" cy="12" r="8.6" fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="1"/><text x="12" y="16.2" text-anchor="middle" font-size="12.5" font-weight="700" fill="#fff" font-family="Noto Sans SC,sans-serif">明</text></svg>明澳彩收单</span>{links}
<span style="margin-left:auto;display:flex;align-items:center;gap:10px;font-size:13px;opacity:.9">
第 {day} 期 · {iso}
<a class="nav-save" href="/save-now">保存数据</a>
<span>{user}</span>
<a href="/logout">退出</a>
</span></nav>
<div class="wrap">{flash_html}{body}</div></body></html>"""

# ---------- 登录 ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    err = ""
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        db = get_db()
        row = db.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
        if row and check_pw(p, row["password"]):
            session["uid"] = row["id"]
            session["user"] = row["username"]
            return redirect("/")
        err = "用户名或密码错误"
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>登录 · 明澳彩收单</title><style>{CSS}</style></head><body>
<div class="login-box">
<p style="font-size:11px;letter-spacing:.2em;color:var(--muted)">MING AOCAI LEDGER</p>
<h1 style="font-size:24px;margin:4px 0 6px;display:flex;align-items:center;justify-content:center;gap:8px"><svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true"><defs><linearGradient id="lgl" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f7b733"/><stop offset="1" stop-color="#e0432e"/></linearGradient></defs><circle cx="12" cy="12" r="11" fill="url(#lgl)"/><circle cx="12" cy="12" r="8.6" fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="1"/><text x="12" y="16.2" text-anchor="middle" font-size="12.5" font-weight="700" fill="#fff" font-family="Noto Sans SC,sans-serif">明</text></svg>明澳彩收单系统</h1>
<p style="color:var(--muted);font-size:13px;margin-bottom:16px">独立版 · 登录后进入主页</p>
<form method="post">
<label style="font-size:12px;color:var(--muted)">用户名</label>
<input name="username" value="admin" required style="width:100%;margin:6px 0 12px">
<label style="font-size:12px;color:var(--muted)">密码</label>
<input type="password" name="password" required style="width:100%;margin:6px 0 12px">
{f'<p style="color:var(--bad);font-size:13px">{err}</p>' if err else ''}
<button class="btn btn-p" style="width:100%">登录</button>
</form>
<p style="margin-top:14px;text-align:center;font-size:13px"><a href="/register">注册新用户</a></p>
</div></body></html>"""

@app.route("/register", methods=["GET", "POST"])
def register():
    err = ""
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        code = request.form.get("invite", "").strip()
        if len(u) < 2 or len(p) < 8:
            err = "用户名至少2位，密码至少8位"
        else:
            db = get_db()
            row = db.execute("SELECT value FROM settings WHERE key='invite_code'").fetchone()
            correct = row["value"] if row else "aocai2026"
            if code != correct:
                err = "邀请码不正确，请联系管理员"
            else:
                try:
                    db.execute("INSERT INTO users (username,password) VALUES (?,?)", (u, hash_pw(p)))
                    db.commit()
                    return redirect("/login")
                except sqlite3.IntegrityError:
                    err = "用户名已存在"
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<div class="login-box"><h1>注册新用户</h1>
<p class="muted" style="margin:6px 0 14px">需邀请码才能注册，请联系管理员获取</p>
<form method="post" style="margin-top:16px">
<input name="username" placeholder="用户名" required style="width:100%;margin-bottom:10px">
<input type="password" name="password" placeholder="密码至少8位" required style="width:100%;margin-bottom:10px">
<input name="invite" placeholder="邀请码" required style="width:100%;margin-bottom:10px">
{f'<p style="color:var(--bad)">{err}</p>' if err else ''}
<button class="btn btn-p" style="width:100%">注册</button>
</form><p style="margin-top:12px"><a href="/login">返回登录</a></p></div></body></html>"""

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
    msg = ""
    if request.method == "POST":
        cur = request.form.get("cur", "")
        new = request.form.get("new", "")
        db = get_db()
        row = db.execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()
        if not check_pw(cur, row["password"]):
            msg = "当前密码不正确"
        elif len(new) < 8:
            msg = "新密码至少8位"
        else:
            db.execute("UPDATE users SET password=? WHERE id=?", (hash_pw(new), session["uid"]))
            db.commit()
            msg = "密码已更新"
    body = f"""<h2>账户与密码</h2>
<div class="card" style="max-width:360px;margin-top:12px">
<form method="post">
<p style="font-size:12px;color:var(--muted);margin-bottom:6px">当前密码</p>
<input type="password" name="cur" required style="width:100%;margin-bottom:10px">
<p style="font-size:12px;color:var(--muted);margin-bottom:6px">新密码</p>
<input type="password" name="new" required minlength="8" style="width:100%;margin-bottom:10px">
<button class="btn btn-p">修改密码</button>
{f'<p style="margin-top:8px">{msg}</p>' if msg else ''}
</form></div>"""
    return page("账户", body, "acc")

# ---------- 押注 ----------
@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    db = get_db()
    iso = request.values.get("date") or today_iso()
    period = ensure_period(iso)
    cid = request.values.get("cid", type=int)
    customers = db.execute("SELECT * FROM customers ORDER BY id").fetchall()
    if not cid and customers:
        cid = customers[0]["id"]
    if request.method == "POST":
        action = request.form.get("action")
        cid = request.form.get("cid", type=int) or cid
        if action == "add":
            btype = request.form.get("bet_type", "number")
            bval = request.form.get("bet_value", "").strip()
            amt = float(request.form.get("amount") or 0)
            if cid and amt > 0 and bval:
                db.execute(
                    "INSERT INTO bets (customer_id,period_id,bet_type,bet_value,amount) VALUES (?,?,?,?,?)",
                    (cid, period["id"], btype, bval, amt),
                )
                db.commit()
        elif action == "batch":
            amt = float(request.form.get("amount") or 0)
            nums = request.form.get("nums", "")
            if cid and amt > 0:
                for n in nums.split(","):
                    n = n.strip()
                    if n:
                        db.execute(
                            "INSERT INTO bets (customer_id,period_id,bet_type,bet_value,amount) VALUES (?,?,?,?,?)",
                            (cid, period["id"], "number", n, amt),
                        )
                db.commit()
        elif action == "del":
            ids = request.form.get("ids", "")
            for i in ids.split(","):
                if i.strip().isdigit():
                    db.execute("DELETE FROM bets WHERE id=?", (int(i),))
            db.commit()
        elif action == "edit":
            bid = request.form.get("bid", type=int)
            amt = float(request.form.get("amount") or 0)
            if bid and amt > 0:
                db.execute("UPDATE bets SET amount=? WHERE id=?", (amt, bid))
                db.commit()
        return redirect(f"/?date={iso}&cid={cid}")

    bets = db.execute(
        "SELECT * FROM bets WHERE period_id=? AND customer_id=? ORDER BY amount DESC, id",
        (period["id"], cid or 0),
    ).fetchall() if cid else []
    amt_map = {}
    for b in bets:
        if b["bet_type"] == "number":
            amt_map[b["bet_value"]] = amt_map.get(b["bet_value"], 0) + b["amount"]
    total = sum(b["amount"] for b in bets)

    cust_html = "".join(
        f'<a class="cust {"on" if c["id"]==cid else ""}" href="/?date={iso}&cid={c["id"]}">{c["name"]}</a>'
        for c in customers
    )
    nums_html = ""
    for n in range(1, 50):
        v = pad2(n)
        col = get_color(n)
        cls = "r" if col == "红" else "b" if col == "蓝" else "g"
        has = " has" if v in amt_map else ""
        extra = f'<span style="font-size:9px;color:var(--accent)">{money(amt_map[v])}</span>' if v in amt_map else ""
        nums_html += f'<button type="button" class="nb {cls}{has}" data-n="{v}" onclick="tog(this)">{v}{extra}</button>'

    zod_html = ""
    for z in ZODIAC_ORDER:
        ns = " ".join(pad2(x) for x in ZODIAC_MAP[z])
        zod_html += f"""<button type="button" class="nb" style="aspect-ratio:auto;padding:8px"
          onclick="one(this,'zodiac','{z}')">{z}<div style="font-size:9px;color:var(--muted);font-weight:400">{ns}</div></button>"""

    color_html = ""
    for c, clr in (("红", "var(--red)"), ("蓝", "var(--blue)"), ("绿", "var(--green)")):
        ns = " ".join(pad2(x) for x in COLOR_MAP[c])
        color_html += f"""<button type="button" class="nb" style="aspect-ratio:auto;padding:10px 6px;background:{clr};color:#fff;border:none"
          onclick="one(this,'color','{c}')"><span style="font-size:15px;font-weight:700">{c}波</span>
          <span style="font-size:9px;opacity:.95;font-weight:400;margin-top:3px;line-height:1.6">{ns}</span></button>"""

    bet_rows = "".join(
        f"""<label class="betrow">
        <span><input type="checkbox" class="bid" value="{b['id']}"> {type_label(b['bet_type'])} {b['bet_value']}</span>
        <a href="#" onclick="editAmt({b['id']},{b['amount']});return false">¥{money(b['amount'])}</a></label>"""
        for b in bets
    )

    body = f"""
    <form class="noprint" style="margin-bottom:12px;display:flex;flex-wrap:wrap;align-items:end;gap:12px">
      <div>
        <div class="muted" style="margin-bottom:4px">录入日期（可补录 / 修改历史）</div>
        <input type="date" name="date" value="{iso}" onchange="this.form.submit()">
      </div>
      <p class="muted">点「批量录入选中」弹出多选框，点数字依序加入后输入统一金额同时录入。单个数字直接点击录入；已押注数字点击可继续追加。</p>
      <input type="hidden" name="cid" value="{cid or ''}">
    </form>
    <div class="layout">
      <div class="card"><b>客户</b>{cust_html or '<p class="muted">请先添加客户</p>'}</div>
      <div class="card">
        <b>数字 01–49</b>
        <div class="grid7" style="margin-top:8px">{nums_html}</div>
        <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          <span id="seln" class="muted">已选 0</span>
          <button class="btn btn-p" type="button" id="batchBtn" onclick="openBatch()">批量录入选中</button>
          <button class="btn btn-o" type="button" onclick="clr()">清空选择</button>
        </div>
        <div id="bmodal" style="display:none;margin-top:12px;border:2px solid var(--accent);border-radius:12px;padding:14px;background:var(--elev)">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <b>批量录入 · 多选数字</b>
            <button class="btn btn-o" type="button" onclick="closeBatch()" style="height:28px;padding:0 10px;font-size:12px">收起</button>
          </div>
          <p class="muted" style="margin:0 0 8px">点击数字网格中的号码依序加入下方；再点已加入号码可取消。已押注号码可继续多选。</p>
          <div id="picklist" style="min-height:46px;border:1px dashed var(--line);border-radius:10px;padding:8px;display:flex;flex-wrap:wrap;gap:6px;align-content:flex-start;background:#fff">尚未选择数字</div>
          <div style="margin-top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <span class="muted">金额</span>
            <input type="number" id="bam2" placeholder="统一金额" style="width:120px">
            <button class="btn btn-s" type="button" onclick="confirmBatch()">确定录入</button>
          </div>
        </div>
        <b style="display:block;margin:12px 0 6px">生肖</b>
        <div class="grid7" style="grid-template-columns:repeat(6,1fr)">{zod_html}</div>
        <b style="display:block;margin:12px 0 6px">波色</b>
        <div class="grid7" style="grid-template-columns:repeat(3,1fr);margin-top:8px">{color_html}</div>
      </div>
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
          <b>当前客户押注</b>
          <span style="font-size:13px;color:var(--muted)">合计 <b style="color:var(--accent);font-size:16px">¥{money(total)}</b></span>
        </div>
        <div style="margin:8px 0;display:flex;gap:6px">
          <button class="btn btn-o" style="flex:1;padding:0 8px" type="button" onclick="selAll()">全选</button>
          <button class="btn btn-o" style="flex:1;padding:0 8px" type="button" onclick="clrBets()">清除选择</button>
          <button class="btn btn-d" style="flex:1;padding:0 8px" type="button" onclick="delSel()">删除选中</button>
        </div>
        <div style="max-height:360px;overflow:auto">{bet_rows}</div>
      </div>
    </div>
    <form id="fadd" method="post" style="display:none">
      <input name="action" value="add"><input name="date" value="{iso}">
      <input name="cid" value="{cid or ''}"><input name="bet_type" id="bt">
      <input name="bet_value" id="bv"><input name="amount" id="ba">
    </form>
    <form id="fbatch" method="post" style="display:none">
      <input name="action" value="batch"><input name="date" value="{iso}">
      <input name="cid" value="{cid or ''}"><input name="nums" id="bnums"><input name="amount" id="bamt">
    </form>
    <form id="fdel" method="post" style="display:none">
      <input name="action" value="del"><input name="date" value="{iso}">
      <input name="cid" value="{cid or ''}"><input name="ids" id="dids">
    </form>
    <form id="fedit" method="post" style="display:none">
      <input name="action" value="edit"><input name="date" value="{iso}">
      <input name="cid" value="{cid or ''}"><input name="bid" id="ebid"><input name="amount" id="eamt">
    </form>
    <div id="amtModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:99;align-items:center;justify-content:center">
      <div style="background:var(--elev);border-radius:16px;padding:22px 20px 18px;width:min(320px,90vw);box-shadow:0 24px 70px rgba(0,0,0,.35);text-align:center">
        <b id="amtTitle" style="font-size:17px;display:block">录入 号码 04</b>
        <input type="number" id="amtInput" value="10" min="1" step="any" style="width:100%;margin:16px 0 18px;height:46px;font-size:20px;text-align:center;border:2px solid var(--accent);border-radius:12px;outline:none">
        <div style="display:flex;gap:10px">
          <button class="btn btn-o" style="flex:1;height:42px" type="button" onclick="closeAmt()">取消</button>
          <button class="btn btn-p" style="flex:1;height:42px" type="button" onclick="submitAmt()">确定</button>
        </div>
      </div>
    </div>
    <script>
    var batchMode=false,batchNums=[];
    function beep(){{
      try{{
        var A=window.AudioContext||window.webkitAudioContext;if(!A)return;
        var c=new A(),o=c.createOscillator(),g=c.createGain();
        o.type='square';o.frequency.value=880;
        g.gain.setValueAtTime(.12,c.currentTime);
        g.gain.exponentialRampToValueAtTime(.001,c.currentTime+.18);
        o.connect(g);g.connect(c.destination);o.start();o.stop(c.currentTime+.2);
      }}catch(e){{}}
    }}
    function updSel(){{document.getElementById('seln').textContent='已选 '+document.querySelectorAll('.nb.sel').length;}}
    function renderPicks(){{
      var box=document.getElementById('picklist');
      if(!batchNums.length){{box.innerHTML='<span class="muted">尚未选择数字</span>';return;}}
      box.innerHTML=batchNums.map(function(v){{
        var el=document.querySelector('.nb[data-n="'+v+'"]');
        var has=el&&el.classList.contains('has');
        return '<span class="pick'+(has?' has':'')+'">'+v+' <a href="#" data-v="'+v+'" onclick="unpick(this.dataset.v);return false">×</a></span>';
      }}).join('');
    }}
    function openBatch(){{
      batchMode=true;batchNums=[];
      document.getElementById('bam2').value='';
      renderPicks();
      document.getElementById('bmodal').style.display='block';
      beep();
    }}
    function closeBatch(){{
      batchMode=false;
      document.getElementById('bmodal').style.display='none';
      document.querySelectorAll('.nb.sel').forEach(function(e){{e.classList.remove('sel');}});
      updSel();
    }}
    function tog(el){{
      if(batchMode){{
        beep();
        el.classList.remove('flash');void el.offsetWidth;el.classList.add('flash');
        var v=el.dataset.n;
        var i=batchNums.indexOf(v);
        if(i>=0){{batchNums.splice(i,1);el.classList.remove('sel');}}
        else{{batchNums.push(v);el.classList.add('sel');}}
        renderPicks();updSel();return;
      }}
      beep();
      el.classList.remove('flash');void el.offsetWidth;el.classList.add('flash');
      var v=el.dataset.n;
      if(el.classList.contains('has')){{
        openAmt('数字 '+v+' 已有押注，继续追加金额','number',v);
      }}else{{
        openAmt('录入 号码 '+v,'number',v);
      }}
    }}
    function unpick(v){{
      var i=batchNums.indexOf(v);
      if(i>=0) batchNums.splice(i,1);
      var el=document.querySelector('.nb[data-n="'+v+'"]');
      if(el) el.classList.remove('sel');
      renderPicks();updSel();beep();
    }}
    function clr(){{document.querySelectorAll('.nb.sel').forEach(e=>e.classList.remove('sel'));updSel();}}
    function confirmBatch(){{
      if(!batchNums.length) return alert('请先点选要录入的号码');
      const a=document.getElementById('bam2').value;
      if(!(+a>0)) return alert('请输入统一金额');
      document.getElementById('bnums').value=batchNums.join(',');
      document.getElementById('bamt').value=a;
      document.getElementById('fbatch').submit();
    }}
    function one(el,t,v){{
      beep();
      el.classList.remove('flash');void el.offsetWidth;el.classList.add('flash');
      openAmt('录入 '+v+' 的金额',t,v);
    }}
    var amtT=null,amtV=null;
    function openAmt(title,t,v){{
      amtT=t;amtV=v;
      document.getElementById('amtTitle').textContent=title;
      document.getElementById('amtInput').value='10';
      document.getElementById('amtModal').style.display='flex';
      document.getElementById('amtInput').focus();
      document.getElementById('amtInput').select();
    }}
    function closeAmt(){{
      amtT=null;amtV=null;
      document.getElementById('amtModal').style.display='none';
    }}
    function submitAmt(){{
      if(!amtT) return;
      const a=document.getElementById('amtInput').value;
      if(!(+a>0)) return alert('请输入有效金额');
      document.getElementById('bt').value=amtT;
      document.getElementById('bv').value=amtV;
      document.getElementById('ba').value=a;
      document.getElementById('fadd').submit();
    }}
    function selAll(){{document.querySelectorAll('.bid').forEach(c=>c.checked=true);}}
    function clrBets(){{document.querySelectorAll('.bid').forEach(c=>c.checked=false);}}
    function delSel(){{
      const ids=[...document.querySelectorAll('.bid:checked')].map(c=>c.value);
      if(!ids.length) return alert('请勾选');
      document.getElementById('dids').value=ids.join(',');
      document.getElementById('fdel').submit();
    }}
    function editAmt(id,cur){{
      const a=prompt('修改金额',cur);
      if(!(+a>0)) return;
      document.getElementById('ebid').value=id;
      document.getElementById('eamt').value=a;
      document.getElementById('fedit').submit();
    }}
    </script>
    """
    return page("押注入录", body, "bet")

# ---------- 客户 ----------
@app.route("/customers", methods=["GET", "POST"])
@login_required
def customers():
    db = get_db()
    if request.method == "POST":
        act = request.form.get("action")
        cid = request.form.get("id", type=int)
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone") or None
        note = request.form.get("note") or None
        if act == "add" and name:
            try:
                db.execute("INSERT INTO customers (name,phone,note) VALUES (?,?,?)", (name, phone, note))
                db.commit()
            except sqlite3.IntegrityError:
                session["flash"] = "客户名已存在"
        elif act == "edit" and cid and name:
            db.execute("UPDATE customers SET name=?, phone=?, note=? WHERE id=?", (name, phone, note, cid))
            db.commit()
        elif act == "del" and cid:
            db.execute("DELETE FROM customers WHERE id=?", (cid,))
            db.commit()
        return redirect("/customers")
    edit_id = request.args.get("edit", type=int)
    edit_row = None
    if edit_id:
        edit_row = db.execute("SELECT * FROM customers WHERE id=?", (edit_id,)).fetchone()
    rows = db.execute("SELECT * FROM customers ORDER BY id").fetchall()
    tr = "".join(
        f"""<tr>
        <td>{r['name']}</td><td>{r['phone'] or '—'}</td><td>{r['note'] or '—'}</td>
        <td>
          <a class="btn btn-o" href="/customers?edit={r['id']}">修改</a>
          <form method="post" style="display:inline" onsubmit="return confirm('删除 {r['name']}？')">
            <input type="hidden" name="action" value="del"><input type="hidden" name="id" value="{r['id']}">
            <button class="btn btn-d">删除</button>
          </form>
        </td></tr>"""
        for r in rows
    )
    if edit_row:
        form = f"""<form method="post" class="card" style="display:flex;gap:8px;flex-wrap:wrap;align-items:end;margin-top:12px">
      <input type="hidden" name="action" value="edit"><input type="hidden" name="id" value="{edit_row['id']}">
      <input name="name" placeholder="姓名" required value="{edit_row['name']}">
      <input name="phone" placeholder="电话" value="{edit_row['phone'] or ''}">
      <input name="note" placeholder="备注" value="{edit_row['note'] or ''}">
      <button class="btn btn-p">保存修改</button>
      <a class="btn btn-o" href="/customers">取消</a>
    </form>"""
    else:
        form = """<form method="post" class="card" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
      <input type="hidden" name="action" value="add">
      <input name="name" placeholder="姓名" required>
      <input name="phone" placeholder="电话">
      <input name="note" placeholder="备注">
      <button class="btn btn-p">添加客户</button>
    </form>"""
    body = f"""<h1>客户管理</h1>
    {form}
    <div class="card" style="padding:0"><table><thead><tr><th>客户</th><th>电话</th><th>备注</th><th>操作</th></tr></thead>
    <tbody>{tr}</tbody></table></div>"""
    return page("客户", body, "cust")


# ---------- 开奖 ----------
@app.route("/draw", methods=["GET", "POST"])
@login_required
def draw():
    db = get_db()
    iso = request.values.get("date") or today_iso()
    period = ensure_period(iso)
    if request.method == "POST":
        sp = int(request.form.get("special") or 0)
        if 1 <= sp <= 49:
            ns = request.form.get("normals", "")
            db.execute("UPDATE periods SET special_num=?, normal_nums=?, status='settled' WHERE id=?",
                       (sp, ns, period["id"]))
            bets = db.execute("SELECT * FROM bets WHERE period_id=?", (period["id"],)).fetchall()
            by = {}
            for b in bets:
                win, amt = evaluate_bet(b["bet_type"], b["bet_value"], b["amount"], sp)
                db.execute("UPDATE bets SET is_win=?, win_amount=? WHERE id=?", (1 if win else 0, amt, b["id"]))
                cur = by.setdefault(b["customer_id"], {"bet": 0, "win": 0})
                cur["bet"] += b["amount"]
                cur["win"] += amt
            for cid, v in by.items():
                net = round(v["bet"] - v["win"], 2)
                db.execute(
                    """INSERT INTO settlements (customer_id,period_id,total_bet,total_win,net_amount)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(customer_id,period_id) DO UPDATE SET
                       total_bet=excluded.total_bet,total_win=excluded.total_win,net_amount=excluded.net_amount""",
                    (cid, period["id"], v["bet"], v["win"], net),
                )
            db.commit()
        return redirect(f"/draw?date={iso}")
    period = ensure_period(iso)
    customers = {c["id"]: c["name"] for c in db.execute("SELECT * FROM customers")}
    bets = db.execute("SELECT * FROM bets WHERE period_id=?", (period["id"],)).fetchall()
    by = {}
    for b in bets:
        cur = by.setdefault(b["customer_id"], {"bet": 0, "win": 0, "hits": []})
        cur["bet"] += b["amount"]
        cur["win"] += b["win_amount"] or 0
        if b["is_win"]:
            cur["hits"].append(b)
    blocks = ""
    if not bets:
        blocks = '<p class="tip">该日暂无押注</p>'
    for cid, v in by.items():
        net = v["bet"] - v["win"]
        lab = "应收" if net >= 0 else "应付"
        hits = "".join(
            f"<li>{h['bet_type']} {h['bet_value']} 押 ¥{money(h['amount'])} → 中 ¥{money(h['win_amount'])}</li>"
            for h in v["hits"]
        ) or "<li>无中奖</li>"
        blocks += f"""<div class="card"><b>{customers.get(cid,cid)}</b>
        <div>押注 ¥{money(v['bet'])} · 中奖 ¥{money(v['win'])} · {lab} ¥{money(abs(net))}</div>
        <ul style="font-size:12px;color:var(--muted);margin-top:6px">{hits}</ul></div>"""
    sp = period["special_num"]
    extra = ""
    if sp:
        extra = f"<p class='tip'>特码记忆：{iso} 期 {pad2(sp)} · {get_color(sp)}波 · {get_zodiac(sp)}</p>"
    body = f"""<h2>开奖结算</h2>
    <form method="get" class="card" style="display:flex;gap:8px;flex-wrap:wrap;align-items:end;margin-top:12px">
      <div>日期（选日期自动显示该期特码与中奖）<br><input type="date" name="date" value="{iso}" onchange="this.form.submit()"></div>
      <button class="btn btn-o">查看该日期</button>
    </form>
    <form method="post" class="card" style="display:flex;gap:8px;flex-wrap:wrap;align-items:end">
      <input type="hidden" name="date" value="{iso}">
      <div>特码<br><input name="special" placeholder="07" style="width:80px" value="{sp or ''}"></div>
      <div>正码（可选）<br><input name="normals" placeholder="01 12 23" value="{period['normal_nums'] or ''}"></div>
      <button class="btn btn-p">保存并自动结算</button>
    </form>{extra}{blocks}"""
    return page("开奖", body, "draw")

# ---------- OCR ----------
@app.route("/ocr", methods=["GET", "POST"])
@login_required
def ocr():
    db = get_db()
    iso = request.values.get("date") or today_iso()
    customers = db.execute("SELECT * FROM customers ORDER BY id").fetchall()
    preview = ""
    if request.method == "POST":
        iso = request.form.get("date") or iso
        cid = request.form.get("cid", type=int)
        text = request.form.get("text", "")
        act = request.form.get("action")
        items = parse_slip(text)
        total = sum(i["amount"] for i in items)
        if act == "write" and cid and items:
            period = ensure_period(iso)
            for it in items:
                old = db.execute(
                    """SELECT id, amount FROM bets
                       WHERE customer_id=? AND period_id=? AND bet_type=? AND bet_value=?""",
                    (cid, period["id"], it["bet_type"], it["bet_value"]),
                ).fetchone()
                if old:
                    db.execute("UPDATE bets SET amount=? WHERE id=?",
                               (round(old["amount"] + it["amount"], 2), old["id"]))
                else:
                    db.execute(
                        "INSERT INTO bets (customer_id,period_id,bet_type,bet_value,amount) VALUES (?,?,?,?,?)",
                        (cid, period["id"], it["bet_type"], it["bet_value"], it["amount"]),
                    )
            db.commit()
            return redirect(f"/?date={iso}&cid={cid}")
        items_sorted = sorted(
            items,
            key=lambda i: (0 if i["bet_type"] == "number" else 1, i["bet_value"]),
        )
        rows = "".join(
            f"""<div class="betrow"><span>{type_label(i['bet_type'])} {i['bet_value']}</span>
            <span>¥{money(i['amount'])}</span></div>"""
            for i in items_sorted
        )
        preview_inner = f"""
        <div style="display:flex;justify-content:space-between;margin-bottom:8px">
          <span>{len(items)} 条</span><strong>合计 ¥{money(total)}</strong>
        </div>
        <div style="max-height:360px;overflow:auto">{rows or '<p class="muted">识别后这里显示号码和金额</p>'}</div>
        <button class="btn btn-s" style="margin-top:12px" form="ocrf" name="action" value="write">确认写入</button>"""
    else:
        preview_inner = """
        <div style="display:flex;justify-content:space-between;margin-bottom:8px">
          <span>0 条</span><strong>合计 ¥0</strong>
        </div>
        <p class="muted">识别后这里显示号码和金额</p>
        <button class="btn btn-s" style="margin-top:12px" form="ocrf" name="action" value="write">确认写入</button>"""
    sel_cid = request.values.get("cid", type=int)
    opts = '<option value="">选择客户</option>' + "".join(
        f'<option value="{c["id"]}" {"selected" if sel_cid==c["id"] else ""}>{c["name"]}</option>'
        for c in customers
    )
    text_val = request.form.get("text", "") if request.method == "POST" else ""
    body = f"""<h1>文字自动录入</h1>
    <p class="muted">支持「马羊猴各字200」「01/37/36各字150」。各字＝每个号码都押该金额；各包＝生肖总额再平均。重叠号码自动相加。号码换算：01＝1，02＝2，03＝3，04＝4，05＝5，06＝6，07＝7，08＝8，09＝9。</p>
    <div class="ocr2">
      <form id="ocrf" method="post" class="card">
        <div style="display:flex;gap:8px;margin-bottom:8px">
          <input type="date" name="date" value="{iso}">
          <select name="cid">{opts}</select>
        </div>
        <textarea name="text" rows="12" placeholder="粘贴客户单…">{text_val}</textarea>
        <button class="btn btn-p" style="margin-top:8px" name="action" value="preview">识别</button>
      </form>
      <div class="card">{preview_inner}</div>
    </div>"""
    return page("文字录入", body, "ocr")

# ---------- 历史 ----------
@app.route("/history", methods=["GET", "POST"])
@login_required
def history():
    db = get_db()
    if request.method == "POST" and request.form.get("action") == "clear":
        db.execute("DELETE FROM bets")
        db.execute("DELETE FROM settlements")
        db.execute("DELETE FROM periods")
        db.commit()
        return redirect("/history")
    today = today_iso()
    frm = request.args.get("from") or today[:8] + "01"
    to = request.args.get("to") or today
    cid = request.args.get("cid", type=int)
    customers = db.execute("SELECT * FROM customers").fetchall()
    q = """SELECT p.draw_date d, p.period_no, p.special_num, c.name, b.customer_id,
                  b.bet_type, b.bet_value, b.amount, COALESCE(b.win_amount,0) win_amount
           FROM bets b JOIN periods p ON p.id=b.period_id
           JOIN customers c ON c.id=b.customer_id
           WHERE p.draw_date>=? AND p.draw_date<=?"""
    params = [frm, to]
    if cid:
        q += " AND b.customer_id=?"
        params.append(cid)
    q += " ORDER BY p.draw_date, c.name"
    raw = db.execute(q, params).fetchall()
    grouped = {}
    for b in raw:
        key = (b["d"], b["period_no"], b["customer_id"], b["name"], b["special_num"])
        agg = grouped.setdefault(key, {"bet": 0, "win": 0, "sp_stake": 0})
        agg["bet"] += b["amount"] or 0
        agg["win"] += b["win_amount"] or 0
        agg["sp_stake"] += stake_on_special(b["bet_type"], b["bet_value"], b["amount"] or 0, b["special_num"])
    rows = []
    for (d, pno, _cid, name, sp), v in grouped.items():
        rows.append({
            "d": d, "period_no": pno, "name": name, "special": sp,
            "bet": v["bet"], "win": v["win"], "net": v["bet"] - v["win"],
            "sp_stake": round(v["sp_stake"], 2),
        })
    rows.sort(key=lambda r: (r["d"], r["name"]))
    sum_bet = sum(r["bet"] for r in rows)
    sum_win = sum(r["win"] for r in rows)
    sum_net = sum_bet - sum_win
    sum_comm = round(sum_bet * COMMISSION_RATE, 2)

    byc, daily = {}, {}
    for r in rows:
        x = byc.setdefault(r["name"], {"bet": 0, "win": 0, "net": 0})
        x["bet"] += r["bet"]
        x["win"] += r["win"]
        x["net"] += r["net"]
        d = daily.setdefault(r["d"], {"bet": 0, "win": 0, "net": 0})
        d["bet"] += r["bet"]
        d["win"] += r["win"]
        d["net"] += r["net"]
    monthly = {}
    for d, v in daily.items():
        m = d[:7]
        y = monthly.setdefault(m, {"bet": 0, "win": 0, "net": 0})
        y["bet"] += v["bet"]
        y["win"] += v["win"]
        y["net"] += v["net"]

    def tbl(title, head, body_html):
        return f'<div class="card" style="padding:0"><div style="padding:10px 12px;font-weight:600">{title}</div><table><thead><tr>{head}</tr></thead><tbody>{body_html}</tbody></table></div>'

    cust_tr = "".join(
        f"<tr><td>{n}</td><td>¥{money(v['bet'])}</td><td>¥{money(v['win'])}</td><td>¥{money(v['net'])}</td></tr>"
        for n, v in byc.items()
    )
    day_tr = "".join(
        f"<tr><td>{d}</td><td>¥{money(v['bet'])}</td><td>¥{money(v['win'])}</td><td>¥{money(v['net'])}</td>"
        f"<td>¥{money(round(v['bet']*COMMISSION_RATE,2))}</td>"
        f"<td><a href='/?date={d}'>补录/修改</a></td></tr>"
        for d, v in sorted(daily.items())
    )
    mon_tr = "".join(
        f"<tr><td>{m}</td><td>¥{money(v['bet'])}</td><td>¥{money(v['win'])}</td><td>¥{money(v['net'])}</td>"
        f"<td>¥{money(round(v['bet']*COMMISSION_RATE,2))}</td></tr>"
        for m, v in sorted(monthly.items())
    )
    det = "".join(
        f"<tr><td>{r['d']}</td><td>{r['period_no']}</td><td>{r['name']}</td>"
        f"<td>{pad2(r['special']) if r['special'] else '—'}</td>"
        f"<td>¥{money(r['sp_stake'])}</td>"
        f"<td>¥{money(r['bet'])}</td><td>¥{money(r['win'])}</td><td>¥{money(r['net'])}</td></tr>"
        for r in rows
    )
    opts = '<option value="">全部客户</option>' + "".join(
        f'<option value="{c["id"]}" {"selected" if cid==c["id"] else ""}>{c["name"]}</option>' for c in customers
    )
    body = f"""<h1>历史查询</h1>
    <form class="card" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      <input type="date" name="from" value="{frm}" onchange="this.form.submit()">
      <input type="date" name="to" value="{to}" onchange="this.form.submit()">
      <select name="cid" onchange="this.form.submit()">{opts}</select>
      <a class="btn btn-o" href="/history?from={today}&to={today}{('&cid='+str(cid)) if cid else ''}">今天</a>
      <a class="btn btn-o" href="/history?from={today[:8]+'01'}&to={today}{('&cid='+str(cid)) if cid else ''}">本月</a>
    </form>
    <div class="stat">
      <div class="b"><div class="l">区间总押注</div><div class="v" style="color:var(--accent)">¥{money(sum_bet)}</div></div>
      <div class="b"><div class="l">区间总中奖</div><div class="v" style="color:var(--ok)">¥{money(sum_win)}</div></div>
      <div class="b"><div class="l">区间盈亏</div><div class="v">¥{money(sum_net)}</div></div>
      <div class="b"><div class="l">区间佣金 3%</div><div class="v" style="color:var(--warn)">¥{money(sum_comm)}</div></div>
    </div>
    <div class="card noprint">
      <b>数据维护</b>
      <p class="muted" style="margin:6px 0 10px">补录或修改：点某日「补录/修改」，或到押注入录页手动选日期。退出页面会自动保存。</p>
      <a class="btn btn-s" href="/save-now">一键保存数据</a>
      <form method="post" style="display:inline" onsubmit="return confirm('清除全部历史押注与结算？客户保留。')">
        <button class="btn btn-d" name="action" value="clear">一键清除历史数据</button></form>
    </div>
    {tbl("按客户汇总","<th>客户</th><th>押注</th><th>中奖</th><th>盈亏</th>", cust_tr)}
    {tbl("按日汇总（含佣金）","<th>日期</th><th>押注</th><th>中奖</th><th>盈亏</th><th>佣金3%</th><th></th>", day_tr)}
    {tbl("按月汇总（含佣金）","<th>月份</th><th>押注</th><th>中奖</th><th>盈亏</th><th>佣金3%</th>", mon_tr)}
    {tbl("明细","<th>日期</th><th>期号</th><th>客户</th><th>开奖号码</th><th>该号押注</th><th>总押注</th><th>中奖</th><th>盈亏</th>", det)}
    """
    return page("历史查询", body, "hist")

# ---------- 打印 ----------
@app.route("/print")
@login_required
def print_bill():
    db = get_db()
    today = today_iso()
    month = request.args.get("month") or today[:7]
    frm = request.args.get("from") or month + "-01"
    to = request.args.get("to") or today
    if request.args.get("month") and not request.args.get("from"):
        y, m = map(int, month.split("-"))
        import calendar
        last = calendar.monthrange(y, m)[1]
        frm = f"{month}-01"
        to = f"{month}-{last:02d}"
    cid = request.args.get("cid", type=int)
    customers = db.execute("SELECT * FROM customers").fetchall()
    q = """SELECT p.draw_date d, p.period_no, p.special_num, c.name, b.customer_id,
                  b.bet_type, b.bet_value, b.amount, COALESCE(b.win_amount,0) win_amount
           FROM bets b JOIN periods p ON p.id=b.period_id
           JOIN customers c ON c.id=b.customer_id
           WHERE p.draw_date>=? AND p.draw_date<=?"""
    params = [frm, to]
    if cid:
        q += " AND b.customer_id=?"
        params.append(cid)
    raw = db.execute(q, params).fetchall()
    grouped = {}
    for b in raw:
        key = (b["d"], b["period_no"], b["name"], b["special_num"])
        agg = grouped.setdefault(key, {"bet": 0, "win": 0, "sp_stake": 0})
        agg["bet"] += b["amount"] or 0
        agg["win"] += b["win_amount"] or 0
        agg["sp_stake"] += stake_on_special(b["bet_type"], b["bet_value"], b["amount"] or 0, b["special_num"])
    rows = []
    for (d, pno, name, sp), v in grouped.items():
        rows.append({
            "d": d, "period_no": pno, "name": name, "special": sp,
            "bet": v["bet"], "win": v["win"], "net": v["bet"] - v["win"],
            "sp_stake": round(v["sp_stake"], 2),
        })
    rows.sort(key=lambda r: (r["d"], r["name"]))
    sb = sum(r["bet"] for r in rows)
    sw = sum(r["win"] for r in rows)
    sn = sb - sw
    tr = "".join(
        f"<tr><td>{r['d']}</td><td>{r['name']}</td>"
        f"<td>{pad2(r['special']) if r['special'] else '—'}</td>"
        f"<td>¥{money(r['sp_stake'])}</td>"
        f"<td>¥{money(r['bet'])}</td><td>¥{money(r['win'])}</td>"
        f"<td>{'应收' if r['net']>=0 else '应付'} ¥{money(abs(r['net']))}</td></tr>"
        for r in rows
    )
    opts = '<option value="">全部客户</option>' + "".join(
        f'<option value="{c["id"]}" {"selected" if cid==c["id"] else ""}>{c["name"]}</option>' for c in customers
    )
    who = next((c["name"] for c in customers if c["id"] == cid), "全部客户") if cid else "全部客户"
    body = f"""
    <form class="card noprint" style="display:flex;gap:8px;flex-wrap:wrap;align-items:end">
      <div>客户<br><select name="cid">{opts}</select></div>
      <div>月份<br><input type="month" name="month" value="{month}"></div>
      <div>开始<br><input type="date" name="from" value="{frm}"></div>
      <div>结束<br><input type="date" name="to" value="{to}"></div>
      <button class="btn btn-p">查询</button>
      <button class="btn btn-o" type="button" onclick="window.print()">打印对账单</button>
    </form>
    <div class="card">
      <h2 style="text-align:center">明澳彩收单对账单</h2>
      <p style="text-align:center;color:var(--muted)">{frm} 至 {to} · {who}</p>
      <table style="margin-top:16px">
        <thead><tr><th>日期</th><th>客户</th><th>开奖号码</th><th>该号押注</th><th>总押注</th><th>中奖</th><th>应收/应付</th></tr></thead>
        <tbody>{tr}</tbody>
        <tfoot><tr><th colspan="4">合计</th><th>¥{money(sb)}</th><th>¥{money(sw)}</th>
        <th>{'总应收' if sn>=0 else '总应付'} ¥{money(abs(sn))}</th></tr></tfoot>
      </table>
      <p style="text-align:center;font-size:12px;color:var(--muted);margin-top:16px">该号押注＝开奖号码上的押注金额（含各字/各包叠加）。应收=客户应付庄家；应付=庄家应付客户。</p>
    </div>"""
    return page("打印对账单", body, "print")


# ---------- 备份 / 恢复 ----------
@app.route("/backup", methods=["GET", "POST"])
@login_required
def backup_page():
    msg = ""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    if request.method == "POST":
        act = request.form.get("action")
        if act == "make":
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = os.path.join(BACKUP_DIR, f"aocai_{ts}.db")
            get_db().commit()
            shutil.copy2(DB_PATH, dest)
            msg = f"已备份到 {os.path.basename(dest)}"
        elif act == "restore_file":
            name = request.form.get("name", "")
            path = os.path.join(BACKUP_DIR, os.path.basename(name))
            if os.path.isfile(path) and path.endswith(".db"):
                _restore_db(path)
                msg = f"已从 {os.path.basename(path)} 恢复"
            else:
                msg = "找不到该备份文件"
        elif act == "restore_upload":
            f = request.files.get("file")
            if not f or not f.filename:
                msg = "请选择备份文件"
            else:
                tmp = os.path.join(BACKUP_DIR, "_upload_tmp.db")
                f.save(tmp)
                try:
                    chk = sqlite3.connect(tmp)
                    chk.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    chk.close()
                    _restore_db(tmp)
                    msg = "已从上传文件恢复"
                except Exception:
                    msg = "文件不是有效的数据库备份"
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
        elif act == "del_backup":
            name = request.form.get("name", "")
            path = os.path.join(BACKUP_DIR, os.path.basename(name))
            if os.path.isfile(path) and path.endswith(".db") and not os.path.basename(path).startswith("_"):
                try:
                    os.remove(path)
                    msg = f"已删除备份 {os.path.basename(path)}"
                except OSError:
                    msg = "删除失败，请检查文件是否被占用"
            else:
                msg = "找不到该备份文件"
    files = sorted(
        [fn for fn in os.listdir(BACKUP_DIR) if fn.endswith(".db") and not fn.startswith("_")],
        key=lambda fn: os.path.getmtime(os.path.join(BACKUP_DIR, fn)),
        reverse=True,
    )

    def fmt_backup_time(fn: str) -> str:
        m = re.match(r"aocai_(\d{8})_(\d{6})\.db$", fn)
        if m:
            try:
                return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        try:
            return datetime.fromtimestamp(os.path.getmtime(os.path.join(BACKUP_DIR, fn))).strftime("%Y-%m-%d %H:%M:%S")
        except OSError:
            return "—"

    rows = "".join(
        f"""<tr><td>{fn}</td><td>{fmt_backup_time(fn)}</td>
        <td>
          <a class="btn btn-o" href="/backup/download/{fn}">下载</a>
          <form method="post" style="display:inline" onsubmit="return confirm('用此备份覆盖当前数据？')">
            <input type="hidden" name="action" value="restore_file">
            <input type="hidden" name="name" value="{fn}">
            <button class="btn btn-p">恢复此备份</button>
          </form>
          <form method="post" style="display:inline" onsubmit="return confirm('确定删除备份 {fn}？')">
            <input type="hidden" name="action" value="del_backup">
            <input type="hidden" name="name" value="{fn}">
            <button class="btn btn-d">删除</button>
          </form>
        </td></tr>"""
        for fn in files
    ) or "<tr><td colspan=3>暂无备份</td></tr>"
    body = f"""<h2>数据备份与恢复</h2>
    {f'<p class="tip">{msg}</p>' if msg else ''}
    <div class="card">
      <form method="post" style="display:inline">
        <button class="btn btn-s" name="action" value="make">立即备份当前数据</button>
      </form>
      <a class="btn btn-o" href="/backup/download-current" style="display:inline-block;line-height:36px;text-decoration:none">下载当前数据库</a>
      <p style="font-size:12px;color:var(--muted);margin-top:8px">备份保存在程序目录 backups 文件夹，可拷到U盘。</p>
    </div>
    <div class="card">
      <b>从文件恢复</b>
      <form method="post" enctype="multipart/form-data" style="margin-top:8px" onsubmit="return confirm('恢复将覆盖当前全部数据，确定？')">
        <input type="hidden" name="action" value="restore_upload">
        <input type="file" name="file" accept=".db">
        <button class="btn btn-p">上传并恢复</button>
      </form>
    </div>
    <div class="card" style="padding:0">
      <div style="padding:10px 12px;font-weight:600">已有备份</div>
      <table><thead><tr><th>文件</th><th>备份时间</th><th>操作</th></tr></thead><tbody>{rows}</tbody></table>
    </div>"""
    return page("备份恢复", body, "bak")


def _restore_db(src: str):
    db = g.pop("db", None)
    if db:
        db.close()
    shutil.copy2(src, DB_PATH)


@app.route("/backup/download-current")
@login_required
def backup_download_current():
    get_db().commit()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(DB_PATH, as_attachment=True, download_name=f"aocai_{ts}.db")


@app.route("/backup/download/<name>")
@login_required
def backup_download_one(name):
    path = os.path.join(BACKUP_DIR, os.path.basename(name))
    if not os.path.isfile(path):
        return redirect("/backup")
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))

if __name__ == "__main__":
    init_db()
    print("明澳彩收单独立版  http://127.0.0.1:9000")
    print("超级用户 admin / gjxing1111")
    try:
        webbrowser.open("http://127.0.0.1:9000/login")
    except Exception:
        pass
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "9000"))
    app.run(host=host, port=port, debug=False)
