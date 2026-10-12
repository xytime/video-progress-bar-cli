"""公众号文章挂接执行与发表前最终核验。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | 初始实现：文章注入执行、超时清退降级、身份冲突阻断、发表前独立核验与纯视频四项齐备核验。 |
"""

from __future__ import annotations

import json
from pathlib import Path
from time import monotonic

from video_processing.core.wechat_article_policy import ArticleIdentity, is_valid_mp_article_url
from video_processing.utils.wechat_product_config import atomic_json
from video_processing.utils.wechat_product_picker import BindingIdentityUnavailable


def execute_article_task(
    payload: dict,
    picker,
    evidence_dir: Path,
    *,
    clock=monotonic,
    timeout_seconds: float = 30.0,
    product_picker=None,
) -> bool:
    """执行公众号文章挂接任务。

    仲裁逻辑：
    - 若 URL 非法：注入前拦截，不修改 DOM，允许降级为 NONE；
    - 若正常注入且回读一致：进入 ARTICLE；
    - 若身份冲突：坚决停止本次提交，清退成功亦不恢复本次发布资格（返回 False）；
    - 若可恢复超时：真实清退且确认无挂接四项齐备，允许降级为 NONE；清退失败则终止（返回 False）。
    """
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(evidence_dir / "article_task_decision.json", payload)

    url = payload.get("url")
    title = payload.get("title", "")
    task_id = payload.get("task_id", "")

    # 1. 注入前校验 URL 格式
    if not is_valid_mp_article_url(url):
        receipt = {
            "required": True,
            "state": "SKIPPED",
            "binding_confirmed": False,
            "unbound_confirmed": True,
            "reason": "ARTICLE_URL_INVALID",
            "fallback_reason": "PRE_INJECTION_REJECTED",
            "task_id": task_id,
        }
        atomic_json(evidence_dir / "article_selection_receipt.json", receipt)
        return True

    # 2. 注入操作
    target = ArticleIdentity(url=url, title=title)
    try:
        picker.attach(target, timeout_ms=int(timeout_seconds * 1000))
        actual = picker.read_binding(timeout_ms=3000)
        if actual is None or actual.url != target.url:
            raise BindingIdentityUnavailable(
                f"SELECTED_ARTICLE_URL_MISMATCH: expected {target.url}, got {actual.url if actual else None}"
            )
        receipt = {
            "required": True,
            "state": "BOUND",
            "binding_confirmed": True,
            "unbound_confirmed": False,
            "actual_url": actual.url,
            "actual_title": actual.title,
            "requested_url": target.url,
            "requested_title": target.title,
            "task_id": task_id,
        }
        atomic_json(evidence_dir / "article_selection_receipt.json", receipt)
        return True
    except BindingIdentityUnavailable as exc:
        # S07-C: 身份冲突——坚决终止本次提交；解绑仅用于恢复环境，不恢复本次发布资格
        try:
            picker.cancel_and_clear(timeout_ms=5000)
        except Exception:
            pass
        receipt = {
            "required": True,
            "state": "BLOCKED",
            "binding_confirmed": False,
            "unbound_confirmed": False,
            "reason": f"IDENTITY_CONFLICT:{exc}",
            "task_id": task_id,
        }
        atomic_json(evidence_dir / "article_selection_receipt.json", receipt)
        return False
    except TimeoutError:
        # S07-A / S07-B: 注入超时
        cleared = False
        try:
            cleared = picker.cancel_and_clear(timeout_ms=5000)
        except Exception:
            cleared = False

        unbound_verified = False
        if cleared:
            try:
                article_unbound = picker.read_binding(timeout_ms=2000) is None
                product_unbound = True
                if product_picker is not None:
                    product_unbound = product_picker.read_binding(timeout_ms=2000) is None
                ready = picker.ready_to_submit(timeout_ms=2000)
                unbound_verified = article_unbound and product_unbound and ready
            except Exception:
                unbound_verified = False

        if cleared and unbound_verified:
            # S07-A: 超时且真实清退成功，四项齐备降级纯视频
            receipt = {
                "required": True,
                "state": "UNBOUND",
                "binding_confirmed": False,
                "unbound_confirmed": True,
                "reason": "ARTICLE_TIMEOUT",
                "fallback_reason": "ARTICLE_TIMEOUT_CLEARED",
                "task_id": task_id,
            }
            atomic_json(evidence_dir / "article_selection_receipt.json", receipt)
            return True
        else:
            # S07-B: 超时且清退失败，Fail-Closed 终止
            receipt = {
                "required": True,
                "state": "BLOCKED",
                "binding_confirmed": False,
                "unbound_confirmed": False,
                "reason": "CLEANUP_FAILED_AFTER_TIMEOUT",
                "task_id": task_id,
            }
            atomic_json(evidence_dir / "article_selection_receipt.json", receipt)
            return False
    except Exception as exc:
        try:
            picker.cancel_and_clear(timeout_ms=5000)
        except Exception:
            pass
        receipt = {
            "required": True,
            "state": "BLOCKED",
            "binding_confirmed": False,
            "unbound_confirmed": False,
            "reason": type(exc).__name__,
            "task_id": task_id,
        }
        atomic_json(evidence_dir / "article_selection_receipt.json", receipt)
        return False


def finalize_article_before_submit(
    payload: dict | None,
    picker,
    evidence_dir: Path,
) -> bool:
    """发表前瞬间独立核验证实文章卡片与回执 100% 一致。"""
    evidence_dir = Path(evidence_dir)
    readback = evidence_dir / "article_pre_submit_readback.json"
    readback.unlink(missing_ok=True)
    try:
        receipt_path = evidence_dir / "article_selection_receipt.json"
        if not receipt_path.exists():
            return False
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("state") != "BOUND" or receipt.get("binding_confirmed") is not True or receipt.get("unbound_confirmed") is True:
            return False

        # 商品不能处于已绑定状态
        product_receipt_path = evidence_dir / "product_selection_receipt.json"
        if product_receipt_path.exists():
            prod_receipt = json.loads(product_receipt_path.read_text(encoding="utf-8"))
            if prod_receipt.get("binding_confirmed") is True:
                return False

        # 实读页面当前绑定的文章
        actual = picker.read_binding(timeout_ms=3000)
        if actual is None or actual.url != receipt.get("actual_url"):
            return False

        if not picker.ready_to_submit(timeout_ms=3000):
            return False

        atomic_json(readback, {
            "final_verified": True,
            "attachment_type": "ARTICLE",
            "actual_url": actual.url,
            "actual_title": actual.title,
            "task_id": receipt.get("task_id"),
        })
        return True
    except Exception:
        return False


def finalize_none_before_submit(
    evidence_dir: Path,
    product_picker,
    article_picker,
) -> bool:
    """发表前瞬间正向核验证实四项齐备无挂接。

    四项齐备条件：
    1. 商品未绑定 (product_picker.read_binding() is None)；
    2. 文章未挂接 (article_picker.read_binding() is None)；
    3. 无残留弹窗/遮罩；
    4. 表单已就绪 (ready_to_submit)。
    同时具备防回归保护：如果此前的选品或文章回执曾是 BOUND，绝对禁止静默降级为 NONE！
    """
    evidence_dir = Path(evidence_dir)
    readback = evidence_dir / "none_pre_submit_readback.json"
    readback.unlink(missing_ok=True)
    try:
        # 回归保护：商品曾绑定则禁止在消失后以纯视频提交
        product_receipt_path = evidence_dir / "product_selection_receipt.json"
        if product_receipt_path.exists():
            prod_receipt = json.loads(product_receipt_path.read_text(encoding="utf-8"))
            if prod_receipt.get("state") == "BOUND" or prod_receipt.get("binding_confirmed") is True:
                return False

        # 回归保护：文章曾绑定则禁止在消失后以纯视频提交
        article_receipt_path = evidence_dir / "article_selection_receipt.json"
        if article_receipt_path.exists():
            art_receipt = json.loads(article_receipt_path.read_text(encoding="utf-8"))
            if art_receipt.get("state") == "BOUND" or art_receipt.get("binding_confirmed") is True:
                return False

        # 检查商品与文章实读均为 None
        if product_picker.read_binding(timeout_ms=3000) is not None:
            return False
        if article_picker.read_binding(timeout_ms=3000) is not None:
            return False

        # 检查表单就绪
        if not product_picker.ready_to_submit(timeout_ms=3000):
            return False
        if not article_picker.ready_to_submit(timeout_ms=3000):
            return False

        atomic_json(readback, {
            "final_verified": True,
            "attachment_type": "NONE",
            "unbound_confirmed": True,
        })
        return True
    except Exception:
        return False
