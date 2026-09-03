# English World Screen Density Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent reliable KET/中考 vocabulary from being discarded before screen-level selection and prevent a deterministically failed locked source from being selected again.

**Architecture:** Preserve the existing PET-and-above `vocabulary` list for the initial learning-value layout, but expose a separate, reliable offline candidate pool down to KET for the renderer's strict per-screen density selection. Extend the daily coordinator's backward-compatible source-ID extraction and production prompt so a locked source that deterministically fails production is persisted as excluded on the next run.

**Tech Stack:** Python 3, pytest, dataclasses, the existing StudyCardContent/template-A renderer, JSON delivery requests.

**Spec:** `AGENTS.md`; `scripts/run_english_world_daily.py` production contract in `PROMPT`.

## Global Constraints

- Use `.venv/bin/python` and `PYTHONPATH=src` for project verification.
- Preserve only reliable offline vocabulary evidence; `unknown` and `ecdict-fallback` must remain excluded.
- Keep the PET-and-above default learning selection for callers that render without a screen-density fallback.
- A failure, review receipt, or local MP4 is not platform-public proof; this change must not submit, resend, or publish content.
- Modify only owned changes and append modification-history entries for changed code/test files.

---

### Task 1: Retain reliable foundation vocabulary for screen-density selection

**Files:**
- Modify: `src/video_processing/study_cards/models.py:87-144`
- Test: `tests/unit/test_study_card_template_a.py`

**Interfaces:**
- Consumes: `select_vocabulary(english_text, candidates, minimum_level=...)`.
- Produces: `StudyCardContent.vocabulary` at the existing PET threshold and `StudyCardContent.vocabulary_candidates` at KET-or-above with the same reliability filter.

- [ ] **Step 1: Write the failing test**

```python
def test_content_keeps_reliable_ket_candidates_for_screen_density_selection():
    content = StudyCardContent.from_mapping(payload_with_eight_reliable_ket_items())

    assert content.vocabulary == ()
    assert [item.word for item in content.vocabulary_candidates] == [
        "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_study_card_template_a.py::test_content_keeps_reliable_ket_candidates_for_screen_density_selection -q`

Expected: FAIL because `StudyCardContent.from_mapping` currently assigns the PET-only selection to `vocabulary_candidates`.

- [ ] **Step 3: Write minimal implementation**

```python
vocabulary = tuple(select_vocabulary(english_text, vocabulary_candidates).items)
screen_candidates = tuple(
    select_vocabulary(english_text, vocabulary_candidates, minimum_level=1).items
)
...
vocabulary_candidates=screen_candidates,
```

- [ ] **Step 4: Run the focused study-card tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_study_card_vocabulary.py tests/unit/test_study_card_template_a.py -q`

Expected: PASS, including the new candidate-pool regression.

### Task 2: Persist deterministic post-lock failures as future source exclusions

**Files:**
- Modify: `scripts/run_english_world_daily.py:55-105,549-590`
- Modify: `tests/unit/test_english_world_daily_scheduler.py`

**Interfaces:**
- Consumes: failure delivery-request JSONs written by the production agent.
- Produces: `_recent_rejected_youtube_ids(log_dir) -> tuple[str, ...]` that recognizes `锁定来源 <youtube_id>` quality failure text but excludes legacy network/access faults, and a daily prompt that instructs the agent to append the locked ID for a deterministic quality/render/QA failure.

- [ ] **Step 1: Write the failing tests**

```python
def test_recent_rejected_candidates_include_locked_source_quality_failure(tmp_path):
    write_failure(tmp_path, "锁定来源 UIJ1PrQOyLM 后，学习卡正式渲染的真实屏幕门禁失败")

    assert runner._recent_rejected_youtube_ids(tmp_path) == ("UIJ1PrQOyLM",)

def test_daily_prompt_persists_deterministic_locked_source_failures():
    assert "锁定来源后若出现可重复的内容、屏幕词汇、渲染封装或音频质检失败" in runner.PROMPT
    assert "追加 `--rejected-youtube-id`" in runner.PROMPT

def test_recent_rejected_candidates_exclude_locked_source_access_failures(tmp_path):
    write_failure(tmp_path, "锁定来源 UIJ1PrQOyLM 后下载时 DNS 解析失败")

    assert runner._recent_rejected_youtube_ids(tmp_path) == ()
```

- [ ] **Step 2: Run the two tests to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_english_world_daily_scheduler.py -k 'locked_source_quality_failure or persists_deterministic_locked_source_failures' -q`

Expected: FAIL because the legacy regex does not recognize `锁定来源`, does not distinguish source access faults, and the prompt only covers preflight rejections.

- [ ] **Step 3: Write minimal implementation**

```python
LEGACY_REJECTED_ID_PATTERN = re.compile(
    r"(?:候选|锁定来源|youtube_id\\s*[=:：]?)[^A-Za-z0-9_-]{0,12}([A-Za-z0-9_-]{11})",
    re.IGNORECASE,
)
```

Add the prompt contract that a deterministic post-lock quality/render/QA failure must append its locked source ID to the existing failure request. Gate legacy ID extraction behind an access-failure matcher so network, Cookie, DNS, TLS, 403, authentication, and source-path failures remain non-rejections.

- [ ] **Step 4: Run the focused coordinator tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_english_world_daily_scheduler.py -q`

Expected: PASS with the new cross-run exclusion tests.

### Task 3: Atomically expose only parseable rendered MP4 containers

**Files:**
- Modify: `src/video_processing/study_cards/renderer.py:75-165`
- Test: `tests/unit/test_study_card_template_a.py`

**Interfaces:**
- Consumes: a same-directory staged MP4 written by FFmpeg.
- Produces: `_validate_and_publish_mp4(staged_path, output_path)` that keeps the visible final path unchanged until `ffprobe` can parse a nonzero-duration container.

- [ ] **Step 1: Write the failing test**

```python
def test_renderer_keeps_existing_final_mp4_when_staged_container_is_invalid(tmp_path):
    staged = tmp_path / ".study-card.mp4"
    final = tmp_path / "study-card.mp4"
    staged.write_bytes(b"partial-container")
    final.write_bytes(b"prior-verified-container")

    with pytest.raises(RuntimeError, match="MP4 容器"):
        StudyCardRenderer._validate_and_publish_mp4(staged, final)

    assert final.read_bytes() == b"prior-verified-container"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_study_card_template_a.py::test_renderer_keeps_existing_final_mp4_when_staged_container_is_invalid -q`

Expected: FAIL because no parse-before-publish boundary exists.

- [ ] **Step 3: Write minimal implementation**

```python
staged_output = _same_directory_staging_path(output_path)
self._run_ffmpeg(..., output_path=staged_output, ...)
self._validate_and_publish_mp4(staged_output, output_path)
```

Use `ffprobe` with a bounded retry and `Path.replace()` only after a positive parseable-duration check. Remove the staged file in the renderer's `finally` block when validation fails.

- [ ] **Step 4: Run the focused renderer tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_study_card_template_a.py -q`

Expected: PASS; invalid staged media never replaces a visible final MP4.

### Task 4: Verify production-shaped evidence and commit only owned files

**Files:**
- Verify: `output/study_cards/2026-09-03/UIJ1PrQOyLM/timeline.enriched.json`
- Verify: `output/study_cards/2026-09-03/oArvHNaAuek/timeline.enriched.json`
- Commit: Task 1, Task 2, and Task 3 files only, after the focused and full-suite gates.

**Interfaces:**
- Consumes: the two failed real timelines and current code.
- Produces: a read-only calculation confirming the current candidate pool can satisfy Template A's screen gate, plus a local Git commit without external delivery.

- [ ] **Step 1: Run the real-timeline candidate-pool regression probe**

Run a read-only `.venv/bin/python` diagnostic that constructs `StudyCardContent` from each timeline, calculates the final screen candidates, and calls `RecordUnderlineTemplate.select_vocabulary_for_screens` with the renderer's offsets.

Expected: UIJ1PrQOyLM and oArvHNaAuek no longer raise a per-screen micro-note error when only reliable offline terms are used.

- [ ] **Step 2: Run all affected test groups and the full suite**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_study_card_vocabulary.py tests/unit/test_study_card_template_a.py tests/unit/test_enrich_study_card_vocabulary.py tests/unit/test_english_world_daily_scheduler.py -q`

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q`

Expected: focused suite is green; report any pre-existing unrelated full-suite failure separately rather than masking it.

- [ ] **Step 3: Inspect and commit the owned diff**

Run: `git diff --check` and inspect `git diff --` for only the plan, study-card model/test, and daily scheduler/test files.

Commit: `git add docs/superpowers/plans/2026-09-03-english-world-screen-density-recovery.md src/video_processing/study_cards/models.py src/video_processing/study_cards/renderer.py tests/unit/test_study_card_template_a.py scripts/run_english_world_daily.py tests/unit/test_english_world_daily_scheduler.py && git commit -m "fix: recover English World screen-density delivery"`

Expected: one local commit containing only this repair and no upload/publish action.
