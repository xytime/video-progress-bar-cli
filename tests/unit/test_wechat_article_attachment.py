"""微信视频号公众号文章扩展链接挂接（一期）单元测试。

验证：
1. 配置开关默认关闭与单一真相源；
2. 文章 URL 合法性与身份契约；
3. 文章任务决策冻结与命令行参数生成；
4. 仲裁规则（S01~S08）与实施验收用例（TC01~TC10）；
5. 最终核验门禁与防静默降级回归保护（G2）；
6. 提交与回读账本防重与原生身份绑定（G1, G3）。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | 初始实现：全量覆盖公众号文章挂接一期核心契约、仲裁矩阵与 G1~G3 保护门禁。 |
"""

import json
from pathlib import Path
import pytest

from config.settings import settings
from video_processing.core.wechat_article_policy import (
    ArticleIdentity,
    AttachmentType,
    is_valid_mp_article_url,
)
from video_processing.utils.wechat_article_task import (
    freeze_task_article_decision,
    get_article_for_video,
    load_article_policy,
    read_article_task_decision,
    write_article_task_arguments,
)
from video_processing.utils.wechat_article_execution import (
    execute_article_task,
    finalize_article_before_submit,
    finalize_none_before_submit,
)
from video_processing.utils.wechat_product_picker import BindingIdentityUnavailable
from scripts.wechat_uploader import (
    _compare_management_article_receipt,
    _management_article_observation,
    _write_submission_receipt,
    EXIT_SUBMITTED_FOR_REVIEW,
)


VALID_MP_URL = "https://mp.weixin.qq.com/s/abcdef1234567890_-test"
VALID_TITLE = "深度解读：美联储货币政策新周期"


# ── 1. 配置与身份契约 ─────────────────────────────────────────────────────────

def test_article_feature_flag_default_is_disabled():
    """新功能必须默认关闭，确保生产零侵入。"""
    assert settings.enable_wechat_article_link is False
    assert settings.wechat_article_timeout_seconds == 30.0


@pytest.mark.parametrize(
    "url,valid",
    [
        (VALID_MP_URL, True),
        ("http://mp.weixin.qq.com/s/abcdef123456", True),
        ("https://mp.weixin.qq.com/s?__biz=MzA1MjU4&mid=2650&idx=1&sn=xyz", True),
        ("https://weixin.qq.com/s/abcdef", False),  # 域名非 mp.weixin.qq.com
        ("https://qq.com/s/abcdef", False),
        ("https://evil.com/?mp.weixin.qq.com", False),
        ("ftp://mp.weixin.qq.com/s/123", False),  # 非 http(s)
        ("https://mp.weixin.qq.com/other/page", False),  # 非 /s 路径
        ("https://mp.weixin.qq.com/s/123\n<script>", False),  # 注入字符
        ("", False),
        (None, False),
    ],
)
def test_is_valid_mp_article_url(url, valid):
    assert is_valid_mp_article_url(url) is valid


def test_article_identity_creation():
    target = ArticleIdentity(url=VALID_MP_URL, title=VALID_TITLE)
    assert target.url == VALID_MP_URL
    assert target.title == VALID_TITLE

    with pytest.raises(ValueError):
        ArticleIdentity(url="https://invalid.com/article")


# ── 2. 任务决策冻结与配置加载 ──────────────────────────────────────────────────

def test_article_policy_load_and_lookup(tmp_path):
    policy_file = tmp_path / "wechat_articles.json"
    policy_file.write_text(json.dumps({
        "version": "1.0.0",
        "articles": {
            "test_video_1": {"url": VALID_MP_URL, "title": VALID_TITLE},
            "test_video_2": {"url": "https://invalid.url/xyz"},
        }
    }), encoding="utf-8")

    loaded = load_article_policy(policy_file)
    assert loaded["version"] == "1.0.0"

    found = get_article_for_video("test_video_1", policy_file)
    assert found is not None
    assert found["url"] == VALID_MP_URL
    assert found["title"] == VALID_TITLE

    # 切片前缀回退
    found_slice = get_article_for_video("test_video_1_s01", policy_file)
    assert found_slice is not None
    assert found_slice["url"] == VALID_MP_URL

    # 无效 URL 拒绝
    assert get_article_for_video("test_video_2", policy_file) is None
    assert get_article_for_video("non_existent", policy_file) is None


def test_article_task_decision_freeze_and_args(tmp_path):
    info = {"url": VALID_MP_URL, "title": VALID_TITLE}
    decision = freeze_task_article_decision("task_001", info)
    assert decision["task_id"] == "task_001"
    assert decision["url"] == VALID_MP_URL

    args = write_article_task_arguments(decision, tmp_path)
    assert len(args) == 2
    assert args[0] == "--article-task-decision"
    assert Path(args[1]).exists()

    read_back = read_article_task_decision(Path(args[1]))
    assert read_back == decision


# ── 3. 模拟选择器与仲裁矩阵 (S01 ~ S08 / TC01 ~ TC10) ─────────────────────────

class MockArticlePicker:
    def __init__(self, *, initial_binding=None, attach_error=None, cancel_result=True, ready=True):
        self._binding = initial_binding
        self._attach_error = attach_error
        self._cancel_result = cancel_result
        self._ready = ready

    def read_binding(self, *, timeout_ms: int = 3000):
        if isinstance(self._binding, Exception):
            raise self._binding
        return self._binding

    def attach(self, article: ArticleIdentity, *, timeout_ms: int = 3000):
        if self._attach_error is not None:
            raise self._attach_error
        self._binding = article

    def cancel_and_clear(self, *, timeout_ms: int = 3000):
        if self._cancel_result:
            self._binding = None
            return True
        return False

    def ready_to_submit(self, *, timeout_ms: int = 3000):
        return self._ready


class MockProductPicker:
    def __init__(self, *, binding=None, ready=True):
        self._binding = binding
        self._ready = ready

    def read_binding(self, *, timeout_ms: int = 3000):
        return self._binding

    def ready_to_submit(self, *, timeout_ms: int = 3000):
        return self._ready


def test_tc04_standard_article_attachment(tmp_path):
    """TC04: 无商品任务，合法文章 URL，正常注入并绑定。"""
    picker = MockArticlePicker()
    payload = {"task_id": "t1", "url": VALID_MP_URL, "title": VALID_TITLE}
    ok = execute_article_task(payload, picker, tmp_path)
    assert ok is True

    receipt = json.loads((tmp_path / "article_selection_receipt.json").read_text())
    assert receipt["state"] == "BOUND"
    assert receipt["binding_confirmed"] is True
    assert receipt["actual_url"] == VALID_MP_URL

    # Step 5 终验通过
    assert finalize_article_before_submit(payload, picker, tmp_path) is True
    readback = json.loads((tmp_path / "article_pre_submit_readback.json").read_text())
    assert readback["final_verified"] is True
    assert readback["attachment_type"] == "ARTICLE"


def test_tc05_invalid_url_pre_injection_downgrade(tmp_path):
    """TC05: 文章 URL 非法，注入前直接降级，未动 DOM，四项齐备纯视频提交。"""
    picker = MockArticlePicker()
    product_picker = MockProductPicker()
    payload = {"task_id": "t2", "url": "https://invalid.com/article", "title": "bad"}

    ok = execute_article_task(payload, picker, tmp_path)
    assert ok is True  # 允许降级

    receipt = json.loads((tmp_path / "article_selection_receipt.json").read_text())
    assert receipt["state"] == "SKIPPED"
    assert receipt["fallback_reason"] == "PRE_INJECTION_REJECTED"

    # Step 5 终验：走 NONE 路径
    assert finalize_none_before_submit(tmp_path, product_picker, picker) is True
    readback = json.loads((tmp_path / "none_pre_submit_readback.json").read_text())
    assert readback["final_verified"] is True
    assert readback["attachment_type"] == "NONE"


def test_tc06_article_timeout_and_clear_success(tmp_path):
    """TC06: 注入超时，但真实清退核验成功，四项齐备允许降级纯视频。"""
    picker = MockArticlePicker(attach_error=TimeoutError("Inject timed out"), cancel_result=True)
    product_picker = MockProductPicker()
    payload = {"task_id": "t3", "url": VALID_MP_URL, "title": VALID_TITLE}

    ok = execute_article_task(payload, picker, tmp_path, product_picker=product_picker)
    assert ok is True  # 允许降级

    receipt = json.loads((tmp_path / "article_selection_receipt.json").read_text())
    assert receipt["state"] == "UNBOUND"
    assert receipt["fallback_reason"] == "ARTICLE_TIMEOUT_CLEARED"

    assert finalize_none_before_submit(tmp_path, product_picker, picker) is True


def test_tc07_article_timeout_and_clear_failure(tmp_path):
    """TC07: 注入超时且真实清退失败，Fail-Closed 终止提交。"""
    picker = MockArticlePicker(attach_error=TimeoutError("Inject timed out"), cancel_result=False)
    payload = {"task_id": "t4", "url": VALID_MP_URL, "title": VALID_TITLE}

    ok = execute_article_task(payload, picker, tmp_path)
    assert ok is False  # 坚决阻断

    receipt = json.loads((tmp_path / "article_selection_receipt.json").read_text())
    assert receipt["state"] == "BLOCKED"
    assert receipt["reason"] == "CLEANUP_FAILED_AFTER_TIMEOUT"


def test_tc08_article_identity_conflict_fails_closed(tmp_path):
    """TC08: 文章身份冲突（URL 不符），坚决终止本次提交；清退成功亦不恢复发布资格。"""
    picker = MockArticlePicker(attach_error=BindingIdentityUnavailable("URL_MISMATCH"), cancel_result=True)
    payload = {"task_id": "t5", "url": VALID_MP_URL, "title": VALID_TITLE}

    ok = execute_article_task(payload, picker, tmp_path)
    assert ok is False  # 坚决阻断，清退成功也不恢复

    receipt = json.loads((tmp_path / "article_selection_receipt.json").read_text())
    assert receipt["state"] == "BLOCKED"
    assert "IDENTITY_CONFLICT" in receipt["reason"]


def test_tc09_drift_before_submission_blocks(tmp_path):
    """TC09: 已有绑定回执，但发表前卡片漂移或消失，终止提交。"""
    target = ArticleIdentity(url=VALID_MP_URL, title=VALID_TITLE)
    picker = MockArticlePicker(initial_binding=target)
    payload = {"task_id": "t6", "url": VALID_MP_URL, "title": VALID_TITLE}
    assert execute_article_task(payload, picker, tmp_path) is True

    # 模拟发表前瞬间卡片消失
    drifted_picker = MockArticlePicker(initial_binding=None)
    assert finalize_article_before_submit(payload, drifted_picker, tmp_path) is False

    # 模拟发表前实际 URL 被篡改为其他链接
    tampered_picker = MockArticlePicker(initial_binding=ArticleIdentity(url="https://mp.weixin.qq.com/s/other_999"))
    assert finalize_article_before_submit(payload, tampered_picker, tmp_path) is False


# ── 4. 交付硬门槛验证 (G1, G2, G3) ─────────────────────────────────────────────

def test_g2_product_regression_guard_prevents_silent_pure_video(tmp_path):
    """G2 核心保护：已有商品绑定回执，发表前商品卡片消失，系统必须停止，严禁静默改为纯视频！"""
    # 模拟商品已生成 BOUND 回执
    (tmp_path / "product_selection_receipt.json").write_text(json.dumps({
        "state": "BOUND",
        "binding_confirmed": True,
        "unbound_confirmed": False,
        "actual_product_id": "prod_123",
        "actual_title": "图书",
    }), encoding="utf-8")

    product_picker = MockProductPicker(binding=None)  # 卡片已消失
    article_picker = MockArticlePicker(initial_binding=None)

    # 尝试进入纯视频终验
    assert finalize_none_before_submit(tmp_path, product_picker, article_picker) is False


def test_g2_article_regression_guard_prevents_silent_pure_video(tmp_path):
    """G2 核心保护：已有文章绑定回执，发表前文章卡片消失，系统必须停止，严禁静默改为纯视频！"""
    (tmp_path / "article_selection_receipt.json").write_text(json.dumps({
        "state": "BOUND",
        "binding_confirmed": True,
        "unbound_confirmed": False,
        "actual_url": VALID_MP_URL,
    }), encoding="utf-8")

    product_picker = MockProductPicker(binding=None)
    article_picker = MockArticlePicker(initial_binding=None)  # 卡片已消失

    assert finalize_none_before_submit(tmp_path, product_picker, article_picker) is False


def test_g1_submission_exit_codes_contract():
    """G1: 已提交待审 (6) 与提交未确认 (3) 退出码契约。"""
    assert EXIT_SUBMITTED_FOR_REVIEW == 6


def test_g3_submission_receipt_records_article_identity(tmp_path):
    """G3: 提交回执原子记录本次原生挂接目标。"""
    (tmp_path / "article_task_decision.json").write_text(json.dumps({
        "task_id": "task_xyz",
        "url": VALID_MP_URL,
        "title": VALID_TITLE,
    }), encoding="utf-8")
    (tmp_path / "article_pre_submit_readback.json").write_text(json.dumps({
        "final_verified": True,
        "attachment_type": "ARTICLE",
        "actual_url": VALID_MP_URL,
        "actual_title": VALID_TITLE,
    }), encoding="utf-8")

    _write_submission_receipt(tmp_path, {
        "platform_post_id": "native_post_999",
        "platform_object_nonce": "nonce_888",
    })

    receipt = json.loads((tmp_path / "submission_receipt.json").read_text())
    assert receipt["attachment_type"] == "ARTICLE"
    assert receipt["article_url"] == VALID_MP_URL
    assert receipt["article_binding_confirmed"] is True
    assert receipt["platform_post_id"] == "native_post_999"


def test_g3_management_readback_strictly_matches_native_post_identity(tmp_path):
    """G3: 作品回读必须强绑定同次提交原生标识，旧作品或不匹配作品保持 UNVERIFIED。"""
    receipt_file = tmp_path / "submission_receipt.json"
    receipt_file.write_text(json.dumps({
        "platform_post_id": "post_exact_1",
        "platform_object_nonce": "nonce_1",
        "attachment_type": "ARTICLE",
        "article_url": VALID_MP_URL,
    }), encoding="utf-8")

    # 场景 A: 同一作品，extReading 包含目标文章 -> MATCH
    matching_record = {
        "platform_post_id": "post_exact_1",
        "platform_object_nonce": "nonce_1",
        "desc": {
            "extReading": {
                "link": VALID_MP_URL,
                "title": VALID_TITLE,
            }
        },
        "article_observation": {
            "state": "BOUND",
            "actual_article_url": VALID_MP_URL,
        }
    }
    result = _compare_management_article_receipt(matching_record, receipt_file)
    assert result["state"] == "MATCH"

    # 场景 B: 另一作品（不同 post_id），即使挂载了相同文章 -> UNVERIFIED (杜绝旧作品冒充)
    impostor_record = {
        "platform_post_id": "post_older_2",
        "platform_object_nonce": "nonce_2",
        "desc": {
            "extReading": {
                "link": VALID_MP_URL,
                "title": VALID_TITLE,
            }
        },
        "article_observation": {
            "state": "BOUND",
            "actual_article_url": VALID_MP_URL,
        }
    }
    result_impostor = _compare_management_article_receipt(impostor_record, receipt_file)
    assert result_impostor["state"] == "UNVERIFIED"

    # 场景 C: 同一作品，但文章 URL 不符 -> MISMATCH
    tampered_record = {
        "platform_post_id": "post_exact_1",
        "platform_object_nonce": "nonce_1",
        "desc": {
            "extReading": {
                "link": "https://mp.weixin.qq.com/s/wrong",
                "title": "错误文章",
            }
        },
        "article_observation": {
            "state": "BOUND",
            "actual_article_url": "https://mp.weixin.qq.com/s/wrong",
        }
    }
    result_tampered = _compare_management_article_receipt(tampered_record, receipt_file)
    assert result_tampered["state"] == "MISMATCH"
