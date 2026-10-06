"""受全局 FFmpeg 守卫约束的音频抽取、分轨混合与两遍母带处理。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-07 | Codex | 独立 16k 对齐副本、48k 母带和实测 loudnorm |
"""
from fractions import Fraction
import json
import math
from pathlib import Path
import re
import subprocess

from video_processing.core.ffmpeg_slot import register_executable
from .contracts import PipelineError


class MediaTools:
    def __init__(self, ffmpeg: str, ffprobe: str, timeout=600):
        self.ffmpeg, self.ffprobe, self.timeout = ffmpeg, ffprobe, timeout
        register_executable(ffmpeg)

    def run(self, args, log: Path):
        with log.open("wb") as stream:
            try:
                result = subprocess.run([self.ffmpeg, "-nostdin", "-hide_banner", "-y", *map(str, args)],
                                        stdout=subprocess.DEVNULL, stderr=stream, timeout=self.timeout)
            except subprocess.TimeoutExpired as exc:
                raise PipelineError("RESOURCE_TIMEOUT", f"FFmpeg 执行超时，见 {log.name}") from exc
        if result.returncode:
            raise PipelineError("RENDER_FAILED", f"FFmpeg exit={result.returncode}，见 {log.name}")

    def probe(self, path):
        try:
            result = subprocess.run([self.ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                                    capture_output=True, text=True, timeout=30, check=True)
            return json.loads(result.stdout)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise PipelineError("INPUT_INVALID", f"媒体 probe 失败: {path}") from exc

    def count_samples(self, path, stream_index, sample_rate, channels, directory):
        """实际解码计数，避免把压缩音轨 duration 当样本数证明。"""
        import threading
        with (directory / f"{Path(path).stem}-sample-count.log").open("wb") as log:
            process = subprocess.Popen([self.ffmpeg, "-nostdin", "-v", "error", "-i", str(path),
                                        "-map", f"0:{stream_index}", "-ar", str(sample_rate), "-ac", str(channels),
                                        "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1"],
                                       stdout=subprocess.PIPE, stderr=log)
            timer = threading.Timer(self.timeout, process.kill)
            timer.start()
            length = 0
            try:
                for block in iter(lambda: process.stdout.read(65536), b""):
                    length += len(block)
                code = process.wait(timeout=self.timeout)
                if code or not length or length % (2 * channels):
                    raise PipelineError("INPUT_INVALID", "音频实际解码样本数不可验证")
            finally:
                timer.cancel()
                process.stdout.close()
                if process.poll() is None:
                    process.kill()
                process.wait()
        return length // (2 * channels)

    def measure(self, path: Path, directory: Path, name="measure", target=-16, peak=-1.5):
        log = directory / f"{name}.log"
        self.run(["-i", path, "-vn", "-af", f"loudnorm=I={target}:TP={peak}:LRA=11:print_format=json", "-f", "null", "-"], log)
        blocks = re.findall(r'\{\s*"input_i".*?\}', log.read_text(), flags=re.S)
        if not blocks:
            raise PipelineError("OUTPUT_QA_FAILED", "缺少 loudnorm 实测数据")
        report = json.loads(blocks[-1])
        if any(not math.isfinite(float(report[k])) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")):
            raise PipelineError("OUTPUT_QA_FAILED", "母带为空/静音或非有限 loudness")
        (directory / f"{name}.json").write_text(json.dumps(report, indent=2))
        return report

    def prepare(self, source, start_tick, end_tick, ticks, directory):
        directory.mkdir(parents=True, exist_ok=True)
        duration = Fraction(end_tick - start_tick, ticks)
        self.run(["-ss", float(Fraction(start_tick, ticks)), "-i", source, "-t", float(duration),
                  "-vn", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le", directory / "original.wav"], directory / "original.log")
        self.run(["-i", directory / "original.wav", "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                  directory / "alignment.wav"], directory / "alignment.log")
        return self.probe(directory / "original.wav")

    def master(self, source, policy, directory, *, vocals=None, instrumental=None):
        mixed = directory / "mix.wav"
        if policy["ducking"]["enabled"]:
            raise PipelineError("INPUT_INVALID", "首版不支持有界 ducking envelope，不能用 compressor 冒充最大降幅")
        if policy["mix_mode"] == "original":
            if policy["vocal_gain_db"] != 0 or policy["instrumental_gain_db"] != 0:
                raise PipelineError("INPUT_INVALID", "原始混音不能独立调人声/伴奏增益")
            args = ["-i", source, "-vn", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le", mixed]
        else:
            if vocals is None or instrumental is None:
                raise PipelineError("STEM_INVALID", "分轨混音必须同时提供人声和伴奏")
            graph = (f"[0:a]volume={policy['vocal_gain_db']}dB[v];"
                     f"[1:a]volume={policy['instrumental_gain_db']}dB[i];"
                     "[v][i]amix=inputs=2:duration=longest:normalize=0[a]")
            args = ["-i", vocals, "-i", instrumental, "-filter_complex", graph, "-map", "[a]", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le", mixed]
        self.run(args, directory / "mix.log")
        first = self.measure(mixed, directory, "first-pass", policy["target_lufs"], policy["master_true_peak_dbtp"])
        target, peak = policy["target_lufs"], policy["master_true_peak_dbtp"]
        filt = (f"loudnorm=I={target}:TP={peak}:LRA=11:measured_I={first['input_i']}:"
                f"measured_TP={first['input_tp']}:measured_LRA={first['input_lra']}:"
                f"measured_thresh={first['input_thresh']}:offset={first['target_offset']}:linear=true:print_format=json")
        if policy["fade_in_tick"] or policy["fade_out_tick"]:
            raise PipelineError("INPUT_INVALID", "首版不支持 fade 参数；拒绝静默忽略")
        self.run(["-i", mixed, "-af", filt, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le", directory / "master.wav"], directory / "second-pass.log")
        result = self.measure(directory / "master.wav", directory, "master-check")
        self.check_loudness(result, policy, encoded=False)
        return result

    @staticmethod
    def check_loudness(report, policy, *, encoded):
        peak = policy["encoded_max_true_peak_dbtp"] if encoded else policy["master_true_peak_dbtp"]
        if abs(float(report["input_i"]) - policy["target_lufs"]) > policy["lufs_tolerance"] or float(report["input_tp"]) > peak + 0.05:
            raise PipelineError("OUTPUT_QA_FAILED", f"响度/真峰值不达标: I={report['input_i']}, TP={report['input_tp']}")
