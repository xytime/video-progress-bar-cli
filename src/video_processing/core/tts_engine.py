# -*- coding: utf-8 -*-
"""TTS 引擎核心模块 — 统一多 Provider 语音合成接口

支持的 Provider：
- EDGE:      Microsoft Edge TTS（免费，中文质量一般）
- INDEXTTS:  IndexTTS 2.0 本地推理（高质量，需要 GPU 环境）
- COSYVOICE: 阿里云百炼 CosyVoice（高质量普通话，云端 API）

# Modification History
| Version | Date       | Author                   | Description |
| ------- | ---------- | ------------------------ | ----------- |
| 1.0.0   | 2026-05-20 | Gemini_3.1_Pro_High_planning  | 初始创建，支持 EDGE / INDEXTTS |
| 2.0.0   | 2026-05-28 | Gemini_2.5_Pro_planning  | 新增 COSYVOICE Provider，集成 DashScope SDK，支持 Instruct 情感控制与字级别时间戳 |
| 2.1.0   | 2026-05-28 | Gemini_3.5_Flash_planning | 自动检测输出音频文件后缀名，动态配置 SDK 音频编码格式（WAV / MP3）并写入 # [Gemini_3.5_Flash_planning] 标志 |
| 2.2.0   | 2026-05-28 | Gemini_3.5_Flash_planning | 变更默认音色为龙安智 (longanzhi_v3) 并增加音色支持的指令自动过滤防御逻辑，标注 # [Gemini_3.5_Flash_planning] |
| 2.3.0   | 2026-05-28 | Gemini_3.5_Flash_planning | 增加根据音色（如 _v2 后缀）自动匹配并重置为合理 CosyVoice 模型版本（v1/v2/v3）的智能映射逻辑，标注 # [Gemini_3.5_Flash_planning] |
| 2.4.0   | 2026-05-28 | Gemini_3.5_Flash_planning | 增加 cosyvoice_volume 和 cosyvoice_speech_rate 参数以控制 API 的音量与语速，标注 # [Gemini_3.5_Flash_planning] |
"""
import os
import logging
import json
import subprocess
import threading
from pathlib import Path
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class TTSProvider(Enum):
    EDGE = "edge"
    INDEXTTS = "indextts"
    COSYVOICE = "cosyvoice"  # [Gemini_2.5_Pro_planning] 阿里云百炼 CosyVoice


# ---------------------------------------------------------------------------
# CosyVoice 默认配置常量
# ---------------------------------------------------------------------------
COSYVOICE_DEFAULT_MODEL = "cosyvoice-v3-flash"
COSYVOICE_DEFAULT_VOICE = "longanzhi_v3"    # [Gemini_3.5_Flash_planning] 默认变更为龙安智 (睿智轻熟男)，适合科技财经知性讲解
COSYVOICE_DEFAULT_INSTRUCTION = "你现在说话的角色是一个旁白，你说话的情感是neutral。"


class _CosyVoiceCallback:
    """
    DashScope ResultCallback 的内部实现。
    
    实时接收音频流数据并写入文件，同时收集字级别时间戳。
    [Gemini_2.5_Pro_planning]
    """

    def __init__(self, output_path: Path):
        self.output_path = output_path
        self._file = None
        self.word_timestamps: list[dict] = []
        self._seen_keys: set[tuple] = set()   # (sentence_index, begin_index) 去重
        self._done_event = threading.Event()
        self._error: Optional[str] = None

    def on_open(self):
        logger.debug(f"[CosyVoice] 连接已建立，写入目标: {self.output_path}")
        self._file = open(self.output_path, "wb")

    def on_data(self, data: bytes):
        if data and self._file:
            self._file.write(data)

    def on_event(self, message: str):
        # 解析服务端事件，提取字级别时间戳
        # 实际格式：payload.output.sentence.words，仅 type=sentence-end 含完整时间数据
        # [Gemini_2.5_Pro_planning] 修正：原型中路径错误，实测确认
        # 注：同一 sentence-end 事件可能被多帧重复推送，用 (sentence_index, begin_index) 去重
        try:
            event_data = json.loads(message)
            payload = event_data.get("payload", {})
            output = payload.get("output", {})
            event_type = output.get("type", "")
            if event_type == "sentence-end":
                sentence = output.get("sentence", {})
                words = sentence.get("words", [])
                for w in words:
                    if w.get("begin_time") is None:
                        continue
                    # begin_index 是字在全文的绝对位置，用于跨句去重
                    key = w.get("begin_index", 0)
                    if key not in self._seen_keys:
                        self._seen_keys.add(key)
                        self.word_timestamps.append(w)
        except Exception:
            pass  # 忽略非 JSON 心跳帧

    def on_complete(self):
        if self._file:
            self._file.close()
            self._file = None
        logger.info(f"[CosyVoice] 合成完成 → {self.output_path} | 时间戳字数: {len(self.word_timestamps)}")
        self._done_event.set()

    def on_error(self, message: str):
        self._error = message
        logger.error(f"[CosyVoice] 合成错误: {message}")
        if self._file:
            self._file.close()
            self._file = None
        self._done_event.set()

    def wait(self, timeout: float = 120.0) -> None:
        """阻塞直到合成完成或超时"""
        if not self._done_event.wait(timeout=timeout):
            raise TimeoutError(f"[CosyVoice] 合成超时（{timeout}s）: {self.output_path}")
        if self._error:
            raise RuntimeError(f"[CosyVoice] 合成失败: {self._error}")


class TTSEngine:
    """
    统一 TTS 引擎接口，按 Provider 分发实际合成逻辑。

    [Gemini_2.5_Pro_planning] v2.0: 新增 CosyVoice Provider 支持
    """

    def __init__(
        self,
        provider: TTSProvider,
        index_tts_path: Optional[Path] = None,
        dashscope_api_key: Optional[str] = None,
        cosyvoice_model: str = COSYVOICE_DEFAULT_MODEL,
        cosyvoice_voice: str = COSYVOICE_DEFAULT_VOICE,
        cosyvoice_instruction: str = COSYVOICE_DEFAULT_INSTRUCTION,
        cosyvoice_volume: int = 90,                  # [Gemini_3.5_Flash_planning]
        cosyvoice_speech_rate: float = 1.0,          # [Gemini_3.5_Flash_planning]
    ):
        self.provider = provider
        self.index_tts_path = index_tts_path

        # --- CosyVoice 配置 [Gemini_3.5_Flash_planning] ---
        self.cosyvoice_voice = cosyvoice_voice
        self.cosyvoice_model = cosyvoice_model
        self.cosyvoice_volume = cosyvoice_volume            # [Gemini_3.5_Flash_planning]
        self.cosyvoice_speech_rate = cosyvoice_speech_rate  # [Gemini_3.5_Flash_planning]
        
        # 自动匹配合理的模型：v2 音色需要使用 cosyvoice-v2 模型，v1 使用 cosyvoice-v1
        if cosyvoice_model == COSYVOICE_DEFAULT_MODEL:
            if self.cosyvoice_voice.endswith("_v2"):
                self.cosyvoice_model = "cosyvoice-v2"
            elif self.cosyvoice_voice == "longwan":
                self.cosyvoice_model = "cosyvoice-v1"
            else:
                self.cosyvoice_model = "cosyvoice-v3-flash"

        # 防御性逻辑：只有标杆音色支持 Instruct 指令控制，其他系统音色传此参数会导致 API 报错
        if self.cosyvoice_voice in ("longanyang", "longanhuan"):
            self.cosyvoice_instruction = cosyvoice_instruction
        else:
            self.cosyvoice_instruction = None

        if self.provider == TTSProvider.INDEXTTS:
            if not self.index_tts_path:
                self.index_tts_path = Path(
                    "/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/indexTTS2.0/index-tts"
                )
            if not self.index_tts_path.exists():
                raise FileNotFoundError(f"IndexTTS 路径不存在: {self.index_tts_path}")

        if self.provider == TTSProvider.COSYVOICE:
            # API Key 优先级：参数 > settings > 环境变量
            if dashscope_api_key:
                self._dashscope_api_key = dashscope_api_key
            else:
                # 尝试从 settings 加载（允许延迟导入，避免循环依赖）
                try:
                    from src.config.settings import settings  # [Gemini_2.5_Pro_planning]
                    self._dashscope_api_key = settings.dashscope_api_key or os.getenv("DASHSCOPE_API_KEY", "")
                except Exception:
                    self._dashscope_api_key = os.getenv("DASHSCOPE_API_KEY", "")

            if not self._dashscope_api_key:
                raise ValueError(
                    "[CosyVoice] 未配置 DASHSCOPE_API_KEY。"
                    "请在 .env 文件中设置 DASHSCOPE_API_KEY 或在实例化时传入 dashscope_api_key 参数。"
                    "API Key 获取地址: https://bailian.console.aliyun.com/"
                )

            # 导入并配置 SDK
            try:
                import dashscope
                dashscope.api_key = self._dashscope_api_key
                self._dashscope = dashscope
            except ImportError:
                raise ImportError(
                    "[CosyVoice] dashscope SDK 未安装。"
                    "请运行: pip install dashscope"
                )

    # -----------------------------------------------------------------------
    # 公共接口
    # -----------------------------------------------------------------------

    def generate_audio(
        self,
        text: str,
        output_file: Path,
        voice: str = "zh-CN-XiaoxiaoNeural",
    ) -> list[dict]:
        """
        合成单条文本，返回字级别时间戳列表（仅 COSYVOICE 有效）。

        Args:
            text:        待合成文本
            output_file: 输出音频文件路径（自动创建父目录）
            voice:       音色标识（对 COSYVOICE 无效，使用初始化时的 cosyvoice_voice）

        Returns:
            list[dict]: 字级别时间戳，格式 [{"text": "字", "begin_time": ms, "end_time": ms}]
                        EDGE / INDEXTTS 返回空列表
        """
        output_file = Path(output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        if self.provider == TTSProvider.EDGE:
            self._generate_edge(text, output_file, voice)
            return []
        elif self.provider == TTSProvider.INDEXTTS:
            self._generate_indextts(text, output_file, voice)
            return []
        elif self.provider == TTSProvider.COSYVOICE:
            return self._generate_cosyvoice(text, output_file)
        else:
            raise ValueError(f"未知的 TTS Provider: {self.provider}")

    def batch_generate(
        self,
        items: list[dict],
        output_dir: Path,
        voice_prompt: Optional[str] = None,
    ) -> dict[str, list[dict]]:
        """
        批量合成音频。

        Args:
            items:        [{"text": str, "filename": str}, ...]
            output_dir:   输出目录
            voice_prompt: EDGE/INDEXTTS 音色/参考音频路径（COSYVOICE 忽略此参数）

        Returns:
            dict: {filename: [时间戳列表]}，仅 COSYVOICE 时间戳非空
        """
        output_dir = Path(output_dir)
        timestamps_map: dict[str, list[dict]] = {}

        if self.provider == TTSProvider.EDGE:
            voice = voice_prompt or "zh-CN-XiaoxiaoNeural"
            for item in items:
                out_path = output_dir / item["filename"]
                if out_path.exists():
                    timestamps_map[item["filename"]] = []
                    continue
                self._generate_edge(item["text"], out_path, voice)
                timestamps_map[item["filename"]] = []

        elif self.provider == TTSProvider.INDEXTTS:
            jobs = []
            for item in items:
                out_path = output_dir / item["filename"]
                if out_path.exists():
                    timestamps_map[item["filename"]] = []
                    continue
                jobs.append({
                    "text": item["text"],
                    "output_path": str(out_path),
                    "voice_prompt": voice_prompt or "examples/test_audio.wav",
                })
                timestamps_map[item["filename"]] = []

            if jobs:
                job_file = output_dir / "tts_batch_jobs.json"
                with open(job_file, "w", encoding="utf-8") as f:
                    json.dump(jobs, f, indent=2, ensure_ascii=False)

                worker_script = self.index_tts_path / "runner_worker.py"
                venv_python = self.index_tts_path / ".venv" / "bin" / "python"
                if not venv_python.exists():
                    venv_python = "python"

                cmd = [str(venv_python), str(worker_script), "--job_file", str(job_file)]
                logger.info(f"[IndexTTS] 批量合成 {len(jobs)} 条...")
                subprocess.run(cmd, cwd=str(self.index_tts_path), check=True)

        elif self.provider == TTSProvider.COSYVOICE:
            # [Gemini_2.5_Pro_planning] CosyVoice 逐条合成（SDK 本身已流式，无需并发）
            for item in items:
                out_path = output_dir / item["filename"]
                if out_path.exists():
                    logger.debug(f"[CosyVoice] 跳过已存在: {out_path.name}")
                    timestamps_map[item["filename"]] = []
                    continue
                ts = self._generate_cosyvoice(item["text"], out_path)
                timestamps_map[item["filename"]] = ts

        return timestamps_map

    # -----------------------------------------------------------------------
    # 私有实现
    # -----------------------------------------------------------------------

    def _generate_edge(self, text: str, output_file: Path, voice: str):
        import asyncio
        import edge_tts

        async def _run():
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(output_file))

        try:
            asyncio.run(_run())
        except Exception as e:
            logger.error(f"[EdgeTTS] 合成失败: {e}")
            raise

    def _generate_indextts(self, text: str, output_file: Path, voice_prompt: str):
        # TODO: 通过 subprocess 调用 runner_worker.py 实现单条合成
        pass

    def _generate_cosyvoice(self, text: str, output_file: Path) -> list[dict]:
        """
        [Gemini_2.5_Pro_planning] 使用 DashScope SDK 合成单条语音。

        核心要点：
        - 流式回调模式，实时写入音频 bytes
        - word_timestamp_enabled=True 获取字级别时间轴
        - Instruct 参数控制情感与角色

        Returns:
            list[dict]: [{"text": str, "begin_time": int(ms), "end_time": int(ms)}]
        """
        from dashscope.audio.tts_v2 import SpeechSynthesizer, ResultCallback, AudioFormat

        # [Gemini_3.5_Flash_planning] 动态根据文件后缀设置正确的音频格式，避免写入非标准数据
        audio_format = AudioFormat.DEFAULT
        if output_file.suffix.lower() == ".wav":
            audio_format = AudioFormat.WAV_16000HZ_MONO_16BIT
        elif output_file.suffix.lower() == ".mp3":
            audio_format = AudioFormat.MP3_22050HZ_MONO_256KBPS

        # 动态构造回调类（内部类继承 ResultCallback）
        class _Callback(ResultCallback):
            def __init__(self_cb):
                self_cb._impl = _CosyVoiceCallback(output_file)

            def on_open(self_cb):
                self_cb._impl.on_open()

            def on_data(self_cb, data: bytes):
                self_cb._impl.on_data(data)

            def on_event(self_cb, message: str):
                self_cb._impl.on_event(message)

            def on_complete(self_cb):
                self_cb._impl.on_complete()

            def on_error(self_cb, message: str):
                self_cb._impl.on_error(message)

        cb_wrapper = _Callback()

        logger.info(
            f"[CosyVoice] 合成 → model={self.cosyvoice_model} voice={self.cosyvoice_voice} "
            f"format={audio_format} text={text[:30]}{'...' if len(text) > 30 else ''}"
        )

        synthesizer = SpeechSynthesizer(
            model=self.cosyvoice_model,
            voice=self.cosyvoice_voice,
            callback=cb_wrapper,
            format=audio_format,
            volume=self.cosyvoice_volume,                  # [Gemini_3.5_Flash_planning]
            speech_rate=self.cosyvoice_speech_rate,        # [Gemini_3.5_Flash_planning]
            instruction=self.cosyvoice_instruction,          # [Gemini_2.5_Pro_planning] 构造时传入
            additional_params={"word_timestamp_enabled": True},  # 通过 additional_params 写入 parameters
        )

        synthesizer.call(text)  # call() 只接受 text
        cb_wrapper._impl.wait(timeout=120.0)

        return cb_wrapper._impl.word_timestamps
