---
name: wechat-interaction
description: >-
  Manage, run, inspect, and troubleshoot WeChat Channels (视频号) automated comment interactions.
  Use when posting author comments/polls on newly published videos, reconciling UNCERTAIN comment statuses,
  running dry-runs, or executing isolated browser tests for WeChat interaction flows.
---

# WeChat Channels Comment Interaction Runbook (视频号首评互动运维与调试指南)

This skill provides operational workflows, diagnostic checklists, and debugging procedures for the WeChat Channels automated comment and poll interaction engine (`scripts/wechat_commenter.py`).

---

## 1. Prerequisites & Flags

All CLI invocations MUST use the virtual environment Python with `PYTHONPATH=src`.

### Configuration in `.env`
```bash
# Master switch for comment interaction (must be true to write real comments)
ENABLE_WECHAT_COMMENT_INTERACTION=true
```

If `ENABLE_WECHAT_COMMENT_INTERACTION` is not set or `false`, the commenter automatically falls back to **safe read-only dry-run** mode.

---

## 2. Standard CLI Workflows

Run from the project root (`/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing`):

### 2.1 Process Next Due Video (Default / Cron Tick)
Pick the latest published video requiring an author comment and submit one:
```bash
ENABLE_WECHAT_COMMENT_INTERACTION=true PYTHONPATH=src .venv/bin/python scripts/wechat_commenter.py --latest
```

### 2.2 Batch Process Recent Videos
Batch process up to $N$ recent published videos (e.g. 5 or 10):
```bash
ENABLE_WECHAT_COMMENT_INTERACTION=true PYTHONPATH=src .venv/bin/python scripts/wechat_commenter.py --count 5
```

### 2.3 Process Specific Video by Native ID
Target a specific WeChat native `exportId`:
```bash
ENABLE_WECHAT_COMMENT_INTERACTION=true PYTHONPATH=src .venv/bin/python scripts/wechat_commenter.py --post-id "export/UzFfBgAA..."
```

### 2.4 Safe Dry-Run (No AI Call, No Browser, No DB Mutation)
Verify pipeline wiring and candidate retrieval safely:
```bash
PYTHONPATH=src .venv/bin/python scripts/wechat_commenter.py --post-id "export/UzFfBgAA..." --dry-run
```

### 2.5 Reconcile Uncertain Comments (Read-Only Verification)
Check records left in `UNCERTAIN` state (e.g. after network drop during submit):
```bash
ENABLE_WECHAT_COMMENT_INTERACTION=true PYTHONPATH=src .venv/bin/python scripts/wechat_commenter.py --reconcile-pending
```

---

## 3. Invariants & Critical Contracts

1. **Natural Short-Format Copy Contract**:
   - **NO** column tags (e.g. `【互动话题】`, `【观点投票】`).
   - **NO** emojis.
   - **Format**: 1 natural question + 2~3 concise options (`A. ...`, `B. ...`) + 1 open-ended heuristic follow-up question (≤30 chars).
   - Must pass `censor_engine` before and during submission.
2. **Micro-Frontend API Interception**:
   - Never rely on video title text to locate cards in WeChat admin DOM.
   - The engine automatically intercepts `post/post_list` API responses, correlates native `exportId` to in-screen array index, and targets `.comment-feed-wrap:visible.nth(idx)`.
3. **Session Concurrency Lock**:
   - Video upload and comment interactions share the same browser storage state (`output/wechat_state.json`).
   - All browser operations must acquire `WeChatSessionLock` to prevent racing against video publishing.

---

## 4. Diagnostics & Troubleshooting Tree

When comment posting fails or times out:

```
Failure Diagnosis
 ├── 1. Check Worker Log:
 │      tail -n 50 output/wechat_interaction_worker.log
 ├── 2. Check Physical Receipt & Error:
 │      cat output/wechat_evidence/interactions/<youtube_id>/attempt-*/receipt.json
 ├── 3. Inspect UI Screenshot:
 │      open output/wechat_evidence/interactions/<youtube_id>/attempt-*/final.png
 ├── 4. Check WeChat Auth State (Cookie expiration):
 │      ls -l output/wechat_state.json
 └── 5. Inspect DB Interactions Table:
        .venv/bin/python -c 'from video_processing.db.database import PipelineDB; db=PipelineDB(); print(db.get_pending_review_wechat_interactions())'
```

---

## 5. Sandboxed Testing

**DO NOT** run bare `pytest` on live checkout. Always run via the sandboxed test runner:

```bash
# Unit tests
.venv/bin/python scripts/run_isolated_tests.py -- -q tests/unit/test_wechat_interaction*.py

# Browser boundary tests (with Chromium copy)
.venv/bin/python scripts/run_isolated_tests.py --browser -- -q tests/browser/test_wechat_interaction_browser.py
```
