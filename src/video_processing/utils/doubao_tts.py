# -*- coding: utf-8 -*-
"""豆包语音合成客户端 (Doubao Voice / Volcengine TTS 2.0)。

封装火山引擎基于 WebSocket V3 协议的双向流式语音合成服务。
原生输出 44,100 Hz 高品质音频，默认发音人为「云舟 2.0」(zh_male_m191_uranus_bigtts) 沉稳男声，
适合宏观政经、商业决策与深度新闻二创场景。

# Modification History
| Version | Date       | Author      | Description |
| ------- | ---------- | ----------- | ----------- |
| 1.0.0   | 2026-10-08 | Antigravity | 初始创建，支持火山引擎双向流式 TTS 2.0 与 44.1kHz 母带音频输出 |
"""

import asyncio
import copy
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

import websockets

from config.settings import settings
from video_processing.utils.volcengine_tts_protocol import (
    EventType,
    MsgType,
    finish_connection,
    finish_session,
    receive_message,
    start_connection,
    start_session,
    task_request,
    wait_for_event,
)

logger = logging.getLogger(__name__)


class DoubaoTTSError(RuntimeError):
    """豆包语音合成异常"""
    pass


class DoubaoTTSClient:
    """豆包语音合成客户端，负责连接管理、会话构建与二进制音频流解析。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        resource_id: Optional[str] = None,
        default_speaker: Optional[str] = None,
        sample_rate: int = 44100,
    ):
        self.api_key = api_key or getattr(settings, "doubao_tts_api_key", None) or getattr(settings, "volc_speech_api_key", None)
        self.endpoint = endpoint or getattr(settings, "doubao_tts_endpoint", "wss://openspeech.bytedance.com/api/v3/tts/bidirection")
        self.resource_id = resource_id or getattr(settings, "doubao_tts_resource_id", "seed-tts-2.0")
        self.default_speaker = default_speaker or getattr(settings, "doubao_tts_speaker", "zh_male_m191_uranus_bigtts")
        self.sample_rate = sample_rate

    async def async_synthesize(
        self,
        text: str,
        output_path: Path,
        speaker: Optional[str] = None,
        sample_rate: Optional[int] = None,
        audio_format: str = "mp3",
    ) -> Path:
        """异步合成单条文本为音频文件。"""
        if not self.api_key:
            raise DoubaoTTSError("未配置豆包语音 API Key (DOUBAO_TTS_API_KEY)，无法调用合成服务")

        text_clean = text.strip()
        if not text_clean:
            raise ValueError("待合成文本不能为空")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        spk = speaker or self.default_speaker
        sr = sample_rate or self.sample_rate

        headers = {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Connect-Id": str(uuid.uuid4()),
            "X-Control-Require-Usage-Tokens-Return": "*",
        }

        # 尝试连接并合成，具备自动重试机制
        last_error = None
        for attempt in range(1, 3):
            try:
                websocket = await asyncio.wait_for(
                    websockets.connect(
                        self.endpoint,
                        additional_headers=headers,
                        max_size=16 * 1024 * 1024,
                        open_timeout=15,
                    ),
                    timeout=20,
                )
                try:
                    await start_connection(websocket)
                    await wait_for_event(websocket, MsgType.FullServerResponse, EventType.ConnectionStarted)

                    session_id = str(uuid.uuid4())
                    base_request = {
                        "req_params": {
                            "speaker": spk,
                            "audio_params": {
                                "format": audio_format,
                                "sample_rate": sr,
                            },
                        }
                    }

                    start_session_request = copy.deepcopy(base_request)
                    start_session_request["event"] = EventType.StartSession
                    await start_session(websocket, json.dumps(start_session_request).encode(), session_id)
                    await wait_for_event(websocket, MsgType.FullServerResponse, EventType.SessionStarted)

                    # 发送合成文本并结束当前会话输入
                    synthesis_request = copy.deepcopy(base_request)
                    synthesis_request["event"] = EventType.TaskRequest
                    synthesis_request["req_params"]["text"] = text_clean
                    await task_request(websocket, json.dumps(synthesis_request).encode(), session_id)
                    await finish_session(websocket, session_id)

                    audio_data = bytearray()
                    audio_received = False
                    while True:
                        msg = await receive_message(websocket)
                        if msg.type == MsgType.FullServerResponse:
                            if msg.event == EventType.SessionFinished:
                                break
                        elif msg.type == MsgType.AudioOnlyServer:
                            audio_received = True
                            audio_data.extend(msg.payload)
                        elif msg.type == MsgType.Error:
                            err_msg = msg.payload.decode("utf-8", "ignore")
                            raise DoubaoTTSError(f"豆包服务端返回错误: code={msg.error_code}, payload={err_msg}")

                    if not audio_received or len(audio_data) == 0:
                        raise DoubaoTTSError("豆包合成未接收到音频数据帧")

                    output_path.write_bytes(audio_data)
                    logger.info("豆包语音合成成功: %s -> %s (%d bytes)", text_clean[:20], output_path, len(audio_data))
                    return output_path

                finally:
                    try:
                        await finish_connection(websocket)
                        await wait_for_event(websocket, MsgType.FullServerResponse, EventType.ConnectionFinished)
                    except Exception:
                        pass
                    await websocket.close()

            except Exception as e:
                last_error = e
                logger.warning("豆包语音合成第 %d 次尝试失败: %s", attempt, e)
                await asyncio.sleep(0.5)

        raise DoubaoTTSError(f"豆包语音合成重试耗尽失败: {last_error}") from last_error

    def synthesize(
        self,
        text: str,
        output_path: Path,
        speaker: Optional[str] = None,
        sample_rate: Optional[int] = None,
        audio_format: str = "mp3",
    ) -> Path:
        """同步接口便捷包装。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        coro = self.async_synthesize(
            text=text,
            output_path=output_path,
            speaker=speaker,
            sample_rate=sample_rate,
            audio_format=audio_format,
        )

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        else:
            return asyncio.run(coro)
