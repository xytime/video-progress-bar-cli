# -*- coding: utf-8 -*-
"""火山方舟 Doubao Seed 2.0 API 测试脚本

# Modification History
| Version | Date       | Author                    | Description |
| ------- | ---------- | ------------------------- | ----------- |
| 1.0.0   | 2026-06-08 | Gemini_3.5_Flash_planning | 初始创建，使用 OpenAI SDK 验证火山方舟的种子模型 2.0 调用 |
"""
import os
import sys
from openai import OpenAI

# [Gemini_3.5_Flash_planning] 配置 API Key（如果环境变量中没有，就回退到用户的测试 Key）
api_key = os.getenv('ARK_API_KEY') or "ark-ef9cba65-fab1-47ee-8203-1c8aba1887e0-03d87"

client = OpenAI(
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    api_key=api_key,
)

# [Gemini_3.5_Flash_planning] 使用 responses.create 接口进行多模态调用测试
try:
    response = client.responses.create(
        model="doubao-seed-2-0-lite-260428",
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/ark_demo_img_1.png"
                    },
                    {
                        "type": "input_text",
                        "text": "你看见了什么？"
                    },
                ],
            }
        ]
    )
    print("✅ 调用成功！以下是返回结果：")
    print(response)
except Exception as e:
    print("❌ 调用失败！错误信息如下：")
    print(e)
