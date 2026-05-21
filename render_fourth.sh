#!/bin/bash
cd /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output

echo "Waiting for any existing ffmpeg or python process to finish..."
while pgrep -x "ffmpeg" > /dev/null || pgrep -f "python -m cli.main auto-caption" > /dev/null; do
    sleep 5
done

echo "Downloading Video 4: Huang Dell..."
yt-dlp --no-check-certificate --cookies-from-browser safari -f "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" "https://www.youtube.com/watch?v=oE5lNDhz9oo" -o "Huang_Dell.%(ext)s"

cd ..
EXT=$(ls output/Huang_Dell.* | head -n 1 | awk -F. '{print $NF}')
echo "Processing Video 4: Huang Dell..."
python -m cli.main auto-caption output/Huang_Dell.$EXT --vertical --style tech_blue --bilingual --title "黄仁勋与迈克尔·戴尔巅峰对话：Agentic AI 与未来市场展望" > output/huang_dell_process.log 2>&1

echo "Render complete for Huang_Dell."
