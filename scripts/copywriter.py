"""微信视频号文案生成器 - 生成短标题、文案正文、分类

# Modification History
| Version | Date       | Author                                  | Description                                      |
|---------|------------|-----------------------------------------|--------------------------------------------------|
| 1.0.0   | 2026-05-21 | Gemini_3.5_Flash_planning               | Initial creation with Gemini API + translator fallback |
| 1.1.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning     | 移除 os.getenv/load_dotenv，通过 settings 注入   |
| 1.2.0   | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning     | 结构化输出：短标题/文案/分类三文件；加原创/分类 LLM 推断 |
| 1.3.0   | 2026-05-24 | Claude_Sonnet_4.6_Thinking_planning     | 错误修复: parse_known_args 导致其他参数丢失；改为预处理 sys.argv + parse_args |
| 1.4.0   | 2026-05-24 | Claude_Sonnet_4.6_Thinking_planning     | P0终极修复: 注册全部4个参数，sys.argv预处理'-'前缀ID，彻底解决AttributeError |
"""

import sys
import os
import json
import argparse
import logging
from pathlib import Path

_src_root = os.path.join(os.path.dirname(__file__), '..', 'src')
if _src_root not in sys.path:
    sys.path.insert(0, _src_root)

from config.settings import settings  # [Claude_Sonnet_4.6_Thinking_planning]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("copywriter")

# 微信视频号支持的分类（与平台实际菜单保持一致）
WECHAT_CATEGORIES = [
    "科技", "财经", "教育", "生活", "娱乐",
    "游戏", "体育", "时事", "资讯", "健康",
]
DEFAULT_CATEGORY = "科技"


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def _strip_md_code_block(text: str) -> str:
    """剥除 LLM 可能输出的 ```json ... ``` 包裹"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # 去掉首行 ```json 和尾行 ```
        lines = lines[1:] if lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        text = "\n".join(lines)
    return text.strip()


# ── 后备路径 ─────────────────────────────────────────────────────────────────

def _translate_fallback(title: str, description: str) -> dict:
    """Gemini 不可用时，用 deep-translator 作兜底翻译"""
    logger.warning("Gemini unavailable — falling back to deep-translator")
    try:
        from deep_translator import GoogleTranslator
        tr = GoogleTranslator(source='auto', target='zh-CN')
        zh_title = tr.translate(title) or title
        desc_lines = [l.strip() for l in description.split("\n") if l.strip()]
        zh_desc = tr.translate(" ".join(desc_lines[:3])) if desc_lines else ""
        short_title = zh_title[:28]
        copy = f"【双语精选】{zh_title}\n\n"
        if zh_desc:
            copy += f"{zh_desc}\n\n"
        copy += "#AI #科技 #双语字幕\n🤖 关注本视频号，解锁更多前沿科技！"
        return {"short_title": short_title, "copy": copy, "category": DEFAULT_CATEGORY}
    except Exception as e:
        logger.error(f"deep-translator fallback failed: {e}")
        return {
            "short_title": title[:28],
            "copy": f"{title}\n\n#AI #科技\n🤖 关注本视频号！",
            "category": DEFAULT_CATEGORY,
        }


# ── 主生成函数 ───────────────────────────────────────────────────────────────

def generate_wechat_content(title: str, description: str,
                             model_name: str = "gemini-2.5-flash") -> dict:
    """调用 Gemini 生成微信视频号所需的全部内容。

    返回 dict:
        short_title : str  — ≤28 字，不含违禁词
        copy        : str  — 文案正文（100-200 字 + hashtag + CTA）
        category    : str  — WECHAT_CATEGORIES 之一
    """
    api_key = settings.gemini_api_key
    if not api_key:
        return _translate_fallback(title, description)

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        cats = "、".join(WECHAT_CATEGORIES)
        prompt = f"""你是微信视频号运营专家。根据以下 YouTube 视频信息，生成微信视频号发布所需内容。

要求：
1. short_title：必须是纯中文！一个极简、吸引眼球的中文短标题（可含 emoji），严格不超过 28 字，不能含有广告、政治等违禁词。绝对不能输出英文标题。
2. copy：文案正文，100-200 字的中文内容摘要 + 3-5 个 hashtag（#AI #科技等）+ 一句 CTA 结尾（可用 emoji），总字数不超过 600 字，纯文本不含 markdown。
3. category：从以下选项中选最合适的一个：{cats}。若不确定选「{DEFAULT_CATEGORY}」。

YouTube 标题：{title}
YouTube 简介（节选）：
{description[:800]}

仅返回 JSON，不要 markdown 代码块：
{{"short_title": "...", "copy": "...", "category": "..."}}"""

        logger.info(f"Calling Gemini [{model_name}]...")
        model = genai.GenerativeModel(model_name)
        raw = model.generate_content(prompt).text or ""
        raw = _strip_md_code_block(raw)
        result = json.loads(raw)

        short_title = str(result.get("short_title", title))[:28]
        copy        = str(result.get("copy", "")).strip()
        category    = result.get("category", DEFAULT_CATEGORY)
        if category not in WECHAT_CATEGORIES:
            logger.warning(f"Unknown category '{category}' from LLM, using default.")
            category = DEFAULT_CATEGORY
        if not copy:
            raise ValueError("Gemini returned empty copy")

        return {"short_title": short_title, "copy": copy, "category": category}

    except Exception as e:
        logger.error(f"Gemini call failed: {e}")
        return _translate_fallback(title, description)


# ── 兼容旧接口 ───────────────────────────────────────────────────────────────

def generate_wechat_copy(title: str, description: str,
                          model_name: str = "gemini-2.5-flash") -> str:
    """向后兼容：仅返回 copy 字符串"""
    return generate_wechat_content(title, description, model_name)["copy"]


# ── CLI 入口 ─────────────────────────────────────────────────────────────────

def main():
    # [Claude_Sonnet_4.6_Thinking_planning] v1.4 argparse '-'前缀 YouTube ID 终极修复
    # 根因: parse_known_args 只注册了 --youtube-id，导致其他参数全部丢失 → AttributeError
    # 根因2: argparse 把 '--youtube-id -X6YzlY_8tM' 中的 '-X...' 误认为 flag
    # 正确解法: 预处理 sys.argv，将 '--youtube-id -X...' 合并为 '--youtube-id=-X...'
    # 然后正常使用 parse_args()，所有参数都正确注册
    import sys
    argv = list(sys.argv[1:])  # 复制，不修改原始 sys.argv
    for i, arg in enumerate(argv):
        if arg == "--youtube-id" and i + 1 < len(argv):
            next_val = argv[i + 1]
            # 如果下一个值以 '-' 开头但不是 '--'，说明是以连字符开头的 YouTube ID
            if next_val.startswith("-") and not next_val.startswith("--"):
                argv[i] = f"--youtube-id={next_val}"
                argv.pop(i + 1)
            break

    parser = argparse.ArgumentParser(description="Generate WeChat Channels copy.")
    parser.add_argument("--youtube-id",  required=True, type=str)
    parser.add_argument("--title",       required=True, type=str)
    parser.add_argument("--desc-file",   default=None,  help="Path to description text file")
    parser.add_argument("--output-dir",  default="output", type=str)
    args = parser.parse_args(argv)

    description = ""
    if args.desc_file:
        p = Path(args.desc_file)
        if p.exists():
            description = p.read_text(encoding="utf-8")

    content = generate_wechat_content(args.title, description)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    (out / f"{args.youtube_id}_title.txt"   ).write_text(content["short_title"], encoding="utf-8")
    (out / f"{args.youtube_id}_copy.txt"    ).write_text(content["copy"],        encoding="utf-8")
    (out / f"{args.youtube_id}_category.txt").write_text(content["category"],    encoding="utf-8")

    logger.info(f"short_title → {content['short_title']!r}")
    logger.info(f"category    → {content['category']!r}")
    logger.info(f"copy        → output/{args.youtube_id}_copy.txt")
    print(out / f"{args.youtube_id}_copy.txt")


if __name__ == "__main__":
    main()
