#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""清理工具 - 用于清除视频加工管线运行中产生的超大视频临时文件和日志。

# Modification History
| Version | Date       | Author                | Description |
|---------|------------|-----------------------|-------------|
| 1.0.0   | 2026-05-27 | Gemini_3.5_Flash      | 初始创建，提供安全的分类清理与 Dry-run 机制 |
"""

import os
import sys
import argparse
import sqlite3
import re
from pathlib import Path

# 将项目根目录和 src 目录添加到 sys.path
_project_root = Path(__file__).parent.parent.resolve()
_src_dir = _project_root / "src"
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from src.config.settings import settings

def format_size(size_bytes: int) -> str:
    """格式化文件大小为可读的字符串"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.2f} MB"
    else:
        return f"{size_bytes / 1024 / 1024 / 1024:.2f} GB"

def get_db_video_statuses(db_path: Path) -> dict[str, str]:
    """读取数据库，返回 youtube_id -> status 的映射"""
    if not db_path.exists():
        return {}
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT youtube_id, status FROM processed_videos")
        mapping = {row["youtube_id"]: row["status"] for row in cursor.fetchall()}
        conn.close()
        return mapping
    except Exception as e:
        print(f"警告: 读取数据库失败 ({e})，将无法根据数据库状态进行精准清理。")
        return {}

def main():
    parser = argparse.ArgumentParser(description="视频加工管线垃圾文件清理工具")
    parser.add_argument("--execute", action="store_true", help="执行真实删除（默认仅进行 Dry-run 模拟）")
    parser.add_argument("--clean-published", action="store_true", help="清理状态为 PUBLISHED 的视频文件 (超大 mp4/vertical.mp4/ass/jpg)")
    parser.add_argument("--clean-failed", action="store_true", help="清理状态为 FAILED 的视频文件")
    parser.add_argument("--clean-metadata", action="store_true", help="同时清理文本元数据 (description, title, copy, category, hints 等)")
    parser.add_argument("--clean-debug-images", action="store_true", help="清理 Playwright 运行中残留的诊断图片/HTML/JSON 网页快照")
    parser.add_argument("--clean-logs", action="store_true", help="清理根目录与 output 目录下的历史 log 日志文件")
    parser.add_argument("--all", action="store_true", help="清理以上所有可清理的内容")
    
    args = parser.parse_args()

    # 如果指定了 --all，则激活所有清理开关
    if args.all:
        args.clean_published = True
        args.clean_failed = True
        args.clean_metadata = True
        args.clean_debug_images = True
        args.clean_logs = True

    # 默认如果没有选中任何开关，则只做展示，不清理任何东西
    has_any_switch = (args.clean_published or args.clean_failed or 
                      args.clean_debug_images or args.clean_logs)

    output_dir = settings.default_output_dir
    db_path = output_dir / "pipeline.db"
    
    print(f"项目根目录: {_project_root}")
    print(f"视频输出目录: {output_dir}")
    print(f"数据库路径: {db_path}")
    print("=" * 60)

    # 获取数据库中视频的状态
    video_statuses = get_db_video_statuses(db_path)
    
    # 扫描 output 目录下的所有文件
    all_output_files = list(output_dir.iterdir()) if output_dir.exists() else []
    
    # 垃圾分类桶
    to_delete_files: list[Path] = []
    
    # 1. 匹配视频相关文件
    # 视频相关的后缀: .mp4, _vertical.mp4, .ass, _cover.jpg, _cover_regen.jpg
    video_extensions = [".mp4", ".ass", "_cover.jpg", "_cover_regen.jpg"]
    # 文本元数据后缀: .description, _category.txt, _copy.txt, _title.txt, _subtitle.txt, _content_hints.json
    meta_extensions = [".description", "_category.txt", "_copy.txt", "_title.txt", "_subtitle.txt", "_content_hints.json"]

    # 遍历 output 目录中的文件
    for file in all_output_files:
        if file.is_dir() or file.name.startswith('.'):
            continue
            
        # 寻找匹配的 youtube_id
        matched_yid = None
        for yid in video_statuses:
            if file.name.startswith(yid):
                matched_yid = yid
                break
                
        if matched_yid:
            status = video_statuses[matched_yid]
            is_video_file = any(file.name.endswith(ext) for ext in video_extensions) or "_vertical.mp4" in file.name
            is_meta_file = any(file.name.endswith(ext) for ext in meta_extensions)
            
            # 判定是否属于已发布 (PUBLISHED) 并需要清理
            if status == "PUBLISHED" and args.clean_published:
                if is_video_file:
                    to_delete_files.append(file)
                elif is_meta_file and args.clean_metadata:
                    to_delete_files.append(file)
                    
            # 判定是否属于失败 (FAILED) 并需要清理
            elif status == "FAILED" and args.clean_failed:
                if is_video_file:
                    to_delete_files.append(file)
                elif is_meta_file and args.clean_metadata:
                    to_delete_files.append(file)

    # 2. 匹配 Playwright 诊断 debug 快照/截图
    # 文件名特征: debug_*.png, diag_*.png, diag_*.json, diag_*.html, diagnose_*.png, diagnose_*.html, diagnose_*.json, page_dump.html, test_dom.json
    debug_patterns = [
        r"^debug_.*\.png$",
        r"^diag_.*\.png$",
        r"^diag_.*\.json$",
        r"^diag_.*\.html$",
        r"^diagnose_.*\.png$",
        r"^diagnose_.*\.html$",
        r"^diagnose_.*\.json$",
        r"^page_dump\.html$",
        r"^test_dom\.json$",
        r"^debug_btn_area\.png$"
    ]
    if args.clean_debug_images:
        for file in all_output_files:
            if any(re.match(pattern, file.name) for pattern in debug_patterns):
                to_delete_files.append(file)

    # 3. 匹配日志文件
    # 包括根目录下和 output 下的 *.log, *.pid
    log_files: list[Path] = []
    if args.clean_logs:
        # 扫描 output 中的日志
        for file in all_output_files:
            if file.name.endswith(".log") or file.name.endswith(".pid"):
                log_files.append(file)
        # 扫描根目录下的日志
        for file in _project_root.iterdir():
            if file.is_file() and (file.name.endswith(".log") or file.name.endswith(".pid") or "_process.log" in file.name):
                log_files.append(file)
                
        to_delete_files.extend(log_files)

    # 去重
    to_delete_files = list(set(to_delete_files))
    
    # 统计容量
    total_reclaimed = sum(f.stat().st_size for f in to_delete_files if f.exists())
    
    print(f"扫描完成。准备清理的文件数量: {len(to_delete_files)}")
    print(f"预计可释放空间: {format_size(total_reclaimed)}")
    print("-" * 60)

    if not has_any_switch:
        print("提示: 未指定任何清理范围。请使用以下开关指定要清理的内容：")
        print("  --clean-published     清理已发布视频的媒体文件")
        print("  --clean-failed        清理失败视频的媒体文件")
        print("  --clean-metadata      配合上面两个开关，同时清理文本元数据")
        print("  --clean-debug-images  清理 Playwright 运行中的快照图片和网页")
        print("  --clean-logs          清理所有的日志文件 (*.log)")
        print("  --all                 清理上述所有内容")
        print("  --execute             确认执行删除 (不加此参数默认只做 Dry-run)")
        return

    # 展示具体要清理的文件
    if to_delete_files:
        print("待清理文件列表 (按大小降序):")
        to_delete_files.sort(key=lambda x: x.stat().st_size if x.exists() else 0, reverse=True)
        for i, file in enumerate(to_delete_files[:30]):
            size = file.stat().st_size if file.exists() else 0
            print(f"  {i+1:2d}. [{format_size(size):>10}] {file.relative_to(_project_root)}")
        if len(to_delete_files) > 30:
            print(f"  ... 还有 {len(to_delete_files) - 30} 个文件未列出 ...")
            
        print("-" * 60)
        if args.execute:
            print("正在执行真实删除...")
            deleted_count = 0
            for file in to_delete_files:
                try:
                    if file.exists():
                        file.unlink()
                        deleted_count += 1
                except Exception as e:
                    print(f"删除失败: {file.name} ({e})")
            print(f"成功删除 {deleted_count} 个文件，释放空间 {format_size(total_reclaimed)}。")
        else:
            print("【DRY-RUN 模式】未执行任何实际删除。")
            print("若确定要删除这些文件，请在命令末尾加上 `--execute` 参数。")
    else:
        print("没有找到符合条件的可清理文件。")

if __name__ == "__main__":
    main()
