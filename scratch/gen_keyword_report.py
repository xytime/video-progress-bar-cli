#!/usr/bin/env python3
"""
[演示脚本] 动态热词注入 — 多维度 HTML 报表（含 YouTube 实际数据）
只读演示，不修改任何生产数据。
# [Claude_Sonnet_4.6_Thinking_planning]
"""
import sys, json, time, subprocess, httpx
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus

# ── HN 配置 ──────────────────────────────────────────────────────────────────
HN_TOPSTORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL       = "https://hacker-news.firebaseio.com/v0/item/{}.json"

TECH_SIGNALS = [
    "AI", "LLM", "GPT", "Claude", "Gemini", "model", "agent",
    "startup", "funding", "open source", "framework", "API",
    "machine learning", "deep learning", "research", "paper",
]

STATIC_KEYWORDS = ["AI interview", "tech keynote 2026", "business podcast", "founder speech"]

# ── 翻译 ──────────────────────────────────────────────────────────────────────
def translate_zh(text: str) -> str:
    try:
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source="auto", target="zh-CN").translate(text[:500]) or text
    except Exception as e:
        return f"[翻译失败: {e}]"

# ── yt-dlp 拉取 Top1 搜索结果 ─────────────────────────────────────────────────
def fetch_yt_top1(keyword: str) -> dict:
    """用 yt-dlp 搜索 keyword，返回第 1 条结果的元数据"""
    cmd = [
        "yt-dlp",
        f"ytsearch1:{keyword}",
        "--print", "%(id)s|%(title)s|%(view_count)s|%(like_count)s|%(duration)s|%(upload_date)s",
        "--no-warnings",
        "--cookies-from-browser", "safari",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        line = res.stdout.strip().split("\n")[0] if res.stdout.strip() else ""
        parts = line.split("|")
        if len(parts) < 4:
            return {}
        vid_id   = parts[0].strip()
        title    = parts[1].strip()
        views    = int(parts[2]) if parts[2].isdigit() else None
        likes    = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
        duration = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else None
        upload   = parts[5].strip() if len(parts) > 5 else ""
        like_rate = round(likes / views * 100, 2) if views and likes and views > 0 else None
        return {
            "vid_id": vid_id,
            "yt_title": title,
            "views": views,
            "likes": likes,
            "like_rate": like_rate,
            "duration": duration,
            "upload_date": upload,
            "yt_url": f"https://www.youtube.com/watch?v={vid_id}",
            "thumb_url": f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg",
        }
    except Exception as e:
        return {"error": str(e)}

# ── 数字格式化 ────────────────────────────────────────────────────────────────
def fmt_num(n):
    if n is None: return "—"
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}K"
    return str(n)

def fmt_dur(s):
    if not s: return "—"
    m, sec = divmod(s, 60)
    h, m   = divmod(m, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

# ── Step 1: 拉取 HN ───────────────────────────────────────────────────────────
print("① 拉取 HackerNews Top Stories…", flush=True)
t0 = time.time()
ids = httpx.get(HN_TOPSTORIES_URL, timeout=10).json()[:30]
hn_rows = []
with httpx.Client(timeout=5) as client:
    for rank, sid in enumerate(ids, 1):
        try:
            item  = client.get(HN_ITEM_URL.format(sid)).json()
            title = item.get("title", "")
            signal = next((s for s in TECH_SIGNALS if s.lower() in title.lower()), None)
            if signal:
                ts = item.get("time", 0)
                age_h = round((time.time() - ts) / 3600, 1) if ts else None
                post_time = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M") if ts else "—"
                keyword = " ".join(title.split()[:5])
                hn_rows.append({
                    "hn_rank": rank, "hn_id": sid,
                    "hn_score": item.get("score", 0),
                    "comments": item.get("descendants", 0),
                    "signal": signal, "title": title,
                    "keyword": keyword, "age_h": age_h, "post_time": post_time,
                    "hn_url": f"https://news.ycombinator.com/item?id={sid}",
                })
        except Exception:
            continue
hn_elapsed = round(time.time() - t0, 1)
print(f"   命中 {len(hn_rows)} 条  ({hn_elapsed}s)", flush=True)

# ── Step 2: 逐条拉 YouTube Top1 + 翻译 ────────────────────────────────────────
print(f"\n② 拉取每个关键词的 YouTube Top1 数据（共 {len(hn_rows)} 条）…", flush=True)
rows = []
for i, r in enumerate(hn_rows, 1):
    print(f"   [{i}/{len(hn_rows)}] {r['keyword'][:50]}", flush=True)
    yt  = fetch_yt_top1(r["keyword"])
    zh  = translate_zh(r["title"])
    yt_zh = translate_zh(yt.get("yt_title", "")) if yt.get("yt_title") else "—"
    rows.append({**r, **yt, "zh_title": zh, "yt_zh_title": yt_zh})

print(f"\n③ 同样处理静态关键词…", flush=True)
static_rows_data = []
for kw in STATIC_KEYWORDS:
    print(f"   {kw}", flush=True)
    yt  = fetch_yt_top1(kw)
    yt_zh = translate_zh(yt.get("yt_title", "")) if yt.get("yt_title") else "—"
    static_rows_data.append({"keyword": kw, **yt, "yt_zh_title": yt_zh})

total_elapsed = round(time.time() - t0, 1)
print(f"\n✓ 全部完成  总耗时 {total_elapsed}s", flush=True)

# ══════════════════════════════════════════════════════════════════════════════
# HTML 生成
# ══════════════════════════════════════════════════════════════════════════════
now_str = datetime.now(tz=timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M CST")

def score_cls(s):
    if s >= 400: return "s-hot"
    if s >= 150: return "s-warm"
    if s >= 50:  return "s-mid"
    return "s-cool"

def age_cls(h):
    if h is None: return ""
    if h <= 6:  return "a-fresh"
    if h <= 24: return "a-today"
    return "a-old"

def like_cls(r):
    if r is None: return ""
    if r >= 5:  return "lr-great"
    if r >= 3:  return "lr-ok"
    if r >= 1:  return "lr-low"
    return "lr-poor"

def views_cls(v):
    if v is None: return ""
    if v >= 1_000_000: return "v-mega"
    if v >= 100_000:   return "v-big"
    if v >= 10_000:    return "v-mid"
    return "v-small"

# ── Dynamic rows ─────────────────────────────────────────────────────────────
dyn_rows_html = ""
for r in rows:
    sc  = score_cls(r["hn_score"])
    ac  = age_cls(r.get("age_h"))
    lc  = like_cls(r.get("like_rate"))
    vc  = views_cls(r.get("views"))
    age_label = f"{r['age_h']}h 前" if r.get("age_h") is not None else "—"
    like_str  = f"{r['like_rate']:.2f}%" if r.get("like_rate") is not None else "—"
    views_str = fmt_num(r.get("views"))
    dur_str   = fmt_dur(r.get("duration"))
    err_note  = f'<span class="err-note">({r["error"]})</span>' if r.get("error") else ""

    yt_thumb = ""
    if r.get("vid_id"):
        # [Claude_Sonnet_4.6_Thinking_planning] 缩略图包裹 <a> 使整个图片可点击
        yt_thumb = f'<a href="{r["yt_url"]}" target="_blank" class="thumb-link"><img src="{r["thumb_url"]}" class="thumb" loading="lazy"><span class="thumb-play">▶</span></a>'

    yt_title_block = "—"
    if r.get("yt_title"):
        yt_title_block = f'''
          <a href="{r['yt_url']}" target="_blank" class="yt-title-link">{r['yt_title'][:60]}{"…" if len(r.get('yt_title',''))>60 else ""}</a>
          <div class="zh-title">{r.get("yt_zh_title","")}</div>
          <a href="{r['yt_url']}" target="_blank" class="watch-inline-btn">🎬 点击观看视频</a>'''

    dyn_rows_html += f"""
    <tr>
      <td class="col-rank">#{r['hn_rank']}</td>
      <td class="col-title">
        <a href="{r['hn_url']}" target="_blank" class="hn-title-link">{r['title'][:70]}{"…" if len(r['title'])>70 else ""}</a>
        <div class="zh-title">{r.get('zh_title','')}</div>
      </td>
      <td><span class="score-badge {sc}">{r['hn_score']}</span></td>
      <td class="col-num">{r['comments']}</td>
      <td><span class="signal-tag">{r['signal']}</span></td>
      <td class="col-age {ac}">{age_label}</td>
      <td class="col-thumb">{yt_thumb}</td>
      <td class="col-yt-title">{yt_title_block}{err_note}</td>
      <td class="col-num {vc}">{views_str}</td>
      <td class="col-lr {lc}">{like_str}</td>
      <td class="col-dur">{dur_str}</td>
      <td class="col-yt">
        {'<a href="' + r["yt_url"] + '" target="_blank" class="yt-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M23.5 6.2a3 3 0 0 0-2.1-2.1C19.5 3.6 12 3.6 12 3.6s-7.5 0-9.4.5A3 3 0 0 0 .5 6.2 31.5 31.5 0 0 0 0 12a31.5 31.5 0 0 0 .5 5.8 3 3 0 0 0 2.1 2.1c1.9.5 9.4.5 9.4.5s7.5 0 9.4-.5a3 3 0 0 0 2.1-2.1A31.5 31.5 0 0 0 24 12a31.5 31.5 0 0 0-.5-5.8zM9.7 15.5V8.5l6.3 3.5-6.3 3.5z"/></svg> 观看</a>' if r.get("vid_id") else '<a href="https://www.youtube.com/results?search_query=' + quote_plus(r['keyword']) + '" target="_blank" class="yt-btn-search">搜索</a>'}
      </td>
    </tr>"""

# ── Static rows ──────────────────────────────────────────────────────────────
stat_rows_html = ""
for r in static_rows_data:
    lc = like_cls(r.get("like_rate"))
    vc = views_cls(r.get("views"))
    like_str  = f"{r['like_rate']:.2f}%" if r.get("like_rate") is not None else "—"
    views_str = fmt_num(r.get("views"))
    dur_str   = fmt_dur(r.get("duration"))

    yt_thumb = f'<a href="{r["yt_url"]}" target="_blank" class="thumb-link"><img src="{r["thumb_url"]}" class="thumb" loading="lazy"><span class="thumb-play">▶</span></a>' if r.get("vid_id") else ""
    yt_title_block = "—"
    if r.get("yt_title"):
        yt_title_block = f'''
          <a href="{r['yt_url']}" target="_blank" class="yt-title-link">{r['yt_title'][:60]}{"…" if len(r.get('yt_title',''))>60 else ""}</a>
          <div class="zh-title">{r.get("yt_zh_title","")}</div>
          <a href="{r['yt_url']}" target="_blank" class="watch-inline-btn">🎬 点击观看视频</a>'''

    stat_rows_html += f"""
    <tr class="static-row">
      <td class="col-rank">—</td>
      <td class="col-title"><span class="static-badge">STATIC</span> {r['keyword']}</td>
      <td><span class="score-badge s-cool">—</span></td>
      <td class="col-num">—</td>
      <td><span class="signal-tag tag-static">固定</span></td>
      <td class="col-age">永久</td>
      <td class="col-thumb">{yt_thumb}</td>
      <td class="col-yt-title">{yt_title_block}</td>
      <td class="col-num {vc}">{views_str}</td>
      <td class="col-lr {lc}">{like_str}</td>
      <td class="col-dur">{dur_str}</td>
      <td class="col-yt">
        {'<a href="' + r["yt_url"] + '" target="_blank" class="yt-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M23.5 6.2a3 3 0 0 0-2.1-2.1C19.5 3.6 12 3.6 12 3.6s-7.5 0-9.4.5A3 3 0 0 0 .5 6.2 31.5 31.5 0 0 0 0 12a31.5 31.5 0 0 0 .5 5.8 3 3 0 0 0 2.1 2.1c1.9.5 9.4.5 9.4.5s7.5 0 9.4-.5a3 3 0 0 0 2.1-2.1A31.5 31.5 0 0 0 24 12a31.5 31.5 0 0 0-.5-5.8zM9.7 15.5V8.5l6.3 3.5-6.3 3.5z"/></svg> 观看</a>' if r.get("vid_id") else "—"}
      </td>
    </tr>"""

# ── Stats ─────────────────────────────────────────────────────────────────────
avg_views = round(sum(r["views"] for r in rows if r.get("views")) / max(1, sum(1 for r in rows if r.get("views"))))
avg_lr    = round(sum(r["like_rate"] for r in rows if r.get("like_rate")) / max(1, sum(1 for r in rows if r.get("like_rate"))), 2)
max_views = max((r.get("views") or 0) for r in rows)
max_lr    = max((r.get("like_rate") or 0) for r in rows)

html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>动态热词注入 — 效果展示</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
  :root{{
    --bg:#0d1117;--bg2:#161b22;--bg3:#21262d;
    --border:#30363d;--text:#e6edf3;--muted:#8b949e;
    --accent:#58a6ff;--green:#3fb950;--yellow:#d29922;
    --orange:#f0883e;--red:#ff7b72;--purple:#bc8cff;--yt:#ff4444;
  }}
  body{{background:var(--bg);color:var(--text);font-family:'Inter',system-ui,sans-serif;font-size:13px;line-height:1.5;padding:28px 20px 60px}}
  .page-header{{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:24px;flex-wrap:wrap;gap:12px}}
  h1{{font-size:20px;font-weight:700;background:linear-gradient(135deg,#58a6ff 0%,#bc8cff 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
  .subtitle{{color:var(--muted);font-size:12px;margin-top:3px}}
  .meta-chips{{display:flex;gap:6px;flex-wrap:wrap;align-items:center}}
  .chip{{background:var(--bg3);border:1px solid var(--border);border-radius:20px;padding:3px 10px;font-size:11px;color:var(--muted)}}
  .chip strong{{color:var(--text)}}
  .stats-bar{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-bottom:24px}}
  .stat-card{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:14px 16px}}
  .stat-label{{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px}}
  .stat-value{{font-size:22px;font-weight:700;margin-top:4px}}
  .v-blue{{color:var(--accent)}}.v-green{{color:var(--green)}}.v-purple{{color:var(--purple)}}.v-orange{{color:var(--orange)}}.v-red{{color:var(--red)}}
  .section-title{{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.8px;margin:24px 0 8px;display:flex;align-items:center;gap:8px}}
  .section-title::after{{content:"";flex:1;height:1px;background:var(--border)}}
  .table-wrap{{border:1px solid var(--border);border-radius:10px;overflow:hidden;overflow-x:auto}}
  table{{width:100%;border-collapse:collapse;white-space:nowrap}}
  thead th{{background:var(--bg3);color:var(--muted);font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;padding:9px 12px;text-align:left;border-bottom:1px solid var(--border);position:sticky;top:0}}
  tbody tr{{border-bottom:1px solid var(--border);transition:background .12s}}
  tbody tr:last-child{{border-bottom:none}}
  tbody tr:hover{{background:rgba(88,166,255,.06)}}
  tbody td{{padding:10px 12px;vertical-align:middle}}
  .col-rank{{width:48px;color:var(--muted);font-size:11px}}
  .col-title{{max-width:260px;white-space:normal;min-width:200px}}
  .col-yt-title{{max-width:240px;white-space:normal;min-width:180px}}
  .col-num{{width:72px;text-align:right;font-variant-numeric:tabular-nums;color:var(--muted)}}
  .col-age{{width:72px;font-size:11px}}
  .col-thumb{{width:100px}}
  .col-lr{{width:76px;text-align:right;font-weight:600;font-variant-numeric:tabular-nums}}
  .col-dur{{width:64px;color:var(--muted);font-size:11px}}
  .col-yt{{width:80px}}
  .hn-title-link{{color:var(--text);text-decoration:none;font-size:12px;font-weight:500;line-height:1.4}}
  .hn-title-link:hover{{color:var(--accent);text-decoration:underline}}
  .yt-title-link{{color:var(--accent);text-decoration:none;font-size:12px;font-weight:500;line-height:1.4;display:block}}
  .yt-title-link:hover{{text-decoration:underline}}
  .zh-title{{color:var(--muted);font-size:11px;margin-top:3px;white-space:normal;line-height:1.3}}
  .thumb{{width:90px;height:51px;object-fit:cover;border-radius:5px;border:1px solid var(--border);display:block;transition:opacity .15s}}
  .thumb-link{{position:relative;display:inline-block;cursor:pointer}}
  .thumb-link:hover .thumb{{opacity:.8}}
  .thumb-play{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:22px;opacity:0;transition:opacity .15s;pointer-events:none}}
  .thumb-link:hover .thumb-play{{opacity:1}}
  .watch-inline-btn{{display:inline-flex;align-items:center;margin-top:5px;padding:3px 8px;border-radius:4px;background:rgba(255,68,68,.15);color:var(--yt);border:1px solid rgba(255,68,68,.3);text-decoration:none;font-size:11px;font-weight:500;transition:background .12s}}
  .watch-inline-btn:hover{{background:rgba(255,68,68,.3)}}
  .score-badge{{display:inline-block;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600}}
  .s-hot{{background:rgba(255,123,114,.15);color:#ff7b72;border:1px solid rgba(255,123,114,.3)}}
  .s-warm{{background:rgba(240,136,62,.15);color:#f0883e;border:1px solid rgba(240,136,62,.3)}}
  .s-mid{{background:rgba(210,153,34,.15);color:#d29922;border:1px solid rgba(210,153,34,.3)}}
  .s-cool{{background:rgba(139,148,158,.1);color:#8b949e;border:1px solid rgba(139,148,158,.2)}}
  .signal-tag{{display:inline-block;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:500;background:rgba(188,140,255,.12);color:var(--purple);border:1px solid rgba(188,140,255,.25)}}
  .tag-static{{background:rgba(139,148,158,.1);color:var(--muted);border-color:rgba(139,148,158,.2)}}
  .a-fresh{{color:var(--green);font-weight:500}}
  .a-today{{color:var(--yellow)}}
  .a-old{{color:var(--muted)}}
  .lr-great{{color:#3fb950}}.lr-ok{{color:#d29922}}.lr-low{{color:#f0883e}}.lr-poor{{color:#ff7b72}}
  .v-mega{{color:#bc8cff;font-weight:600}}.v-big{{color:#58a6ff;font-weight:500}}.v-mid{{color:var(--text)}}.v-small{{color:var(--muted)}}
  .yt-btn{{display:inline-flex;align-items:center;gap:5px;padding:4px 9px;border-radius:5px;background:rgba(255,68,68,.12);color:var(--yt);border:1px solid rgba(255,68,68,.25);text-decoration:none;font-size:11px;font-weight:500;transition:background .12s;white-space:nowrap}}
  .yt-btn:hover{{background:rgba(255,68,68,.25)}}
  .yt-btn-search{{display:inline-flex;align-items:center;gap:5px;padding:4px 9px;border-radius:5px;background:rgba(88,166,255,.1);color:var(--accent);border:1px solid rgba(88,166,255,.2);text-decoration:none;font-size:11px;font-weight:500;white-space:nowrap}}
  .static-row{{opacity:.7}}
  .static-badge{{display:inline-block;font-size:9px;font-weight:600;padding:1px 5px;border-radius:3px;background:rgba(139,148,158,.15);color:var(--muted);margin-right:4px;vertical-align:middle}}
  .err-note{{color:var(--red);font-size:10px}}
  .legend{{display:flex;gap:16px;flex-wrap:wrap;margin-top:16px;font-size:11px;color:var(--muted)}}
  .legend-item{{display:flex;align-items:center;gap:5px}}
  .dot{{width:7px;height:7px;border-radius:50%}}
  .footer{{margin-top:36px;padding-top:14px;border-top:1px solid var(--border);font-size:11px;color:var(--muted);display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px}}
</style>
</head>
<body>

<div class="page-header">
  <div>
    <h1>🔥 动态热词注入 — 多维度效果展示</h1>
    <p class="subtitle">HackerNews 热点 × YouTube 实际数据 × 中文翻译 · 只读演示，不影响生产</p>
  </div>
  <div class="meta-chips">
    <div class="chip">📅 <strong>{now_str}</strong></div>
    <div class="chip">HN 采样 <strong>Top 30</strong></div>
    <div class="chip">⏱ 总耗时 <strong>{total_elapsed}s</strong></div>
  </div>
</div>

<div class="stats-bar">
  <div class="stat-card"><div class="stat-label">静态词 (旧方案)</div><div class="stat-value v-purple">{len(STATIC_KEYWORDS)}</div></div>
  <div class="stat-card"><div class="stat-label">动态词 (今日 HN)</div><div class="stat-value v-orange">{len(rows)}</div></div>
  <div class="stat-card"><div class="stat-label">合并总词数</div><div class="stat-value v-green">{len(rows)+len(STATIC_KEYWORDS)}</div></div>
  <div class="stat-card"><div class="stat-label">搜索覆盖提升</div><div class="stat-value v-blue">+{round(len(rows)/len(STATIC_KEYWORDS)*100)}%</div></div>
  <div class="stat-card"><div class="stat-label">动态词均观看数</div><div class="stat-value v-blue">{fmt_num(avg_views)}</div></div>
  <div class="stat-card"><div class="stat-label">动态词均点赞率</div><div class="stat-value v-green">{avg_lr}%</div></div>
  <div class="stat-card"><div class="stat-label">最高观看数</div><div class="stat-value v-purple">{fmt_num(max_views)}</div></div>
  <div class="stat-card"><div class="stat-label">最高点赞率</div><div class="stat-value v-orange">{max_lr}%</div></div>
</div>

<div class="section-title">🚀 今日动态热词 — YouTube Top1 实际数据</div>
<div class="table-wrap">
<table>
  <thead>
    <tr>
      <th>HN排名</th>
      <th>HN 帖子标题 / 中文</th>
      <th>HN热度</th>
      <th style="text-align:right">评论</th>
      <th>信号词</th>
      <th>发帖</th>
      <th>缩略图</th>
      <th>YouTube Top1 标题 / 中文</th>
      <th style="text-align:right">观看数</th>
      <th style="text-align:right">点赞率</th>
      <th>时长</th>
      <th>跳转</th>
    </tr>
  </thead>
  <tbody>{dyn_rows_html}</tbody>
</table>
</div>

<div class="section-title">📌 静态兜底词 (旧方案) — YouTube Top1 实际数据</div>
<div class="table-wrap">
<table>
  <thead>
    <tr>
      <th>来源</th>
      <th>搜索词</th>
      <th>HN热度</th>
      <th style="text-align:right">评论</th>
      <th>类型</th>
      <th>更新</th>
      <th>缩略图</th>
      <th>YouTube Top1 标题 / 中文</th>
      <th style="text-align:right">观看数</th>
      <th style="text-align:right">点赞率</th>
      <th>时长</th>
      <th>跳转</th>
    </tr>
  </thead>
  <tbody>{stat_rows_html}</tbody>
</table>
</div>

<div class="legend">
  <strong>观看数：</strong>
  <div class="legend-item"><span class="dot" style="background:#bc8cff"></span> ≥ 1M</div>
  <div class="legend-item"><span class="dot" style="background:#58a6ff"></span> ≥ 100K</div>
  <div class="legend-item"><span class="dot" style="background:#e6edf3"></span> ≥ 10K</div>
  <div class="legend-item"><span class="dot" style="background:#8b949e"></span> &lt; 10K</div>
  &nbsp;&nbsp;<strong>点赞率：</strong>
  <div class="legend-item"><span class="dot" style="background:#3fb950"></span> ≥ 5%（优质）</div>
  <div class="legend-item"><span class="dot" style="background:#d29922"></span> ≥ 3%（达标）</div>
  <div class="legend-item"><span class="dot" style="background:#f0883e"></span> ≥ 1%（偏低）</div>
  <div class="legend-item"><span class="dot" style="background:#ff7b72"></span> &lt; 1%（差）</div>
</div>

<div class="footer">
  <span>⚠ 只读演示，未修改任何生产数据库或配置文件</span>
  <span>开启方式：在 .env 设置 <code>ENABLE_DYNAMIC_KEYWORDS=true</code></span>
</div>
</body>
</html>"""

out = Path("output/keyword_report.html")
out.write_text(html, encoding="utf-8")
print(f"Report saved → {out.resolve()}")
