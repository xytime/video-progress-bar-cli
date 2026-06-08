import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path("src").resolve()))

from video_processing.processors.vertical_processor import VerticalCaptionProcessor

input_video = Path("XcSdPK5Xwbk_1min.mp4")
output_video = Path("demo_vocabulary_3words_1min.mp4")

print(f"Processing {input_video} to {output_video}...")

processor = VerticalCaptionProcessor(
    input_path=input_video,
    output_path=output_video,
    style="default",
    bilingual=True
)

processor.process()

print("Done!")
