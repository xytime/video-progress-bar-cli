import subprocess
import sys
import os

# ================= CONFIGURATION START =================

# 1. 输入输出文件
INPUT_VIDEO = "input.mp4"
OUTPUT_VIDEO = "output_with_advanced_bar.mp4"

# 2. 关键：中文字体文件路径 (必须修改为你电脑上的实际路径!)
# Windows 示例: "C:\\Windows\\Fonts\\simhei.ttf" 或者 "C:/Windows/Fonts/msyh.ttf"
# Mac 示例: "/System/Library/Fonts/PingFang.ttc"
FONT_PATH = "/Library/Fonts/Arial.ttf" 

# 3. 进度栏样式设置
BAR_HEIGHT = 80          # 进度栏高度 (像素)，设大一点以容纳文字
BG_COLOR = '#003366@0.6' # 背景色：深蓝色，@0.6 表示透明度
FILL_COLOR = '#00AAAA@0.5' # 进度填充色：青色/蓝绿色，半透明
TEXT_COLOR = 'white'     # 文字颜色
FONT_SIZE = 24           # 字体大小
DIVIDER_COLOR = 'white@0.8' # 分割线颜色

# 4. 章节数据 (包含开始时间点和标题)
# 格式: {"time": 分钟:秒数, "title": "章节标题"}
# 必须包含从 0 秒开始的第一个章节
CHAPTERS_DATA = [
    {"time": "00:00",   "title": "教程介绍"},
    {"time": "00:30",  "title": "绘制进度条"},
    {"time": "01:15",  "title": "制作进度条动画"},
    {"time": "02:45", "title": "添加刻度和文字"},
    {"time": "03:50", "title": "透明度动画"},
    {"time": "04:30", "title": "教程预告及结尾"}
]

# ================= CONFIGURATION END =================


def get_video_duration(input_file):
    """获取视频总时长（秒）"""
    cmd = [
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', input_file
    ]
    try:
        # 增加 encoding='utf-8' 以防止在某些系统上读取输出乱码
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        return float(result.stdout.strip())
    except (ValueError, FileNotFoundError):
        print(f"错误：无法获取视频时长。请确保已安装 FFmpeg 且输入文件 '{input_file}' 存在。")
        sys.exit(1)

def create_advanced_progressbar():
    # 0. 基础检查
    if not os.path.exists(INPUT_VIDEO):
        print(f"错误：找不到输入文件: {INPUT_VIDEO}")
        return
    if not os.path.exists(FONT_PATH):
        print(f"错误：找不到字体文件: {FONT_PATH}\n请在脚本配置区域正确设置 FONT_PATH。")
        return

    duration = get_video_duration(INPUT_VIDEO)
    print(f"视频时长: {duration:.2f} 秒")

    # 确保章节按时间排序
    sorted_chapters = sorted(CHAPTERS_DATA, key=lambda x: x['time'])
    
    # 准备滤镜链
    filters = []

    # --- 1. 绘制背景底条 (半透明蓝色) ---
    # y=H-h: 放在最底部
    filters.append(f"drawbox=y=iw:color={BG_COLOR}:width=iw:height={BAR_HEIGHT}:t=fill")

    # --- 2. 绘制动态进度填充 (半透明青色) ---
    # 宽度随时间 t 动态计算
    filters.append(f"drawbox=y=ih-{BAR_HEIGHT}:color={FILL_COLOR}:width='iw*(t/{duration})':height={BAR_HEIGHT}:t=fill")

    # --- 3. 循环绘制每个章节的分割线和文字 ---
    for i, section in enumerate(sorted_chapters):
        start_time = section['time']
        title = section['title']
        
        # 确定当前章节的结束时间（下一个章节的开始，或者视频末尾）
        if i + 1 < len(sorted_chapters):
            end_time = sorted_chapters[i+1]['time']
        else:
            end_time = duration
            
        # 安全检查：防止时间超出视频长度
        if start_time >= duration: continue
        end_time = min(end_time, duration)

        # 计算关键百分比位置
        start_pct = start_time / duration
        end_pct = end_time / duration
        center_pct = (start_pct + end_pct) / 2

        # A. 绘制分割线 (跳过第一个0秒的)
        if start_time > 0.5: # 用 0.5 稍微容错
            filters.append(
                f"drawbox=x=iw*{start_pct}:y=ih-{BAR_HEIGHT}:"
                f"w=2:h={BAR_HEIGHT}:color={DIVIDER_COLOR}:t=fill"
            )

        # B. 绘制文字标题
        # 需要转义标题中的特殊字符以便 ffmpeg 识别
        escaped_title = title.replace(":", "\\:").replace("'", "'\\''")
        escaped_font_path = FONT_PATH.replace("\\", "/").replace(":", "\\:")

        # 计算文字位置：
        # x: 位于该段落中心点 (iw*center_pct) 减去文字自身宽度的一半 (tw/2)
        # y: 位于底部栏的垂直中心。总高度 H 减去栏高的一半，再微调文字高度
        text_x_expr = f"(iw*{center_pct})-(tw/2)"
        text_y_expr = f"H-({BAR_HEIGHT}/2)-(th/3)" # th/3 是为了视觉垂直居中做的微调

        filters.append(
            f"drawtext=fontfile='{escaped_font_path}':"
            f"text='{escaped_title}':"
            f"fontcolor={TEXT_COLOR}:fontsize={FONT_SIZE}:"
            f"x={text_x_expr}:y={text_y_expr}"
        )

    # 构建最终滤镜字符串
    filter_str = ",".join(filters)

    # --- 运行 FFmpeg 命令 ---
    cmd = [
        'ffmpeg', '-v', 'warning', # 减少日志输出
        '-i', INPUT_VIDEO,
        '-vf', filter_str,
        '-c:a', 'copy',    # 音频流直接复制
        '-c:v', 'libx264', # 视频重新编码
        '-preset', 'medium', # 编码速度平衡
        '-y', OUTPUT_VIDEO
    ]

    print("正在渲染视频，这需要一些时间 (因为要处理文字和透明度)...")
    # print(f"调试：滤镜字符串长度: {len(filter_str)}") # 如果报错可以打印看看
    
    try:
        # 在 Windows 上处理中文路径和字符可能需要设置 shell=True 并且注意编码
        # 这里尝试使用列表传参，通常更安全
        subprocess.run(cmd, check=True, encoding='utf-8')
        print(f"\n成功！输出文件位于: {OUTPUT_VIDEO}")
    except subprocess.CalledProcessError as e:
        print(f"\nFFmpeg 执行出错: {e}")
        print("请检查字体路径是否正确，或者是否有特殊字符导致命令截断。")
    except FileNotFoundError:
        print("\n错误：未找到 'ffmpeg' 命令。请确保已安装并配置环境变量。")

if __name__ == "__main__":
    create_advanced_progressbar()