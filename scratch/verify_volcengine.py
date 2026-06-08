# -*- coding: utf-8 -*-
"""火山引擎 (Volcengine) API 快速验证工具

# Modification History
| Version | Date       | Author                    | Description |
| ------- | ---------- | ------------------------- | ----------- |
| 1.0.0   | 2026-06-08 | Gemini_3.5_Flash_planning | 初始创建，支持豆包 LLM 和火山 TTS API 的快速验证 |
"""
import os
import sys
import time
import base64
import json
import asyncio
import httpx
from pathlib import Path

# [Gemini_3.5_Flash_planning] 从环境变量或.env加载配置
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 火山方舟（豆包大模型 API）配置
VOLC_ARK_API_KEY = os.getenv("VOLC_ARK_API_KEY", "")
VOLC_ARK_ENDPOINT_ID = os.getenv("VOLC_ARK_ENDPOINT_ID", "")  # 模型推理接入点ID，如 ep-2026xxxx

# 火山语音合成（TTS）配置
VOLC_TTS_APP_ID = os.getenv("VOLC_TTS_APP_ID", "")
VOLC_TTS_ACCESS_TOKEN = os.getenv("VOLC_TTS_ACCESS_TOKEN", "")
# 常用音色：bv001_streaming (标准女声), bv002_streaming (标准男声), bv700_streaming (精品解说老铁)
VOLC_TTS_VOICE = os.getenv("VOLC_TTS_VOICE", "bv700_streaming")

async def verify_doubao_llm(client: httpx.AsyncClient, text_segment: str) -> dict:
    """[Gemini_3.5_Flash_planning] 验证豆包大模型翻译与生词提取能力"""
    if not VOLC_ARK_API_KEY or not VOLC_ARK_ENDPOINT_ID:
        print("⚠️ 未配置 VOLC_ARK_API_KEY 或 VOLC_ARK_ENDPOINT_ID，跳过豆包 LLM 真实请求测试。")
        return {}

    url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    headers = {
        "Authorization": f"Bearer {VOLC_ARK_API_KEY}",
        "Content-Type": "application/json"
    }

    # 构造与 Gemini 类似的结构化提取 Prompt
    prompt = (
        "You are an expert bilingual translator. Translate the following English sentence into natural Chinese. "
        "Also, identify 1-2 difficult vocabulary words or idioms, and provide their Chinese definitions. "
        "Output the result strictly in JSON format as: "
        '{"translation": "中文翻译", "vocab": {"english_word": "中文释义"}}\n\n'
        f"Text to translate: {text_segment}"
    )

    data = {
        "model": VOLC_ARK_ENDPOINT_ID,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3
    }

    print("🚀 正在请求豆包大模型 API...")
    start_time = time.time()
    
    response = await client.post(url, headers=headers, json=data, timeout=30.0)
    latency = time.time() - start_time
    
    if response.status_code != 200:
        print(f"❌ 豆包 LLM API 请求失败: HTTP {response.status_code}\n响应内容: {response.text}")
        return {}

    result = response.json()
    content = result["choices"][0]["message"]["content"]
    
    print(f"✅ 豆包 LLM 响应成功! 耗时: {latency:.2f} 秒")
    print(f"💬 模型返回原始内容: {content}")
    try:
        # 尝试解析 JSON
        parsed = json.loads(content.strip().strip("```json").strip("```"))
        return parsed
    except Exception as e:
        print(f"⚠️ 解析 JSON 失败: {e}")
        return {"raw_content": content}

async def verify_volcano_tts(client: httpx.AsyncClient, text_to_speak: str) -> Path:
    """[Gemini_3.5_Flash_planning] 验证火山语音合成 (TTS) API 并将生成的音频保存到本地"""
    if not VOLC_TTS_APP_ID or not VOLC_TTS_ACCESS_TOKEN:
        print("⚠️ 未配置 VOLC_TTS_APP_ID 或 VOLC_TTS_ACCESS_TOKEN，跳过火山 TTS 真实请求测试。")
        return None

    # 火山引擎 TTS HTTP 非流式接口
    url = "https://openspeech.bytedance.com/api/v1/tts"
    headers = {
        "Authorization": f"Bearer; {VOLC_TTS_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    data = {
        "app": {
            "appid": VOLC_TTS_APP_ID,
            "token": VOLC_TTS_ACCESS_TOKEN,
            "cluster": "volcano_tts"
        },
        "user": {
            "uid": "388808999999999"
        },
        "audio": {
            "voice_type": VOLC_TTS_VOICE,
            "encoding": "mp3",
            "speed_ratio": 1.0,
            "volume_ratio": 1.0,
            "pitch_ratio": 1.0
        },
        "request": {
            "reqid": f"req_{int(time.time())}",
            "text": text_to_speak,
            "text_type": "plain",
            "operation": "query"
        }
    }

    print(f"🚀 正在请求火山 TTS API (音色: {VOLC_TTS_VOICE})...")
    start_time = time.time()

    response = await client.post(url, headers=headers, json=data, timeout=30.0)
    latency = time.time() - start_time

    if response.status_code != 200:
        print(f"❌ 火山 TTS 请求失败: HTTP {response.status_code}\n响应内容: {response.text}")
        return None

    result = response.json()
    if result.get("code") != 30000000:
        print(f"❌ 火山 TTS 服务端返回错误码: {result.get('code')}, 消息: {result.get('message')}")
        return None

    audio_base64 = result.get("data", "")
    if not audio_base64:
        print("❌ 火山 TTS 返回的音频数据为空")
        return None

    # 解码音频并保存
    audio_data = base64.b64decode(audio_base64)
    output_path = Path(__file__).parent / "volc_test_tts.mp3"
    with open(output_path, "wb") as f:
        f.write(audio_data)

    print(f"✅ 火山 TTS 成功! 耗时: {latency:.2f} 秒，音频文件已保存至: {output_path}")
    return output_path

async def main():
    test_english_segment = "There was a moment when someone decided you would not make it."
    test_chinese_segment = "曾经有那么一个时刻，有人断定你不会成功。"

    print("================ 火山引擎 API 验证工具 ================")
    print("当前环境变量配置：")
    print(f"- VOLC_ARK_API_KEY: {'[已配置]' if VOLC_ARK_API_KEY else '[未配置]'}")
    print(f"- VOLC_ARK_ENDPOINT_ID: {VOLC_ARK_ENDPOINT_ID or '[未配置]'}")
    print(f"- VOLC_TTS_APP_ID: {'[已配置]' if VOLC_TTS_APP_ID else '[未配置]'}")
    print(f"- VOLC_TTS_ACCESS_TOKEN: {'[已配置]' if VOLC_TTS_ACCESS_TOKEN else '[未配置]'}")
    print(f"- VOLC_TTS_VOICE: {VOLC_TTS_VOICE}")
    print("=====================================================")

    async with httpx.AsyncClient() as client:
        # 1. 验证豆包 LLM
        print("\n--- 1. 豆包大语言模型测试 ---")
        llm_result = await verify_doubao_llm(client, test_english_segment)
        if llm_result:
            print(f"🔍 结构化数据解析成功:")
            print(json.dumps(llm_result, ensure_ascii=False, indent=2))
        else:
            print("💡 模拟数据演示 (如果配置了密钥，模型应返回此格式):")
            mock_llm_json = {
                "translation": "曾经有那么一个时刻，有人断定你不会成功。",
                "vocab": {
                    "make it": "成功，撑过去"
                }
            }
            print(json.dumps(mock_llm_json, ensure_ascii=False, indent=2))

        # 2. 验证火山 TTS
        print("\n--- 2. 火山语音合成 (TTS) 测试 ---")
        audio_file = await verify_volcano_tts(client, test_chinese_segment)
        if not audio_file:
            print("💡 提示: 火山 TTS 请求成功后会直接返回 Base64 编码的 MP3 音频流，可以直接保存和播放。")
            print("常见音色推荐:")
            print("  - bv700_streaming: 爆款短视频解说「老铁」")
            print("  - bv001_streaming: 自然流利女声")
            print("  - bv002_streaming: 磁性故事男声")
            
    print("\n==================== 验证结束 ====================")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
