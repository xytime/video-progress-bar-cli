#!/bin/bash
cd /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing

echo "Processing Video 1: Ray Dalio..."
python -m cli.main auto-caption output/Dalio_Speech.mp4 --vertical --style tech_blue --bilingual --title "瑞·达利欧：长岛大学毕业典礼演讲 - 15分钟核心人生经验" > output/dalio_process.log 2>&1 &

echo "Downloading Video 2: Jensen Huang..."
yt-dlp --no-check-certificate -f "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" "https://www.youtube.com/watch?v=FZh_0uRgrg4" -o "output/Huang_Speech.%(ext)s"

# Ensure the file is named properly to process
EXT=$(ls output/Huang_Speech.* | head -n 1 | awk -F. '{print $NF}')
echo "Processing Video 2: Jensen Huang..."
python -m cli.main auto-caption output/Huang_Speech.$EXT --vertical --style tech_blue --bilingual --title "黄仁勋 CMU 2026 毕业演讲：奔跑吧，不要行走" > output/huang_process.log 2>&1 &

echo "All processing started in background."
