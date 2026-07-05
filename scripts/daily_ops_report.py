"""每日运维工单巡检 — 自动每天执行，推送 Telegram。

固化「每日该盯的循环项」（源自 2026-06-26 自我审查）：
  1. 发布健康：今日发布/失败数、可发队列、在途
  2. 黑名单完整性：有无已拉黑频道的视频泄漏到 PUBLISHED/可发队列（防 2026-06-25 事故复发）
  3. 微信会话：是否失效（~24h 服务端硬上限，几乎每天需重扫）
  4. 限流：discovery/rescore 的 exit-101/取不到 比例

只读巡检，不改任何状态。报告推 Telegram；同时落 output/daily_ops_report.log。

# Modification History
| Version | Date       | Author          | Description                          |
|---------|------------|-----------------|--------------------------------------|
| 1.0.0   | 2026-06-26 | Claude_Opus_4.8 | 初版：每日发布/黑名单/会话/限流巡检工单 |
| 1.1.0   | 2026-07-05 | Codex           | 接入翻译质量审计聚合摘要，纳入每日巡检 |
| 1.2.0   | 2026-07-05 | Codex           | 翻译质量摘要显示非阻断告警数，便于追踪术语一致性漂移 |
| 1.3.0   | 2026-07-05 | Codex           | 翻译质量摘要分开展示最高频告警与最高频阻断 |
| 1.4.0   | 2026-07-06 | Codex           | 翻译质量摘要展示最高频 provider-issue 组合，便于定位供应商质量问题 |
| 1.5.0   | 2026-07-06 | Codex           | 翻译质量摘要展示最终采用 provider 与采用候选告警 |
"""
from __future__ import annotations

import datetime
import sqlite3
import sys
from pathlib import Path

PRJ = Path(__file__).parent.parent
sys.path.insert(0, str(PRJ / "src"))
from config.settings import settings  # noqa: E402
from video_processing.utils.translation_quality_report import aggregate_quality_reports  # noqa: E402

_DB = PRJ / "output" / "pipeline.db"
_DASH_LOG = PRJ / "output" / "dashboard.log"
_MON_LOG = PRJ / "output" / "monitor.log"
_OUT_DIR = PRJ / "output"


def _ro_conn():
    return sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=10)


def _one(con, sql, *args):
    return con.execute(sql, args).fetchone()[0]


def format_translation_quality(summary: dict) -> str:
    """把翻译质量聚合结果格式化为 Telegram 友好的日报行。"""
    files_scanned = int(summary.get("files_scanned") or 0)
    event_count = int(summary.get("event_count") or 0)
    selected_count = int(summary.get("selected_count") or 0)
    selected_warning_count = int(summary.get("selected_warning_count") or 0)
    warning_count = int(summary.get("warning_count") or 0)
    blocked_count = int(summary.get("blocked_count") or 0)
    issue_counts = summary.get("issue_counts") or {}
    warning_issue_counts = summary.get("warning_issue_counts") or {}
    blocking_issue_counts = summary.get("blocking_issue_counts") or {}
    provider_counts = summary.get("provider_counts") or {}
    selected_provider_counts = summary.get("selected_provider_counts") or {}
    selected_warning_issue_counts = summary.get("selected_warning_issue_counts") or {}
    provider_issue_counts = summary.get("provider_issue_counts") or {}

    if files_scanned == 0:
        return "翻译质量: 暂无审计报告"

    top_issue = "无"
    if issue_counts:
        code, count = max(issue_counts.items(), key=lambda item: item[1])
        top_issue = f"{code}×{count}"

    top_warning = "无"
    if warning_issue_counts:
        code, count = max(warning_issue_counts.items(), key=lambda item: item[1])
        top_warning = f"{code}×{count}"

    top_blocking = "无"
    if blocking_issue_counts:
        code, count = max(blocking_issue_counts.items(), key=lambda item: item[1])
        top_blocking = f"{code}×{count}"

    top_provider = "无"
    if provider_counts:
        provider, count = max(provider_counts.items(), key=lambda item: item[1])
        top_provider = f"{provider}×{count}"

    top_selected_provider = "无"
    if selected_provider_counts:
        provider, count = max(selected_provider_counts.items(), key=lambda item: item[1])
        top_selected_provider = f"{provider}×{count}"

    top_selected_warning = "无"
    if selected_warning_issue_counts:
        code, count = max(selected_warning_issue_counts.items(), key=lambda item: item[1])
        top_selected_warning = f"{code}×{count}"

    top_provider_issue = "无"
    flattened_provider_issues = [
        (provider, code, count)
        for provider, issue_counts_for_provider in provider_issue_counts.items()
        for code, count in issue_counts_for_provider.items()
    ]
    if flattened_provider_issues:
        provider, code, count = max(flattened_provider_issues, key=lambda item: item[2])
        top_provider_issue = f"{provider}:{code}×{count}"

    return (
        f"翻译质量: 报告 {files_scanned} | 事件 {event_count} | "
        f"采用 {selected_count} | 采用告警 {selected_warning_count} | "
        f"告警 {warning_count} | 阻断/降级 {blocked_count} | "
        f"最高频告警 {top_warning} | 最高频阻断 {top_blocking} | "
        f"最高频错误 {top_issue} | provider {top_provider} | "
        f"采用provider {top_selected_provider} | 采用告警项 {top_selected_warning} | "
        f"provider问题 {top_provider_issue}"
    )


def collect() -> str:
    # 北京今天 00:00 ≈ UTC 前一天 16:00；用 datetime('now','-16 hours')(SQLite UTC) 对齐"今天"
    since = "datetime('now','-16 hours')"
    con = _ro_conn()

    pub = _one(con, f"SELECT count(*) FROM processed_videos WHERE status='PUBLISHED' AND updated_at>={since}")
    fail = _one(con, f"SELECT count(*) FROM processed_videos WHERE status='FAILED' AND updated_at>={since}")
    queue = _one(con, "SELECT count(*) FROM processed_videos WHERE status='PENDING' AND score>=75 AND IFNULL(source,'')!='DISCOVERY'")
    active = _one(con, "SELECT count(*) FROM processed_videos WHERE status IN ('DOWNLOADING','TRANSCRIBING','COPYWRITING','PUBLISHING')")
    login_req = _one(con, "SELECT count(*) FROM processed_videos WHERE status='LOGIN_REQUIRED'")

    # 黑名单泄漏：已拉黑频道的视频出现在 已发(今日) 或 可发队列(≥75 PENDING) = 异常
    leak = _one(con, f"""SELECT count(*) FROM processed_videos p
        JOIN recommended_channels r ON p.channel_id=r.channel_id
        WHERE r.status='BLACKLISTED'
          AND ( (p.status='PUBLISHED' AND p.updated_at>={since})
                OR (p.status='PENDING' AND p.score>=75) )""")
    con.close()

    # 微信会话：keepalive 最近判活 + LOGIN_REQUIRED
    sess = "未知"
    try:
        lines = _DASH_LOG.read_text(errors="ignore").splitlines()
        for ln in reversed(lines):
            if "Keepalive" not in ln:
                continue
            if "Session active" in ln:
                sess = "🟢 活跃"; break
            if "expired" in ln or "Redirected to login" in ln:
                sess = "🔴 已失效→需扫码"; break
    except Exception:
        pass
    if login_req > 0:
        sess = f"🔴 已失效→需扫码（{login_req} 条卡 LOGIN_REQUIRED）"

    # 限流：今日 monitor 限流跳过次数
    rl = "?"
    try:
        txt = _MON_LOG.read_text(errors="ignore")
        rl = str(txt.count("重试后仍被限流"))
    except Exception:
        pass

    try:
        translation_quality_line = format_translation_quality(aggregate_quality_reports(_OUT_DIR))
    except Exception:
        translation_quality_line = "翻译质量: 汇总失败"

    leak_line = "0 ✅" if leak == 0 else f"⚠️ {leak} 条（需立刻排查！）"
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    return (
        f"📋 <b>每日运维工单 {today}</b>\n"
        f"━━ 发布健康 ━━\n"
        f"今日发布 <b>{pub}</b> | 失败 {fail} | 可发队列(≥75) {queue} | 在途 {active}\n"
        f"━━ 黑名单完整性 ━━\n"
        f"已拉黑频道泄漏: {leak_line}\n"
        f"━━ 微信会话 ━━\n"
        f"{sess}（~24h 服务端硬上限，几乎每天需重扫）\n"
        f"━━ 限流 ━━\n"
        f"discovery 累计限流跳过(monitor.log): {rl}\n"
        f"━━ 翻译质量 ━━\n"
        f"{translation_quality_line}\n"
        f"━━ 每日须办 ━━\n"
        f"• 会话若失效→ <code>python scripts/wechat_uploader.py --login-only</code> 重扫\n"
        f"• 泄漏若&gt;0→ 立刻查 get_high_score_pending_videos 黑名单过滤是否被绕过"
    )


def push_telegram(text: str) -> bool:
    token = settings.telegram_bot_token
    chat = settings.active_telegram_chat_id or (settings.telegram_admin_ids or "").split(",")[0].strip()
    if not (token and chat):
        return False
    try:
        import urllib.request, urllib.parse, json
        data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        r = json.load(urllib.request.urlopen(req, timeout=15))
        return bool(r.get("ok"))
    except Exception as e:
        print("telegram push failed:", e)
        return False


def main():
    report = collect()
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    plain = report.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "").replace("&gt;", ">")
    print(f"[{ts}]\n{plain}\n")
    ok = push_telegram(report)
    print("telegram:", "✅ sent" if ok else "❌ not sent")


if __name__ == "__main__":
    main()
