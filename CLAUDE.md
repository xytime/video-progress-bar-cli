# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project actually is

The README describes a "video processing tool library," but that is only the bottom layer. This is a **fully automated YouTube → WeChat Channels (视频号) publishing pipeline**:

1. **Discover** high-engagement YouTube videos from a channel whitelist (`scripts/monitor_channels.py`)
2. **Score** them with Gemini; videos scoring ≥ 75 enter the auto-publish queue
3. **Download** (yt-dlp + curl), optionally **slice** long videos into chapter segments
4. **Generate copy** (Chinese title/short-title/description) and a **cover** image
5. **Transcribe** (Whisper) → **translate** (Gemini, Aliyun MT fallback) → render **bilingual subtitles** + optional **TTS** voiceover and progress bar
6. **Censor** (banned-word / channel-policy checks)
7. **Publish** to WeChat Channels via Playwright browser automation, with Telegram notifications

The whole flow is a checkpoint-resumable finite state machine driven by `PipelineManager`. Most code comments and docstrings are in **Chinese** — match that when editing.

## Architecture

### Dependency DAG (strictly one-directional — enforced)

```
scripts/  cli/
   ↓
src/video_processing/pipeline_manager.py   (the FSM orchestrator)
   ↓
db/  processors/  core/  utils/  validators/
   ↓
src/config/settings.py
```

The core domain (`db/`, `core/`) must **never** import from outer layers (`scripts/`, `cli/`). If you find yourself needing such an import, the design is wrong — stop and restructure. See `CONTRIBUTING.md` (the project's "engineering constitution").

### The pipeline FSM (`src/video_processing/pipeline_manager.py`, ~1200 lines)

Status flow per video: `PENDING → DOWNLOADING → COPYWRITING → TRANSCRIBING (+ RENDERING) → [CENSORSHIP] → cover → PUBLISHING → PUBLISHED`, with `FAILED` and `LOGIN_REQUIRED` as off-ramps. A parent video that was sliced becomes `SEGMENTED`; its slices are separate rows.

Key behaviors that are easy to break:
- **Every step is checkpoint-resumable**: if the expected output file already exists (and passes validation), the step is skipped. Several bugs in history came from a checkpoint matching when a *dependent* artifact (e.g. the cover ribbon `label` file, or a bilingual `.ass`) was actually missing — checkpoints validate the full output set, not just one file.
- **`source='DISCOVERY'` videos are browse-only**: they are skipped by scoring and never auto-published (they only populate the dashboard's 高赞 tab).
- **Score 75 is the auto-publish threshold** (`get_high_score_pending_videos(min_score=75)`).
- **Subprocess orchestration**: the manager shells out to `yt-dlp`, `python -m cli.main auto-caption`, `scripts/copywriter.py`, `scripts/cover_generator.py`, and `scripts/wechat_uploader.py`. All run with `.venv/bin/python`, `cwd=PROJECT_ROOT`, `PYTHONPATH=src`, and an env built by `_build_subprocess_env()` (dynamic proxy detection + Telegram vars). Child processes are isolated in their own process group (`Popen` + `os.setsid`) and PID-tracked so a SIGTERM during deletion can kill the whole tree.

### Database (`src/video_processing/db/database.py`)

SQLite at `output/pipeline.db`, WAL mode, foreign keys on. The schema self-migrates on `PipelineDB.__init__` (additive `ALTER TABLE` guards). Tables: `processed_videos` (composite unique key `(youtube_id, slice_index)`, `parent_id` self-FK with `ON DELETE CASCADE` for slices), `recommended_channels`, `blacklisted_videos`.

### Other major components

- **`src/web/app.py`** — FastAPI dashboard on **:8765** (the control center; serves stats, video queue tabs, channel management, manual trigger/retry/priority endpoints). Started via `./vpanel ui start`.
- **`src/cli/`** — Click CLI; commands registered in `cli/main.py`: `add-progressbar`, `auto-caption`, `extract-subs`, `ass-to-tts`.
- **`src/video_processing/processors/`** — the actual FFmpeg/Whisper/pysubs2 work (caption, slicer, vertical, progress_bar, subtitle/chapter extractors). **Read `docs/experience_log/critical_lessons.md` before major changes here.**
- **`src/cover/`** — cover image generation engine (layout/renderer/themes/semantic).
- **`src/bot/`** — Telegram bot for remote pipeline control (async, **httpx not requests**, to avoid blocking the event loop).
- **`scripts/`** — operational glue: `monitor_channels.py` (discovery), `copywriter.py`, `cover_generator.py`, `wechat_uploader.py` (Playwright, ~80KB), `wechat_keepalive.py` (session watchdog), `bot_daemon.py`.

## Commands

The project uses a `.venv`. **Always use the venv's `python`, never system `python3`** (Whisper/Gemini/etc. live in the venv). The README repeats this warning for a reason.

### Operating the pipeline (preferred entry points)

```bash
./vpanel ui start          # start dashboard (http://localhost:8765)
./vpanel ui stop|status|logs|open
./vpanel job run           # one full cycle: monitor_channels.py → pipeline_manager
./vpanel job logs          # tail output/pipeline.log
./vpanel job channels      # list approved channel whitelist
./vpanel job add-channel <YouTube URL>   # validate via yt-dlp, then whitelist
./vpanel bot start|stop|status|logs|restart
./vhelp                    # terminal cheat sheet for this + sibling projects
```

Run the pipeline directly (note the required `PYTHONPATH`):

```bash
PYTHONPATH=src .venv/bin/python -m video_processing.pipeline_manager   # = run_daily_job(): score + process
.venv/bin/python scripts/monitor_channels.py                          # discovery pass only
```

### CLI video tools

```bash
# Either put src on the path via the wrapper...
./scripts/video-process auto-caption ~/Videos/Test.mp4 --src-lang en --target-lang zh-CN --style movie_yellow
# ...or run the module from the project root
python -m cli.main add-progressbar input.mp4 -c 00:00 -t "Intro" -c 01:20 -t "Chapter" --font-path /System/Library/Fonts/PingFang.ttc
```

If you hit `Error: No such option: -t`, you are running a stale installed copy — clear caches / reinstall, or use `scripts/video-process` (see `TROUBLESHOOTING.md`).

### Tests

```bash
pytest                                          # all (testpaths=tests, pattern test_*.py)
pytest tests/unit/test_database_slices.py       # single file
pytest tests/unit/test_database_slices.py::TestClass::test_method   # single test
pytest -k red_blue                              # by keyword
```

## Non-negotiable conventions (the "constitution" — `CONTRIBUTING.md`)

1. **Config single source of truth**: every env var is declared in `src/config/settings.py` (pydantic-settings) and read via the `settings` singleton. **Never call `os.getenv` / `os.environ` outside `settings.py`.** New var → add typed field in `settings.py` + `.env.example` key.
2. **DAL encapsulation**: every SQL statement lives inside a `PipelineDB` method. **Never open `get_connection()` or run raw SQL from business code.**
3. **Dependency DAG**: no reverse imports (core never imports scripts/cli); no cycles.
4. **Mock gate**: if a unit test needs to mock **more than 3** external objects, the module is too coupled — redesign it (facade / service layer), don't pile on mocks.
5. **Modification History**: new files or changes ≥ 10 logic lines must update the `# Modification History` markdown table in the file's docstring (see any existing module for the format).
6. **Port registry**: register new service ports in `PORTS.md` and read them from env vars, never hardcode. :8765 is the dashboard.

## Critical video/subtitle rules (`docs/experience_log/critical_lessons.md`, `.windsurfrules`)

These encode hard-won failures — violating them silently corrupts subtitles:

- **ASS line breaks**: pysubs2 does not honor Python `\n`. Run `text.replace('\n', '\\N')` before building any `SSAEvent`. `\N` is ASS's only forced line break.
- **Order matters**: wrap text *first*, then apply Chinese highlights — applying `{...}` ASS tags before `textwrap.fill` lets `\N` land inside a tag and breaks libass parsing. (English highlights are tag-aware and may precede wrapping.)
- **Bilingual margins are dynamic**: the Chinese layer's bottom margin must be computed from the English layer's actual wrapped line count (e.g. `margin_zh = 10 + en_lines*18 + 5`) — never a fixed offset, or layers overlap.
- **Whisper input**: always re-sample extracted audio to **16 kHz mono** (`-ar 16000 -ac 1`).
- **`pysubs2.Color`**: pass `(R, G, B)` integers, not hex/RGBA. ASS alpha is **inverted** (255 = fully transparent).
- **Glossary font size**: clamp it to the *current rendered* English font size at runtime (`{\fs...}` inline), not the static style value.

## Feature flags

`src/config/settings.py` defines v7.0 feature flags that **default to `False`** for production safety; enable per-flag in `.env`: `enable_blacklist_tombstone`, `enable_manual_score_lock`, `enable_censorship_engine`, `enable_channel_policy_filter`, `enable_sigterm_kill`, `enable_dynamic_keywords`.

## Repo hygiene note

The project root is littered with one-off artifacts — `scratch_*.py`, `dump_*.py`, `render_*.sh`, `*.mp4`, `*.ass`, `*.log`, `draft-code/`, `scratch/`. These are debugging/demo leftovers, **not** the real codebase. The maintained code is in `src/`, `scripts/`, and `tests/`.
