#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compliance Video Remix - Card Generator Entrypoint"""
import sys
from pathlib import Path

def _find_project_root() -> Path:
    cur = Path(__file__).resolve()
    for parent in [cur] + list(cur.parents):
        if (parent / "src").is_dir() and (parent / "scripts").is_dir():
            return parent
    return cur.parents[4]

PROJECT_ROOT = _find_project_root()
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from video_processing.compliance_remix.card_generator import (
    FinancialCardGenerator,
    generate_vertical_frame_overlay,
    main,
)

if __name__ == "__main__":
    main()
