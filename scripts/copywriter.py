"""微信视频号文案生成器 - 生成短标题、文案正文、分类

# Modification History
| Version | Date       | Author                                  | Description                                      |
|---------|------------|-----------------------------------------|--------------------------------------------------|
| 1.0.0   | 2026-05-21 | Gemini_3.5_Flash_planning               | Initial creation with Gemini API + translator fallback |
| 1.1.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning     | 移除 os.getenv/load_dotenv，通过 settings 注入   |
| 1.2.0   | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning     | 结构化输出：短标题/文案/分类三文件；加原创/分类 LLM 推断 |
| 1.3.0   | 2026-05-24 | Claude_Sonnet_4.6_Thinking_planning     | 错误修复: parse_known_args 导致其他参数丢失；改为预处理 sys.argv + parse_args |
| 1.4.0   | 2026-05-24 | Claude_Sonnet_4.6_Thinking_planning     | P0终极修复: 注册全部4个参数，sys.argv预处理'-'前缀ID，彻底解决AttributeError |
| 1.5.0   | 2026-05-26 | Claude_Sonnet_4.6_Thinking_fast         | 标题质量改造: 短标题字数修歗6-16（匹配微信平台真实限制）; 新增 hook_subtitle 和 content_hints 输出 |
| 1.6.0   | 2026-05-26 | Gemini_3.5_Flash_planning               | 标题调性补强：增加专业术语词典映射与负向营销词黑名单，提升文案格调并引入兜底纠偏 |
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
        short_title   : str  — 6-16 字（匹配微信视频号后台真实限制），自媒体流量型标题
        hook_subtitle : str  — ≤ 24 字，封面副标题 Hook（悬念/利益/冲突延伸）
        copy          : str  — 文案正文（100-200 字 + hashtag + CTA）
        category      : str  — WECHAT_CATEGORIES 之一
        content_hints : list — 2-5 个语义 token（英文），给封面引擎使用
    """
    api_key = settings.gemini_api_key
    if not api_key:
        return _translate_fallback(title, description)

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        cats = "、".join(WECHAT_CATEGORIES)
        # [Gemini_3.5_Flash_planning] v1.6.0 标题质量与格调深度强化：
        # 1. 约束字数在 6-16 字 (微信视频号后台真实限制)
        # 2. 引入行业专业术语词汇对照映射，杜绝直译硬译机翻感
        # 3. 设定负向黑名单，绝对禁止使用廉价自媒体营销词
        # 4. 提供 High-End 调性对照 Few-Shot 示例
        prompt = f"""你是顶级微信视频号内容策划和中文科技媒体专栏主编。

【核心认知】封面标题是用户划走还是停留的唯一决策依据。平庸的「信息摘要型」标题无法吸引注意力。你必须生成兼具传播力与高级感的「流量型」标题。

【专业词汇映射规范（必须使用本土化中文科技/财经语境词汇，禁止生硬直译）】
- concept laptop -> 概念机/原型机/黑科技电脑 (严禁直译为“概念本”)
- prompting / prompt playbook -> 提示词/向AI提问/提问方法论 (严禁直译为“提示词剧本”)
- exit trap -> 资本接盘/套现陷阱 (严禁直译为“退出陷阱”)
- crushes -> 彻底碾压/超越/颠覆 (严禁直译为“击碎”)

【文案格调规范（禁止廉价营销词与情绪垃圾）】
- 严禁在标题和副标题中使用以下自媒体字眼：爆款、干货、秘籍、公式、逆天、震惊、绝密、必看、收藏、保姆级、悄悄告诉你。
- 标题应当呈现高端、专业、深度的“科技评论/财经观察”质感。使用认知冲突、底层逻辑、思维框架来吸引高净值用户，避免滥用叹号。

【调性对比示范】
- 廉价营销（严禁）：《爆款提示词公式，3步压榨AI全部潜能！》 ❌
- 高端质感（推荐）：《向AI提问的艺术：如何构建你的提示词体系》 ✅
- 廉价营销（严禁）：《最强概念本曝光，性能逆天震惊全网！》 ❌
- 高端质感（推荐）：《未来电脑长这样？超前原型机震撼曝光》 ✅

【短标题黄金公式，选择最适合内容的一种】
- 冲突型：「A正在崩塌，B却在逆势崛起」
- 悬念型：「没人告诉你的X真相」
- 利益型：「看完这个你将比99%的人更早理解X」
- 颠覆型：「所有人都错了——X的真相是」
- 预言型：「未来5年，做X的人会被彻底淘汰」

【硬性约束（必须遵守）】
- short_title：纯中文，6-16字（微信视频号后台实际限制），必须达到流量型标题的情绪张力
- hook_subtitle：纯中文，≤ 24 字，呼应短标题，制造悬念延伸或承诺具体利益
- copy：100-200字中文文案摘要 + 3-5个 hashtag + 一句 CTA，纯文本不含 markdown
- category：从以下选一：{cats}
- content_hints：从以下英文 token 中选 2-5 个：
  policy market capital robot ai crypto mindset health geopolitics space energy quantum
- 禁止：emoji / 广告废话 / 翻译腔 / 政治敏感词

YouTube 标题：{title}
YouTube 简介（节选）：
{description[:800]}

仅返回 JSON，无 markdown：
{{"short_title": "...", "hook_subtitle": "...", "copy": "...", "category": "...", "content_hints": ["ai", "market"]}}"""

        logger.info(f"Calling Gemini [{model_name}]...")
        model = genai.GenerativeModel(model_name)
        raw = model.generate_content(prompt).text or ""
        raw = _strip_md_code_block(raw)
        result = json.loads(raw)

        # 小标题：微信平台限制16字，少于6字为无效将导致上传失败
        raw_title = str(result.get("short_title", title))
        short_title = raw_title[:16]  # 硬截断最大限制
        if len(short_title) < 6:
            logger.warning(f"short_title too short ({len(short_title)} chars), padding with original title")
            short_title = title[:16]

        hook_subtitle = str(result.get("hook_subtitle", ""))[:24].strip()
        copy          = str(result.get("copy", "")).strip()
        category      = result.get("category", DEFAULT_CATEGORY)
        content_hints = result.get("content_hints", [])
        if not isinstance(content_hints, list):
            content_hints = []
        if category not in WECHAT_CATEGORIES:
            logger.warning(f"Unknown category '{category}' from LLM, using default.")
            category = DEFAULT_CATEGORY
        if not copy:
            raise ValueError("Gemini returned empty copy")

        # [Gemini_3.5_Flash_planning] v1.6.0 后处理纠偏兜底：强制替换残留的劣质词汇与生硬直译词汇
        replacements = {
            "概念本": "原型机",
            "爆款": "高阶",
            "秘籍": "指南",
            "公式": "体系",
            "逆天": "突破",
            "震惊": "震撼",
        }
        for bad_word, good_word in replacements.items():
            if bad_word in short_title:
                logger.info(f"Post-processing: replacing forbidden word {bad_word!r} with {good_word!r} in title")
                short_title = short_title.replace(bad_word, good_word)
            if bad_word in hook_subtitle:
                logger.info(f"Post-processing: replacing forbidden word {bad_word!r} with {good_word!r} in subtitle")
                hook_subtitle = hook_subtitle.replace(bad_word, good_word)

        return {
            "short_title":   short_title,
            "hook_subtitle": hook_subtitle,
            "copy":          copy,
            "category":      category,
            "content_hints": content_hints,
        }

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

    yid = args.youtube_id
    (out / f"{yid}_title.txt"   ).write_text(content["short_title"],   encoding="utf-8")
    (out / f"{yid}_copy.txt"    ).write_text(content["copy"],           encoding="utf-8")
    (out / f"{yid}_category.txt").write_text(content["category"],       encoding="utf-8")

    # [Claude_Sonnet_4.6_Thinking_fast] v1.5.0 新增：写出封面引擎依赖的两个文件
    if content.get("hook_subtitle"):
        (out / f"{yid}_subtitle.txt").write_text(content["hook_subtitle"], encoding="utf-8")
        logger.info(f"hook_subtitle → {content['hook_subtitle']!r}")
    if content.get("content_hints"):
        (out / f"{yid}_content_hints.json").write_text(
            json.dumps(content["content_hints"], ensure_ascii=False), encoding="utf-8"
        )
        logger.info(f"content_hints → {content['content_hints']!r}")

    logger.info(f"short_title → {content['short_title']!r} (len={len(content['short_title'])})")
    logger.info(f"category    → {content['category']!r}")
    logger.info(f"copy        → output/{yid}_copy.txt")
    print(out / f"{yid}_copy.txt")


if __name__ == "__main__":
    main()
