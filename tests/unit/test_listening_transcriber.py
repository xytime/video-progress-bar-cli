from pathlib import Path
import sys

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from web import listening_transcriber
from web.listening_transcriber import _audio_only_question_is_complete, _collapse_consecutive_duplicate_segments, _collapse_repeated_passages, _document_title_from_source, _extract_pdf_visual_cards, is_allowed_audio_name, is_allowed_source_name


def test_listening_transcriber_accepts_only_supported_audio_extensions():
    assert is_allowed_audio_name("exercise.mp3")
    assert is_allowed_audio_name("exercise.WAV")
    assert is_allowed_audio_name("exercise.m4a")
    assert not is_allowed_audio_name("exercise.pdf")
    assert not is_allowed_audio_name("")


def test_listening_transcriber_accepts_text_sources_only():
    assert is_allowed_source_name("questions.pdf")
    assert is_allowed_source_name("questions.txt")
    assert is_allowed_source_name("questions.md")
    assert not is_allowed_source_name("questions.docx")


def test_source_metadata_title_is_preferred_for_a_pdf_question_document(tmp_path):
    import fitz

    document = fitz.open()
    document.new_page().insert_text((40, 80), "PART 1 QUESTIONS 1-7")
    document.set_metadata({"title": "Unit 2 Listening Test 1"})
    pdf = tmp_path / "worksheet.pdf"
    document.save(pdf)
    document.close()

    assert _document_title_from_source(pdf, ".pdf", "PART 1 QUESTIONS 1-7") == "Unit 2 Listening Test 1"


def test_pdf_picture_choices_are_returned_as_a_cropped_original_paper_card(tmp_path):
    import fitz

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((40, 90), "1 What will they eat for dinner?", fontsize=16)
    page.draw_rect((50, 130, 170, 250), color=(0, 0, 0), fill=(1, 0.8, 0.8))
    page.draw_rect((240, 130, 360, 250), color=(0, 0, 0), fill=(0.8, 1, 0.8))
    page.insert_text((65, 275), "A", fontsize=14)
    page.insert_text((255, 275), "B", fontsize=14)
    page.insert_text((40, 360), "2 Where did the police find the stolen statue?", fontsize=16)
    pdf = tmp_path / "picture-choices.pdf"
    document.save(pdf)
    document.close()

    cards = _extract_pdf_visual_cards(pdf, ["What will they eat for dinner?", "Where did the police find the stolen statue?"])

    assert len(cards) == 2
    assert cards[0]["question"] == "What will they eat for dinner?"
    assert cards[0]["contentType"] == "image/png"
    assert len(cards[0]["imageBase64"]) > 100


def test_audio_only_question_requires_all_options_in_transcript():
    result = {
        "status": "ready",
        "options": {"A": "At nine", "B": "At ten", "C": "At eleven"},
    }
    transcript = "The library opens at 9, but on Saturday it opens at 10."
    assert not _audio_only_question_is_complete(result, transcript)


def test_repeated_transcript_run_is_collapsed_into_one_readable_script_line():
    segments = [
        {"startMs": 492_000, "endMs": 494_000, "text": "I'm going to get my bike."},
        {"startMs": 494_000, "endMs": 496_000, "text": "I'm going to get my bike."},
        {"startMs": 496_000, "endMs": 498_000, "text": "I'm going to get my bike."},
    ]
    assert _collapse_consecutive_duplicate_segments(segments) == [
        {"startMs": 492_000, "endMs": 498_000, "text": "I'm going to get my bike."},
    ]


def test_repeated_full_passage_is_not_shown_twice_in_the_study_script():
    first_passage = [
        {"startMs": 0, "endMs": 2_000, "text": "The library opens at nine."},
        {"startMs": 2_000, "endMs": 4_000, "text": "On Saturday it opens at ten."},
        {"startMs": 4_000, "endMs": 6_000, "text": "Please bring your student card."},
    ]
    repeated_passage = [
        {**segment, "startMs": segment["startMs"] + 20_000, "endMs": segment["endMs"] + 20_000}
        for segment in first_passage
    ]
    assert _collapse_repeated_passages(first_passage + repeated_passage) == first_passage


def test_repeated_passage_after_a_long_gap_is_kept_as_new_audio_content():
    first_passage = [
        {"startMs": 0, "endMs": 2_000, "text": "The library opens at nine."},
        {"startMs": 2_000, "endMs": 4_000, "text": "On Saturday it opens at ten."},
        {"startMs": 4_000, "endMs": 6_000, "text": "Please bring your student card."},
    ]
    legitimate_repeat = [
        {**segment, "startMs": segment["startMs"] + 120_000, "endMs": segment["endMs"] + 120_000}
        for segment in first_passage
    ]

    assert _collapse_repeated_passages(first_passage + legitimate_repeat) == first_passage + legitimate_repeat


def test_transcription_job_returns_before_whisper_finishes_and_keeps_result(tmp_path, monkeypatch):
    audio = tmp_path / "exercise.mp3"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(listening_transcriber, "_transcribe", lambda _: {"transcript": "Hello", "segments": []})

    job_id = listening_transcriber._queue_transcription_job(audio, 5, "test-request")
    job = listening_transcriber._transcription_job(job_id)
    assert job and job["status"] in {"queued", "running", "succeeded"}

    listening_transcriber._transcription_jobs[job_id]["future"].result(timeout=2)
    assert listening_transcriber._transcription_job(job_id) == {"id": job_id, "status": "succeeded", "transcript": "Hello", "segments": []}
