"""有界选品编排；平台适配器须使用已验证的当前界面，不能由此模块猜测选择器。

依赖：scripts → 本模块 → core.wechat_product_policy → 标准库。
本模块没有浏览器创建、登录、上传或发表动作，也不读取平台凭据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| cleanup-timeout-v1 | 2026-10-24 | Codex | 区分清理单步超时与总时限耗尽；未确认清空继续闭锁，不增加任何预算。 |
| 1.1.0 | 2026-10-11 | Codex | 商品挂接改为可选；失败后在总预算内核实清空与就绪，允许无商品继续。 |
| 1.0.0 | 2026-10-10 | Codex | 两次尝试共享总预算；身份冲突或绑定不明阻止发表；默认回退保留原因。 |
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from time import monotonic
from typing import Callable, Protocol

from video_processing.core.wechat_product_policy import (
    ProductCatalog, ProductDecision, ProductIdentity, ProductLookup,
)


DIAGNOSTIC_STAGES = frozenset({"CHECK_PRODUCT_DIALOG", "SELECT_LINK_TYPE", "OPEN_PRODUCT_DIALOG",
    "WAIT_PRODUCT_DIALOG", "READ_PRODUCT_BINDING", "SEARCH_PRODUCT", "WAIT_PRODUCT_SEARCH_RESULTS",
    "WAIT_PRODUCT_ROWS", "SELECT_PRODUCT_ROW", "WAIT_PRODUCT_ROW_SELECTION",
    "CONFIRM_PRODUCT_SELECTION", "WAIT_PRODUCT_BINDING", "CANCEL_PRODUCT_DIALOGS", "CLEAR_PRODUCT_CARD", "VERIFY_PRODUCT_CLEARED"})


def picker_diagnostic_stage(picker):
    value = getattr(picker, "diagnostic_stage", None)
    return value if isinstance(value, str) and value in DIAGNOSTIC_STAGES else None


class ProductPicker(Protocol):
    """界面适配器契约；所有操作必须遵守传入超时，不得自行发表或保存草稿。"""

    def read_binding(self, *, timeout_ms: int) -> ProductIdentity | None:
        """回读表单完整商品身份；None 仅表示已确认无商品，未知必须抛错。"""
        ...

    def find(self, product: ProductIdentity, *, timeout_ms: int) -> ProductLookup:
        """只按 ID 和完整名称查找，唯一且可挂载才返回 AVAILABLE。"""
        ...

    def select(self, product: ProductIdentity, *, timeout_ms: int) -> None:
        """选择并完成弹窗确认；点击成功并不表示商品已绑定。"""
        ...

    def cancel_and_clear(self, *, timeout_ms: int) -> bool:
        """取消选择并核实无商品、无残留弹窗；未知返回 False。"""
        ...

    def ready_to_submit(self, *, timeout_ms: int) -> bool:
        """正向确认商品弹窗关闭且表单可操作；不是发表授权。"""
        ...


@dataclass(frozen=True)
class ProductSelectionResult:
    decision: ProductDecision
    requested: ProductIdentity
    actual: ProductIdentity | None
    state: str
    reason: str
    fallback_reason: str | None
    attempts: int
    elapsed_seconds: float
    attempt_records: tuple[dict, ...] = ()

    @property
    def binding_confirmed(self) -> bool:
        """只表示同次表单绑定；不能用来宣称平台受理或播放页可购买。"""
        return self.state == "BOUND" and self.actual is not None

    @property
    def submission_allowed(self) -> bool:
        """商品阶段已完成；其他发布门禁仍须照常执行。"""
        return self.binding_confirmed or (self.state == "UNBOUND" and self.actual is None)


class _Deadline:
    def __init__(self, seconds: float, clock: Callable[[], float]):
        if not math.isfinite(seconds) or not 0 < seconds <= 60:
            raise ValueError("选品总预算须为 0–60 秒之间的有限正数")
        self.clock = clock
        self.started = clock()
        self.ends = self.started + seconds

    def remaining_ms(self) -> int:
        # 向下取整：不能把不足一毫秒的剩余时间扩成一次完整浏览器等待。
        remaining = int((self.ends - self.clock()) * 1000)
        if remaining <= 0:
            raise TimeoutError("PRODUCT_SELECTION_BUDGET_EXHAUSTED")
        return remaining


def select_required_product(
    *, decision: ProductDecision, catalog: ProductCatalog | None = None,
    picker: ProductPicker | None, timeout_seconds: float = 30,
    clock: Callable[[], float] = monotonic,
) -> ProductSelectionResult:
    """只能确认绑定或返回阻止发表；没有无商品继续发表的结果。

    当前平台适配器不可用时只返回阻断结果，不能绕过宿主策略访问平台。
    超时由真实适配器执行；此处向每步传递剩余预算并拒绝超时后的成功结果。
    """
    budget = _Deadline(timeout_seconds, clock)
    if decision.candidates:
        candidates = decision.candidates
        if len(candidates) > decision.max_attempts:
            raise ValueError("候选链超过尝试上限")
        if len(candidates) == 1:
            candidates = candidates * decision.max_attempts
        fallback_reason = None
    elif catalog is not None:
        candidates = catalog.attempts(decision)
        fallback_reason = "TARGET_NOT_CONFIGURED" if catalog.configuration_fallback(decision) else None
    else:
        raise ValueError("缺少已验证的选品配置")
    requested = candidates[0]
    records = []
    attempted = 0

    def result(state: str, reason: str, actual: ProductIdentity | None = None):
        if records and records[-1]["outcome"] == "STARTED":
            records[-1]["outcome"] = reason
        return ProductSelectionResult(
            decision, requested, actual, state, reason, fallback_reason,
            attempted, max(0.0, clock() - budget.started), tuple(dict(r) for r in records),
        )

    if picker is None:
        return result("BLOCKED", "CURRENT_UI_ADAPTER_NOT_VERIFIED")

    try:
        existing = picker.read_binding(timeout_ms=budget.remaining_ms())
        budget.remaining_ms()
        if existing is not None:
            if existing != requested:
                return result("BLOCKED", "EXISTING_LINK_CONFLICT", existing)
            if not picker.ready_to_submit(timeout_ms=budget.remaining_ms()):
                return result("BLOCKED", "FORM_NOT_READY", existing)
            confirmed = picker.read_binding(timeout_ms=budget.remaining_ms())
            budget.remaining_ms()
            if confirmed != existing:
                return result("BLOCKED", "BINDING_CHANGED_BEFORE_SUBMIT", confirmed)
            return result("BOUND", "EXISTING_BINDING_VERIFIED", existing)

        for index, target in enumerate(candidates):
            attempted += 1
            # 在同一总 deadline 内给后续候选保留时间；清理也计入当前候选份额。
            share_ms = budget.remaining_ms() // (len(candidates) - index)
            attempt_end = clock() + share_ms / 1000
            cleanup_ms = min(2500, share_ms // 4) if index < len(candidates) - 1 else 0
            action_end = attempt_end - cleanup_ms / 1000

            def remaining_until(end):
                remaining = min(budget.remaining_ms(), int((end - clock()) * 1000))
                if remaining <= 0:
                    raise TimeoutError("PRODUCT_CANDIDATE_BUDGET_EXHAUSTED")
                return remaining

            record = {"product_id": target.product_id, "title": target.title, "outcome": "STARTED",
                      "kind": "TECHNICAL_RETRY" if index and target == candidates[index - 1] else "CANDIDATE",
                      "allocated_ms": share_ms}
            records.append(record)
            try:
                status = picker.find(target, timeout_ms=remaining_until(action_end))
                remaining_until(action_end)
                if status is ProductLookup.IDENTITY_CONFLICT:
                    return result("BLOCKED", "PRODUCT_IDENTITY_CONFLICT")
                if status is ProductLookup.AVAILABLE:
                    picker.select(target, timeout_ms=remaining_until(action_end))
                    remaining_until(action_end)
                    actual = picker.read_binding(timeout_ms=remaining_until(action_end))
                    remaining_until(action_end)
                    if actual is not None and actual != target:
                        return result("BLOCKED", "BINDING_IDENTITY_CONFLICT", actual)
                    if actual == target:
                        if not picker.ready_to_submit(timeout_ms=remaining_until(action_end)):
                            return result("BLOCKED", "FORM_NOT_READY", actual)
                        confirmed = picker.read_binding(timeout_ms=remaining_until(action_end))
                        remaining_until(action_end)
                        if confirmed != target:
                            return result("BLOCKED", "BINDING_CHANGED_BEFORE_SUBMIT", confirmed)
                        record["outcome"] = "BOUND"
                        return result("BOUND", "BINDING_VERIFIED", actual)
                    failure = "BINDING_NOT_APPLIED"
                elif status is ProductLookup.UNAVAILABLE:
                    failure = "TARGET_UNAVAILABLE"
                else:
                    return result("BLOCKED", "INVALID_LOOKUP_RESULT")
            except TimeoutError:
                record["failure_stage"] = picker_diagnostic_stage(picker)
                # 单个动作先超时、总预算仍有余量时，可以核实清空后尝试默认商品。
                budget.remaining_ms()
                failure = "TARGET_OPERATION_TIMEOUT"

            record["outcome"] = failure
            if index == len(candidates) - 1:
                return result("BLOCKED", "DEFAULT_PRODUCT_NOT_BOUND")
            if not picker.cancel_and_clear(timeout_ms=remaining_until(attempt_end)):
                return result("BLOCKED", "CANNOT_CONFIRM_CLEARED")
            remaining_until(attempt_end)
            # 再次回读，不把单个取消按钮的点击当成已清空证据。
            if picker.read_binding(timeout_ms=remaining_until(attempt_end)) is not None:
                return result("BLOCKED", "RESIDUAL_LINK_AFTER_CANCEL")
            remaining_until(attempt_end)
            if target != candidates[index + 1]:
                fallback_reason = fallback_reason or failure
    except TimeoutError:
        try:
            budget.remaining_ms()
        except TimeoutError:
            return result("BLOCKED", "PRODUCT_SELECTION_BUDGET_EXHAUSTED")
        return result("BLOCKED", "PRODUCT_OPERATION_TIMEOUT")
    except Exception as exc:
        # 不归档异常正文，避免平台请求/凭据进入回执；未知状态一律停止。
        return result("BLOCKED", "ADAPTER_ERROR:" + type(exc).__name__)

    return result("BLOCKED", "DEFAULT_PRODUCT_NOT_BOUND")


def select_optional_product(
    *, decision: ProductDecision, catalog: ProductCatalog | None = None,
    picker: ProductPicker | None, timeout_seconds: float = 30,
    clock: Callable[[], float] = monotonic,
    selection_block_reason: str | None = None,
) -> ProductSelectionResult:
    """挂接失败后清空并核验表单；总预算预留 20% 用于恢复。

    未核实候选不尝试选择；回执保留失败原因，无法确认清空仍为表单异常。
    """
    budget = _Deadline(timeout_seconds, clock)
    if selection_block_reason:
        requested = decision.candidates[0] if decision.candidates else catalog.attempts(decision)[0]
        selected = ProductSelectionResult(
            decision, requested, None, "BLOCKED", selection_block_reason, None, 0, 0,
        )
    else:
        selected = select_required_product(
            decision=decision, catalog=catalog, picker=picker,
            timeout_seconds=timeout_seconds * 0.8, clock=clock,
        )
    if selected.binding_confirmed or picker is None:
        return selected

    def result(state: str, reason: str, actual: ProductIdentity | None = None):
        return replace(selected, state=state, reason=reason, actual=actual,
                       fallback_reason=selected.reason,
                       elapsed_seconds=max(0.0, clock() - budget.started))

    try:
        if not picker.cancel_and_clear(timeout_ms=budget.remaining_ms()):
            return result("BLOCKED", "CANNOT_CONFIRM_CLEARED")
        actual = picker.read_binding(timeout_ms=budget.remaining_ms())
        budget.remaining_ms()
        if actual is not None:
            return result("BLOCKED", "RESIDUAL_LINK_AFTER_CANCEL", actual)
        if not picker.ready_to_submit(timeout_ms=budget.remaining_ms()):
            return result("BLOCKED", "FORM_NOT_READY")
        actual = picker.read_binding(timeout_ms=budget.remaining_ms())
        budget.remaining_ms()
        if actual is not None:
            return result("BLOCKED", "BINDING_CHANGED_BEFORE_SUBMIT", actual)
        return result("UNBOUND", "OPTIONAL_PRODUCT_NOT_BOUND")
    except TimeoutError:
        try:
            budget.remaining_ms()
        except TimeoutError:
            return result("BLOCKED", "PRODUCT_CLEANUP_BUDGET_EXHAUSTED")
        # 内层适配器的短超时不代表30秒总时限耗尽；清空未确认时禁止盲目重检。
        return result("BLOCKED", "PRODUCT_CLEANUP_OPERATION_TIMEOUT")
    except Exception as exc:
        return result("BLOCKED", "PRODUCT_CLEANUP_ERROR:" + type(exc).__name__)
