---
name: handwritten-pager-video
description: >-
  Generate high-fidelity, vertical (1080x1920 60fps) bilingual handwriting notebook videos with realistic fountain pen physics,
  authentic Chinese calligraphy, Cosmic Eye brand seal, vibrant prestige accolades, contextual doodles, and platform publishing.
---

# Handwritten Pager Video Skill (沉浸式手写手账跟唱视频制作与发布指南)

This skill provides the complete end-to-end workflow for producing and publishing viral bilingual handwriting notebook videos (`/handwritten-pager-video`).

---

## 1. System Architecture & Components

The pipeline is organized under `src/video_processing/handwritten_pager/`:

- **`canvas_builder.py` (`CanvasBuilder`)**:
  - Builds the 1080×1920 ivory ruled notebook paper with organic fiber texture.
  - Renders the **Cosmic Eye brand seal** (`assets/brand/01_logos/concept_a.png`) in a hand-drawn golden circular stamp with brand name `六维时空号` and slogan `“不同的视角，看见更大的世界。”` in authentic hard-pen calligraphy (`TianYingZhang.ttf`).
  - Renders multi-color artistic display titles (`Let Me Down` navy + `Slowly` coral + `《慢慢放手》` in calligraphy with sunshine gold marker wash).
  - Renders 3 vibrant prestige accolade badges (`★ 全网超 30 亿播放量`, `◆ 现象级传世治愈神曲`, `● RIAA 双白金销量认证`) in a hand-sketched washi tape container, with highlighted curator commentary.
  - Renders enlarged English lyrics (45px, tracking `-1.2px`) and Chinese calligraphy translations (28px) with a **+76px vertical separation** to strictly prevent letter descender overlap (`g`, `y`, `p`).
  - Automatically composites **5 contextual hand-drawn doodles** (`doodle_01_leaf` to `doodle_05_notes`) matching the emotional narrative of each stanza.
  - Builds the educational study notes card at the bottom (`◆ 重点表达手账解析`) with IPA phonetic support (`Arial Unicode.ttf`).

- **`pen_physics.py` (`PenPhysicsEngine`)**:
  - Simulates a photorealistic fountain pen with chrome nib, black lacquered barrel, and realistic dual shadows:
    1. **Contact Shadow (AO)**: Tight, dark contact shadow directly beneath the nib touching the paper.
    2. **Directional Body Shadow**: Soft, blurred drop shadow cast by the angled barrel according to simulated overhead lighting.
  - Physics dynamics: Natural non-linear easing, subtle hand micro-jitter, dynamic wrist tilt, and strictly tracking underneath the active spoken word.

- **`renderer.py` (`HandwrittenPagerRenderer`)**:
  - Direct frame streaming to FFmpeg stdin pipe (`libx264`, 60fps, CRF 18, high-fidelity AAC 320k stereo audio, `+faststart`).
  - High performance: typically renders a 15-second 60fps video (900 frames) in **~7 seconds** (>120 fps).

- **`cover_generator.py` (`CoverGenerator`)**:
  - Generates platform-compliant covers:
    - **WeChat Channels**: 9:16 vertical poster (1080×1920).
    - **Douyin**: 3:4 vertical poster (1080×1440) & 4:3 open journal spread banner (1440×1080).

- **`copywriter.py`**:
  - Produces viral titles and descriptions adhering to platform constraints (WeChat 6-16 chars; Douyin ≤ 30 chars).

---

## 2. Standard Production Workflows

### 2.1 Fast CLI & Pipeline Operations (Preferred Entry Points)

#### A. One-Command End-to-End Pipeline (from YouTube URL or Audio)
```bash
# 1. Full pipeline from YouTube URL (download -> 60fps render -> covers -> copywriting -> dual publish)
PYTHONPATH=src .venv/bin/python scripts/pipeline_handwritten_pager.py \
  --url "https://www.youtube.com/shorts/U1RKC6Fyyg0" \
  --title "Let Me Down Slowly" \
  --artist "Alec Benjamin" \
  --chinese-title "慢慢放手" \
  --publish-wechat \
  --publish-douyin

# 2. Local generation dry-run (generate video + covers + copy without publishing)
PYTHONPATH=src .venv/bin/python scripts/pipeline_handwritten_pager.py \
  --audio output/handwritten_pager/U1RKC6Fyyg0/audio.wav \
  --lyrics-json output/handwritten_pager/U1RKC6Fyyg0/lyrics.json \
  --work-dir output/handwritten_pager/U1RKC6Fyyg0 \
  --dry-run
```

#### B. Quick CLI Generation via `vpanel` or `video-process`
```bash
# Via project control panel vpanel:
./vpanel pager \
  --audio output/handwritten_pager/<ID>/audio.wav \
  --lyrics-json output/handwritten_pager/<ID>/lyrics.json \
  --output output/handwritten_pager/<ID>/final_video.mp4 \
  --covers-dir output/handwritten_pager/<ID>/covers \
  --copy-output output/handwritten_pager/<ID>/copywriting.json

# Or directly via CLI wrapper:
./scripts/video-process handwritten-pager \
  --audio output/handwritten_pager/<ID>/audio.wav \
  --lyrics-json output/handwritten_pager/<ID>/lyrics.json \
  --output output/handwritten_pager/<ID>/final_video.mp4
```

### 2.2 Programmatic Python API
```python
from pathlib import Path
import json
from video_processing.handwritten_pager.renderer import HandwrittenPagerRenderer
from video_processing.handwritten_pager.cover_generator import CoverGenerator
from video_processing.handwritten_pager.contracts import HandwrittenPagerConfig

config = HandwrittenPagerConfig(fps=60)
renderer = HandwrittenPagerRenderer(config)
cover_gen = CoverGenerator(config)

raw_lyrics = json.loads(Path("output/handwritten_pager/<ID>/lyrics.json").read_text("utf-8"))

# 1. Render Video
renderer.render_video(
    audio_path=Path("output/handwritten_pager/<ID>/audio.wav"),
    output_path=Path("output/handwritten_pager/<ID>/final_video.mp4"),
    raw_lyrics=raw_lyrics,
    title="Let Me Down Slowly",
    artist="Alec Benjamin",
)

# 2. Generate Covers
cover_gen.generate_covers(
    raw_lyrics=raw_lyrics,
    output_dir=Path("output/handwritten_pager/<ID>/covers"),
    title="Let Me Down Slowly",
    artist="Alec Benjamin",
)
```

---

## 3. Platform Publishing Workflows

### 3.1 WeChat Channels (视频号)
```bash
PYTHONPATH=src .venv/bin/python scripts/wechat_uploader.py \
  --video output/handwritten_pager/<ID>/final_video.mp4 \
  --title-file output/handwritten_pager/<ID>/wechat_title.txt \
  --copy output/handwritten_pager/<ID>/wechat_copy.txt \
  --cover output/handwritten_pager/<ID>/covers/cover_wechat_9_16.jpg \
  --state output/wechat_state.json
```
- Short Title: 6-16 characters (e.g. `听歌学英语慢慢放手`).
- Cover: 9:16 JPEG (1080×1920).

### 3.2 Douyin (抖音)
```bash
PYTHONPATH=src .venv/bin/python scripts/douyin_uploader.py \
  --video output/handwritten_pager/<ID>/final_video.mp4 \
  --title-file output/handwritten_pager/<ID>/douyin_title.txt \
  --copy output/handwritten_pager/<ID>/douyin_copy.txt \
  --cover output/handwritten_pager/<ID>/covers/cover_douyin_3_4.jpg \
  --horizontal-cover output/handwritten_pager/<ID>/covers/cover_douyin_4_3.jpg \
  --state output/douyin_state.json \
  --prepare-description
```
- Title: ≤ 30 characters (e.g. `全网超30亿播放的治愈神曲《慢慢放手》双语伴读`).
- Dual Covers: Vertical 3:4 poster + Horizontal 4:3 open notebook spread.

---

## 4. Critical Design Rules & Pitfalls

1. **Font Encoding Traps (`TianYingZhang.ttf`)**:
   - `TianYingZhang.ttf` is an authentic hard-pen Chinese calligraphy font, but lacks ASCII punctuation and Unicode symbols (`·`, `“`, `”`, `✎`, `★`, `◆`, `●`). If passed directly, it renders pilcrow `¶` or garbled glyphs.
   - **Enforced Solution**: Always use `draw_mixed_text()` which routes CJK ideographs to `TianYingZhang` and symbols/punctuation/Latin to `Hiragino Sans GB` or `Arial Unicode.ttf`.

2. **IPA Phonetics (Tofu Box Prevention)**:
   - International Phonetic Alphabet symbols (`/ˈsɪmpəθi/`, `/ˈləʊnli/`) require full IPA glyph coverage.
   - Use `/System/Library/Fonts/Supplemental/Arial Unicode.ttf` for phonetics to prevent tofu boxes (`▯`).

3. **Bilingual Separation (+76px Rule)**:
   - English handwriting fonts at 45px have deep descenders (`y`, `g`, `p`).
   - Chinese translation must be placed at least **`y_en + 76px`** below the English baseline. Smaller spacing (e.g. 62px) causes visual collisions.

4. **Accolade Badge Visibility**:
   - Social proof badges (`30亿播放`, `治愈神曲`, `双白金认证`) must use high-saturation jewel colors (Sunkist Orange, Capri Blue, Royal Violet) with crisp white text to act as immediate visual anchors for viewer retention.
