"""有界选品编排；平台适配器须使用已验证的当前界面，不能由此模块猜测选择器。

依赖：scripts → 本模块 → core.wechat_product_policy → 标准库。
本模块没有浏览器创建、登录、上传或发表动作，也不读取平台凭据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-10 | Codex | 两次尝试共享总预算；身份冲突或绑定不明阻止发表；默认回退保留原因。 |
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from time import monotonic
from typing import Callable, Protocol

from video_processing.core.wechat_product_policy import (
    ProductCatalog, ProductDecision, ProductIdentity, ProductLookup,
)


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

    @property
    def binding_confirmed(self) -> bool:
        """只表示同次表单绑定；不能用来宣称平台受理或播放页可购买。"""
        return self.state == "BOUND" and self.actual is not None


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
    *, decision: ProductDecision, catalog: ProductCatalog,
    picker: ProductPicker | None, timeout_seconds: float = 30,
    clock: Callable[[], float] = monotonic,
) -> ProductSelectionResult:
    """只能确认绑定或返回阻止发表；没有无商品继续发表的结果。

    当前平台适配器不可用时只返回阻断结果，不能绕过宿主策略访问平台。
    超时由真实适配器执行；此处向每步传递剩余预算并拒绝超时后的成功结果。
    """
    budget = _Deadline(timeout_seconds, clock)
    candidates = catalog.attempts(decision)
    requested = candidates[0]
    fallback_reason = "TARGET_NOT_CONFIGURED" if catalog.configuration_fallback(decision) else None
    attempted = 0

    def result(state: str, reason: str, actual: ProductIdentity | None = None):
        return ProductSelectionResult(
            decision, requested, actual, state, reason, fallback_reason,
            attempted, max(0.0, clock() - budget.started),
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
            try:
                status = picker.find(target, timeout_ms=budget.remaining_ms())
                budget.remaining_ms()
                if status is ProductLookup.IDENTITY_CONFLICT:
                    return result("BLOCKED", "PRODUCT_IDENTITY_CONFLICT")
                if status is ProductLookup.AVAILABLE:
                    picker.select(target, timeout_ms=budget.remaining_ms())
                    budget.remaining_ms()
                    actual = picker.read_binding(timeout_ms=budget.remaining_ms())
                    budget.remaining_ms()
                    if actual is not None and actual != target:
                        return result("BLOCKED", "BINDING_IDENTITY_CONFLICT", actual)
                    if actual == target:
                        if not picker.ready_to_submit(timeout_ms=budget.remaining_ms()):
                            return result("BLOCKED", "FORM_NOT_READY", actual)
                        confirmed = picker.read_binding(timeout_ms=budget.remaining_ms())
                        budget.remaining_ms()
                        if confirmed != target:
                            return result("BLOCKED", "BINDING_CHANGED_BEFORE_SUBMIT", confirmed)
                        return result("BOUND", "BINDING_VERIFIED", actual)
                    failure = "BINDING_NOT_APPLIED"
                elif status is ProductLookup.UNAVAILABLE:
                    failure = "TARGET_UNAVAILABLE"
                else:
                    return result("BLOCKED", "INVALID_LOOKUP_RESULT")
            except TimeoutError:
                # 单个动作先超时、总预算仍有余量时，可以核实清空后尝试默认商品。
                budget.remaining_ms()
                failure = "TARGET_OPERATION_TIMEOUT"

            if index == 1:
                return result("BLOCKED", "DEFAULT_PRODUCT_NOT_BOUND")
            if not picker.cancel_and_clear(timeout_ms=budget.remaining_ms()):
                return result("BLOCKED", "CANNOT_CONFIRM_CLEARED")
            budget.remaining_ms()
            # 再次回读，不把单个取消按钮的点击当成已清空证据。
            if picker.read_binding(timeout_ms=budget.remaining_ms()) is not None:
                return result("BLOCKED", "RESIDUAL_LINK_AFTER_CANCEL")
            budget.remaining_ms()
            if target != candidates[1]:
                fallback_reason = failure
    except TimeoutError:
        return result("BLOCKED", "PRODUCT_SELECTION_BUDGET_EXHAUSTED")
    except Exception as exc:
        # 不归档异常正文，避免平台请求/凭据进入回执；未知状态一律停止。
        return result("BLOCKED", "ADAPTER_ERROR:" + type(exc).__name__)

    return result("BLOCKED", "DEFAULT_PRODUCT_NOT_BOUND")
