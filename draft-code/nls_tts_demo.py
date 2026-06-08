# -*- coding: utf-8 -*-
"""阿里云智能语音交互 (NLS) 语音合成 RESTful API Demo

# Modification History
| Version | Date       | Author                     | Description |
| ------- | ---------- | -------------------------- | ----------- |
| 1.0.0   | 2026-05-28 | Gemini_3.5_Flash_planning  | 初始创建 NLS TTS 接口调用 Demo，支持自动获取 Token |
| 1.0.1   | 2026-06-09 | Gemini_3.5_Flash_planning  | [安全加固] 移除硬编码 AccessKey 凭证，改用环境变量动态加载 |
"""

import os
import sys
import json
import requests
from pathlib import Path
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.request import CommonRequest

# [Gemini_3.5_Flash_planning] 从环境变量中动态获取凭证，避免明文硬编码密钥泄露风险
AK_ID = os.getenv("ALIYUN_AK_ID", "YOUR_ACCESS_KEY_ID")
AK_SECRET = os.getenv("ALIYUN_AK_SECRET", "YOUR_ACCESS_KEY_SECRET")

# ⚠️ 注意：智能语音交互 (NLS) 服务没有公共 AppKey，需要您在控制台创建一个项目获取 AppKey。
# 详情参见控制台：https://nls-portal.console.aliyun.com/applist
NLS_APP_KEY = os.getenv("NLS_APP_KEY", "YOUR_NLS_APP_KEY")

OUTPUT_DIR = Path("output/nls_test")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_nls_token(ak_id: str, ak_secret: str, region_id: str = "cn-shanghai") -> str:
    """使用 AccessKey ID 和 Secret 动态生成 NLS 访问 Token"""
    print(f"正在从 {region_id} 获取 NLS 访问令牌 (Token)...")
    client = AcsClient(ak_id, ak_secret, region_id)
    request = CommonRequest()
    request.set_method('POST')
    request.set_protocol_type('https')
    request.set_domain('nls-meta.cn-shanghai.aliyuncs.com')
    request.set_version('2019-02-28')
    request.set_action_name('CreateToken')

    response = client.do_action_with_exception(request)
    resp_json = json.loads(response.decode('utf-8'))
    token = resp_json.get("Token", {}).get("Id")
    if not token:
         raise ValueError(f"获取 Token 失败，响应: {resp_json}")
    print(f"成功获取 Token: {token}")
    return token


def text_to_speech(text: str, token: str, app_key: str, voice: str = "xiaoyun", output_name: str = "nls_output.wav"):
    """通过 NLS RESTful API 提交语音合成"""
    url = "https://nls-gateway-cn-shanghai.aliyuncs.com/stream/v1/tts"
    
    headers = {
        "Content-Type": "application/json"
    }
    
    payload = {
        "appkey": app_key,
        "token": token,
        "text": text,
        "format": "wav",
        "sample_rate": 16000,
        "voice": voice,
        "volume": 50,
        "speech_rate": 0,
        "pitch_rate": 0
    }
    
    print(f"发送 TTS 合成请求 (音色: {voice})...")
    response = requests.post(url, headers=headers, json=payload, stream=True)
    
    content_type = response.headers.get("Content-Type", "")
    if "audio" in content_type:
        output_path = OUTPUT_DIR / output_name
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
        print(f"🎉 语音合成成功！已保存至: {output_path}")
    else:
        print(f"❌ 语音合成失败，服务端返回非音频数据。HTTP 状态码: {response.status_code}")
        try:
            print("错误信息:", response.text)
        except Exception:
            pass


def main():
    if NLS_APP_KEY == "YOUR_NLS_APP_KEY":
        print("⚠️ 警告：请先设置环境变量 NLS_APP_KEY 或将脚本中的 YOUR_NLS_APP_KEY 修改为您在控制台创建的 NLS AppKey。")
        sys.exit(1)
        
    text = "您好，这是阿里云智能语音交互的语音合成演示。我们正在使用 AccessKey 获取访问令牌并进行本地语音文件渲染。"
    try:
        token = get_nls_token(AK_ID, AK_SECRET)
        text_to_speech(text, token, NLS_APP_KEY, voice="xiaoyun", output_name="nls_xiaoyun.wav")
    except Exception as e:
        print(f"运行失败: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
