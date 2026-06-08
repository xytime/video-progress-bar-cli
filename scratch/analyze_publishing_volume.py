import sqlite3
import os
import glob
import re

conn = sqlite3.connect("output/pipeline.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Get the count of published videos in the last 7 days or total frequency
cursor.execute("SELECT COUNT(*) FROM processed_videos WHERE status='PUBLISHED'")
total_published = cursor.fetchone()[0]

cursor.execute("SELECT AVG(duration_sec), MIN(duration_sec), MAX(duration_sec) FROM processed_videos WHERE status='PUBLISHED' AND duration_sec IS NOT NULL")
duration_stats = cursor.fetchone()
avg_dur = duration_stats[0]
min_dur = duration_stats[1]
max_dur = duration_stats[2]

# Let's count published videos per day in May 2026 (or recent dates)
cursor.execute("""
    SELECT SUBSTR(updated_at, 1, 10) as date, COUNT(*) as cnt 
    FROM processed_videos 
    WHERE status='PUBLISHED' 
    GROUP BY date 
    ORDER BY date DESC 
    LIMIT 15
""")
daily_stats = [dict(row) for row in cursor.fetchall()]

# Let's analyze a few .ass files to see average Chinese character count per video
ass_files = glob.glob("output/*.ass")
total_chars = 0
ass_count = 0
for f in ass_files[:10]:
    try:
        with open(f, "r", encoding="utf-8") as file:
            content = file.read()
            # Extract dialogues
            lines = content.split("\n")
            chars_in_file = 0
            for line in lines:
                if line.startswith("Dialogue:"):
                    parts = line.split(",", 9)
                    if len(parts) >= 10:
                        text = parts[9]
                        # Extract Chinese part
                        if r"{\fs50" in text:
                            zh = text.split(r"{\fs50")[0]
                        else:
                            zh = text
                        # Remove tags
                        zh = re.sub(r'\{[^}]*\}', '', zh)
                        zh = zh.replace(r'\N', '').strip()
                        # Count only Chinese characters/alphanumeric
                        zh_only = [c for c in zh if c.isalnum() or '\u4e00' <= c <= '\u9fff']
                        chars_in_file += len(zh_only)
            total_chars += chars_in_file
            ass_count += 1
    except Exception as e:
        print(f"Exception for {f}: {e}")

avg_chars_per_video = total_chars / ass_count if ass_count > 0 else 0

print(f"Total Published: {total_published}")
print(f"Duration Stats (seconds) - Avg: {avg_dur:.1f}, Min: {min_dur}, Max: {max_dur}")
print(f"Average Chinese characters per video (from .ass): {avg_chars_per_video:.1f}")
print("\nDaily stats of published videos:")
for d in daily_stats:
    print(f"  {d['date']}: {d['cnt']} videos")

conn.close()
