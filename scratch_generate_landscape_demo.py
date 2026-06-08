import sys
from pathlib import Path
sys.path.insert(0, str(Path("src").resolve()))

from video_processing.processors.vertical_processor import VerticalCaptionProcessor

# 横屏 demo — 使用 VerticalCaptionProcessor（含双语字幕 + GlossaryCard）
# 输入: 1280x720 横屏原素材，将被 letterbox 嵌入 1080x1920 画布
# 字幕起始位置: Y=1300（紧接于视频下方）
input_video = Path("landscape_1min.mp4")
output_video = Path("demo_landscape_bilingual_1min.mp4")

print(f"Processing landscape with bilingual subtitles: {input_video} → {output_video}...")

processor = VerticalCaptionProcessor(
    input_path=input_video,
    output_path=output_video,
    style="default",
    bilingual=True,
    font_size=84,   # 与竖屏 demo 相同字号，横屏画布同为 1080x1920
)

processor.process()
print("Landscape Bilingual Done!")
