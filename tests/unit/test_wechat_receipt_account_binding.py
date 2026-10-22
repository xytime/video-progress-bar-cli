"""原创表单凭证不能当作投稿回执；只有真实原生 ID 绑定账户调度。"""
import json
from scripts.wechat_uploader import _write_original_declaration_receipt, _write_submission_receipt
from video_processing.core import wechat_session_lock


def test_original_receipt_does_not_bind_publication(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(wechat_session_lock, "bind_current_wechat_publication", lambda *args: calls.append(args))
    _write_original_declaration_receipt(tmp_path, required=True, requested=True, applied=True)
    assert json.loads((tmp_path / "original_declaration_receipt.json").read_text())["applied_in_ui"]
    assert calls == []


def test_submission_receipt_binds_persisted_native_id(tmp_path, monkeypatch):
    calls = []
    def bind(native_id, path):
        assert json.loads(path.read_text())["platform_post_id"] == native_id
        calls.append(native_id)
    monkeypatch.setattr(wechat_session_lock, "bind_current_wechat_publication", bind)
    _write_submission_receipt(tmp_path, {"platform_post_id": "native-id"}, expected_attachment="NONE")
    assert calls == ["native-id"]
