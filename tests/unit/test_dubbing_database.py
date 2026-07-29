"""独立配音账本的边界测试。"""

import os
import tempfile

import pytest

from video_processing.db.database import PipelineDB


@pytest.fixture
def dubbing_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = PipelineDB(path)
    assert db.add_video("dub-source", "Source", "channel", score=88, upload_date="20260728")
    db.update_video_status("dub-source", "PUBLISHED")
    yield db
    os.unlink(path)


def test_dubbing_job_never_mutates_source_status(dubbing_db):
    source_before = dubbing_db.get_video_by_youtube_id("dub-source")
    job = dubbing_db.create_dubbing_job(
        "dub-source", model="speech-2.8-turbo", voice_id="Chinese (Mandarin)_Male_Announcer",
        requested_platforms=["wechat"], config={"audio_policy": "zh_only"},
    )
    dubbing_db.update_dubbing_job(job["id"], "QA_REQUIRED", output_video_path="/tmp/dub.mp4", asset_sha256="a" * 64)
    source_after = dubbing_db.get_video_by_youtube_id("dub-source")

    assert source_before["status"] == source_after["status"] == "PUBLISHED"
    assert job["state"] == "DRAFT"
    assert dubbing_db.get_dubbing_job(job["id"])["state"] == "QA_REQUIRED"


def test_dubbing_job_exposes_source_upload_date(dubbing_db):
    job = dubbing_db.create_dubbing_job(
        "dub-source", model="speech-2.8-turbo", voice_id="Chinese (Mandarin)_Male_Announcer",
    )

    by_id = dubbing_db.get_dubbing_job(job["id"])
    by_source = dubbing_db.get_dubbing_job_by_source("dub-source")

    assert by_id["source_upload_date"] == "20260728"
    assert by_source["source_upload_date"] == "20260728"


def test_dubbing_publication_has_its_own_state(dubbing_db):
    job = dubbing_db.create_dubbing_job(
        "dub-source", model="speech-2.8-turbo", voice_id="Chinese (Mandarin)_Male_Announcer",
    )
    publication = dubbing_db.update_dubbing_publication(job["id"], "douyin", "UNDER_REVIEW", error_message="等待平台确认")
    source = dubbing_db.get_video_by_youtube_id("dub-source")

    assert publication["platform"] == "douyin"
    assert publication["state"] == "UNDER_REVIEW"
    assert source["status"] == "PUBLISHED"


def test_dubbing_publication_correction_does_not_increment_attempts(dubbing_db):
    job = dubbing_db.create_dubbing_job(
        "dub-source", model="speech-2.8-turbo", voice_id="Chinese (Mandarin)_Male_Announcer",
    )
    first = dubbing_db.update_dubbing_publication(job["id"], "douyin", "RETRYABLE_FAILED", error_message="误判")
    corrected = dubbing_db.correct_dubbing_publication_state(
        job["id"], "douyin", "UNDER_REVIEW", error_message="已提交，等待回查"
    )

    assert first["attempt_count"] == corrected["attempt_count"] == 1
    assert corrected["state"] == "UNDER_REVIEW"
    assert corrected["last_error_message"] == "已提交，等待回查"


def test_dubbing_speaker_mapping_is_scoped_to_job(dubbing_db):
    job = dubbing_db.create_dubbing_job(
        "dub-source", model="speech-2.8-turbo", voice_id="Chinese (Mandarin)_Male_Announcer",
    )
    dubbing_db.upsert_dubbing_speaker(job["id"], "NARRATOR", voice_id="Chinese (Mandarin)_Male_Announcer")
    assert dubbing_db.get_dubbing_speakers(job["id"])[0]["speaker_key"] == "NARRATOR"


def test_non_published_source_cannot_enter_dubbing(dubbing_db):
    assert dubbing_db.add_video("not-published", "Draft", "channel", score=88)
    with pytest.raises(ValueError, match="platform-published"):
        dubbing_db.create_dubbing_job(
            "not-published", model="speech-2.8-turbo", voice_id="Chinese (Mandarin)_Male_Announcer",
        )
