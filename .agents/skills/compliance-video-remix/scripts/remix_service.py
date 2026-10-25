#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compliance Video Remix - Remix Service Entrypoint"""
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

from video_processing.compliance_remix.remix_service import (
    ComplianceRemixService,
    fetch_source_metadata_and_subtitles,
)
