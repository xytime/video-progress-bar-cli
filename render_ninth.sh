#!/bin/bash
cd /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output

echo "Waiting for any existing ffmpeg or python process to finish..."
while pgrep -x "ffmpeg" > /dev/null || pgrep -f "python -m cli.main auto-caption" > /dev/null; do
    sleep 5
done

echo "Downloading Video 9: Claude AI Money..."
yt-dlp --no-check-certificate --cookies-from-browser safari -f "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" "https://www.youtube.com/watch?v=beBRtz_VSGU" -o "Claude_Money.%(ext)s"

cd ..
EXT=$(ls output/Claude_Money.* | head -n 1 | awk -F. '{print $NF}')
echo "Processing Video 9: Claude AI Money..."
nice -n 19 python -m cli.main auto-caption output/Claude_Money.$EXT --vertical --style cyberpunk --bilingual --title "2026年如何用Claude搞钱" > output/claude_money_process.log 2>&1

echo "Render complete for Claude_Money."
