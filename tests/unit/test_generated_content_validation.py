"""发布文案错误页防护回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-04 | Codex | 覆盖 HTTP 错误页阻断及正常技术标题不误伤 |
"""

import pytest

from video_processing.utils.generated_content_validation import (
    GeneratedContentValidationError,
    validate_publishable_generated_content,
)


def test_rejects_exact_http_error_title():
    with pytest.raises(GeneratedContentValidationError, match="短标题是上游错误响应"):
        validate_publishable_generated_content("Error 500", "这是一段正常文案。")


def test_rejects_google_error_page_copy():
    copy = (
        "Error 500 (Server Error)!!1500. That's an error. "
        "There was an error. Please try again later. That's all we know."
    )

    with pytest.raises(GeneratedContentValidationError, match="HTTP 错误页"):
        validate_publishable_generated_content("英伟达芯片变革", copy)


def test_allows_normal_technical_error_500_topic():
    validate_publishable_generated_content(
        "如何修复 Error 500",
        "从网关、应用日志和数据库连接三个方向排查服务器错误。",
    )


@pytest.mark.parametrize("title,copy", [("", "有效文案"), ("有效标题", "")])
def test_rejects_empty_required_content(title, copy):
    with pytest.raises(GeneratedContentValidationError):
        validate_publishable_generated_content(title, copy)
