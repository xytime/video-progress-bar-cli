"""WeChat Channels Copywriter - Generate WeChat Channel-friendly Chinese copy from YouTube metadata.

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-21 | Gemini_3.5_Flash_planning | Initial creation of the copywriter script with Gemini API and translator fallback |
| 1.1.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 地基重构：移除 os.getenv 和 load_dotenv，通过 settings 注入 GEMINI_API_KEY |
"""

import sys
import os
import argparse
import logging
from pathlib import Path

# 确保可以导入 src 目录下的模块（scripts/ 与 src/ 同级）
_src_root = os.path.join(os.path.dirname(__file__), '..', 'src')
if _src_root not in sys.path:
    sys.path.insert(0, _src_root)

from config.settings import settings  # [Claude_Sonnet_4.6_Thinking_planning] 统一通过 settings 注入

# 设置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("copywriter")

def translate_fallback(title: str, description: str) -> str:
    """当 Gemini API 无法使用时，使用 deep-translator 进行备用翻译"""
    # [Gemini_3.5_Flash_planning] 备用逻辑，防止 API 密钥缺失导致管线崩溃
    logger.warning("Gemini API key not found or call failed. Using deep-translator fallback.")
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source='auto', target='zh-CN')
        
        translated_title = translator.translate(title)
        
        # 限制简介字数，避免过长
        desc_lines = [line.strip() for line in description.split("\n") if line.strip()]
        desc_snippet = " ".join(desc_lines[:3]) # 取前三行非空内容
        translated_desc = ""
        if desc_snippet:
            translated_desc = translator.translate(desc_snippet)
            
        copy_text = f"【双语精选】{translated_title}\n\n"
        if translated_desc:
            copy_text += f"{translated_desc}\n\n"
        copy_text += "#AI #科技 #翻译 #双语字幕\n"
        copy_text += "🤖 关注本视频号，解锁更多前沿AI与科技资讯！"
        return copy_text
    except Exception as e:
        logger.error(f"Fallback translation also failed: {e}")
        # 最极端的兜底：直接输出原标题和预设后缀
        return f"{title}\n\n#AI #科技\n🤖 关注本视频号，解锁更多前沿科技！"

def generate_wechat_copy(title: str, description: str, model_name: str = "gemini-2.5-flash") -> str:
    """调用 Gemini API 生成适合微信视频号的宣传文案"""
    # [Claude_Sonnet_4.6_Thinking_planning] 通过 settings 统一注入，消灭散落的 os.getenv
    api_key = settings.gemini_api_key
    if not api_key:
        return translate_fallback(title, description)
        
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        
        # [Gemini_3.5_Flash_planning] 构造高质量的提示词，要求输出精简、吸引人且带有话题的中文文案
        prompt = f"""
You are an expert social media manager specializing in tech content for WeChat Channels (微信视频号).
Please translate and rewrite the following YouTube video title and description into an engaging Chinese social media post.

Requirements:
1. Title: Create a catchy, click-worthy Chinese title/slogan (incorporate emojis).
2. Body: Write a concise, engaging summary in Chinese (100-200 words) summarizing the core value or most interesting parts of the video.
3. Hashtags: Generate 3 to 5 highly relevant tech hashtags starting with # (e.g. #AI #AIGC #科技).
4. Ending: Append a custom call-to-action inviting users to follow the channel.
5. Length: Keep the total output under 600 Chinese characters. Do NOT output any English or markdown formatting like '【标题】' in the final output. The format should be clean text.

YouTube Video Title: {title}
YouTube Video Description:
{description}

Example Output Format:
🚀【视频号标题】
(简短而具有吸引力的视频介绍内容，吸引用户点击和看完视频)

#标签1 #标签2 #标签3
🤖 关注本视频号，每天为您解锁更多前沿AI与科技黑科技！
"""
        logger.info(f"Calling Gemini model {model_name}...")
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        if not text:
            raise ValueError("Gemini returned empty text")
            
        return text
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        return translate_fallback(title, description)

def main():
    parser = argparse.ArgumentParser(description="Generate WeChat Channels copy from YouTube metadata.")
    parser.add_argument("--youtube-id", required=True, help="YouTube Video ID")
    parser.add_argument("--title", required=True, help="Original Video Title")
    parser.add_argument("--desc-file", help="Path to the file containing original video description")
    parser.add_argument("--output-dir", default="output", help="Directory to save the generated copy")
    
    args = parser.parse_args()
    
    description = ""
    if args.desc_file:
        desc_path = Path(args.desc_file)
        if desc_path.exists():
            description = desc_path.read_text(encoding="utf-8")
            
    # 生成文案
    copy_text = generate_wechat_copy(args.title, description)
    
    # 写入输出文件
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    output_path = out_dir / f"{args.youtube_id}_copy.txt"
    output_path.write_text(copy_text, encoding="utf-8")
    
    logger.info(f"Successfully generated WeChat copy: {output_path}")
    print(output_path)

if __name__ == "__main__":
    main()
