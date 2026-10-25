"""旧版回复策略的纯结构校验；配置层与业务层共用，避免相互导入。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 原样迁移既有严格校验，供联动入口解析旧版时段。 |
"""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

_TIME_START_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_TIME_END_RE = re.compile(r"^(?:(?:[01]\d|2[0-3]):[0-5]\d|24:00)$")

class SecondaryReplyPolicyModel(BaseModel):
    """二级回复运营策略 Schema（禁止额外字段与类型强转）。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, strict=True, ge=1, le=1)
    window_start_shanghai: str = Field(default="00:00")
    window_end_shanghai: str = Field(default="24:00")
    min_interval_seconds: int = Field(default=3600, strict=True, ge=0, le=86400)
    hourly_quota: int = Field(default=10, strict=True, ge=1, le=100)
    max_per_video: int = Field(default=3, strict=True, ge=1, le=20)
    approval_mode: Literal["manual", "hybrid_auto"] = "manual"


class LinkedReplyPolicyModel(SecondaryReplyPolicyModel):
    """运行配置既有秒数上界为七天；旧文件契约仍沿用一天。"""
    min_interval_seconds: int = Field(default=3600, strict=True, ge=0, le=604800)


def parse_policy(data: dict, *, editor=False) -> dict:
    """校验并规范化二级回复策略字典。"""
    value = (LinkedReplyPolicyModel if editor else SecondaryReplyPolicyModel).model_validate(data).model_dump()
    start = value["window_start_shanghai"]
    end = value["window_end_shanghai"]
    if not _TIME_START_RE.fullmatch(start):
        raise ValueError(f"开始时间格式不合法（须为 00:00–23:59）：{start}")
    if not _TIME_END_RE.fullmatch(end):
        raise ValueError(f"结束时间格式不合法（须为 00:00–24:00）：{end}")
    return value
