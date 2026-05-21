#!/bin/bash
cd /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output

echo "Waiting for any existing ffmpeg or python process to finish..."
while pgrep -x "ffmpeg" > /dev/null || pgrep -f "python -m cli.main auto-caption" > /dev/null; do
    sleep 5
done

echo "Downloading Video 6: The Oppenheimer of AI..."
yt-dlp --no-check-certificate --cookies-from-browser safari -f "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" "https://www.youtube.com/watch?v=MHiVBoWB3OE" -o "Oppenheimer_AI.%(ext)s"

cd ..
EXT=$(ls output/Oppenheimer_AI.* | head -n 1 | awk -F. '{print $NF}')
echo "Processing Video 6: The Oppenheimer of AI..."
python -m cli.main auto-caption output/Oppenheimer_AI.$EXT --vertical --style tech_blue --bilingual --title "AI时代的“奥本海默”：科技巨头背后的野心与博弈" > output/oppenheimer_ai_process.log 2>&1

echo "Render complete for Oppenheimer_AI."
