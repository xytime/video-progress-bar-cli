# -*- coding: utf-8 -*-
"""阿里云百炼平台 (Model Studio) CosyVoice 语音合成 SDK Demo

本 Demo 演示如何使用 dashscope SDK 调用 cosyvoice-v3-flash 模型。
支持功能：
1. 流式音频合成
2. Instruct 情感与角色控制
3. Word-level 字级别时间戳导出

# Modification History
| Version | Date       | Author                     | Description |
| ------- | ---------- | -------------------------- | ----------- |
| 1.0.0   | 2026-05-28 | Gemini_3.5_Flash_planning  | 初始创建 DashScope CosyVoice SDK 语音合成 Demo，支持 Instruct 情感与时间戳 |
"""

import os
import sys
import json
from pathlib import Path

# [Gemini_3.5_Flash_planning] 检查与导入 SDK
try:
    import dashscope
    from dashscope.audio.tts_v2 import SpeechSynthesizer, ResultCallback
except ImportError:
    print("❌ 错误：请先安装 dashscope SDK，运行命令：pip install dashscope")
    sys.exit(1)

# ⚠️ 注意：百炼（灵积）服务使用独立的 API-KEY 进行鉴权，而不是 AccessKey ID/Secret。
# 请前往百炼控制台获取 API-KEY：https://bailian.console.aliyun.com/
# 并在此处或者环境变量中设置：export DASHSCOPE_API_KEY="sk-xxx"
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "YOUR_DASHSCOPE_API_KEY")

OUTPUT_DIR = Path("output/cosyvoice_test")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


class CosyVoiceDemoCallback(ResultCallback):
    """自定义语音合成回调类，用于实时接收音频二进制数据与字级别时间戳"""
    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.file = None
        self.word_timestamps = []

    def on_open(self):
        print("-> 连接已建立，准备写入音频文件...")
        self.file = open(self.output_path, "wb")

    def on_data(self, data: bytes):
        # 写入实时返回的音频数据流
        if data:
            self.file.write(data)

    def on_event(self, message: str):
        # 接收并解析服务端返回的事件（包含字级别时间戳）
        try:
            event_data = json.loads(message)
            payload = event_data.get("payload", {})
            output = payload.get("output", {})
            if "timestamp" in output:
                # 收集字级别时间戳列表 [{"text": "字", "begin_time": ms, "end_time": ms}, ...]
                self.word_timestamps.extend(output["timestamp"])
        except Exception as e:
            # 忽略解析心跳或非 result 消息时的错误
            pass

    def on_complete(self):
        if self.file:
            self.file.close()
        print(f"🎉 语音合成完成！已保存音频至: {self.output_path}")
        
        # 打印部分导出的字级别时间戳，验证同步数据
        if self.word_timestamps:
            print("\n⏰ 字级别时间戳 (前5个字样例):")
            for ts in self.word_timestamps[:5]:
                print(f" - 字: '{ts['text']}' | 起始时间: {ts['begin_time']}ms | 结束时间: {ts['end_time']}ms")
            print(f"共获得 {len(self.word_timestamps)} 个字的时间轴数据，可直接用于 SRT/ASS 字幕精准对齐！\n")
        else:
            print("⚠️ 未收到时间戳数据，请确保所选音色支持该功能且 word_timestamp_enabled 已开启。\n")

    def on_error(self, message: str):
        print(f"❌ 发生错误: {message}")
        if self.file:
            self.file.close()


def run_cosyvoice_demo():
    if DASHSCOPE_API_KEY == "YOUR_DASHSCOPE_API_KEY":
        print("⚠️ 警告：请先设置环境变量 DASHSCOPE_API_KEY 或将脚本中的 YOUR_DASHSCOPE_API_KEY 修改为您在百炼控制台申请的 API-KEY。")
        sys.exit(1)

    # 设置 API-KEY
    dashscope.api_key = DASHSCOPE_API_KEY

    # 1. 基础配置
    model = "cosyvoice-v3-flash"
    voice = "longanyang"  # 阳光大男孩 (标杆音色，支持 SSML, Instruct 情感与时间戳)
    output_path = OUTPUT_DIR / "cosyvoice_longanyang.mp3"
    
    # 2. 待合成文本
    text = "观众朋友们大家好，这里是最新科技动态。今天我们将深度剖析大模型领域的最新技术进展。"
    
    # 3. Instruct 情感控制参数 (Instruct 文本必须使用中文，须严格按格式填写并以句号结尾)
    # 支持情感值：neutral、fearful、angry、sad、surprised、happy、disgusted
    # 支持角色：一个旁白
    instruction = "你现在说话的角色是一个旁白，你说话的情感是neutral。"
    
    print(f"--- 启动 CosyVoice 语音合成 ---")
    print(f"模型: {model}")
    print(f"音色: {voice}")
    print(f"指令: {instruction}")
    print(f"文本: {text}\n")

    # 实例化回调接口
    callback = CosyVoiceDemoCallback(output_path)

    # 初始化合成器
    # 启用 word_timestamp_enabled=True 以获取字级对齐数据
    synthesizer = SpeechSynthesizer(
        model=model,
        voice=voice,
        callback=callback,
        word_timestamp_enabled=True
    )
    
    # 提交合成请求 (传入文本与微调指令)
    # 如果要使用 SSML 功能，请直接在 text 参数中填入符合 SSML 规范的 XML 内容
    synthesizer.call(text, instruction=instruction)


if __name__ == "__main__":
    run_cosyvoice_demo()
