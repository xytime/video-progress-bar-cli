#!/bin/bash
cd /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output

echo "Waiting for any existing ffmpeg or python process to finish..."
while pgrep -x "ffmpeg" > /dev/null || pgrep -f "python -m cli.main auto-caption" > /dev/null; do
    sleep 5
done

echo "Downloading Video 8: Jeff Bezos on AI..."
yt-dlp --no-check-certificate --cookies-from-browser safari -f "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" "https://www.youtube.com/watch?v=BxG_ysI3xr4" -o "Bezos_AI.%(ext)s"

cd ..
EXT=$(ls output/Bezos_AI.* | head -n 1 | awk -F. '{print $NF}')
echo "Processing Video 8: Jeff Bezos on AI..."
nice -n 19 python -m cli.main auto-caption output/Bezos_AI.$EXT --vertical --style tech_blue --bilingual --title "贝索斯谈AI：生产力革命与通缩" > output/bezos_ai_process.log 2>&1

echo "Render complete for Bezos_AI."
