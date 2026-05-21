#!/bin/bash
cd /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output

echo "Waiting for any existing ffmpeg or python process to finish..."
while pgrep -x "ffmpeg" > /dev/null || pgrep -f "python -m cli.main auto-caption" > /dev/null; do
    sleep 5
done

echo "Downloading Video 5: Meta AI Interview..."
yt-dlp --no-check-certificate --cookies-from-browser safari -f "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" "https://www.youtube.com/watch?v=A1kX8fJx53c" -o "Meta_Interview.%(ext)s"

cd ..
EXT=$(ls output/Meta_Interview.* | head -n 1 | awk -F. '{print $NF}')
echo "Processing Video 5: Meta AI Interview..."
python -m cli.main auto-caption output/Meta_Interview.$EXT --vertical --style tech_blue --bilingual --title "Meta工程师教你通关AI编程面试" > output/meta_interview_process.log 2>&1

echo "Render complete for Meta_Interview."
