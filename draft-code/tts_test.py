import os
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load env
# Try loading from .env in current dir, or parent dirs
load_dotenv()

OUTPUT_DIR = Path("output/tts_test")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Test text with "professional news anchor" vibe
TEST_TEXT = "观众朋友们大家好，这里是最新科技动态。刚才画面中展示的技术突破令人瞩目，它标志着我们在人工智能应用领域又迈出了坚实的一步。如果您希望深入了解这项技术的细节，请持续关注我们的深度报道。"

async def test_edge_tts(text, voice="zh-CN-XiaoxiaoNeural", output_name="edge_xiaoxiao.mp3"):
    """Generate audio using Edge TTS"""
    try:
        import edge_tts
    except ImportError:
        logger.error("edge-tts not installed.")
        return

    logger.info(f"Generating EdgeTTS ({voice})...")
    try:
        communicate = edge_tts.Communicate(text, voice)
        output_path = OUTPUT_DIR / output_name
        await communicate.save(str(output_path))
        logger.info(f"Saved to {output_path}")
    except Exception as e:
        logger.error(f"EdgeTTS failed: {e}")

async def test_edge_tts_ssml(text, voice="zh-CN-XiaoxiaoNeural", style="newscast", output_name="edge_xiaoxiao_news.mp3"):
    """Generate audio using Edge TTS with SSML style"""
    try:
        import edge_tts
    except ImportError:
        logger.error("edge-tts not installed.")
        return

    logger.info(f"Generating EdgeTTS SSML ({voice}, style={style})...")
    
    ssml_text = f"""
    <speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="zh-CN">
        <voice name="{voice}">
            <mstts:express-as style="{style}">
                {text}
            </mstts:express-as>
        </voice>
    </speak>
    """
    
    try:
        # Note: When using SSML, we usually just pass the SSML string as text. 
        # But we must ensure the voice matches or is omitted in Communicate init if SSML has it?
        # Actually edge-tts Communicate(text, voice) overrides voice in SSML or vice versa?
        # Safe bet: pass voice in init too.
        communicate = edge_tts.Communicate(ssml_text, voice)
        output_path = OUTPUT_DIR / output_name
        await communicate.save(str(output_path))
        logger.info(f"Saved to {output_path}")
    except Exception as e:
        logger.error(f"EdgeTTS SSML failed: {e}")

def test_openai_tts(text, voice="onyx", output_name="openai_onyx.mp3"):
    """Generate audio using OpenAI TTS"""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not found. Skipping OpenAI TTS.")
        return

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
    except ImportError:
        logger.error("openai module not installed.")
        return

    logger.info(f"Generating OpenAI TTS ({voice})...")
    try:
        response = client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text
        )
        output_path = OUTPUT_DIR / output_name
        response.stream_to_file(output_path)
        logger.info(f"Saved to {output_path}")
    except Exception as e:
        logger.error(f"OpenAI TTS failed: {e}")

async def main():
    logger.info("Starting TTS Test...")
    logger.info(f"Text: {TEST_TEXT}")
    
    # 1. Edge TTS Tests (Free, high quality)
    # Common high quality voices: zh-CN-XiaoxiaoNeural (Female), zh-CN-YunxiNeural (Male)
    await test_edge_tts(TEST_TEXT, "zh-CN-XiaoxiaoNeural", "edge_xiaoxiao.mp3")
    await test_edge_tts(TEST_TEXT, "zh-CN-YunxiNeural", "edge_yunxi.mp3")
    
    # SSML Style Test (Newscast)
    await test_edge_tts_ssml(TEST_TEXT, "zh-CN-XiaoxiaoNeural", "newscast", "edge_xiaoxiao_news.mp3")
    await test_edge_tts_ssml(TEST_TEXT, "zh-CN-YunxiNeural", "newscast", "edge_yunxi_news.mp3")
    
    # 2. OpenAI TTS Tests (Paid, "English tone" candidate?)
    # Voices: alloy, echo, fable, onyx, nova, shimmer
    # Alloy is very neutral/versatile.
    test_openai_tts(TEST_TEXT, "alloy", "openai_alloy.mp3")
    # Shimmer is often good for narration
    test_openai_tts(TEST_TEXT, "shimmer", "openai_shimmer.mp3") 
    test_openai_tts(TEST_TEXT, "echo", "openai_echo.mp3")
    
    logger.info("Test complete. Check output/tts_test/ folder.")

if __name__ == "__main__":
    asyncio.run(main())
