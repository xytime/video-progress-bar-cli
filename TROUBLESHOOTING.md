# 故障排除指南

## 问题：`Error: No such option: -t`

如果遇到 "No such option: -t" 错误，请尝试以下解决方案：

### 解决方案 1: 清理 Python 缓存

```bash
# 清理项目中的缓存
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -r {} + 2>/dev/null

# 重新安装项目
pip uninstall -y video-processing
pip install -e .
```

### 解决方案 2: 确认使用最新代码

确保使用的是项目根目录下的代码，而不是已安装的旧版本：

```bash
# 使用项目中的脚本（推荐）
./scripts/video-process add-progressbar input.mp4 -c 00:00 -t "标题" --font-path /path/to/font.ttf

# 或使用 Python 模块（确保在项目目录下）
python -m cli.main add-progressbar input.mp4 -c 00:00 -t "标题" --font-path /path/to/font.ttf
```

### 解决方案 3: 验证选项是否存在

```bash
# 查看帮助信息，确认 -t 选项存在
python -m cli.main add-progressbar --help | grep -A 2 "-t"
```

### 解决方案 4: 检查 Click 版本

确保 Click 版本正确：

```bash
pip install --upgrade click
```

## 正确的命令格式

### 简单模式（只添加时间点）
```bash
python -m cli.main add-progressbar input.mp4 -c 30 -c 75 -c 120
```

### 高级模式（带章节标题）
```bash
python -m cli.main add-progressbar input.mp4 \
    -c 00:00 -t "教程介绍" \
    -c 00:30 -t "章节一" \
    -c 01:20 -t "章节二" \
    --font-path /Library/Fonts/Arial.ttf
```

**注意**：
- `-c` 和 `-t` 必须配对使用
- 如果使用标题，必须指定 `--font-path`
- 时间格式支持：秒数（如 `30`）、MM:SS（如 `00:30`）、HH:MM:SS（如 `01:05:30`）

