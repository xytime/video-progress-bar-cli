"""公众号文章挂接执行与发表前最终核验。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-12 | Antigravity | 修复 G2 漏洞与仲裁逃逸：严格检查 payload 一致性（task_id/config_version/digest/url）；finalize_none 坚决阻断 BLOCKED 状态；支持 require_article 强制文章不降级。 |
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
    - 若 URL 非法：
      - 若 require_article=True：坚决阻断（返回 False）；
      - 若普通任务：注入前拦截，不修改 DOM，允许降级为 NONE（返回 True）；
    - 若正常注入且回读一致：进入 ARTICLE，回执记 BOUND（返回 True）；
    - 若身份冲突：坚决停止本次提交，清退成功亦不恢复本次发布资格（返回 False）；
    - 若可恢复超时：
      - 若 require_article=True：清退后坚决阻断，不能降级（返回 False）；
      - 真实清退且确认无挂接四项齐备，允许降级为 NONE（返回 True）；清退失败则终止（返回 False）。
    """
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(evidence_dir / "article_task_decision.json", payload)

    url = payload.get("url")
    title = payload.get("title", "")
    task_id = payload.get("task_id", "")
    require_article = bool(payload.get("require_article", False))
    config_version = str(payload.get("config_version", "1.0.0"))
    config_digest = str(payload.get("config_digest", ""))

    # 1. 注入前校验 URL 格式
    if not is_valid_mp_article_url(url):
        if require_article:
            receipt = {
                "required": True,
                "binding_required": True,
                "state": "BLOCKED",
                "binding_confirmed": False,
                "unbound_confirmed": False,
                "reason": "ARTICLE_URL_INVALID_REQUIRED",
                "task_id": task_id,
                "config_version": config_version,
                "config_digest": config_digest,
            }
            atomic_json(evidence_dir / "article_selection_receipt.json", receipt)
            return False

        receipt = {
            "required": True,
            "binding_required": False,
            "state": "SKIPPED",
            "binding_confirmed": False,
            "unbound_confirmed": True,
            "reason": "ARTICLE_URL_INVALID",
            "fallback_reason": "PRE_INJECTION_REJECTED",
            "task_id": task_id,
            "config_version": config_version,
            "config_digest": config_digest,
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
            "binding_required": require_article,
            "state": "BOUND",
            "binding_confirmed": True,
            "unbound_confirmed": False,
            "actual_url": actual.url,
            "actual_title": actual.title,
            "requested_url": target.url,
            "requested_title": target.title,
            "task_id": task_id,
            "config_version": config_version,
            "config_digest": config_digest,
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
            "binding_required": require_article,
            "state": "BLOCKED",
            "binding_confirmed": False,
            "unbound_confirmed": False,
            "reason": f"IDENTITY_CONFLICT:{exc}",
            "task_id": task_id,
            "config_version": config_version,
            "config_digest": config_digest,
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
            if require_article:
                # 强制文章任务即使清退成功亦禁止降级纯视频
                receipt = {
                    "required": True,
                    "binding_required": True,
                    "state": "BLOCKED",
                    "binding_confirmed": False,
                    "unbound_confirmed": False,
                    "reason": "ARTICLE_TIMEOUT_REQUIRED_BLOCKED",
                    "task_id": task_id,
                    "config_version": config_version,
                    "config_digest": config_digest,
                }
                atomic_json(evidence_dir / "article_selection_receipt.json", receipt)
                return False

            # S07-A: 普通文章超时且真实清退成功，四项齐备降级纯视频
            receipt = {
                "required": True,
                "binding_required": False,
                "state": "UNBOUND",
                "binding_confirmed": False,
                "unbound_confirmed": True,
                "reason": "ARTICLE_TIMEOUT",
                "fallback_reason": "ARTICLE_TIMEOUT_CLEARED",
                "task_id": task_id,
                "config_version": config_version,
                "config_digest": config_digest,
            }
            atomic_json(evidence_dir / "article_selection_receipt.json", receipt)
            return True
        else:
            # S07-B: 超时且清退失败，Fail-Closed 终止
            receipt = {
                "required": True,
                "binding_required": require_article,
                "state": "BLOCKED",
                "binding_confirmed": False,
                "unbound_confirmed": False,
                "reason": "CLEANUP_FAILED_AFTER_TIMEOUT",
                "task_id": task_id,
                "config_version": config_version,
                "config_digest": config_digest,
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
            "binding_required": require_article,
            "state": "BLOCKED",
            "binding_confirmed": False,
            "unbound_confirmed": False,
            "reason": type(exc).__name__,
            "task_id": task_id,
            "config_version": config_version,
            "config_digest": config_digest,
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

        # G2 保护：校验传入的本次任务快照一致性
        if payload is not None:
            if receipt.get("task_id") != payload.get("task_id"):
                return False
            if payload.get("config_version") and receipt.get("config_version") != payload.get("config_version"):
                return False
            if payload.get("config_digest") and receipt.get("config_digest") != payload.get("config_digest"):
                return False
            if payload.get("url") and receipt.get("requested_url") != payload.get("url"):
                return False

        # 商品不能处于已绑定状态
        product_receipt_path = evidence_dir / "product_selection_receipt.json"
        if product_receipt_path.exists():
            prod_receipt = json.loads(product_receipt_path.read_text(encoding="utf-8"))
            if prod_receipt.get("binding_confirmed") is True or prod_receipt.get("state") == "BOUND":
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
            "requested_url": receipt.get("requested_url"),
            "task_id": receipt.get("task_id"),
            "config_version": receipt.get("config_version"),
            "config_digest": receipt.get("config_digest"),
            "binding_confirmed": True,
            "unbound_confirmed": False,
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
    同时具备防回归与防逃逸保护：
    - 如果此前的选品或文章回执曾是 BOUND，绝对禁止静默降级为 NONE；
    - 如果选品或文章回执处于 BLOCKED、异常或未确认清退，严格禁止按纯视频提交！
    """
    evidence_dir = Path(evidence_dir)
    readback = evidence_dir / "none_pre_submit_readback.json"
    readback.unlink(missing_ok=True)
    try:
        # 商品回执核验：曾绑定或处于阻断状态，均严禁以纯视频提交
        product_receipt_path = evidence_dir / "product_selection_receipt.json"
        prod_receipt = None
        if product_receipt_path.exists():
            prod_receipt = json.loads(product_receipt_path.read_text(encoding="utf-8"))
            if prod_receipt.get("state") in ("BOUND", "BLOCKED"):
                return False
            if prod_receipt.get("binding_confirmed") is True:
                return False
            if prod_receipt.get("unbound_confirmed") is not True:
                return False

        # 文章回执核验：曾绑定或处于阻断状态，均严禁以纯视频提交
        article_receipt_path = evidence_dir / "article_selection_receipt.json"
        art_receipt = None
        if article_receipt_path.exists():
            art_receipt = json.loads(article_receipt_path.read_text(encoding="utf-8"))
            if art_receipt.get("state") in ("BOUND", "BLOCKED"):
                return False
            if art_receipt.get("binding_confirmed") is True:
                return False
            if art_receipt.get("unbound_confirmed") is not True:
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
            "product_receipt_state": prod_receipt.get("state") if prod_receipt else None,
            "article_receipt_state": art_receipt.get("state") if art_receipt else None,
        })
        return True
    except Exception:
        return False

