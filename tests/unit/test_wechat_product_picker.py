"""PlaywrightProductPicker 及商品挂载接入的隔离单元测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-10 | Antigravity | 覆盖 PlaywrightProductPicker 契约方法及 _write_product_selection_receipt 回执生成。 |
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, call
import pytest

from video_processing.core.wechat_product_policy import (
    ProductCatalog, ProductDecision, ProductIdentity, ProductLookup, ProductRole,
    get_verified_product_catalog,
)
from video_processing.utils.wechat_product_picker import PlaywrightProductPicker
from video_processing.utils.wechat_product_selection import ProductSelectionResult
from scripts.wechat_uploader import _write_product_selection_receipt


@pytest.fixture
def catalog():
    return get_verified_product_catalog()


class FakeFrame:
    def __init__(self, name="content", url="https://channels.weixin.qq.com/micro/content/post/create"):
        self.name = name
        self.url = url
        self.evaluate_responses = []
        self.evaluates = []

    def evaluate(self, script, arg=None):
        self.evaluates.append((script, arg))
        if self.evaluate_responses:
            resp = self.evaluate_responses.pop(0)
            if isinstance(resp, Exception):
                raise resp
            if callable(resp):
                return resp(script, arg)
            return resp
        return {}


class FakePage:
    def __init__(self, frames=None):
        self.frames = frames or []
        self.wait_for_timeout_calls = []
        self.keyboard = MagicMock()
        self.locators = {}

    def wait_for_timeout(self, ms):
        self.wait_for_timeout_calls.append(ms)

    def locator(self, selector):
        if selector not in self.locators:
            loc = MagicMock()
            loc.count.return_value = 0
            loc.is_visible.return_value = False
            self.locators[selector] = loc
        return self.locators[selector]

    def get_by_text(self, text, exact=False):
        loc = MagicMock()
        loc.last = MagicMock()
        return loc


def test_picker_get_content_frame_found(catalog):
    frame = FakeFrame(name="content", url="https://channels.weixin.qq.com/micro/content/post/create")
    page = FakePage(frames=[frame])
    picker = PlaywrightProductPicker(page, catalog)
    assert picker._get_content_frame() is frame


def test_picker_get_content_frame_fallback(catalog):
    page = FakePage(frames=[])
    picker = PlaywrightProductPicker(page, catalog)
    assert picker._get_content_frame() is page


def test_picker_read_binding_unbound(catalog):
    frame = FakeFrame()
    frame.evaluate_responses = [{"bound": False}]
    page = FakePage(frames=[frame])
    picker = PlaywrightProductPicker(page, catalog)
    assert picker.read_binding(timeout_ms=5000) is None


def test_picker_read_binding_known_product(catalog):
    frame = FakeFrame()
    target_product = catalog.products[ProductRole.FINANCE]
    frame.evaluate_responses = [{"bound": True, "title": target_product.title}]
    page = FakePage(frames=[frame])
    picker = PlaywrightProductPicker(page, catalog)
    bound = picker.read_binding(timeout_ms=5000)
    assert bound == target_product


def test_picker_read_binding_unknown_product(catalog):
    frame = FakeFrame()
    frame.evaluate_responses = [{"bound": True, "title": "未录入的图书"}]
    page = FakePage(frames=[frame])
    picker = PlaywrightProductPicker(page, catalog)
    bound = picker.read_binding(timeout_ms=5000)
    assert bound.product_id == "unknown_bound_id"
    assert bound.title == "未录入的图书"


def test_picker_read_binding_indeterminate_raises(catalog):
    frame = FakeFrame()
    frame.evaluate_responses = [{"bound": None}]
    page = FakePage(frames=[frame])
    picker = PlaywrightProductPicker(page, catalog)
    with pytest.raises(RuntimeError, match="无法识别当前发布表单商品绑定状态"):
        picker.read_binding(timeout_ms=5000)


def test_picker_find_available(catalog):
    frame = FakeFrame()
    # 1: _ensure_modal_open dialog check (open)
    # 2: find evaluation
    frame.evaluate_responses = [True, "AVAILABLE"]
    page = FakePage(frames=[frame])
    picker = PlaywrightProductPicker(page, catalog)
    target = catalog.products[ProductRole.FINANCE]
    status = picker.find(target, timeout_ms=5000)
    assert status == ProductLookup.AVAILABLE


def test_picker_find_conflict(catalog):
    frame = FakeFrame()
    frame.evaluate_responses = [True, "IDENTITY_CONFLICT"]
    page = FakePage(frames=[frame])
    picker = PlaywrightProductPicker(page, catalog)
    target = catalog.products[ProductRole.FINANCE]
    status = picker.find(target, timeout_ms=5000)
    assert status == ProductLookup.IDENTITY_CONFLICT


def test_picker_find_unavailable(catalog):
    frame = FakeFrame()
    frame.evaluate_responses = [True, "UNAVAILABLE"]
    page = FakePage(frames=[frame])
    picker = PlaywrightProductPicker(page, catalog)
    target = catalog.products[ProductRole.FINANCE]
    status = picker.find(target, timeout_ms=5000)
    assert status == ProductLookup.UNAVAILABLE


def test_picker_select_success(catalog):
    frame = FakeFrame()
    # 1: _ensure_modal_open (is_open=True)
    # 2: select click (clicked=True)
    # 3: add click (add_clicked=True)
    # 4: poll status (dialogOpen=False, name="some title")
    frame.evaluate_responses = [
        True,
        True,
        True,
        {"dialogOpen": False, "name": catalog.products[ProductRole.DEFAULT].title},
    ]
    page = FakePage(frames=[frame])
    picker = PlaywrightProductPicker(page, catalog)
    target = catalog.products[ProductRole.DEFAULT]
    picker.select(target, timeout_ms=5000)


def test_picker_select_target_not_found(catalog):
    frame = FakeFrame()
    frame.evaluate_responses = [True, False]
    page = FakePage(frames=[frame])
    picker = PlaywrightProductPicker(page, catalog)
    target = catalog.products[ProductRole.DEFAULT]
    with pytest.raises(RuntimeError, match="未找到要选择的目标商品"):
        picker.select(target, timeout_ms=5000)


def test_picker_cancel_and_clear(catalog):
    frame = FakeFrame()
    # 1: cancelBtn click
    # 2: closeBtn click
    # 3: is_cleared evaluation (True)
    frame.evaluate_responses = [None, None, True]
    page = FakePage(frames=[frame])
    picker = PlaywrightProductPicker(page, catalog)
    assert picker.cancel_and_clear(timeout_ms=5000) is True
    page.keyboard.press.assert_called_with("Escape")


def test_picker_ready_to_submit(catalog):
    frame = FakeFrame()
    frame.evaluate_responses = [True]
    page = FakePage(frames=[frame])
    picker = PlaywrightProductPicker(page, catalog)
    assert picker.ready_to_submit(timeout_ms=5000) is True


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


def test_write_product_selection_receipt_not_required(tmp_path):
    _write_product_selection_receipt(tmp_path, required=False)

    receipt_file = tmp_path / "product_selection_receipt.json"
    assert receipt_file.is_file()
    data = json.loads(receipt_file.read_text(encoding="utf-8"))
    assert data["required"] is False
    assert data["binding_confirmed"] is False
    assert data["state"] == "BLOCKED"
    assert data["reason"] == "UNKNOWN"
