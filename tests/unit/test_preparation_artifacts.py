"""任务产物隔离兼容既有导出器，并保留 ASR 方法实现身份。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 验证共享别名留在尝试目录、具名原子回写及跨片拒绝。 |
"""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile

import pytest

from video_processing.utils.preparation_artifacts import isolated_caption_artifacts


def test_alias_and_audio_temp_are_attempt_scoped(tmp_path):
    scope = SimpleNamespace(output=tmp_path, key='video:0', owner='a' * 32)
    class Processor:
        input_path = tmp_path / 'video.mp4'
        output_path = tmp_path / 'video_vertical.mp4'
        def export_vocabulary_json(self, segments, output_path=None):
            target = Path(output_path)
            raw = json.dumps({'video_id': 'video', 'items': segments})
            target.write_text(raw)
            (target.parent / 'vocabulary.json').write_text(raw)
            return target
    processor = Processor()
    (tmp_path / 'vocabulary.json').write_text('other task')
    previous = tempfile.tempdir
    with isolated_caption_artifacts(processor, scope):
        result = processor.export_vocabulary_json([{'word': 'test'}])
        assert str(result.parent) == tempfile.gettempdir()
        assert result.parent.name == scope.owner
        assert json.loads((tmp_path / 'video_vocabulary.json').read_text())['video_id'] == 'video'
    assert tempfile.tempdir == previous
    assert (tmp_path / 'vocabulary.json').read_text() == 'other task'


def test_wrong_source_or_wrong_export_identity_cannot_overwrite(tmp_path):
    scope = SimpleNamespace(output=tmp_path, key='video:0', owner='a' * 32)
    processor = SimpleNamespace(input_path=tmp_path/'other.mp4')
    with pytest.raises(ValueError, match='source identity'):
        with isolated_caption_artifacts(processor, scope):
            pass
    processor.input_path = tmp_path/'video.mp4'
    processor.output_path = tmp_path/'video_vertical.mp4'
    def wrong(segments, output_path=None):
        output_path.write_text('{"video_id":"other"}')
        return output_path
    processor.export_vocabulary_json = wrong
    previous = tempfile.tempdir
    with pytest.raises(ValueError, match='vocabulary identity'):
        with isolated_caption_artifacts(processor, scope):
            processor.export_vocabulary_json([])
    assert tempfile.tempdir == previous
    assert not (tmp_path/'video_vocabulary.json').exists()
