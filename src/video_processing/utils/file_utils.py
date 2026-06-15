"""文件操作工具"""
from pathlib import Path
from typing import List, Optional
import shutil


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

