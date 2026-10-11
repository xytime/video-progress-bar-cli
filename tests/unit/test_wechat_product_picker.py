"""适配器异常、时限与回执测试；实际 DOM 逻辑另用隔离浏览器执行。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-12 | Codex | 验证正式挂商品验收开关经 CLI 传入，日常默认关闭，逐次证据保留。 |
"""
import json
from unittest.mock import MagicMock
import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from video_processing.core.wechat_product_policy import ProductDecision, ProductIdentity, ProductRole
from video_processing.utils.wechat_product_picker import PlaywrightProductPicker, BindingIdentityUnavailable
from video_processing.utils.wechat_product_selection import ProductSelectionResult
from scripts.wechat_uploader import _write_product_selection_receipt


def test_playwright_timeout_normalized():
    page = MagicMock(frames=[])
    page.locator.return_value.count.return_value = 0
    page.locator.return_value.first = page.locator.return_value
    page.locator.return_value.evaluate.side_effect = PlaywrightTimeoutError("test only")
    with pytest.raises(TimeoutError):
        PlaywrightProductPicker(page).read_binding(timeout_ms=100)


def test_binding_does_not_infer_id_from_catalog():
    page = MagicMock(frames=[])
    page.locator.return_value.count.return_value = 0
    page.locator.return_value.first = page.locator.return_value
    page.locator.return_value.evaluate.return_value = {"title": "同名书"}
    with pytest.raises(BindingIdentityUnavailable):
        PlaywrightProductPicker(page, catalog=MagicMock()).read_binding(timeout_ms=100)


def test_expired_budget_does_not_touch_dom():
    page = MagicMock(frames=[])
    page.locator.return_value.count.return_value = 0
    page.locator.return_value.first = page.locator.return_value
    with pytest.raises(TimeoutError):
        PlaywrightProductPicker(page).read_binding(timeout_ms=0)
    page.locator.assert_not_called()


def test_nested_operations_share_deadline():
    page = MagicMock(frames=[])
    page.locator.return_value.count.return_value = 0
    page.locator.return_value.first = page.locator.return_value
    times = iter([0, 0.01, 0.10])
    page.locator.return_value.evaluate.return_value = True
    picker = PlaywrightProductPicker(page, clock=lambda: next(times))
    with pytest.raises(TimeoutError):
        picker.find(ProductIdentity("id", "书"), timeout_ms=100)
    assert page.locator.return_value.evaluate.call_args.kwargs["timeout"] <= 90


def test_write_product_selection_receipt_required_bound(tmp_path):
    decision = ProductDecision(ProductRole.FINANCE, "WALLSTREET_CHANNEL")
    product = ProductIdentity("10000028955239", "股市趋势技术分析")
    result = ProductSelectionResult(
        decision=decision,
        requested=product,
        actual=product,
        state="BOUND",
        reason="BINDING_VERIFIED",
        fallback_reason=None,
        attempts=1,
        elapsed_seconds=3.5,
        attempt_records=({'product_id':product.product_id,'title':product.title,'outcome':'BOUND'},),
    )
    _write_product_selection_receipt(tmp_path, required=True, result=result)

    receipt_file = tmp_path / "product_selection_receipt.json"
    assert receipt_file.is_file()
    data = json.loads(receipt_file.read_text(encoding="utf-8"))
    assert data["required"] is True
    assert data["binding_confirmed"] is True
    assert data["state"] == "BOUND"
    assert data["reason"] == "BINDING_VERIFIED"
    assert data["role"] == "finance"
    assert data["requested_product_id"] == "10000028955239"
    assert data["actual_product_id"] == "10000028955239"
    assert data["attempts"] == 1
    assert data["elapsed_seconds"] == 3.5
    assert data['attempt_records'] == list(result.attempt_records)


def test_write_product_selection_receipt_not_required(tmp_path):
    _write_product_selection_receipt(tmp_path, required=False)

    receipt_file = tmp_path / "product_selection_receipt.json"
    assert receipt_file.is_file()
    data = json.loads(receipt_file.read_text(encoding="utf-8"))
    assert data["required"] is False
    assert data["binding_confirmed"] is False
    assert data["state"] == "BLOCKED"
    assert data["reason"] == "UNKNOWN"


@pytest.mark.parametrize('flags', [[], ['--require-bound-product']])
def test_formal_binding_verification_cli_is_opt_in(monkeypatch, flags):
    from scripts import wechat_uploader
    import sys
    calls=[]
    monkeypatch.setattr(sys,'argv',['wechat_uploader.py','--stop-before-submit',*flags])
    monkeypatch.setattr(wechat_uploader,'run_uploader',lambda **kw:calls.append(kw) or 0)
    with pytest.raises(SystemExit) as result:
        wechat_uploader.main()
    assert result.value.code == 0
    assert calls[0]['require_bound_product'] is bool(flags)
    assert calls[0]['stop_before_submit'] is True
