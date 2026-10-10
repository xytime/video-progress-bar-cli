"""视频号选品规则与已核实商品身份；只依赖标准库，不访问平台或运行数据库。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-10 | Antigravity | 从真实账号清单核实并固化三本书的商品 ID 与完整名称，提供统一 get_verified_product_catalog。 |
| 1.0.0 | 2026-10-10 | Codex | 财经/新闻/默认选品，按商品 ID 与完整名称核对，指定商品缺失时回退默认。 |
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


WALLSTREET_CHANNEL_ID = "UCTK_cv-y88CScoudcXnS1Ew"
RULE_VERSION = "wechat-book-product-v1"


class ProductRole(str, Enum):
    FINANCE = "finance"
    NEWS = "news"
    DEFAULT = "default"


class ProductLookup(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"


@dataclass(frozen=True)
class ProductIdentity:
    """来自账号商品清单的稳定 ID 与完整名称/版本，不能用列表序号代替。"""

    product_id: str
    title: str

    def __post_init__(self) -> None:
        for name in ("product_id", "title"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"商品 {name} 必须是无首尾空白的非空字符串")


@dataclass(frozen=True)
class ProductDecision:
    role: ProductRole
    reason: str
    rule_version: str = RULE_VERSION


def choose_product_role(
    *, category: str | None = None, source_channel_id: str | None = None,
) -> ProductDecision:
    """只用可信频道 ID 与单条明确分类；缺失、冲突及其他类别使用默认商品。"""
    if source_channel_id == WALLSTREET_CHANNEL_ID:
        return ProductDecision(ProductRole.FINANCE, "WALLSTREET_CHANNEL")
    normalized = category.strip() if isinstance(category, str) else ""
    if normalized == "财经":
        return ProductDecision(ProductRole.FINANCE, "FINANCE_CATEGORY")
    if normalized in {"资讯", "时事"}:
        return ProductDecision(ProductRole.NEWS, "NEWS_CATEGORY")
    return ProductDecision(ProductRole.DEFAULT, "OTHER_OR_UNKNOWN_CATEGORY")


@dataclass(frozen=True)
class ProductCatalog:
    """已经核实的账号商品目录；默认商品必填，其他目标缺失时允许回退。"""

    products: Mapping[ProductRole, ProductIdentity]

    def __post_init__(self) -> None:
        entries = dict(self.products)
        if ProductRole.DEFAULT not in entries:
            raise ValueError("必须核实并配置默认商品《思考快与慢》")
        if any(not isinstance(role, ProductRole) or not isinstance(item, ProductIdentity)
               for role, item in entries.items()):
            raise ValueError("商品目录只能包含明确角色与商品身份")
        ids = [item.product_id for item in entries.values()]
        if len(set(ids)) != len(ids):
            raise ValueError("不同图书角色不能复用同一商品 ID")
        object.__setattr__(self, "products", MappingProxyType(entries))

    def attempts(self, decision: ProductDecision) -> tuple[ProductIdentity, ProductIdentity]:
        """至多两次：指定商品→默认商品；初始就是默认时只允许重试默认。"""
        default = self.products[ProductRole.DEFAULT]
        return self.products.get(decision.role, default), default

    def configuration_fallback(self, decision: ProductDecision) -> bool:
        return decision.role not in self.products


# 真实账号已核实图书商品清单（经 2026-10-10 实机页面实测与 DOM 校验）
VERIFIED_FINANCE_PRODUCT = ProductIdentity(
    product_id="10000028955239",
    title="股市趋势技术分析10版爱德华兹原书第10版金融投资策略股票入门基础知识指标价值投资书籍书新华文轩旗舰店正",
)
VERIFIED_NEWS_PRODUCT = ProductIdentity(
    product_id="10000129752415",
    title="维特根斯坦说逻辑与语言 (英)维特根斯坦著",
)
VERIFIED_DEFAULT_PRODUCT = ProductIdentity(
    product_id="10001054866768",
    title="思考快与慢 丹尼尔卡尼曼 噪声作者行为经济学诺贝尔经济学奖 快思考慢思考 社会科学经济学心理学",
)


def get_verified_product_catalog() -> ProductCatalog:
    """返回基于账号实测真实上架商品的不可变目录。"""
    return ProductCatalog({
        ProductRole.FINANCE: VERIFIED_FINANCE_PRODUCT,
        ProductRole.NEWS: VERIFIED_NEWS_PRODUCT,
        ProductRole.DEFAULT: VERIFIED_DEFAULT_PRODUCT,
    })

