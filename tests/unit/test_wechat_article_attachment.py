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
| 1.2.0 | 2026-10-13 | Antigravity | 补齐 P1 串联测试：验证普通文章超时清退后真实回执写入 requested_url 并成功通过 _finalize_submission_attachments 降级 NONE；补充 URL/配置漂移、强制文章与清退失败反向用例。 |
| 1.1.0 | 2026-10-12 | Antigravity | 补充 P1/P2 回归测试：NONE 分支旧回执/配置漂移/应有回执缺失拒绝测试；上传器开关隔离与显式参数阻断测试；证据目录复用防 NONE 覆盖测试。 |
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
    _compare_management_product_receipt,
    _finalize_submission_attachments,
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
        ("https://mp.weixin.qq.com/settings", False),  # 路径边界漏洞：非文章路径
        ("https://mp.weixin.qq.com/shop", False),  # 路径边界漏洞：非文章路径
        ("https://mp.weixin.qq.com/service", False),  # 路径边界漏洞：非文章路径
        ("https://attacker@mp.weixin.qq.com/s/123", False),  # 凭据注入
        ("https://mp.weixin.qq.com:8080/s/123", False),  # 非标端口
        ("https://mp.weixin.qq.com/s/123 with space", False),  # 空格
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
    assert len(loaded["digest"]) == 64

    found = get_article_for_video("test_video_1", policy_file)
    assert found is not None
    assert found["url"] == VALID_MP_URL
    assert found["title"] == VALID_TITLE
    assert found["config_version"] == "1.0.0"
    assert found["config_digest"] == loaded["digest"]

    # 切片前缀回退
    found_slice = get_article_for_video("test_video_1_s01", policy_file)
    assert found_slice is not None
    assert found_slice["url"] == VALID_MP_URL

    # 无效 URL 拒绝
    assert get_article_for_video("test_video_2", policy_file) is None
    assert get_article_for_video("non_existent", policy_file) is None


def test_article_task_decision_freeze_and_args(tmp_path):
    info = {"url": VALID_MP_URL, "title": VALID_TITLE, "config_version": "1.0.0", "config_digest": "abcdef123456"}
    decision = freeze_task_article_decision("task_001", info)
    assert decision["task_id"] == "task_001"
    assert decision["url"] == VALID_MP_URL
    assert decision["config_version"] == "1.0.0"
    assert decision["config_digest"] == "abcdef123456"

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

    assert finalize_none_before_submit(tmp_path, product_picker, picker, article_payload=payload) is True


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
        "article_binding_confirmed": True,
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
    assert result["expected"]["article_url"] == VALID_MP_URL

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


def test_g3_management_readback_rejects_unconfirmed_submission(tmp_path):
    """G3: 未确认绑定的提交回执（article_binding_confirmed!=True）严禁宣称匹配。"""
    receipt_file = tmp_path / "submission_receipt.json"
    receipt_file.write_text(json.dumps({
        "platform_post_id": "post_unconfirmed_1",
        "attachment_type": "ARTICLE",
        "article_url": VALID_MP_URL,
        "article_binding_confirmed": False,
    }), encoding="utf-8")

    record = {
        "platform_post_id": "post_unconfirmed_1",
        "article_observation": {
            "state": "BOUND",
            "actual_article_url": VALID_MP_URL,
        }
    }
    result = _compare_management_article_receipt(record, receipt_file)
    assert result["state"] == "UNVERIFIED"


def test_g2_finalize_article_rejects_task_or_config_mismatch(tmp_path):
    """G2: 任务标识、配置版本/摘要或请求 URL 发生漂移时，发表前核验坚决阻断。"""
    (tmp_path / "article_selection_receipt.json").write_text(json.dumps({
        "task_id": "task_REAL",
        "config_version": "1.0.0",
        "config_digest": "digest_REAL",
        "requested_url": VALID_MP_URL,
        "actual_url": VALID_MP_URL,
        "state": "BOUND",
        "binding_confirmed": True,
        "unbound_confirmed": False,
    }), encoding="utf-8")

    picker = MockArticlePicker(initial_binding=ArticleIdentity(url=VALID_MP_URL))

    # 1. 任务 ID 不匹配
    assert finalize_article_before_submit({
        "task_id": "task_IMPOSTOR",
        "config_version": "1.0.0",
        "config_digest": "digest_REAL",
        "url": VALID_MP_URL,
    }, picker, tmp_path) is False

    # 2. 配置摘要漂移
    assert finalize_article_before_submit({
        "task_id": "task_REAL",
        "config_version": "1.0.0",
        "config_digest": "digest_DRIFTED",
        "url": VALID_MP_URL,
    }, picker, tmp_path) is False

    # 3. 目标 URL 不匹配
    assert finalize_article_before_submit({
        "task_id": "task_REAL",
        "config_version": "1.0.0",
        "config_digest": "digest_REAL",
        "url": "https://mp.weixin.qq.com/s/another_url",
    }, picker, tmp_path) is False

    # 4. 全部吻合 -> 放行
    assert finalize_article_before_submit({
        "task_id": "task_REAL",
        "config_version": "1.0.0",
        "config_digest": "digest_REAL",
        "url": VALID_MP_URL,
    }, picker, tmp_path) is True


def test_g2_finalize_none_rejects_blocked_receipts(tmp_path):
    """G2 & 仲裁防逃逸：若选品或文章回执处于 BLOCKED，绝对禁止按纯视频提交！"""
    product_picker = MockProductPicker(binding=None)
    article_picker = MockArticlePicker(initial_binding=None)

    # 场景 1: 文章因身份冲突或清退失败被 BLOCKED
    (tmp_path / "article_selection_receipt.json").write_text(json.dumps({
        "state": "BLOCKED",
        "binding_confirmed": False,
        "unbound_confirmed": False,
        "reason": "IDENTITY_CONFLICT",
    }), encoding="utf-8")
    assert finalize_none_before_submit(tmp_path, product_picker, article_picker) is False

    # 场景 2: 文章回执恢复为合法清退 SKIPPED，但商品被 BLOCKED
    (tmp_path / "article_selection_receipt.json").write_text(json.dumps({
        "state": "SKIPPED",
        "binding_confirmed": False,
        "unbound_confirmed": True,
    }), encoding="utf-8")
    (tmp_path / "product_selection_receipt.json").write_text(json.dumps({
        "state": "BLOCKED",
        "binding_confirmed": False,
        "unbound_confirmed": False,
    }), encoding="utf-8")
    assert finalize_none_before_submit(tmp_path, product_picker, article_picker) is False

    # 场景 3: 商品与文章均明确为合法未绑定 -> 放行纯视频
    (tmp_path / "product_selection_receipt.json").write_text(json.dumps({
        "state": "SKIPPED",
        "binding_confirmed": False,
        "unbound_confirmed": True,
    }), encoding="utf-8")
    assert finalize_none_before_submit(tmp_path, product_picker, article_picker) is True


def test_mandatory_article_fails_closed_on_invalid_url_and_timeout(tmp_path):
    """强制文章任务 (require_article=True) 遇到非法 URL 或超时，坚决 Fail-Closed，禁止降级！"""
    # 场景 1: 强制文章任务遭遇非法 URL
    bad_payload = {
        "task_id": "mand_1",
        "url": "https://invalid.com/article",
        "require_article": True,
    }
    picker = MockArticlePicker()
    assert execute_article_task(bad_payload, picker, tmp_path) is False
    receipt_1 = json.loads((tmp_path / "article_selection_receipt.json").read_text())
    assert receipt_1["state"] == "BLOCKED"
    assert receipt_1["binding_required"] is True

    # 场景 2: 强制文章任务遭遇注入超时（即使清退成功亦禁止降级）
    timeout_payload = {
        "task_id": "mand_2",
        "url": VALID_MP_URL,
        "require_article": True,
    }
    timeout_picker = MockArticlePicker(attach_error=TimeoutError("timeout"), cancel_result=True)
    product_picker = MockProductPicker()
    assert execute_article_task(timeout_payload, timeout_picker, tmp_path, product_picker=product_picker) is False
    receipt_2 = json.loads((tmp_path / "article_selection_receipt.json").read_text())
    assert receipt_2["state"] == "BLOCKED"
    assert receipt_2["binding_required"] is True


# ── 7. P1/P2 回归门禁：任务一致性、开关隔离与回执防覆盖 ─────────────────────


def test_g2_finalize_none_rejects_missing_required_receipt(tmp_path):
    """P1 门禁：传入本次商品或文章任务时，若应有回执缺失，坚决拒绝提交！"""
    product_picker = MockProductPicker(binding=None)
    article_picker = MockArticlePicker(initial_binding=None)

    # 场景 1: 传入本次商品任务，但商品回执缺失
    product_task = {
        "task_id": "prod_task_1",
        "config_version": "1.0",
        "config_digest": "dig_prod",
        "require_product": False,
    }
    assert finalize_none_before_submit(
        tmp_path, product_picker, article_picker, product_payload=product_task
    ) is False

    # 场景 2: 补充有效商品回执后，传入本次文章任务，但文章回执缺失
    (tmp_path / "product_selection_receipt.json").write_text(json.dumps({
        "task_id": "prod_task_1",
        "config_version": "1.0",
        "config_digest": "dig_prod",
        "required": False,
        "state": "SKIPPED",
        "binding_confirmed": False,
        "unbound_confirmed": True,
    }), encoding="utf-8")

    article_task = {
        "task_id": "art_task_1",
        "config_version": "1.0",
        "config_digest": "dig_art",
        "url": VALID_MP_URL,
    }
    assert finalize_none_before_submit(
        tmp_path, product_picker, article_picker,
        product_payload=product_task, article_payload=article_task
    ) is False


def test_g2_finalize_none_rejects_old_task_receipt(tmp_path):
    """P1 门禁：当前任务与回执的 task_id 不符（旧任务回执残存），坚决拒绝提交！"""
    product_picker = MockProductPicker(binding=None)
    article_picker = MockArticlePicker(initial_binding=None)

    # 场景 1: 商品回执属于历史旧任务
    (tmp_path / "product_selection_receipt.json").write_text(json.dumps({
        "task_id": "old_prod_task",
        "config_version": "1.0",
        "config_digest": "dig_prod",
        "required": False,
        "state": "SKIPPED",
        "binding_confirmed": False,
        "unbound_confirmed": True,
    }), encoding="utf-8")

    current_prod_task = {
        "task_id": "new_prod_task",
        "config_version": "1.0",
        "config_digest": "dig_prod",
        "require_product": False,
    }
    assert finalize_none_before_submit(
        tmp_path, product_picker, article_picker, product_payload=current_prod_task
    ) is False

    # 场景 2: 商品回执匹配，但文章回执属于历史旧任务
    (tmp_path / "product_selection_receipt.json").write_text(json.dumps({
        "task_id": "new_prod_task",
        "config_version": "1.0",
        "config_digest": "dig_prod",
        "required": False,
        "state": "SKIPPED",
        "binding_confirmed": False,
        "unbound_confirmed": True,
    }), encoding="utf-8")

    (tmp_path / "article_selection_receipt.json").write_text(json.dumps({
        "task_id": "old_art_task",
        "config_version": "1.0",
        "config_digest": "dig_art",
        "requested_url": VALID_MP_URL,
        "state": "SKIPPED",
        "binding_confirmed": False,
        "unbound_confirmed": True,
    }), encoding="utf-8")

    current_art_task = {
        "task_id": "new_art_task",
        "config_version": "1.0",
        "config_digest": "dig_art",
        "url": VALID_MP_URL,
    }
    assert finalize_none_before_submit(
        tmp_path, product_picker, article_picker,
        product_payload=current_prod_task, article_payload=current_art_task
    ) is False


def test_g2_finalize_none_rejects_config_drift(tmp_path):
    """P1 门禁：当前任务与回执版本/摘要/URL漂移，坚决拒绝提交！"""
    product_picker = MockProductPicker(binding=None)
    article_picker = MockArticlePicker(initial_binding=None)

    # 场景 1: 商品配置版本漂移
    (tmp_path / "product_selection_receipt.json").write_text(json.dumps({
        "task_id": "task_1",
        "config_version": "v1.0",
        "config_digest": "digest_A",
        "required": False,
        "state": "SKIPPED",
        "binding_confirmed": False,
        "unbound_confirmed": True,
    }), encoding="utf-8")

    drifted_prod_task = {
        "task_id": "task_1",
        "config_version": "v2.0",  # 漂移
        "config_digest": "digest_A",
        "require_product": False,
    }
    assert finalize_none_before_submit(
        tmp_path, product_picker, article_picker, product_payload=drifted_prod_task
    ) is False

    # 场景 2: 文章配置摘要漂移
    (tmp_path / "product_selection_receipt.json").write_text(json.dumps({
        "task_id": "task_1",
        "config_version": "v1.0",
        "config_digest": "digest_A",
        "required": False,
        "state": "SKIPPED",
        "binding_confirmed": False,
        "unbound_confirmed": True,
    }), encoding="utf-8")
    (tmp_path / "article_selection_receipt.json").write_text(json.dumps({
        "task_id": "art_1",
        "config_version": "v1.0",
        "config_digest": "digest_X",
        "requested_url": VALID_MP_URL,
        "state": "SKIPPED",
        "binding_confirmed": False,
        "unbound_confirmed": True,
    }), encoding="utf-8")

    drifted_art_task = {
        "task_id": "art_1",
        "config_version": "v1.0",
        "config_digest": "digest_Y",  # 漂移
        "url": VALID_MP_URL,
    }
    valid_prod_task = {
        "task_id": "task_1",
        "config_version": "v1.0",
        "config_digest": "digest_A",
        "require_product": False,
    }
    assert finalize_none_before_submit(
        tmp_path, product_picker, article_picker,
        product_payload=valid_prod_task, article_payload=drifted_art_task
    ) is False


def test_g2_finalize_none_succeeds_with_consistent_tasks_and_downgrade(tmp_path):
    """P1 门禁：商品与文章任务一致、降级清退真实确证且页面干净时，正向放行纯视频。"""
    product_picker = MockProductPicker(binding=None)
    article_picker = MockArticlePicker(initial_binding=None)

    prod_task = {
        "task_id": "task_prod_ok",
        "config_version": "v1.0",
        "config_digest": "digest_P",
        "require_product": False,
    }
    (tmp_path / "product_selection_receipt.json").write_text(json.dumps({
        "task_id": "task_prod_ok",
        "config_version": "v1.0",
        "config_digest": "digest_P",
        "required": False,
        "state": "SKIPPED",
        "binding_confirmed": False,
        "unbound_confirmed": True,
    }), encoding="utf-8")

    art_task = {
        "task_id": "task_art_ok",
        "config_version": "v1.0",
        "config_digest": "digest_A",
        "url": VALID_MP_URL,
    }
    (tmp_path / "article_selection_receipt.json").write_text(json.dumps({
        "task_id": "task_art_ok",
        "config_version": "v1.0",
        "config_digest": "digest_A",
        "requested_url": VALID_MP_URL,
        "state": "UNBOUND",
        "binding_confirmed": False,
        "unbound_confirmed": True,
    }), encoding="utf-8")

    assert finalize_none_before_submit(
        tmp_path, product_picker, article_picker,
        product_payload=prod_task, article_payload=art_task
    ) is True

    readback = json.loads((tmp_path / "none_pre_submit_readback.json").read_text())
    assert readback["final_verified"] is True
    assert readback["attachment_type"] == "NONE"
    assert readback["product_task_id"] == "task_prod_ok"
    assert readback["article_task_id"] == "task_art_ok"


def test_p1_uploader_switch_disabled_rejects_explicit_article_arguments(tmp_path, monkeypatch):
    """P1 门禁：enable_wechat_article_link=False 时，显式文章参数被严格拦截，禁止绕过，不启动浏览器。"""
    from scripts.wechat_uploader import run_uploader
    from unittest.mock import patch

    monkeypatch.setattr(settings, "enable_wechat_article_link", False)

    video = tmp_path / "video.mp4"
    copy = tmp_path / "copy.txt"
    cover = tmp_path / "cover.jpg"
    video.write_bytes(b"video")
    copy.write_text("copy", encoding="utf-8")
    cover.write_bytes(b"cover")

    # 1. 显式 --article-url
    with patch("scripts.wechat_uploader.sync_playwright") as mock_pw:
        code = run_uploader(
            video_path=str(video),
            copy_path=str(copy),
            cover_path=str(cover),
            state_path=str(tmp_path / "state.json"),
            article_url=VALID_MP_URL,
        )
        assert code == 1
        mock_pw.assert_not_called()

    # 2. 显式 --article-task-decision
    decision_file = tmp_path / "art_decision.json"
    decision_file.write_text(json.dumps({"task_id": "art_1", "url": VALID_MP_URL}))
    with patch("scripts.wechat_uploader.sync_playwright") as mock_pw:
        code = run_uploader(
            video_path=str(video),
            copy_path=str(copy),
            cover_path=str(cover),
            state_path=str(tmp_path / "state.json"),
            article_task_decision=str(decision_file),
        )
        assert code == 1
        mock_pw.assert_not_called()


def test_p2_submission_receipt_isolated_from_stale_none_readback(tmp_path):
    """P2 门禁：证据目录复用存在旧 none 回执时，本次文章回读绝不被覆盖为 NONE。"""
    import time

    # 构造更早的旧 NONE 回执
    stale_none = tmp_path / "none_pre_submit_readback.json"
    stale_none.write_text(json.dumps({
        "final_verified": True,
        "attachment_type": "NONE",
        "unbound_confirmed": True,
    }), encoding="utf-8")

    time.sleep(0.05)

    # 构造本次文章回执
    art_readback = tmp_path / "article_pre_submit_readback.json"
    art_readback.write_text(json.dumps({
        "final_verified": True,
        "attachment_type": "ARTICLE",
        "actual_url": VALID_MP_URL,
        "actual_title": VALID_TITLE,
    }), encoding="utf-8")

    # 测试显式传入 expected_attachment="ARTICLE"
    _write_submission_receipt(
        tmp_path,
        {"platform_post_id": "native_post_101", "platform_object_nonce": "nonce_101"},
        expected_attachment="ARTICLE",
    )
    receipt = json.loads((tmp_path / "submission_receipt.json").read_text())
    assert receipt["attachment_type"] == "ARTICLE"
    assert receipt["article_url"] == VALID_MP_URL
    assert receipt["article_binding_confirmed"] is True

    # 测试未显式传入 expected_attachment 时，基于最新修改时间同样正确识别 ARTICLE
    _write_submission_receipt(
        tmp_path,
        {"platform_post_id": "native_post_102", "platform_object_nonce": "nonce_102"},
    )
    receipt_auto = json.loads((tmp_path / "submission_receipt.json").read_text())
    assert receipt_auto["attachment_type"] == "ARTICLE"
    assert receipt_auto["article_url"] == VALID_MP_URL


def test_p1_finalize_submission_attachments_routing(tmp_path):
    """P1 门禁：_finalize_submission_attachments 在开关开启与关闭下的执行分支隔离验证。"""
    from unittest.mock import MagicMock, patch

    mock_prod_picker = MagicMock()
    mock_art_picker = MagicMock()

    # 1. 开关关闭 (enable_article_link=False)
    with patch("video_processing.utils.wechat_product_execution.finalize_product_before_submit") as mock_fin_prod, \
         patch("video_processing.utils.wechat_article_execution.finalize_none_before_submit") as mock_fin_none, \
         patch("video_processing.utils.wechat_article_execution.finalize_article_before_submit") as mock_fin_art:

        # 1a. 无商品任务且无回执 -> 直接放行 (True, 0)
        ok, code = _finalize_submission_attachments(
            evidence_root=tmp_path,
            product_picker=mock_prod_picker,
            article_picker=mock_art_picker,
            task_product=None,
            task_article=None,
            expected_attachment="NONE",
            require_bound_product=False,
            enable_article_link=False,
        )
        assert ok is True and code == 0
        mock_fin_prod.assert_not_called()
        mock_fin_none.assert_not_called()
        mock_fin_art.assert_not_called()

        # 1b. 有非强制商品任务，商品核验成功 -> (True, 0)
        mock_fin_prod.return_value = True
        ok, code = _finalize_submission_attachments(
            evidence_root=tmp_path,
            product_picker=mock_prod_picker,
            article_picker=mock_art_picker,
            task_product={"require_product": False},
            task_article={"url": VALID_MP_URL},
            expected_attachment="NONE",
            require_bound_product=False,
            enable_article_link=False,
        )
        assert ok is True and code == 0
        mock_fin_prod.assert_called_once()
        mock_fin_none.assert_not_called()
        mock_fin_art.assert_not_called()
        mock_fin_prod.reset_mock()

        # 1c. 有强制商品任务，商品核验失败 -> 必须返回 (False, 14)，不可调用文章逻辑
        mock_fin_prod.return_value = False
        ok, code = _finalize_submission_attachments(
            evidence_root=tmp_path,
            product_picker=mock_prod_picker,
            article_picker=mock_art_picker,
            task_product={"require_product": True},
            task_article=None,
            expected_attachment="NONE",
            require_bound_product=True,
            enable_article_link=False,
        )
        assert ok is False and code == 14
        mock_fin_none.assert_not_called()
        mock_fin_art.assert_not_called()
        mock_fin_prod.reset_mock()

    # 2. 开关开启 (enable_article_link=True)
    with patch("video_processing.utils.wechat_product_execution.finalize_product_before_submit") as mock_fin_prod, \
         patch("video_processing.utils.wechat_article_execution.finalize_none_before_submit") as mock_fin_none, \
         patch("video_processing.utils.wechat_article_execution.finalize_article_before_submit") as mock_fin_art:

        # 2a. expected_attachment="PRODUCT" 路由到商品门禁
        mock_fin_prod.return_value = True
        ok, code = _finalize_submission_attachments(
            evidence_root=tmp_path,
            product_picker=mock_prod_picker,
            article_picker=mock_art_picker,
            task_product={"require_product": True},
            task_article=None,
            expected_attachment="PRODUCT",
            require_bound_product=True,
            enable_article_link=True,
        )
        assert ok is True and code == 0
        mock_fin_prod.assert_called_once_with(
            {"require_product": True}, mock_prod_picker, tmp_path, require_bound=True
        )
        mock_fin_none.assert_not_called()
        mock_fin_art.assert_not_called()
        mock_fin_prod.reset_mock()

        # 2b. expected_attachment="ARTICLE" 路由到文章门禁
        mock_fin_art.return_value = True
        ok, code = _finalize_submission_attachments(
            evidence_root=tmp_path,
            product_picker=mock_prod_picker,
            article_picker=mock_art_picker,
            task_product=None,
            task_article={"url": VALID_MP_URL},
            expected_attachment="ARTICLE",
            require_bound_product=False,
            enable_article_link=True,
        )
        assert ok is True and code == 0
        mock_fin_art.assert_called_once_with({"url": VALID_MP_URL}, mock_art_picker, tmp_path)
        mock_fin_prod.assert_not_called()
        mock_fin_none.assert_not_called()
        mock_fin_art.reset_mock()

        # 2c. expected_attachment="NONE" 路由到全量 NONE 门禁，透传双任务 payload
        mock_fin_none.return_value = True
        ok, code = _finalize_submission_attachments(
            evidence_root=tmp_path,
            product_picker=mock_prod_picker,
            article_picker=mock_art_picker,
            task_product={"require_product": False},
            task_article={"url": VALID_MP_URL},
            expected_attachment="NONE",
            require_bound_product=False,
            enable_article_link=True,
        )
        assert ok is True and code == 0
        mock_fin_none.assert_called_once_with(
            tmp_path,
            mock_prod_picker,
            mock_art_picker,
            product_payload={"require_product": False},
            article_payload={"url": VALID_MP_URL},
            require_bound_product=False,
        )
        mock_fin_prod.assert_not_called()
        mock_fin_art.assert_not_called()
        mock_fin_none.reset_mock()

        # 2d. expected_attachment 为非法值 -> (False, 1)
        ok, code = _finalize_submission_attachments(
            evidence_root=tmp_path,
            product_picker=mock_prod_picker,
            article_picker=mock_art_picker,
            task_product=None,
            task_article=None,
            expected_attachment="INVALID",
            require_bound_product=False,
            enable_article_link=True,
        )
        assert ok is False and code == 1

        # 2e. expected_attachment="NONE" 但强制商品任务未满足 -> 必须返回 (False, 14)
        mock_fin_none.return_value = False
        ok, code = _finalize_submission_attachments(
            evidence_root=tmp_path,
            product_picker=mock_prod_picker,
            article_picker=mock_art_picker,
            task_product={"require_product": True},
            task_article=None,
            expected_attachment="NONE",
            require_bound_product=True,
            enable_article_link=True,
        )
        assert ok is False and code == 14
        mock_fin_none.reset_mock()


def test_reviewer_reproduction_p1_none_branch_task_drift_rejected(tmp_path):
    """P1 定向复现验收：当前任务与回执的 task_id、版本、摘要全不同，页面为空且可提交，新门禁必须返回 False。"""
    product_picker = MockProductPicker(binding=None)
    article_picker = MockArticlePicker(initial_binding=None)

    # 磁盘上为历史旧任务回执（旧 task_id, 旧版本，旧摘要）
    (tmp_path / "product_selection_receipt.json").write_text(json.dumps({
        "task_id": "old_task_id",
        "config_version": "v1.0",
        "config_digest": "digest_old_sha256",
        "required": False,
        "state": "SKIPPED",
        "binding_confirmed": False,
        "unbound_confirmed": True,
    }), encoding="utf-8")

    # 本次任务快照为全新任务
    current_product_task = {
        "task_id": "current_task_id",
        "config_version": "v2.0",
        "config_digest": "digest_new_sha256",
        "require_product": False,
    }

    # 必须坚决拒绝提交返回 False
    result = finalize_none_before_submit(
        tmp_path,
        product_picker,
        article_picker,
        product_payload=current_product_task,
        article_payload=None,
    )
    assert result is False


def test_submission_receipt_none_preserves_product_unbound_confirmation(tmp_path):
    """P2 门禁增强：expected_attachment='NONE' 时完整回读 product_pre_submit_readback 并保留对账字段。"""
    from scripts.run_wallstreet_ab import product_submission_matches

    task = {
        "task_id": "task_wallstreet_unbound",
        "config_version": "1.0.0",
        "config_digest": "digest_123",
        "require_product": False,
        "reason": "WALLSTREET_SKIP",
    }
    (tmp_path / "product_task_decision.json").write_text(json.dumps(task), encoding="utf-8")
    (tmp_path / "product_pre_submit_readback.json").write_text(json.dumps({
        "final_verified": True,
        "task_id": "task_wallstreet_unbound",
        "config_version": "1.0.0",
        "config_digest": "digest_123",
        "binding_confirmed": False,
        "unbound_confirmed": True,
        "actual_product_id": None,
        "actual_title": None,
        "identity_source": "FINAL_FORM_READBACK",
    }), encoding="utf-8")

    receipt_meta = {
        "platform_post_id": "native_post_999",
        "platform_object_nonce": "nonce_999",
    }
    _write_submission_receipt(tmp_path, receipt_meta, expected_attachment="NONE")

    receipt_file = tmp_path / "submission_receipt.json"
    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))

    # 校验基础属性
    assert receipt["attachment_type"] == "NONE"
    assert receipt["unbound_confirmed"] is True
    assert receipt["product_binding_confirmed"] is False
    assert receipt["product_unbound_confirmed"] is True
    assert receipt["product_identity_source"] == "FINAL_FORM_READBACK"
    assert receipt["product_id"] is None
    assert receipt["product_title"] is None

    # 校验 Wallstreet 对账契约通过
    assert product_submission_matches(receipt, task) is True

    # 校验作品管理页回读比较通过
    record = {
        "platform_post_id": "native_post_999",
        "platform_object_nonce": "nonce_999",
        "product_observation": {"state": "UNBOUND"},
    }
    cmp_res = _compare_management_product_receipt(record, receipt_file)
    assert cmp_res["state"] == "MATCH"


def test_article_downgrade_rejects_url_drift_and_mandatory_article(tmp_path):
    """P1 门禁：文章降级路径核验 URL 漂移与强制文章禁止降级。"""
    product_picker = MockProductPicker(binding=None)
    article_picker = MockArticlePicker(initial_binding=None)

    # 场景 1: 降级回执请求的 URL 与本次文章任务 URL 漂移 -> 拒绝提交
    (tmp_path / "article_selection_receipt.json").write_text(json.dumps({
        "task_id": "art_task_1",
        "config_version": "1.0",
        "config_digest": "dig_art",
        "requested_url": "https://mp.weixin.qq.com/s/stale_article_123456",
        "state": "UNBOUND",
        "binding_confirmed": False,
        "unbound_confirmed": True,
    }), encoding="utf-8")

    art_task_drift = {
        "task_id": "art_task_1",
        "config_version": "1.0",
        "config_digest": "dig_art",
        "url": VALID_MP_URL,
    }
    assert finalize_none_before_submit(
        tmp_path, product_picker, article_picker,
        article_payload=art_task_drift
    ) is False

    # 场景 2: 任务要求强制挂文章 (require_article=True) -> 严禁降级为 NONE
    (tmp_path / "article_selection_receipt.json").write_text(json.dumps({
        "task_id": "art_task_mandatory",
        "config_version": "1.0",
        "config_digest": "dig_art",
        "requested_url": VALID_MP_URL,
        "state": "UNBOUND",
        "binding_confirmed": False,
        "unbound_confirmed": True,
    }), encoding="utf-8")

    art_task_mandatory = {
        "task_id": "art_task_mandatory",
        "config_version": "1.0",
        "config_digest": "dig_art",
        "url": VALID_MP_URL,
        "require_article": True,
    }
    assert finalize_none_before_submit(
        tmp_path, product_picker, article_picker,
        article_payload=art_task_mandatory
    ) is False


def test_finalize_none_rejects_unbound_receipt_with_residual_product_or_article(tmp_path):
    """鲁棒性门禁：即使未传任务 payload，若回执标为 UNBOUND 但残留实际绑定 ID/URL，坚决拒绝提交。"""
    product_picker = MockProductPicker(binding=None)
    article_picker = MockArticlePicker(initial_binding=None)

    # 场景 1: 商品回执标称 UNBOUND，但包含实际商品 ID 残留
    (tmp_path / "product_selection_receipt.json").write_text(json.dumps({
        "state": "UNBOUND",
        "binding_confirmed": False,
        "unbound_confirmed": True,
        "actual_product_id": "residual_prod_id",
    }), encoding="utf-8")
    assert finalize_none_before_submit(tmp_path, product_picker, article_picker) is False
    (tmp_path / "product_selection_receipt.json").unlink()

    # 场景 2: 文章回执标称 UNBOUND，但包含实际文章 URL 残留
    (tmp_path / "article_selection_receipt.json").write_text(json.dumps({
        "state": "UNBOUND",
        "binding_confirmed": False,
        "unbound_confirmed": True,
        "actual_url": VALID_MP_URL,
    }), encoding="utf-8")
    assert finalize_none_before_submit(tmp_path, product_picker, article_picker) is False


def test_p1_article_timeout_cleared_downgrade_e2e_integration(tmp_path):
    """P1 终验串联集成测试：
    验证普通非强制文章任务发生超时后，真实清退成功生成包含 requested_url 的 UNBOUND 回执，
    并完整通过上传器真实 _finalize_submission_attachments 门禁降级为 NONE (True, 0)；
    同时验证 URL 漂移、强制文章、清退失败与配置漂移坚决阻断。
    """
    # 1. 正向用例：普通文章超时 + 清退成功 -> 真实产物走 _finalize_submission_attachments 成功降级 (True, 0)
    payload = {
        "task_id": "art_timeout_e2e_001",
        "config_version": "1.0.0",
        "config_digest": "sha256_digest_art_e2e_001",
        "url": VALID_MP_URL,
        "title": VALID_TITLE,
        "require_article": False,
    }
    picker = MockArticlePicker(attach_error=TimeoutError("Inject timed out"), cancel_result=True)
    product_picker = MockProductPicker(binding=None)

    ok = execute_article_task(payload, picker, tmp_path, product_picker=product_picker)
    assert ok is True

    receipt_path = tmp_path / "article_selection_receipt.json"
    assert receipt_path.exists()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["state"] == "UNBOUND"
    assert receipt["fallback_reason"] == "ARTICLE_TIMEOUT_CLEARED"
    assert receipt["task_id"] == "art_timeout_e2e_001"
    assert receipt["config_version"] == "1.0.0"
    assert receipt["config_digest"] == "sha256_digest_art_e2e_001"
    assert receipt["requested_url"] == VALID_MP_URL
    assert receipt["requested_title"] == VALID_TITLE
    assert receipt["binding_confirmed"] is False
    assert receipt["unbound_confirmed"] is True

    # 串联调用上传器终验门禁
    fin_ok, code = _finalize_submission_attachments(
        evidence_root=tmp_path,
        product_picker=product_picker,
        article_picker=picker,
        task_product=None,
        task_article=payload,
        expected_attachment="NONE",
        require_bound_product=False,
        enable_article_link=True,
    )
    assert fin_ok is True
    assert code == 0

    readback_path = tmp_path / "none_pre_submit_readback.json"
    assert readback_path.exists()
    readback = json.loads(readback_path.read_text(encoding="utf-8"))
    assert readback["final_verified"] is True
    assert readback["attachment_type"] == "NONE"
    assert readback["article_task_id"] == "art_timeout_e2e_001"
    assert readback["article_receipt_state"] == "UNBOUND"

    # 2. 反向用例 A: URL 漂移 (payload url 与 receipt requested_url 不一致) -> 坚决阻断
    drift_url_payload = dict(payload, url="https://mp.weixin.qq.com/s/another_article_url_drift")
    fin_ok, code = _finalize_submission_attachments(
        evidence_root=tmp_path,
        product_picker=product_picker,
        article_picker=picker,
        task_product=None,
        task_article=drift_url_payload,
        expected_attachment="NONE",
        require_bound_product=False,
        enable_article_link=True,
    )
    assert fin_ok is False
    assert code == 1

    # 3. 反向用例 B: task_id / config 漂移 -> 坚决阻断
    drift_task_payload = dict(payload, task_id="drifted_task_999")
    fin_ok, code = _finalize_submission_attachments(
        evidence_root=tmp_path,
        product_picker=product_picker,
        article_picker=picker,
        task_product=None,
        task_article=drift_task_payload,
        expected_attachment="NONE",
        require_bound_product=False,
        enable_article_link=True,
    )
    assert fin_ok is False
    assert code == 1

    drift_ver_payload = dict(payload, config_version="2.0.0")
    fin_ok, code = _finalize_submission_attachments(
        evidence_root=tmp_path,
        product_picker=product_picker,
        article_picker=picker,
        task_product=None,
        task_article=drift_ver_payload,
        expected_attachment="NONE",
        require_bound_product=False,
        enable_article_link=True,
    )
    assert fin_ok is False
    assert code == 1

    drift_dig_payload = dict(payload, config_digest="drifted_digest_sha256")
    fin_ok, code = _finalize_submission_attachments(
        evidence_root=tmp_path,
        product_picker=product_picker,
        article_picker=picker,
        task_product=None,
        task_article=drift_dig_payload,
        expected_attachment="NONE",
        require_bound_product=False,
        enable_article_link=True,
    )
    assert fin_ok is False
    assert code == 1

    # 4. 反向用例 C: require_article=True (强制文章任务) 即使清退成功亦禁止降级
    tmp_mandatory = tmp_path / "mandatory"
    tmp_mandatory.mkdir()
    mandatory_payload = dict(payload, require_article=True, task_id="art_mandatory_task")
    picker_m = MockArticlePicker(attach_error=TimeoutError("Inject timed out"), cancel_result=True)
    prod_picker_m = MockProductPicker(binding=None)

    ok_m = execute_article_task(mandatory_payload, picker_m, tmp_mandatory, product_picker=prod_picker_m)
    assert ok_m is False  # 执行器拒绝

    receipt_m = json.loads((tmp_mandatory / "article_selection_receipt.json").read_text(encoding="utf-8"))
    assert receipt_m["state"] == "BLOCKED"
    assert receipt_m["binding_required"] is True
    assert receipt_m["reason"] == "ARTICLE_TIMEOUT_REQUIRED_BLOCKED"
    assert receipt_m["requested_url"] == VALID_MP_URL

    fin_ok_m, code_m = _finalize_submission_attachments(
        evidence_root=tmp_mandatory,
        product_picker=prod_picker_m,
        article_picker=picker_m,
        task_product=None,
        task_article=mandatory_payload,
        expected_attachment="NONE",
        require_bound_product=False,
        enable_article_link=True,
    )
    assert fin_ok_m is False
    assert code_m == 1

    # 5. 反向用例 D: 清退失败 (cancel_and_clear=False) -> Fail-Closed 坚决阻断
    tmp_clear_fail = tmp_path / "clear_fail"
    tmp_clear_fail.mkdir()
    fail_payload = dict(payload, task_id="art_clear_fail_task")
    picker_f = MockArticlePicker(attach_error=TimeoutError("Inject timed out"), cancel_result=False)
    prod_picker_f = MockProductPicker(binding=None)

    ok_f = execute_article_task(fail_payload, picker_f, tmp_clear_fail, product_picker=prod_picker_f)
    assert ok_f is False

    receipt_f = json.loads((tmp_clear_fail / "article_selection_receipt.json").read_text(encoding="utf-8"))
    assert receipt_f["state"] == "BLOCKED"
    assert receipt_f["reason"] == "CLEANUP_FAILED_AFTER_TIMEOUT"
    assert receipt_f["requested_url"] == VALID_MP_URL

    fin_ok_f, code_f = _finalize_submission_attachments(
        evidence_root=tmp_clear_fail,
        product_picker=prod_picker_f,
        article_picker=picker_f,
        task_product=None,
        task_article=fail_payload,
        expected_attachment="NONE",
        require_bound_product=False,
        enable_article_link=True,
    )
    assert fin_ok_f is False
    assert code_f == 1
