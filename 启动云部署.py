# -*- coding: utf-8 -*-
"""云部署一键启动：启动 Flask + Cloudflare Tunnel（在你的真实电脑上运行）"""
import json, os, subprocess, sys, time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.stdout.reconfigure(encoding='utf-8')

def wait_port(port, timeout=10):
    import socket
    for _ in range(timeout * 2):
        s = socket.socket()
        try:
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except OSError:
            time.sleep(0.5)
    return False

print("=" * 50)
print("  澳彩收单系统 · 云部署启动")
print("  https://www.ioss.eu.cc")
print("=" * 50)

# 1. 启动 Flask
print("\n[1/2] 启动本地服务 (127.0.0.1:5000) ...")
flask_proc = subprocess.Popen(
    [sys.executable, f"{BASE}/aocai_app.py"],
    cwd=BASE,
    stdout=open(f"{BASE}/flask.log", "a"),
    stderr=subprocess.STDOUT,
)
print(f"  Flask PID: {flask_proc.pid}")

if not wait_port(5000, 15):
    print("  ⚠️ 本地服务启动超时，请检查 flask.log")
else:
    print("  ✅ 本地服务已启动")

# 2. 启动隧道
print("\n[2/2] 启动 Cloudflare Tunnel ...")
cf = f"{BASE}/cloudflared.exe"
cfg = f"{BASE}/config.yml"
tun = subprocess.Popen(
    [cf, "tunnel", "--config", cfg, "run"],
    cwd=BASE,
    stdout=open(f"{BASE}/tunnel.log", "a"),
    stderr=subprocess.STDOUT,
)
print(f"  cloudflared PID: {tun.pid}")

time.sleep(8)
# 检查隧道是否注册
log = open(f"{BASE}/tunnel.log").read()
if "Registered tunnel connection" in log:
    print("  ✅ 隧道已连接到 Cloudflare 边缘")
    print("\n  🌐 访问地址: https://www.ioss.eu.cc")
    print("  登录: 使用你的系统账号")
else:
    print("  ⚠️ 隧道连接中，查看 tunnel.log 了解详情")

print("\n按 Ctrl+C 停止服务")
try:
    while True:
        time.sleep(60)
except KeyboardInterrupt:
    print("\n停止中...")
    tun.terminate()
    flask_proc.terminate()
