"""文件操作工具

# Modification History
| Version | Date       | Author          | Description                                                        |
|---------|------------|-----------------|-------------------------------------------------------------------|
| 1.0.0   | 2026-06-15 | Claude_Opus_4.8 | find_downloaded_video 单一真相源（bot 与管线共用）                  |
| 1.1.0   | 2026-06-22 | Claude_Opus_4.8 | 新增 read_subtitle_text（.ass 纯文本，管线字幕审查与复核 UI 共用）   |
| 1.2.0   | 2026-06-22 | Claude_Opus_4.8 | [Review Fix] read_subtitle_text 精确匹配切片，排除 {yid}_s1 误配子切片/_s11 |
| 1.3.0   | 2026-07-31 | Codex | 新增 WebVTT 纯文本读取，供下载前源字幕安全预检复用 |
"""
import html
import re
import shutil
from pathlib import Path
from typing import Iterable, List, Optional


def ensure_directory(path: Path) -> Path:
    """
    确保目录存在，如果不存在则创建
    
    Args:
        path: 目录路径
        
    Returns:
        目录路径
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_file_size(path: Path) -> int:
    """
    获取文件大小（字节）
    
    Args:
        path: 文件路径
        
    Returns:
        文件大小（字节）
    """
    return path.stat().st_size


def format_file_size(size_bytes: int) -> str:
    """
    格式化文件大小
    
    Args:
        size_bytes: 文件大小（字节）
        
    Returns:
        格式化后的文件大小字符串
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def find_video_files(directory: Path, extensions: Optional[List[str]] = None) -> List[Path]:
    """
    查找目录中的视频文件
    
    Args:
        directory: 目录路径
        extensions: 文件扩展名列表，默认为常见视频格式
        
    Returns:
        视频文件路径列表
    """
    if extensions is None:
        extensions = ['.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.webm']
    
    video_files = []
    for ext in extensions:
        video_files.extend(directory.glob(f"*{ext}"))
        video_files.extend(directory.glob(f"*{ext.upper()}"))
    
    return sorted(video_files)


# 真实视频容器扩展名白名单 —— 把【源视频】与 .ass/.srt/.json/.jpg 等衍生产物区分开。
# 单一真相源：pipeline 与 bot 均从此处取用，杜绝两处实现分叉。
VIDEO_CONTAINER_SUFFIXES = {'.mp4', '.webm', '.mkv', '.mov', '.m4v', '.avi', '.flv', '.ts'}


def find_downloaded_video(
    output_dir: Path,
    yid: str,
    archive_dir: Optional[Path] = None,
    min_size: int = 50_000,
) -> Optional[str]:
    """定位某 youtube_id 已下载的【源视频主文件】。

    选择规则（防止把 `.ass` 字幕 / `{yid}.f398.mp4` 无音轨 DASH 分片误当源视频）：
    - 扩展名必须在 :data:`VIDEO_CONTAINER_SUFFIXES` 白名单内；
    - 文件名主干 ``stem`` 必须严格等于 ``yid``（排除 ``{yid}.f398`` / ``{yid}_vertical`` 等衍生件）；
    - 体积 > ``min_size``（默认 50KB，过滤占位/碎片）。

    查找顺序：先热目录 ``output_dir``，未命中再查冷归档 ``archive_dir``。
    结果按文件名排序后取首个，保证选择**确定性**（旧实现依赖 glob 任意顺序）。

    Args:
        output_dir: 热目录（yt-dlp 刚下载、尚未归档）。
        yid: YouTube 视频 ID。
        archive_dir: 冷归档目录（如 ``output/original_video/``），可选。
        min_size: 有效视频的最小字节数。

    Returns:
        命中文件的绝对路径字符串；未找到返回 ``None``。
    """
    def _scan(directory: Optional[Path]) -> List[Path]:
        if directory is None:
            return []
        d = Path(directory)
        if not d.is_dir():
            return []
        out: List[Path] = []
        for f in d.glob(f"{yid}.*"):
            if f.suffix.lower() not in VIDEO_CONTAINER_SUFFIXES:
                continue
            if f.stem != yid:  # 拒绝 {yid}.f398.mp4 / {yid}_vertical.mp4 等衍生件
                continue
            try:
                if f.stat().st_size <= min_size:
                    continue
            except OSError:
                continue
            out.append(f)
        return sorted(out)

    hot = _scan(output_dir)
    if hot:
        return str(hot[0])
    archived = _scan(archive_dir)
    if archived:
        return str(archived[0])
    return None


def read_subtitle_text(
    output_dir: Path,
    youtube_id: str,
    slice_index: int = 0,
    max_chars: int = 40000,
) -> str:
    """读取某视频（或指定切片）已渲染的 .ass 双语字幕纯文本（去 ASS 标签）并拼接。

    单一真相源：Web 复核 UI（app.py）与管线字幕审查（pipeline_manager）共用本函数，
    杜绝两处实现分叉。失败（pysubs2 缺失 / 文件损坏）时返回空串，由调用方决定如何降级。

    [Claude_Opus_4.8] BUG-1 配套：切片走 ``{yid}_s{n}`` 前缀，避免读到父/其它切片字幕。

    Args:
        output_dir: .ass 所在目录（通常为 output/）。
        youtube_id: YouTube 视频 ID。
        slice_index: 切片序号，0 表示整片。
        max_chars: 纯文本累计上限，超过即截断返回（字幕动辄数万字，限长控成本）。

    Returns:
        去标签后的字幕纯文本（多事件以换行拼接）；无字幕或读取失败返回空串。
    """
    try:
        import pysubs2
    except Exception:
        return ""
    out = Path(output_dir)
    # [Claude_Opus_4.8] v1.2.0 精确匹配本切片，避免：
    #   • 整片(slice 0) 误读子切片 {yid}_s1.ass → 把切片字幕并入父片审查；
    #   • 切片 1 的 glob {yid}_s1*.ass 误配 {yid}_s11.ass（≥11 切片时）。
    # 接受 {stem}.ass 与 {stem}.<lang>.ass，排除其余。
    if slice_index and slice_index > 0:
        stem = f"{youtube_id}_s{slice_index}"
        glob_pat = f"{stem}*.ass"
    else:
        stem = youtube_id
        glob_pat = f"{youtube_id}*.ass"
    accept = re.compile(rf"^{re.escape(stem)}(\.|$)")
    parts: List[str] = []
    total = 0
    for ass in sorted(p for p in out.glob(glob_pat) if accept.match(p.stem)):
        try:
            subs = pysubs2.load(str(ass))
        except Exception:
            continue
        for ev in subs:
            txt = (getattr(ev, "plaintext", "") or "").strip()
            if not txt:
                continue
            parts.append(txt)
            total += len(txt)
            if total >= max_chars:
                return "\n".join(parts)
    return "\n".join(parts)


def read_webvtt_text(subtitle_files: Iterable[Path], max_chars: int = 40000) -> str:
    """读取 WebVTT cue 正文并去除时间轴、HTML 标签和实体。

    仅接受时间轴之后的 cue 内容，避免把 ``WEBVTT`` 头、语言元数据或样式表送进
    内容审查。自动字幕可能包含重叠/渐进式 cue，函数保留原文而不尝试去重，宁可
    审查更完整的源文本，也不能因猜测性合并漏掉敏感片段。
    """
    parts: List[str] = []
    total = 0
    for subtitle_file in sorted(Path(path) for path in subtitle_files):
        try:
            lines = subtitle_file.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except OSError:
            continue

        in_cue = False
        cue_lines: List[str] = []

        def flush_cue() -> bool:
            nonlocal total
            if not cue_lines:
                return False
            text = html.unescape(re.sub(r"<[^>]+>", "", " ".join(cue_lines))).strip()
            cue_lines.clear()
            if not text:
                return False
            parts.append(text)
            total += len(text)
            return total >= max_chars

        for raw_line in lines:
            line = raw_line.strip()
            if "-->" in line:
                if flush_cue():
                    return "\n".join(parts)
                in_cue = True
                continue
            if not in_cue:
                continue
            if not line:
                if flush_cue():
                    return "\n".join(parts)
                in_cue = False
                continue
            cue_lines.append(line)

        if flush_cue():
            return "\n".join(parts)
    return "\n".join(parts)


def safe_remove(path: Path) -> bool:
    """
    安全删除文件或目录
    
    Args:
        path: 要删除的路径
        
    Returns:
        是否成功删除
    """
    try:
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        return True
    except Exception:
        return False
