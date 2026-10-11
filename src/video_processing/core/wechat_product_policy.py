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
    config_digest: str = ""
    candidates: tuple[ProductIdentity, ...] = ()
    max_attempts: int = 2
    timeout_seconds: float = 30
    context: tuple[tuple[str, str | None], ...] = ()
    video_group: str = "other"
    group_reason: str = "未命中特定类型"



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



@dataclass(frozen=True)
class ProductEntry:
    identity: ProductIdentity
    enabled: bool
    verified_at: str
    verified_source: str


@dataclass(frozen=True)
class ProductRule:
    rule_id: str
    kind: str
    values: tuple[str, ...]
    candidates: tuple[str, ...]
    role: ProductRole = ProductRole.DEFAULT


VIDEO_GROUPS = ("english_world", "wallstreet", "ted", "ai_news", "other")
GROUP_LABELS = dict(zip(VIDEO_GROUPS, ("英语世界短视频", "华尔街事实炸弹", "TED 类", "AI 相关资讯", "其他")))


@dataclass(frozen=True)
class ProductProfile:
    candidates: tuple[str, ...]
    channel_ids: tuple[str, ...]


@dataclass(frozen=True)
class ProductPolicy:
    """不可变策略快照；规则来自配置，不在领域层内置商品或频道特例。"""

    version: str
    digest: str
    products: Mapping[str, ProductEntry]
    rules: tuple[ProductRule, ...]
    defaults: tuple[str, ...]
    timeout_seconds: float
    max_attempts: int
    serialized: str
    profiles: Mapping[str, ProductProfile]

    def chain(self, aliases: tuple[str, ...]) -> tuple[ProductIdentity, ...]:
        result = []
        for alias in (*aliases, *self.defaults):
            entry = self.products.get(alias)
            if entry is None or not entry.enabled:
                raise ValueError(f"商品不存在或已停用: {alias}")
            if entry.identity not in result:
                result.append(entry.identity)
        if len(result) > self.max_attempts:
            raise ValueError("候选链超过尝试上限，默认回退不可达")
        return tuple(result)

    def decide(self, *, category: str | None = None, source_channel_id: str | None = None,
               product_alias: str | None = None, content_type: str | None = None,
               product_topic: str | None = None) -> ProductDecision:
        context = (("category", category), ("source_channel_id", source_channel_id),
                   ("product_alias", product_alias), ("content_type", content_type),
                   ("product_topic", product_topic))
        if any(v is not None and not isinstance(v, str) for _, v in context):
            raise ValueError("视频上下文字段必须为字符串")
        group, group_reason = "other", "未命中特定类型"
        if self.profiles:
            if content_type == "ENGLISH_WORLD_SHORT":
                group, group_reason = "english_world", "内容类型 ENGLISH_WORLD_SHORT"
            else:
                for name in ("wallstreet", "ted", "ai_news"):
                    if source_channel_id and source_channel_id.strip() in self.profiles[name].channel_ids:
                        group, group_reason = name, "来源频道精确匹配"
                        break
                else:
                    if product_topic == "AI":
                        group, group_reason = "ai_news", "显式主题 AI"
        role, rule_id, aliases = ProductRole.DEFAULT, "DEFAULT", ()
        if product_alias is not None:
            rule_id, aliases = "MANUAL", (product_alias,)
        elif group != "other":
            aliases, rule_id = self.profiles[group].candidates, group
            role = {"wallstreet": ProductRole.FINANCE, "ai_news": ProductRole.NEWS}.get(group, ProductRole.DEFAULT)
        else:
            for kind, value in (("channel", source_channel_id), ("category", category)):
                normalized = value.strip() if isinstance(value, str) else ""
                match = next((r for r in self.rules if r.kind == kind and normalized in r.values), None)
                if match:
                    role, rule_id, aliases = match.role, match.rule_id, match.candidates
                    break
            else:
                if self.profiles:
                    aliases = self.profiles["other"].candidates
        return ProductDecision(role, rule_id, self.version, self.digest, self.chain(aliases),
                               self.max_attempts, self.timeout_seconds, context, group, group_reason)


def parse_product_policy(data: dict) -> ProductPolicy:
    """校验全部引用/冲突/预算后生成内容摘要；非法更新不能成为有效策略。"""
    import hashlib
    import json
    import math
    from datetime import datetime

    def obj(value, allowed, required):
        if not isinstance(value, dict) or set(value) - set(allowed) or not set(required) <= set(value):
            raise ValueError("配置字段缺失、类型错误或含未知字段")

    def string(value):
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ValueError("配置字符串必须非空且无首尾空白")
        return value

    def strings(value):
        if not isinstance(value, list) or not value:
            raise ValueError("候选/条件列表不能为空")
        values = tuple(string(v) for v in value)
        if len(values) != len(set(values)):
            raise ValueError("列表包含重复项")
        return values

    fields = {"schema_version", "version", "products", "rules", "default_candidates", "timeout_seconds", "max_attempts"}
    if isinstance(data, dict) and data.get('schema_version') == 2:
        fields.add('profiles')
    obj(data, fields, fields)
    if type(data['schema_version']) is not int or data['schema_version'] not in (1, 2):
        raise ValueError("不支持的 schema_version")
    version = string(data['version'])
    seconds, attempts = data['timeout_seconds'], data['max_attempts']
    if type(seconds) not in (int, float) or not 0 < seconds <= 60 or not math.isfinite(seconds):
        raise ValueError("总预算必须在 0–60 秒之间")
    if type(attempts) is not int or not 1 <= attempts <= 3:
        raise ValueError("尝试次数必须为 1–3")
    if not isinstance(data['products'], dict) or not data['products']:
        raise ValueError("商品目录不能为空")
    products, identities = {}, {}
    for alias, item in data['products'].items():
        string(alias)
        fields = {"product_id", "title", "enabled", "verified_at", "verified_source"}
        obj(item, fields, fields)
        identity = ProductIdentity(item['product_id'], item['title'])
        if type(item['enabled']) is not bool:
            raise ValueError("enabled 必须是布尔值")
        datetime.fromisoformat(string(item['verified_at']))
        source = string(item['verified_source'])
        if identity.product_id in identities and identities[identity.product_id] != identity:
            raise ValueError("同一 ID 存在矛盾身份")
        identities[identity.product_id] = identity
        products[alias] = ProductEntry(identity, item['enabled'], item['verified_at'], source)
    if not isinstance(data['rules'], list):
        raise ValueError("rules 必须为列表")
    rules, ids, conditions = [], set(), set()
    for item in data['rules']:
        obj(item, {'id','kind','values','candidates','role'}, {'id','kind','values','candidates'})
        rule_id, kind = string(item['id']), string(item['kind'])
        if rule_id in ids or rule_id in {'DEFAULT','MANUAL'} or kind not in {'channel','category'}:
            raise ValueError("规则 ID 重复、保留或规则类型非法")
        values = strings(item['values'])
        for value in values:
            if (kind, value) in conditions:
                raise ValueError("同优先级规则条件冲突")
            conditions.add((kind, value))
        ids.add(rule_id)
        rules.append(ProductRule(rule_id, kind, values, strings(item['candidates']),
                                 ProductRole(item.get('role', 'default'))))
    profiles = {}
    if data['schema_version'] == 2:
        obj(data['profiles'], VIDEO_GROUPS, VIDEO_GROUPS)
        for name, item in data['profiles'].items():
            obj(item, {'candidates', 'channel_ids'}, {'candidates', 'channel_ids'})
            channels = item['channel_ids']
            if not isinstance(channels, list):
                raise ValueError('频道 ID 必须为列表')
            channels = strings(channels) if channels else ()
            if name in {'english_world', 'other'} and channels:
                raise ValueError('英语世界与其他不支持频道条件')
            # 空候选代表直接继承全局默认；备选与默认合并后仍必须可达。
            candidates = item['candidates']
            if not isinstance(candidates, list):
                raise ValueError('候选必须为列表')
            profiles[name] = ProductProfile(strings(candidates) if candidates else (), channels)
    serialized = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    policy = ProductPolicy(version, hashlib.sha256(serialized.encode()).hexdigest(),
                           MappingProxyType(products), tuple(rules), strings(data['default_candidates']),
                           float(seconds), attempts, serialized, MappingProxyType(profiles))
    policy.chain(())
    for rule in rules:
        policy.chain(rule.candidates)
    for profile in profiles.values():
        policy.chain(profile.candidates)
    # 目录中的每个启用商品都可人工指定，默认回退必须同样可达。
    for alias, entry in products.items():
        if entry.enabled:
            policy.chain((alias,))
    return policy
