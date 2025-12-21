# 性能优化指南

## 大文件处理优化

### 进度反馈

处理大文件时，工具会自动显示实时进度：

```bash
# 使用 tqdm 进度条（如果已安装）
python -m cli.main add-progressbar large_video.mp4 -c 00:00 -t "开始"

# 输出示例：
# 处理进度: 45%|████████████████████▌                    | 45/100 [02:15<02:45]
```

如果没有安装 `tqdm`，会使用简单的文本进度显示。

### 性能优化参数

#### 1. 编码预设 (`--preset`)

控制编码速度和质量平衡：

- `ultrafast` / `superfast` / `veryfast` / `faster` / `fast`：快速编码，适合大文件
- `medium`：平衡（默认）
- `slow` / `slower` / `veryslow`：高质量，但速度慢

```bash
# 快速处理大文件
python -m cli.main add-progressbar input.mp4 -c 00:00 -t "开始" --preset fast
```

#### 2. 线程数控制 (`--threads`)

控制 FFmpeg 使用的线程数，避免过度占用 CPU：

```bash
# 限制为 4 个线程
python -m cli.main add-progressbar input.mp4 -c 00:00 -t "开始" --threads 4
```

如果不指定，会自动选择最优线程数（CPU 核心数，但不超过 8）。

#### 3. 硬件加速 (`--enable-hwaccel`)

如果系统支持，可以启用硬件加速：

```bash
# macOS 使用 VideoToolbox
python -m cli.main add-progressbar input.mp4 -c 00:00 -t "开始" --enable-hwaccel
```

**注意**：硬件加速可能在某些系统上不可用或导致兼容性问题。

### 内存优化

工具已自动优化内存使用：

1. **自动线程数控制**：根据 CPU 核心数自动选择，避免过度占用
2. **优化编码参数**：使用 `-movflags +faststart` 优化输出文件结构
3. **流式处理**：FFmpeg 使用流式处理，不会将整个文件加载到内存

### 性能建议

**小文件（< 500MB）**：
- 使用默认设置即可

**中等文件（500MB - 2GB）**：
- 使用 `--preset fast` 加快处理速度
- 可以启用硬件加速（如果支持）

**大文件（> 2GB）**：
- 使用 `--preset fast` 或 `veryfast`
- 限制线程数：`--threads 4` 或 `--threads 6`
- 考虑启用硬件加速

### 禁用进度条

如果不需要进度显示（例如在脚本中运行）：

```bash
python -m cli.main add-progressbar input.mp4 -c 00:00 -t "开始" --no-progress
```

### 作为库使用时的进度回调

```python
from video_processing.processors.progress_bar import ProgressBarProcessor

def progress_callback(progress: float):
    """进度回调：progress 为 0.0-1.0"""
    percent = int(progress * 100)
    print(f"处理进度: {percent}%")

processor = ProgressBarProcessor(
    input_path=Path("input.mp4"),
    chapters=[{"time": "00:00", "title": "开始"}],
    preset="fast",  # 快速模式
    threads=4,      # 限制线程数
)

output_path = processor.process(progress_callback=progress_callback)
```

### 性能监控

如果需要监控内存和 CPU 使用情况，可以安装 `psutil`：

```bash
pip install psutil
```

然后在代码中监控：

```python
import psutil
import os

process = psutil.Process(os.getpid())
memory_mb = process.memory_info().rss / 1024 / 1024
print(f"内存使用: {memory_mb:.2f} MB")
```

