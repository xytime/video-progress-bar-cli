import sys
from pathlib import Path
import subprocess
import shutil

sys.path.append(str(Path('src')))
from video_processing.db import PipelineDB

db = PipelineDB()
out_dir = Path("output")
artifact_dir = Path("/Users/ryusei/.gemini/antigravity/brain/11cc548f-1a93-4780-93df-ada5f9761875/artifacts")
artifact_dir.mkdir(parents=True, exist_ok=True)

with db.get_connection() as conn:
    # Get the latest 5 published videos based on some reasonable logic
    ids = ["PtbZY9HCatE", "iB2eApp0Kmo", "5YHIrTYxM3w", "XFaeIbL-lvE", "eLP3ag0YpyA", "sRvUXLquiRg"]
    
    markdown_content = ["# 重制已发布视频封面\n\n这 5 个视频的封面已经使用最新的 **V5 玻璃态方案** 并且应用了**浓缩的短标题**进行了重新生成。\n\n````carousel\n"]
    
    for i, yid in enumerate(ids):
        # Fetch original title from DB just in case
        cursor = conn.execute("SELECT title FROM processed_videos WHERE youtube_id=?", (yid,))
        row = cursor.fetchone()
        orig_title = row['title'] if row else "Unknown Video"
        
        title_file = out_dir / f"{yid}_title.txt"
        
        if title_file.exists():
            cover_title = title_file.read_text(encoding="utf-8").strip()
        else:
            # Fallback
            cover_title = orig_title
            
        cover_file = out_dir / f"{yid}_cover_regen.jpg"
        
        # Generate
        cmd = [
            ".venv/bin/python",
            "scripts/cover_generator.py",
            "--title", cover_title,
            "--output", str(cover_file)
        ]
        subprocess.run(cmd, check=True)
        
        # Copy to artifacts
        artifact_path = artifact_dir / f"{yid}_cover.jpg"
        shutil.copy(cover_file, artifact_path)
        
        # Append to markdown
        if i > 0:
            markdown_content.append("<!-- slide -->\n")
        markdown_content.append(f"### {cover_title}\n")
        markdown_content.append(f"*(原标题: {orig_title})*\n\n")
        markdown_content.append(f"![{cover_title}](/Users/ryusei/.gemini/antigravity/brain/11cc548f-1a93-4780-93df-ada5f9761875/artifacts/{yid}_cover.jpg)\n\n")

    markdown_content.append("````")
    
    # Write artifact
    with open(artifact_dir / "regenerated_covers.md", "w", encoding="utf-8") as f:
        f.write("".join(markdown_content))
    print("Done. Generated regenerated_covers.md")
