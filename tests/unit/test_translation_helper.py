# -*- coding: utf-8 -*-
"""翻译终级兜底单元测试。"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

import video_processing.utils.translation_helper as th


def test_translate_batch_uses_google_directly():
    with patch.object(th, "_google_translate_batch", return_value=["谷歌译文"]) as mock_google:
        assert th.translate_batch(["Hello"]) == ["谷歌译文"]
    mock_google.assert_called_once()


def test_translate_text_keeps_original_on_failed_fallback():
    with patch.object(th, "_google_translate_batch", return_value=[""]):
        assert th.translate_text("Stoicism") == "Stoicism"


def test_google_batch_filters_error_pages_and_keeps_length():
    translator = MagicMock()
    translator.translate_batch.return_value = ["<html>Error</html>", "正常译文"]
    with patch.object(th, "GoogleTranslator", return_value=translator):
        assert th._google_translate_batch(["a", "b"]) == ["", "正常译文"]


def test_google_batch_returns_empty_entries_when_unavailable():
    with patch.object(th, "GoogleTranslator", None):
        assert th._google_translate_batch(["a", "b"]) == ["", ""]
