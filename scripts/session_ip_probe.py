"""微信会话失效根因判定 — 只读探针（临时诊断，实验结束后可删）

每次运行记录一行到 output/wechat_session_probe.csv：
  时间戳 | 直连出口IP(国内目标,禁代理) | IP相对上次是否变化 | 最近一次keepalive判活 | 当前LOGIN_REQUIRED条数

目的：区分「登录一天就失效」的两个候选根因——
  ① 住宅动态IP每日轮换  → 会话失效紧跟 IP 变化
  ② 微信服务端~24h硬上限 → IP 全程不变却仍失效

刻意约束（避免干扰生产）：
  - 不启动 Playwright / 不触碰 wechat_state.json（不与真实 keepalive/上传抢会话文件）
  - 直连 IP 用 urllib 禁代理 + 查【国内】回显服务（Clash 对 CN 目标走 DIRECT，等同微信视角）
  - 会话判活信号复用既有 keepalive 写入 dashboard.log 的结论，不另起浏览器

# Modification History
| Version | Date       | Author          | Description                                         |
|---------|------------|-----------------|-----------------------------------------------------|
| 1.0.0   | 2026-06-24 | Claude_Opus_4.8 | 临时诊断探针：直连IP + keepalive判活，定位会话失效根因 |
| 1.1.0   | 2026-07-10 | Codex             | 出口 IP 变化时推送 Telegram 告警，提前暴露可能触发微信风控的网络漂移 |
"""
import csv
import datetime
import re
import urllib.request
from pathlib import Path

import sys

_PRJ = Path(__file__).parent.parent
_CSV = _PRJ / "output" / "wechat_session_probe.csv"
_DASH = _PRJ / "output" / "dashboard.log"
_DB = _PRJ / "output" / "pipeline.db"


def _send_ip_change_alert(old_ip: str, new_ip: str) -> None:
    """出口 IP 变化时告警，不修改微信 state。"""
    try:
        sys.path.insert(0, str(_PRJ / "src"))
        from config.settings import settings
        import requests
        token = (settings.telegram_bot_token or "").strip()
        chat_id = (settings.active_telegram_chat_id or "").strip()
        if token and chat_id:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": f"⚠️ 微信出口 IP 变化：{old_ip} → {new_ip}\n会话可能被风控，请关注 keepalive 状态。"},
                timeout=10,
            )
    except Exception as exc:
        print(f"IP change alert failed: {exc}")

# 国内 IP 回显服务（Clash 对 CN 目标走 DIRECT → 反映微信实际看到的直连 IP）
_CN_IP_URLS = ["https://myip.ipip.net/", "http://cip.cc/"]
_IP_RE = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")


def get_direct_cn_ip() -> str:
    """禁用 HTTP 代理，查国内服务，取直连出口 IP。失败返回空串。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for url in _CN_IP_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
            txt = opener.open(req, timeout=10).read().decode("utf-8", "ignore")
            m = _IP_RE.search(txt)
            if m:
                return m.group(1)
        except Exception:
            continue
    return ""


def last_keepalive_verdict() -> str:
    """从 dashboard.log 反向找最近一次 keepalive 判活结论（不另起浏览器）。"""
    try:
        lines = _DASH.read_text(errors="ignore").splitlines()
    except Exception:
        return "unknown"
    for ln in reversed(lines):
        if "Keepalive" not in ln:
            continue
        if "Session active" in ln:
            return "active"
        if "expired" in ln or "LOGIN_REQUIRED" in ln or "login page" in ln:
            return "expired"
    return "unknown"


def login_required_count() -> str:
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=5)
        n = con.execute(
            "SELECT count(*) FROM processed_videos WHERE status='LOGIN_REQUIRED'"
        ).fetchone()[0]
        con.close()
        return str(n)
    except Exception:
        return "?"


def prev_ip() -> str:
    try:
        rows = list(csv.reader(_CSV.open()))
        for r in reversed(rows):
            if r and re.match(r"\d{1,3}\.", r[1] if len(r) > 1 else ""):
                return r[1]
    except Exception:
        pass
    return ""


def main():
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ip = get_direct_cn_ip()
    old_ip = prev_ip()
    changed = "NEW" if (ip and old_ip and ip != old_ip) else ("" if ip else "FAIL")
    verdict = last_keepalive_verdict()
    lr = login_required_count()

    new_file = not _CSV.exists()
    with _CSV.open("a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["ts", "direct_cn_ip", "ip_changed", "keepalive", "login_required_cnt"])
        w.writerow([ts, ip, changed, verdict, lr])
    if changed == "NEW":
        _send_ip_change_alert(old_ip, ip)
    print(f"{ts} ip={ip or 'FAIL'} changed={changed or '-'} keepalive={verdict} login_req={lr}")


if __name__ == "__main__":
    main()
