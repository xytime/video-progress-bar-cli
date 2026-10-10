"""选品规则与有界编排的隔离单测；假界面只验证逻辑，不代表真实商品 DOM 验收。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-10 | Codex | 覆盖默认回退、身份冲突、取消失败及共享时间预算；不访问平台。 |
"""

import pytest

from video_processing.core.wechat_product_policy import (
    ProductCatalog, ProductIdentity, ProductLookup, ProductRole,
    WALLSTREET_CHANNEL_ID, choose_product_role,
)
from video_processing.utils.wechat_product_selection import select_required_product


# 明确为虚构 ID 和版本，不是用户账号的商品清单。
FINANCE = ProductIdentity("fictional-finance", "股市技术分析（虚构测试版本）")
NEWS = ProductIdentity("fictional-news", "维特根斯坦（虚构测试版本）")
DEFAULT = ProductIdentity("fictional-default", "思考快与慢（虚构测试版本）")


def catalog():
    return ProductCatalog({
        ProductRole.FINANCE: FINANCE, ProductRole.NEWS: NEWS,
        ProductRole.DEFAULT: DEFAULT,
    })


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakePicker:
    """仅为单测用的界面契约替身；没有浏览器或发表方法。"""

    def __init__(self, rows=(), clock=None):
        self.rows = list(rows)
        self.clock = clock or FakeClock()
        self.binding = None
        self.calls = []
        self.no_effect = set()
        self.find_timeouts = set()
        self.delays = {}
        self.clear_success = True
        self.residual_after_clear = None
        self.ready = True
        self.wrong_binding = None
        self.invalid_lookup = False

    def _call(self, action, timeout_ms):
        assert timeout_ms > 0
        self.calls.append((action, timeout_ms))
        # 可模拟不遵守预算的迟到回执，编排仍须拒绝将其放行。
        self.clock.now += self.delays.get(action, 0)

    def read_binding(self, *, timeout_ms):
        self._call("read", timeout_ms)
        return self.binding

    def find(self, product, *, timeout_ms):
        self._call("find:" + product.product_id, timeout_ms)
        if product.product_id in self.find_timeouts:
            raise TimeoutError("synthetic timeout")
        if self.invalid_lookup:
            return "AVAILABLE"
        matches = [row for row in self.rows if row.product_id == product.product_id]
        if not matches:
            return ProductLookup.UNAVAILABLE
        if len(matches) != 1 or matches[0] != product:
            return ProductLookup.IDENTITY_CONFLICT
        return ProductLookup.AVAILABLE

    def select(self, product, *, timeout_ms):
        self._call("select:" + product.product_id, timeout_ms)
        if product.product_id not in self.no_effect:
            self.binding = self.wrong_binding or product

    def cancel_and_clear(self, *, timeout_ms):
        self._call("clear", timeout_ms)
        if self.clear_success:
            self.binding = self.residual_after_clear
        return self.clear_success

    def ready_to_submit(self, *, timeout_ms):
        self._call("ready", timeout_ms)
        return self.ready


def run(picker, *, category="财经", directory=None, seconds=30):
    return select_required_product(
        decision=choose_product_role(category=category),
        catalog=directory or catalog(), picker=picker,
        timeout_seconds=seconds, clock=picker.clock,
    )


@pytest.mark.parametrize("category,role", [
    ("财经", ProductRole.FINANCE), (" 财经\n", ProductRole.FINANCE),
    ("资讯", ProductRole.NEWS), ("时事", ProductRole.NEWS),
    ("科技", ProductRole.DEFAULT), ("健康", ProductRole.DEFAULT),
    ("教育", ProductRole.DEFAULT), ("生活", ProductRole.DEFAULT),
    (None, ProductRole.DEFAULT), ("", ProductRole.DEFAULT),
    ("财经/科技", ProductRole.DEFAULT), ("ENGLISH_WORLD_SHORT", ProductRole.DEFAULT),
])
def test_topic_mapping(category, role):
    assert choose_product_role(category=category).role is role


def test_wallstreet_uses_stable_channel_id_and_has_priority():
    assert choose_product_role(category="资讯", source_channel_id=WALLSTREET_CHANNEL_ID).role is ProductRole.FINANCE
    assert choose_product_role(category=None, source_channel_id="华尔街事实炸弹").role is ProductRole.DEFAULT


@pytest.mark.parametrize("identifier,title", [("", "书"), (" id", "书"), ("id", ""), ("id", "书 ")])
def test_catalog_rejects_incomplete_identity(identifier, title):
    with pytest.raises(ValueError):
        ProductIdentity(identifier, title)


def test_catalog_requires_default_and_unique_ids():
    with pytest.raises(ValueError):
        ProductCatalog({ProductRole.FINANCE: FINANCE})
    with pytest.raises(ValueError):
        ProductCatalog({ProductRole.FINANCE: DEFAULT, ProductRole.DEFAULT: DEFAULT})
    with pytest.raises(ValueError):
        ProductCatalog({"default": DEFAULT})


def test_catalog_is_immutable_and_does_not_keep_mutable_input():
    data = {ProductRole.DEFAULT: DEFAULT}
    directory = ProductCatalog(data)
    data.clear()
    assert directory.products[ProductRole.DEFAULT] == DEFAULT
    with pytest.raises(TypeError):
        directory.products[ProductRole.NEWS] = NEWS


@pytest.mark.parametrize("rows", [(NEWS, DEFAULT, FINANCE), (FINANCE, NEWS, DEFAULT)])
def test_list_order_cannot_change_selected_product(rows):
    result = run(FakePicker(rows))
    assert result.binding_confirmed
    assert result.actual == FINANCE
    assert result.attempts == 1


@pytest.mark.parametrize("category,expected", [("财经", FINANCE), ("资讯", NEWS), ("教育", DEFAULT)])
def test_each_video_is_matched_independently(category, expected):
    assert run(FakePicker((FINANCE, NEWS, DEFAULT)), category=category).actual == expected


def test_missing_target_falls_back_to_default():
    result = run(FakePicker((NEWS, DEFAULT)))
    assert result.binding_confirmed
    assert result.requested == FINANCE
    assert result.actual == DEFAULT
    assert result.fallback_reason == "TARGET_UNAVAILABLE"
    assert result.attempts == 2


def test_missing_target_configuration_also_falls_back():
    result = run(FakePicker((DEFAULT,)), directory=ProductCatalog({ProductRole.DEFAULT: DEFAULT}))
    assert result.binding_confirmed
    assert result.actual == DEFAULT
    assert result.decision.role is ProductRole.FINANCE
    assert result.fallback_reason == "TARGET_NOT_CONFIGURED"


def test_click_without_binding_is_not_success_and_uses_default():
    picker = FakePicker((FINANCE, DEFAULT))
    picker.no_effect.add(FINANCE.product_id)
    result = run(picker)
    assert result.actual == DEFAULT
    assert result.fallback_reason == "BINDING_NOT_APPLIED"


def test_no_default_means_blocked_never_empty_publish():
    result = run(FakePicker(()))
    assert not result.binding_confirmed
    assert result.state == "BLOCKED"
    assert result.reason == "DEFAULT_PRODUCT_NOT_BOUND"
    assert result.attempts == 2


@pytest.mark.parametrize("rows", [
    (ProductIdentity(FINANCE.product_id, "其他版本"), DEFAULT),
    (FINANCE, FINANCE, DEFAULT),
])
def test_conflicting_id_or_duplicate_rows_cannot_be_selected(rows):
    picker = FakePicker(rows)
    result = run(picker)
    assert result.reason == "PRODUCT_IDENTITY_CONFLICT"
    assert not result.binding_confirmed
    assert not any(action.startswith("select:") for action, _ in picker.calls)


def test_same_title_different_id_is_not_the_target():
    picker = FakePicker((ProductIdentity("other-id", FINANCE.title), DEFAULT))
    result = run(picker)
    assert result.actual == DEFAULT
    assert not any(action == "select:other-id" for action, _ in picker.calls)


def test_wrong_binding_stops_without_trying_to_cover_it_up():
    picker = FakePicker((FINANCE, DEFAULT))
    picker.wrong_binding = NEWS
    result = run(picker)
    assert result.reason == "BINDING_IDENTITY_CONFLICT"
    assert result.actual == NEWS
    assert not result.binding_confirmed
    assert result.attempts == 1


def test_preexisting_foreign_link_is_not_overwritten():
    picker = FakePicker((FINANCE, DEFAULT))
    picker.binding = NEWS
    result = run(picker)
    assert result.reason == "EXISTING_LINK_CONFLICT"
    assert result.attempts == 0


def test_existing_matching_binding_needs_ready_form():
    picker = FakePicker((FINANCE,))
    picker.binding = FINANCE
    assert run(picker).binding_confirmed
    picker.ready = False
    assert not run(picker).binding_confirmed


@pytest.mark.parametrize("residual", [None, NEWS])
def test_cancel_failure_or_residual_link_prevents_default_attempt(residual):
    picker = FakePicker((DEFAULT,))
    picker.clear_success = residual is not None
    picker.residual_after_clear = residual
    result = run(picker)
    assert result.reason in {"CANNOT_CONFIRM_CLEARED", "RESIDUAL_LINK_AFTER_CANCEL"}
    assert result.attempts == 1
    assert not result.binding_confirmed


def test_modal_not_closed_is_not_ready_to_submit():
    picker = FakePicker((FINANCE,))
    picker.ready = False
    assert run(picker).reason == "FORM_NOT_READY"


@pytest.mark.parametrize("replacement", [None, NEWS])
@pytest.mark.parametrize("preexisting", [False, True])
def test_binding_change_when_modal_closes_is_not_allowed(replacement, preexisting):
    class ChangedOnClose(FakePicker):
        def ready_to_submit(self, *, timeout_ms):
            self._call("ready", timeout_ms)
            self.binding = replacement
            return True
    picker = ChangedOnClose((FINANCE, DEFAULT))
    if preexisting:
        picker.binding = FINANCE
    result = run(picker)
    assert result.reason == "BINDING_CHANGED_BEFORE_SUBMIT"
    assert not result.binding_confirmed


def test_default_retries_once_and_cannot_loop():
    picker = FakePicker((DEFAULT,))
    picker.no_effect.add(DEFAULT.product_id)
    result = run(picker, category="科技")
    assert result.attempts == 2
    assert not result.binding_confirmed
    assert sum(action.startswith("select:") for action, _ in picker.calls) == 2


def test_operation_timeout_with_remaining_budget_can_use_default():
    picker = FakePicker((DEFAULT,))
    picker.find_timeouts.add(FINANCE.product_id)
    picker.delays["find:" + FINANCE.product_id] = 5
    result = run(picker)
    assert result.actual == DEFAULT
    assert result.fallback_reason == "TARGET_OPERATION_TIMEOUT"
    assert all(timeout <= 25000 for action, timeout in picker.calls if action == "clear")


def test_attempts_and_cleanup_share_one_budget():
    picker = FakePicker((DEFAULT,))
    picker.delays["find:" + FINANCE.product_id] = 20
    picker.delays["clear"] = 2
    picker.delays["find:" + DEFAULT.product_id] = 9
    result = run(picker)
    assert result.reason == "PRODUCT_SELECTION_BUDGET_EXHAUSTED"
    assert not result.binding_confirmed
    default_timeout = [timeout for action, timeout in picker.calls if action == "find:" + DEFAULT.product_id]
    assert default_timeout == [8000]
    assert not any(action == "select:" + DEFAULT.product_id for action, _ in picker.calls)


def test_late_success_after_budget_does_not_authorize_publish():
    picker = FakePicker((FINANCE,))
    picker.delays["ready"] = 30
    result = run(picker)
    assert result.reason == "PRODUCT_SELECTION_BUDGET_EXHAUSTED"
    assert not result.binding_confirmed


def test_missing_current_ui_adapter_blocks_without_any_browser():
    result = select_required_product(decision=choose_product_role(category="财经"), catalog=catalog(), picker=None)
    assert result.reason == "CURRENT_UI_ADAPTER_NOT_VERIFIED"
    assert not result.binding_confirmed
    assert result.attempts == 0


def test_invalid_lookup_cannot_be_treated_as_available():
    picker = FakePicker((FINANCE,))
    picker.invalid_lookup = True
    assert run(picker).reason == "INVALID_LOOKUP_RESULT"


def test_unknown_readback_is_not_assumed_empty_and_exception_is_redacted():
    class UnknownReadback(FakePicker):
        def read_binding(self, *, timeout_ms):
            raise RuntimeError("synthetic private exception text")
    result = run(UnknownReadback((FINANCE,)))
    assert result.reason == "ADAPTER_ERROR:RuntimeError"
    assert "private" not in result.reason
    assert not result.binding_confirmed


@pytest.mark.parametrize("seconds", [0, -1, 61, float("inf"), float("nan")])
def test_invalid_budget_is_rejected(seconds):
    with pytest.raises(ValueError):
        run(FakePicker((FINANCE,)), seconds=seconds)
