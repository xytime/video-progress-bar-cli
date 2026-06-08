# -*- coding: utf-8 -*-
"""测试使用豆包 Seed 2.0 模型进行字幕翻译和词汇提取

# Modification History
| Version | Date       | Author                    | Description |
| ------- | ---------- | ------------------------- | ----------- |
| 1.0.0   | 2026-06-08 | Gemini_3.5_Flash_planning | 初始创建，评估豆包 Seed 2.0 模型的实际翻译和生词提取效果 |
"""
import os
import json
from openai import OpenAI

# [Gemini_3.5_Flash_planning] 使用用户的 API Key 进行调用
api_key = os.getenv('ARK_API_KEY') or "ark-ef9cba65-fab1-47ee-8203-1c8aba1887e0-03d87"

client = OpenAI(
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    api_key=api_key,
)

# 测试句段列表（来自实际视频）
test_segments = [
    {
        "id": 1,
        "text": "There was a moment, and you remember it exactly, when someone looked at you and decided you would not make it."
    },
    {
        "id": 2,
        "text": "Maybe it was subtler than that, a raised eyebrow, a dismissive silence."
    },
    {
        "id": 3,
        "text": "a gentle and devastating suggestion that you should be more realistic, aim lower."
    }
]

# [Gemini_3.5_Flash_planning] 组装批量处理 Prompt
prompt = (
    "You are an expert bilingual translation engine. Translate the following list of English video segments into natural, "
    "flowing, contextual Chinese. For each segment, also extract 1 or 2 difficult vocabulary words/idioms, providing their "
    "exact Chinese definitions in this context.\n"
    "Respond ONLY with a JSON array matching the following structure:\n"
    "[\n"
    "  {\n"
    "    \"id\": 1,\n"
    "    \"translation\": \"中文翻译\",\n"
    "    \"vocab\": {\n"
    "      \"english_word\": \"精确中文释义\"\n"
    "    }\n"
    "  }\n"
    "]\n\n"
    f"Segments to translate:\n{json.dumps(test_segments, indent=2, ensure_ascii=False)}"
)

print("🚀 正在请求豆包大模型 (doubao-seed-2-0-lite-260428) 进行批量翻译与词汇解析...")

try:
    # [Gemini_3.5_Flash_planning] 发送 API 请求
    response = client.chat.completions.create(
        model="doubao-seed-2-0-lite-260428",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )
    
    output = response.choices[0].message.content
    print("\n✅ 调用成功！以下是豆包模型生成的真实翻译与词汇提取结果：\n")
    
    # 尝试美化 JSON 输出
    try:
        parsed_data = json.loads(output)
        # 兼容包裹在大 key 里的情形，如 {"results": [...]}
        if isinstance(parsed_data, dict) and len(parsed_data) == 1:
            key = list(parsed_data.keys())[0]
            if isinstance(parsed_data[key], list):
                parsed_data = parsed_data[key]
        print(json.dumps(parsed_data, ensure_ascii=False, indent=2))
    except Exception:
        print(output)
        
except Exception as e:
    print("❌ 调用失败！错误信息如下：")
    print(e)
