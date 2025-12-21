# 进度条功能升级说明

## 升级内容

进度条功能已升级，现在支持：

1. **章节标题显示**：支持在进度条上显示章节标题（支持中文）
2. **灵活的时间格式**：支持 `MM:SS`、`HH:MM:SS` 或纯秒数格式
3. **丰富的样式选项**：支持自定义颜色、字体、大小等
4. **向后兼容**：仍然支持简单的只添加时间点模式

## 使用方式

### 简单模式（只添加时间点分割线）

```bash
python -m cli.main add-progressbar input.mp4 -c 30 -c 75 -c 120
```

### 高级模式（添加章节标题）

```bash
python -m cli.main add-progressbar input.mp4 \\
    -c 00:00 -t "教程介绍" \\
    -c 00:30 -t "章节一" \\
    -c 01:20 -t "章节二" \\
    --font-path /Library/Fonts/Arial.ttf
```

### 参数说明

- `-c, --chapter-time`: 章节时间点，支持格式：
  - 秒数：`30`（30秒）
  - MM:SS：`00:30`（30秒）
  - HH:MM:SS：`01:05:30`（3930秒）
- `-t, --chapter-title`: 章节标题（与 `-c` 配对使用）
- `--font-path`: 字体文件路径（显示中文标题必需）
  - Mac 示例：`/Library/Fonts/Arial.ttf` 或 `/System/Library/Fonts/PingFang.ttc`
  - Windows 示例：`C:\\Windows\\Fonts\\simhei.ttf`
- `--bar-height`: 进度条高度（默认 80，建议 80 以上以容纳文字）
- `--bar-color`: 进度条填充颜色（默认 `#00AAAA@0.5`）
- `--bg-color`: 背景条颜色（默认 `#003366@0.6`）
- `--font-size`: 字体大小（默认 24）
- `--text-color`: 文字颜色（默认 `white`）

## 作为库使用

```python
from pathlib import Path
from video_processing.processors.progress_bar import ProgressBarProcessor

# 高级模式：带标题
chapters = [
    {"time": "00:00", "title": "教程介绍"},
    {"time": "00:30", "title": "章节一"},
    {"time": "01:20", "title": "章节二"}
]

processor = ProgressBarProcessor(
    input_path=Path("input.mp4"),
    chapters=chapters,
    font_path="/Library/Fonts/Arial.ttf",
    bar_height=80,
    bar_color="#00AAAA@0.5",
    bg_color="#003366@0.6",
)

output_path = processor.process()
```

## 注意事项

1. **字体文件**：如果使用章节标题功能，必须指定字体文件路径（`--font-path`）
2. **进度条高度**：如果显示文字，建议将 `--bar-height` 设置为 80 或更大
3. **时间格式**：章节时间点支持多种格式，会自动识别
4. **配对使用**：`-c` 和 `-t` 必须配对使用，数量要一致

## 示例

完整示例请参考 `examples/add_progressbar_example.py`

