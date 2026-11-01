"""正常字幕入口必须续用具名原片已复核的ASR模型，仍尊重显式模型选择。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 真实Click解析验证默认续跑、准确源绑定、显式参数与未知来源。 |
"""
import importlib

import pytest
from click.testing import CliRunner

from video_processing.processors import reviewed_caption_sources as reviewed
from video_processing.utils.render_source_binding import digest


@pytest.mark.parametrize('case,expected', [
    ('default', 'large-v3'),
    ('explicit', 'small'),
    ('unreviewed', 'small'),
    ('no_approved_model', 'small'),
    ('not_preserving', 'small'),
    ('changed_source', None),
])
def test_real_caption_cli_uses_source_bound_reviewed_model(tmp_path, monkeypatch, case, expected):
    module = importlib.import_module('cli.commands.auto_caption')
    source = tmp_path / 'reviewed001.mp4'
    source.write_bytes(b'known reviewed original source')
    record = dict(source_sha256=digest(source), timeline_sha256='a' * 64,
                  duration=121.5, asr_model='large-v3')
    monkeypatch.setattr(reviewed, 'SOURCES', {'reviewed001': record})
    if case == 'unreviewed':
        source = source.rename(tmp_path / 'unknown001.mp4')
    if case == 'no_approved_model':
        record.pop('asr_model')
    if case == 'changed_source':
        source.write_bytes(b'changed unreviewed source')
    calls = []

    class Processor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            calls.append(kwargs)

        def process(self):
            return self.kwargs['output_path']

    monkeypatch.setattr(module, 'VerticalCaptionProcessor', Processor)
    args = [str(source), '--vertical', '--bilingual', '--output', str(tmp_path / 'result.mp4')]
    if case != 'not_preserving':
        args.append('--preserve-source-chinese')
    if case == 'explicit':
        args.extend(['--model', 'small'])
    result = CliRunner().invoke(module.auto_caption, args)
    if expected is None:
        assert result.exit_code != 0 and not calls
        assert '摘要不符' in result.output
    else:
        assert result.exit_code == 0, result.output
        assert calls[0]['model_size'] == expected


def test_actual_7031_record_keeps_reviewed_large_model():
    assert reviewed.SOURCES['CatuGloDkTQ']['asr_model'] == 'large-v3'
    assert reviewed.SOURCES['CatuGloDkTQ']['source_sha256'] == '2d525f43d92280d23c845880c60a1044ff6ea342b638fb40d93eccd29d5939ed'
