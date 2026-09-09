"""发布文案错误页防护回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-04 | Codex | 覆盖 HTTP 错误页阻断及正常技术标题不误伤 |
| 1.1.0 | 2026-08-05 | Codex | 覆盖完整 Error 500 错误页不能作为标题翻译入库 |
| 1.2.0 | 2026-09-09 | Codex | 中文正文检查排除模板/链接/标签，保留通用英文工作流 |
"""

import pytest

from video_processing.utils.generated_content_validation import (
    GeneratedContentValidationError,
    is_upstream_error_response,
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


def test_rejects_full_error_page_as_title_translation():
    error_page = (
        "Error 500 (Server Error)!!1500.That’s an error.There was an error. "
        "Please try again later.That’s all we know."
    )

    assert is_upstream_error_response(error_page)
    with pytest.raises(GeneratedContentValidationError, match="短标题是上游错误响应"):
        validate_publishable_generated_content(error_page, "这是一段正常文案。")


def test_allows_normal_technical_error_500_topic():
    validate_publishable_generated_content(
        "如何修复 Error 500",
        "从网关、应用日志和数据库连接三个方向排查服务器错误。",
    )


@pytest.mark.parametrize("title,copy", [("", "有效文案"), ("有效标题", "")])
def test_rejects_empty_required_content(title, copy):
    with pytest.raises(GeneratedContentValidationError):
        validate_publishable_generated_content(title, copy)


def test_chinese_heading_and_tags_cannot_hide_english_body():
    body = "【双语精选】财政部回购国债\n\nWashington is quietly buying back its own long bonds this coming week.\n#国债 #财经 #双语"
    with pytest.raises(GeneratedContentValidationError, match="中文合同"):
        validate_publishable_generated_content("财政部回购国债", body, require_chinese=True)


def test_chinese_copy_allows_product_names_and_source_links():
    validate_publishable_generated_content(
        "AI改变法律服务", "OpenAI 与 MGX 合作，讨论人工智能对法律服务流程的影响。https://example.com/english-source #AI",
        require_chinese=True,
    )


def test_non_chinese_workflows_keep_generic_contract():
    validate_publishable_generated_content("English World", "This is an English learning video.")
