# Video Processing

视频处理工具库，提供视频加工相关的工具方法。

## 项目概述

本项目是一个视频处理工具库，前期专注于视频加工相关的工具方法开发，未来将集成系统性的任务目标。

## 功能特性

- 模块化设计，易于扩展
- 支持作为Python库导入使用
- 提供命令行工具（CLI）
- 清晰的架构分层

### 已实现功能

- **添加进度条**：为视频添加动态进度条和章节分割线
  - 支持简单模式：只添加时间点分割线
  - 支持高级模式：添加章节标题（支持中文显示）
  - 支持自定义样式：颜色、字体、大小等
  - **实时进度反馈**：显示处理进度和预计剩余时间
  - **性能优化**：针对大文件优化内存占用和处理速度

## 项目结构

```
Video-precessing/
├── draft-code/              # 需求代码/伪代码存放目录
├── src/                     # 源代码目录
│   ├── video_processing/   # 核心视频处理模块
│   ├── cli/                # 命令行接口
│   └── config/             # 配置管理
├── tests/                   # 测试目录
├── docs/                    # 文档目录
├── examples/                # 示例代码
└── scripts/                 # 辅助脚本
```

## 安装

### 前置要求

- Python 3.8+
- FFmpeg（需要安装并配置在系统 PATH 中）

### 安装步骤

```bash
# 安装依赖
pip install -r requirements.txt

# 或者以开发模式安装
pip install -e .
```

### 验证 FFmpeg 安装

```bash
ffmpeg -version
ffprobe -version
```

## 使用方式

### 作为库使用

```python
from pathlib import Path
from video_processing.processors.progress_bar import ProgressBarProcessor

# 为视频添加进度条
processor = ProgressBarProcessor(
    input_path=Path("input.mp4"),
    chapters=[30, 75, 120],  # 章节时间点（秒）
    bar_color="red",
    bar_height=15
)
output_path = processor.process()
print(f"处理完成: {output_path}")
```

### 作为CLI工具使用

**方式一：使用 Python 模块运行（推荐）**

```bash
# 查看帮助
python -m cli.main --help

# 简单模式：只添加时间点分割线
python -m cli.main add-progressbar input.mp4 -c 30 -c 75 -c 120

# 高级模式：添加章节标题（支持中文，使用默认字体）
python -m cli.main add-progressbar input.mp4 \\
    -c 00:00 -t "教程介绍" \\
    -c 00:30 -t "章节一" \\
    -c 01:20 -t "章节二"

# 使用自定义字体
python -m cli.main add-progressbar input.mp4 \\
    -c 00:00 -t "教程介绍" \\
    -c 00:30 -t "章节一" \\
    --font-path /System/Library/Fonts/PingFang.ttc

# 自定义样式
python -m cli.main add-progressbar input.mp4 \\
    -c 00:00 -t "开始" -c 01:00 -t "结束" \\
    --font-path /System/Library/Fonts/PingFang.ttc \\
    --bar-color "#FF0000@0.5" --bg-color "#000000@0.6" \\
    --bar-height 100 --font-size 30

# 性能优化选项（大文件处理）
python -m cli.main add-progressbar input.mp4 \\
    -c 00:00 -t "开始" -c 01:00 -t "结束" \\
    --preset fast --threads 4 --enable-hwaccel
```

**方式二：使用便捷脚本**

```bash
# 使用项目中的脚本
./scripts/video-process --help

# 简单模式
./scripts/video-process add-progressbar input.mp4 -c 30 -c 75 -c 120

# 高级模式（带标题）
./scripts/video-process add-progressbar input.mp4 \\
    -c 00:00 -t "教程介绍" \\
    -c 00:30 -t "章节一" \\
    --font-path /Library/Fonts/Arial.ttf
```

**方式三：安装后使用（如果 entry_points 正常工作）**

```bash
# 安装后可以直接使用
video-process --help
video-process add-progressbar input.mp4 -c 30 -c 75 -c 120
```


## 应用案例
```
<!-- 例1 -->
python -m cli.main add-progressbar ~/Downloads/4Video-processing/input.mp4 \
    -c 00:00 -t "Supergirl" \
    -c 01:57 -t "怪奇物语-第五季"\
    -c 04:00 -t "Mortal Kombat 2" \
    -c 06:25 -t "Ready Or Not Here I Come" \
    -c 08:45 -t "Hijack Season2" \
--title-position top_right --title-bg-color 'gray@1.0'

<!-- 例2 -->
 python -m cli.main add-progressbar ~/Downloads/4Video-processing/NEW_MOVIE_TRAILERS_2026.mp4 \
    -c 00:00 -t "Supergirl" \
    -c 01:57 -t "怪奇物语-第五季"\
    -c 04:00 -t "Mortal Kombat 2" \
    -c 06:25 -t "Ready Or Not Here I Come" \
    -c 08:45 -t "Hijack Season2" \
    -c 10:41 -t "Shelter" \
    -c 13:12 -t "Protector" \
    -c 15:00 -t "Solo Mio" \
    -c 17:18 -t "Atropia" \
    -c 19:02 -t "Street Fighter" \
    -c 19:57 -t "Mother of Files"\
    -c 21:58 -t "We Burry The Dead" \
    --color-scheme tech_dark
```



## 开发

### 运行测试

```bash
pytest
```

### 效果图
![效果图](./docs/assets/effect-proccess-bar.png)

### 代码规范

项目遵循PEP 8代码规范。

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request。

