"""Private Whisper endpoint used by the listening helper.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-26 | Codex  | 新增听力助手音频转写、题源解析与作业状态 API |
"""

from __future__ import annotations

import secrets
import tempfile
import threading
import json
import logging
import uuid
import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

import httpx
import whisper
from fastapi import APIRouter, Header, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from config.settings import settings


router = APIRouter()
logger = logging.getLogger(__name__)
_model: Optional[Any] = None
_model_lock = threading.Lock()
_max_audio_bytes = 50 * 1024 * 1024
_max_source_bytes = 20 * 1024 * 1024
_allowed_extensions = {".mp3", ".wav", ".m4a"}
_allowed_source_extensions = {".pdf", ".txt", ".md"}
_transcription_jobs: dict[str, dict[str, Any]] = {}
_transcription_jobs_lock = threading.Lock()
_transcription_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="listening-whisper")
_artifact_repeat_gap_ms = 30_000
_max_source_visual_cards = 12
_max_source_visual_bytes = 6 * 1024 * 1024


def is_allowed_audio_name(name: str) -> bool:
    return bool(name and Path(name).suffix.lower() in _allowed_extensions)


def is_allowed_source_name(name: str) -> bool:
    return bool(name and Path(name).suffix.lower() in _allowed_source_extensions)


def _clean_document_title(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    title = " ".join(value.replace("\x00", " ").split()).strip(" -_:|")
    return title if 3 <= len(title) <= 160 else None


def _document_title_from_source(source_path: Path, suffix: str, source_text: str) -> Optional[str]:
    """Return only an explicit document title, never a random extracted line."""
    if suffix == ".pdf":
        from pypdf import PdfReader

        metadata = PdfReader(str(source_path)).metadata
        return _clean_document_title(getattr(metadata, "title", None))
    if suffix == ".md":
        for line in source_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return _clean_document_title(stripped[2:])
    return None


def _load_model() -> Any:
    global _model
    if _model is None:
        _model = whisper.load_model(settings.listening_whisper_model, device="cpu")
    return _model


def _normalized_segment_text(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())


def _collapse_consecutive_duplicate_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one study-script line when Whisper emits the same adjacent line repeatedly."""
    collapsed: list[dict[str, Any]] = []
    for segment in segments:
        normalized = _normalized_segment_text(str(segment.get("text", "")))
        if normalized and collapsed and normalized == _normalized_segment_text(str(collapsed[-1]["text"])):
            collapsed[-1]["endMs"] = max(int(collapsed[-1]["endMs"]), int(segment["endMs"]))
            continue
        collapsed.append(dict(segment))
    return collapsed


def _collapse_repeated_passages(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove only a short-gap duplicated pass caused by transcription artifacts."""
    study_segments: list[dict[str, Any]] = []
    index = 0
    while index < len(segments):
        longest_repeat = 0
        for start in range(len(study_segments)):
            length = 0
            characters = 0
            while index + length < len(segments) and start + length < len(study_segments):
                left = _normalized_segment_text(str(study_segments[start + length]["text"]))
                right = _normalized_segment_text(str(segments[index + length]["text"]))
                if not left or left != right:
                    break
                characters += len(right)
                length += 1
            prior_end_ms = int(study_segments[start + length - 1]["endMs"]) if length else 0
            repeat_gap_ms = int(segments[index]["startMs"]) - prior_end_ms
            if (length >= 3 or characters >= 60) and 0 <= repeat_gap_ms <= _artifact_repeat_gap_ms:
                longest_repeat = max(longest_repeat, length)
        if longest_repeat:
            index += longest_repeat
            continue
        study_segments.append(dict(segments[index]))
        index += 1
    return study_segments


def _segments_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "startMs": round(float(segment.get("start", 0)) * 1000),
            "endMs": round(float(segment.get("end", 0)) * 1000),
            "text": str(segment.get("text", "")).strip(),
        }
        for segment in result.get("segments", [])
        if str(segment.get("text", "")).strip()
    ]


def _transcribe(audio_path: Path) -> dict[str, Any]:
    """Run one CPU-bound transcription at a time on the shared host."""
    with _model_lock:
        result = _load_model().transcribe(
            str(audio_path),
            language="en",
            fp16=False,
            temperature=0,
            beam_size=5,
            condition_on_previous_text=False,
        )
    segments = _collapse_repeated_passages(_collapse_consecutive_duplicate_segments(_segments_from_result(result)))
    transcript = " ".join(segment["text"] for segment in segments).strip()
    if not transcript:
        raise RuntimeError("Whisper 未能识别出可用的英文脚本。")
    return {"transcript": transcript, "language": result.get("language"), "segments": segments}


def _run_transcription_job(job_id: str, audio_path: Path, total_bytes: int, request_id: str) -> None:
    with _transcription_jobs_lock:
        _transcription_jobs[job_id].update(status="running")
    try:
        result = _transcribe(audio_path)
        with _transcription_jobs_lock:
            _transcription_jobs[job_id].update(status="succeeded", transcript=result["transcript"], segments=result["segments"])
        logger.info("Listening transcription completed request_id=%s bytes=%s segments=%s", request_id, total_bytes, len(result["segments"]))
    except Exception as error:
        logger.exception("Listening transcription failed request_id=%s bytes=%s", request_id, total_bytes)
        with _transcription_jobs_lock:
            _transcription_jobs[job_id].update(status="failed", detail=f"Whisper transcription failed: {error}")
    finally:
        audio_path.unlink(missing_ok=True)


def _queue_transcription_job(audio_path: Path, total_bytes: int, request_id: str) -> str:
    job_id = uuid.uuid4().hex
    with _transcription_jobs_lock:
        _transcription_jobs[job_id] = {"id": job_id, "status": "queued"}
    future = _transcription_executor.submit(_run_transcription_job, job_id, audio_path, total_bytes, request_id)
    with _transcription_jobs_lock:
        _transcription_jobs[job_id]["future"] = future
    return job_id


def _transcription_job(job_id: str) -> Optional[dict[str, Any]]:
    with _transcription_jobs_lock:
        job = _transcription_jobs.get(job_id)
        if not job:
            return None
        return {key: value for key, value in job.items() if key != "future"}


def _is_authorized(token: Optional[str]) -> bool:
    expected_token = (settings.listening_transcriber_token or "").strip()
    return bool(expected_token and token and secrets.compare_digest(expected_token, token))


def _normalize_for_evidence(value: str) -> str:
    number_words = {
        "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
        "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
        "10": "ten", "11": "eleven", "12": "twelve",
    }
    normalized = value.lower()
    for digit, word in sorted(number_words.items(), key=lambda item: len(item[0]), reverse=True):
        normalized = normalized.replace(digit, word)
    return "".join(character for character in normalized if character.isalnum())


def _audio_only_question_is_complete(result: dict[str, Any], transcript: str) -> bool:
    if result.get("status") != "ready":
        return False
    raw_options = result.get("options")
    if isinstance(raw_options, dict):
        options = list(raw_options.values())
    elif isinstance(raw_options, list):
        options = [item.get("text") if isinstance(item, dict) else None for item in raw_options]
    else:
        return False
    evidence = _normalize_for_evidence(transcript)
    return len(options) >= 2 and all(isinstance(option, str) and _normalize_for_evidence(option) in evidence for option in options)


def _source_visual_stems(value: Optional[str]) -> list[str]:
    """Read the audio-anchored stems passed by the private Worker request."""
    if not value:
        return []
    try:
        items = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    return [item.strip() for item in items if isinstance(item, str) and len(item.strip()) >= 8][:_max_source_visual_cards]


def _search_source_stem(page: Any, stem: str) -> list[Any]:
    matches = page.search_for(stem)
    if matches:
        return matches
    # Page extraction can insert hard line breaks. A distinctive opening phrase
    # still anchors the visual region without asking an AI model to infer it.
    words = stem.split()
    for length in range(min(8, len(words)), 3, -1):
        matches = page.search_for(" ".join(words[:length]))
        if matches:
            return matches
    return []


def _extract_pdf_visual_cards(pdf_path: Path, stems: list[str]) -> list[dict[str, str]]:
    """Crop each original-paper picture-choice region between adjacent stems."""
    if not stems:
        return []
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF is unavailable; skipping picture-choice extraction")
        return []

    cards: list[dict[str, str]] = []
    total_bytes = 0
    document = fitz.open(pdf_path)
    try:
        for page in document:
            matches: list[tuple[str, Any]] = []
            for stem in stems:
                rectangles = _search_source_stem(page, stem)
                if rectangles:
                    matches.append((stem, min(rectangles, key=lambda rectangle: (rectangle.y0, rectangle.x0))))
            matches.sort(key=lambda item: item[1].y0)
            for index, (stem, rectangle) in enumerate(matches):
                if len(cards) >= _max_source_visual_cards:
                    return cards
                same_row = [candidate for candidate in matches if candidate[0] != stem and abs(candidate[1].y0 - rectangle.y0) < 36]
                left_neighbors = [candidate[1] for candidate in same_row if candidate[1].x0 < rectangle.x0]
                right_neighbors = [candidate[1] for candidate in same_row if candidate[1].x0 > rectangle.x0]
                left = max((neighbor.x1 for neighbor in left_neighbors), default=page.rect.x0 + 14)
                right = min((neighbor.x0 for neighbor in right_neighbors), default=page.rect.x1 - 14)
                same_lane_below = [candidate[1] for candidate in matches if candidate[1].y0 > rectangle.y0 + 36 and abs(candidate[1].x0 - rectangle.x0) < 110]
                next_top = min((neighbor.y0 - 14 for neighbor in same_lane_below), default=page.rect.y1 - 18)
                top = max(page.rect.y0 + 12, rectangle.y0 - 26)
                bottom = min(page.rect.y1 - 12, max(top + 80, next_top))
                clip = fitz.Rect(max(page.rect.x0 + 14, left - 14), top, min(page.rect.x1 - 14, right + 14), bottom)
                image = page.get_pixmap(matrix=fitz.Matrix(1.35, 1.35), clip=clip, alpha=False).tobytes("png")
                if not image or total_bytes + len(image) > _max_source_visual_bytes:
                    return cards
                total_bytes += len(image)
                cards.append({
                    "question": stem,
                    "contentType": "image/png",
                    "imageBase64": base64.b64encode(image).decode("ascii"),
                })
    finally:
        document.close()
    return cards


@router.post("/api/internal/listening/transcriptions", status_code=202)
async def create_listening_transcription(
    request: Request,
    x_listening_token: Optional[str] = Header(default=None),
    x_audio_name: Optional[str] = Header(default=None),
    x_listening_request_id: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Transcribe one server-to-server audio stream without retaining it."""
    if not _is_authorized(x_listening_token):
        raise HTTPException(status_code=401, detail="Unauthorized listening transcription request.")
    if not x_audio_name or not is_allowed_audio_name(x_audio_name):
        raise HTTPException(status_code=415, detail="Only mp3, wav, and m4a files are supported.")

    logger.info("Listening transcription started request_id=%s audio=%s", x_listening_request_id or "unknown", x_audio_name)

    content_length = request.headers.get("content-length")
    if content_length and (not content_length.isdigit() or int(content_length) > _max_audio_bytes):
        raise HTTPException(status_code=413, detail="Audio file exceeds the 50 MB limit.")

    temp_path: Optional[Path] = None
    total_bytes = 0
    try:
        with tempfile.NamedTemporaryFile(prefix="listening-", suffix=Path(x_audio_name).suffix.lower(), delete=False) as handle:
            temp_path = Path(handle.name)
            async for chunk in request.stream():
                total_bytes += len(chunk)
                if total_bytes > _max_audio_bytes:
                    raise HTTPException(status_code=413, detail="Audio file exceeds the 50 MB limit.")
                handle.write(chunk)
        job_id = _queue_transcription_job(temp_path, total_bytes, x_listening_request_id or "unknown")
        temp_path = None
        return {"id": job_id, "status": "queued"}
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Listening transcription failed request_id=%s audio=%s bytes=%s", x_listening_request_id or "unknown", x_audio_name, total_bytes)
        raise HTTPException(status_code=422, detail=f"Whisper transcription failed: {error}") from error
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


@router.get("/api/internal/listening/transcriptions/{job_id}")
async def get_listening_transcription(
    job_id: str,
    x_listening_token: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    if not _is_authorized(x_listening_token):
        raise HTTPException(status_code=401, detail="Unauthorized listening transcription request.")
    job = _transcription_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Listening transcription job was not found.")
    return job


@router.post("/api/internal/listening/sources")
async def extract_listening_source(
    request: Request,
    x_listening_token: Optional[str] = Header(default=None),
    x_source_name: Optional[str] = Header(default=None),
    x_listening_question_stems: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Extract text and original-paper picture-choice cards from a source."""
    if not _is_authorized(x_listening_token):
        raise HTTPException(status_code=401, detail="Unauthorized listening source request.")
    if not x_source_name or not is_allowed_source_name(x_source_name):
        raise HTTPException(status_code=415, detail="Only PDF, TXT, and Markdown sources are supported.")

    content_length = request.headers.get("content-length")
    if content_length and (not content_length.isdigit() or int(content_length) > _max_source_bytes):
        raise HTTPException(status_code=413, detail="Source file exceeds the 20 MB limit.")

    temp_path: Optional[Path] = None
    total_bytes = 0
    try:
        suffix = Path(x_source_name).suffix.lower()
        with tempfile.NamedTemporaryFile(prefix="listening-source-", suffix=suffix, delete=False) as handle:
            temp_path = Path(handle.name)
            async for chunk in request.stream():
                total_bytes += len(chunk)
                if total_bytes > _max_source_bytes:
                    raise HTTPException(status_code=413, detail="Source file exceeds the 20 MB limit.")
                handle.write(chunk)
        visual_cards: list[dict[str, str]] = []
        if suffix in {".txt", ".md"}:
            text = temp_path.read_text(encoding="utf-8", errors="replace")
        else:
            from pypdf import PdfReader

            text = "\n".join((page.extract_text() or "") for page in PdfReader(str(temp_path)).pages)
            visual_cards = _extract_pdf_visual_cards(temp_path, _source_visual_stems(x_listening_question_stems))
        if not text.strip():
            raise HTTPException(status_code=422, detail="未能从题目文件提取文字；请上传可复制文字的 PDF、TXT 或 Markdown 文件。")
        document_title = _document_title_from_source(temp_path, suffix, text)
        return {"text": text.strip(), "visualCards": visual_cards, "documentTitle": document_title}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=422, detail=f"题目来源解析失败: {error}") from error
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


@router.post("/api/internal/listening/questions")
async def extract_listening_questions(
    request: Request,
    x_listening_token: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Use the local DeepSeek credential to conservatively reconstruct a question."""
    if not _is_authorized(x_listening_token):
        raise HTTPException(status_code=401, detail="Unauthorized listening question request.")
    try:
        body = await request.json()
        transcript = body.get("transcript") if isinstance(body, dict) else None
        source_text = body.get("sourceText") if isinstance(body, dict) else None
        transcript_segments = body.get("transcriptSegments") if isinstance(body, dict) else None
        if not isinstance(transcript, str) or not transcript.strip():
            raise HTTPException(status_code=400, detail="A transcript is required.")
        if source_text is not None and not isinstance(source_text, str):
            raise HTTPException(status_code=400, detail="Source text must be a string.")
        if transcript_segments is not None and not isinstance(transcript_segments, list):
            raise HTTPException(status_code=400, detail="Transcript segments must be a list.")
        if not settings.deepseek_api_key:
            raise HTTPException(status_code=503, detail="DeepSeek is not configured for listening questions.")
        response = await run_in_threadpool(
            lambda: httpx.post(
                f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                json={
                    "model": settings.deepseek_model,
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                    "max_tokens": 8000,
                    "messages": [
                        {"role": "system", "content": "You are a rigorous English listening exam analyst. Use only the transcript, its timestamped segments, and optional question source. Never invent missing information. The source may contain multiple sections for different recordings. Return only questions that belong to the current audio; never include a question merely because it is first in the source. For every returned question, copy one exact continuous English evidenceText phrase of at least three words from the current transcript and set evidenceStartMs/evidenceEndMs to the segment range containing that phrase. Exclude any candidate without verifiable audio evidence. Return every matched complete question in source order. Return ready only when at least one matched question has a stem and two or more explicit options. An answer may be empty when the source does not provide an answer key. Return JSON only: status, reason, questions. Each questions item has id, question, options (A-D ids and text), correctAnswer, evidenceText, evidenceStartMs, evidenceEndMs."},
                        {"role": "user", "content": json.dumps({"transcript": transcript.strip(), "transcriptSegments": transcript_segments or [], "sourceText": source_text.strip() if isinstance(source_text, str) else None})},
                    ],
                },
                timeout=45,
            ),
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        result = json.loads(content)
        if not isinstance(result, dict):
            raise ValueError("DeepSeek returned a non-object response.")
        if not source_text and not _audio_only_question_is_complete(result, transcript):
            return {
                "status": "needs_source",
                "reason": "音频已转写，但题干或全部选项无法从音频中逐项核验。请上传题目 PDF、TXT 或粘贴题目。",
                "question": "",
                "options": [],
                "correctAnswer": "",
            }
        return result
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"题目识别服务暂时不可用: {error}") from error
