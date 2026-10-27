"""单片人工确认的原字幕保留：原片与交付片逐字节相同，不生成虚假烧录字幕。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 摘要绑定用户确认、审查正文与原样交付，禁止泛化为字幕跳过开关。 |
"""
import json
from pathlib import Path
import shutil

from config.settings import settings
from .render_source_binding import digest


APPROVALS = Path(settings.project_root) / 'config/native_caption_sources.json'


def approved_entry(prefix: str) -> dict | None:
    if not APPROVALS.is_file():
        return None
    data = json.loads(APPROVALS.read_text(encoding='utf-8'))
    if data.get('version') != 1:
        raise ValueError('原字幕保留清单版本无效')
    return data['sources'].get(prefix)


def _entry(prefix: str) -> dict:
    entry = approved_entry(prefix)
    if (not entry or not entry.get('user_confirmed') or not entry.get('review_text', '').strip()
            or not entry.get('source_sha256')):
        raise ValueError('缺少单片用户确认或内容审查正文')
    return entry


def receipt_path(vertical: Path) -> Path:
    return vertical.with_suffix('.native-captions.json')


def validate_preserved(vertical: Path, source: Path | None = None) -> dict:
    prefix = vertical.stem.removesuffix('_vertical')
    if vertical.name != f'{prefix}_vertical.mp4':
        raise ValueError('原字幕保留只接受标准交付文件')
    entry = _entry(prefix)
    receipt = json.loads(receipt_path(vertical).read_text(encoding='utf-8'))
    expected = {'version': 1, 'mode': 'preserve_native_captions',
                'approval_sha256': digest(APPROVALS), 'source_sha256': entry['source_sha256']}
    if receipt != expected or digest(vertical) != entry['source_sha256']:
        raise ValueError('原字幕成片或确认凭证已变更')
    if source is not None and (source.stem != prefix or digest(source) != entry['source_sha256']):
        raise ValueError('原字幕保留源片与确认摘要不匹配')
    return entry


def preserve(source: Path, vertical: Path) -> None:
    prefix = vertical.stem.removesuffix('_vertical')
    entry = _entry(prefix)
    if source.stem != prefix or digest(source) != entry['source_sha256']:
        raise ValueError('原字幕保留源片与确认摘要不匹配')
    # 先验证源片再写入；原子替换避免留下半份交付文件。
    temporary = vertical.with_suffix('.native-pending.mp4')
    try:
        shutil.copyfile(source, temporary)
        if digest(temporary) != entry['source_sha256']:
            raise ValueError('原字幕复制摘要不匹配')
        temporary.replace(vertical)
    finally:
        temporary.unlink(missing_ok=True)
    receipt = {'version': 1, 'mode': 'preserve_native_captions',
               'approval_sha256': digest(APPROVALS), 'source_sha256': entry['source_sha256']}
    destination = receipt_path(vertical)
    pending = destination.with_suffix('.pending.json')
    pending.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    pending.replace(destination)
    validate_preserved(vertical, source)


def review_text(vertical: Path) -> str:
    return validate_preserved(vertical)['review_text']
