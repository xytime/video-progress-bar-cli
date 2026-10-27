"""坏例快照必须可追溯、幂等，不能覆盖或跟随链接。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 覆盖内容寻址、完整历史、并发保存、篡改及链接边界。 |
"""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import pytest

from video_processing.utils.subtitle_bad_cases import iter_bad_cases, load_bad_case, save_bad_case


def payload():
    return {"segments": [{"text": "Oil costs $115.", "start": 0, "end": 2}],
            "translations": ["油价为1150亿美元。"], "candidate_sha256": "a" * 64,
            "summary_sha256": "b" * 64, "media_sha256": "c" * 64,
            "asr_sha256": "d" * 64, "contract_sha256": "e" * 64,
            "report": {"status": "accepted_with_warnings", "issues": [{"segment_number": 1,
                       "code": "NUMBER_MAGNITUDE_MISMATCH"}]},
            "repair_history": [{"strategy": "targeted_retranslation", "executed": True,
                                "segment_numbers": [1]}]}


def test_snapshot_keeps_original_evidence_and_defaults_unreviewed(tmp_path):
    original = payload()
    ref = save_bad_case(tmp_path, original)
    path = Path(ref["path"])
    loaded = load_bad_case(path, ref["sha256"])
    assert loaded["payload"] == original
    assert loaded["review"] == {"status": "unreviewed", "ground_truth": False}
    assert ref["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert path == tmp_path / "cases" / ref["case_id"][:2] / (ref["case_id"] + ".json")
    assert list(iter_bad_cases(tmp_path)) == [loaded]


def test_same_payload_is_idempotent_without_rewriting_file(tmp_path):
    first = save_bad_case(tmp_path, payload())
    path = Path(first["path"])
    inode, mtime = path.stat().st_ino, path.stat().st_mtime_ns
    assert save_bad_case(tmp_path, payload()) == first
    assert (path.stat().st_ino, path.stat().st_mtime_ns) == (inode, mtime)
    changed = payload()
    changed["translations"] = ["油价为115美元。"]
    second = save_bad_case(tmp_path, changed)
    assert second["case_id"] != first["case_id"]
    assert len(list(iter_bad_cases(tmp_path))) == 2


def test_parallel_save_create_if_absent(tmp_path):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: save_bad_case(tmp_path, payload()), range(8)))
    assert all(value == results[0] for value in results)
    assert len(list(iter_bad_cases(tmp_path))) == 1


def test_changed_bytes_not_silently_overwritten(tmp_path):
    ref = save_bad_case(tmp_path, payload())
    path = Path(ref["path"])
    path.chmod(0o600)
    path.write_text("{}"); corrupt = path.read_bytes()
    with pytest.raises(ValueError, match="sha256_mismatch"):
        load_bad_case(path, ref["sha256"])
    with pytest.raises(ValueError, match="existing_content_mismatch"):
        save_bad_case(tmp_path, payload())
    assert path.read_bytes() == corrupt


@pytest.mark.parametrize("location", ["root", "cases", "shard", "file"])
def test_reject_symlink_at_every_store_level(tmp_path, location):
    root = tmp_path / "store"
    ref = save_bad_case(root, payload())
    path = Path(ref["path"])
    item = {"root": root, "cases": root / "cases", "shard": path.parent, "file": path}[location]
    relocated = item.with_name(item.name + "-real")
    item.rename(relocated)
    item.symlink_to(relocated, target_is_directory=relocated.is_dir())
    with pytest.raises(ValueError, match="symlink"):
        save_bad_case(root, payload())
    with pytest.raises(ValueError, match="symlink"):
        list(iter_bad_cases(root))


def test_missing_leaf_does_not_hide_symlink_ancestor(tmp_path):
    real = tmp_path / "real"; real.mkdir()
    alias = tmp_path / "alias"; alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        save_bad_case(alias / "not-yet-created", payload())
    assert not (real / "not-yet-created").exists()


def test_filename_and_payload_content_are_both_bound(tmp_path):
    ref = save_bad_case(tmp_path, payload())
    path = Path(ref["path"])
    alternate = path.with_name("f" * 64 + ".json")
    alternate.write_bytes(path.read_bytes())
    with pytest.raises(ValueError, match="filename"):
        load_bad_case(alternate)
    changed = json.loads(path.read_bytes())
    changed["payload"]["translations"] = ["篡改"]
    path.chmod(0o600); path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="content_identity"):
        load_bad_case(path)


def test_unknown_tmp_files_not_cases_but_tmp_symlinks_rejected(tmp_path):
    ref = save_bad_case(tmp_path, payload())
    shard = Path(ref["path"]).parent
    temporary = shard / ".case-inprogress.tmp"; temporary.write_text("partial")
    assert len(list(iter_bad_cases(tmp_path))) == 1
    temporary.unlink(); temporary.symlink_to(Path(ref["path"]))
    with pytest.raises(ValueError, match="symlink"):
        list(iter_bad_cases(tmp_path))


def test_empty_store_is_empty_and_invalid_payload_rejected(tmp_path):
    assert list(iter_bad_cases(tmp_path)) == []
    with pytest.raises(ValueError, match="payload_not_object"):
        save_bad_case(tmp_path, [])
    with pytest.raises(ValueError):
        save_bad_case(tmp_path, {"number": float("nan")})
