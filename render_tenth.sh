#!/bin/bash
cd /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output

echo "Waiting for any existing ffmpeg or python process to finish..."
while pgrep -x "ffmpeg" > /dev/null || pgrep -f "python -m cli.main auto-caption" > /dev/null; do
    sleep 5
done

echo "Downloading Video 10: Death of Internet..."
yt-dlp --no-check-certificate --cookies-from-browser safari -f "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" "https://www.youtube.com/watch?v=8qVbE9DHkEk" -o "Death_Internet.%(ext)s"

cd ..
EXT=$(ls output/Death_Internet.* | head -n 1 | awk -F. '{print $NF}')
echo "Processing Video 10: Death of Internet..."
nice -n 19 python -m cli.main auto-caption output/Death_Internet.$EXT --vertical --style tech_blue --bilingual --title "AI 会导致互联网终结吗？| DW纪录片" > output/death_internet_process.log 2>&1

echo "Render complete for Death_Internet."
