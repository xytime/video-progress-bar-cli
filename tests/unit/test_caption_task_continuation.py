"""字幕入口在维护排空中延续同一任务，拒绝新任务或错配凭据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 真实子进程、CLI 和 DAL 审计写入验证，不调用媒体或供应商。 |
"""
from pathlib import Path
import subprocess
import sys

from video_processing.core.maintenance_child import child_continuation
from video_processing.db.database import PipelineDB


def test_real_caption_entry_continues_audit_and_rejects_forged_arguments(tmp_path, isolated_running_maintenance):
    script = tmp_path / 'caption_audit_probe.py'
    database = tmp_path / 'audit.db'
    script.write_text('''
import click, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from cli.main import cli
from scripts.run_caption_task import main
from video_processing.core.maintenance import current
from video_processing.db.database import PipelineDB
@cli.command('audit-probe')
@click.argument('database')
def probe(database):
    assert current().key == 'caption-A:0'
    db = PipelineDB(database)
    run = db.start_ai_processing_run('caption-A')
    db.record_ai_provider_attempt(run, provider='fixture', model='none', capabilities='translate',
                                attempt_order=1, status='FAILED', error_class='network')
    db.finish_ai_processing_run(run, status='FAILED', error_class='network')
main()
''')
    cmd = [sys.executable, str(script), 'audit-probe', str(database)]
    control = isolated_running_maintenance
    with control.admit('video', 'caption-A:0') as ticket:
        ticket.start()
        with child_continuation(cmd, {}) as options:
            control.enter('字幕任务在途排空')
            result = subprocess.run(cmd, **options, capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stderr
            forbidden = tmp_path / 'forged.db'
            mismatch = subprocess.run(cmd[:-1] + [str(forbidden)], **options,
                                      capture_output=True, text=True, timeout=30)
            assert mismatch.returncode != 0
            assert 'INVALID_CONTINUATION' in mismatch.stderr
            assert not forbidden.exists()
    runs = PipelineDB(str(database), read_only=True).get_ai_audit_for_video('caption-A')
    assert runs[0]['status'] == 'FAILED' and runs[0]['finished_at']
    assert len(runs[0]['attempts']) == 1
    assert runs[0]['attempts'][0]['error_class'] == 'network'
    denied = subprocess.run(cmd[:-1] + [str(tmp_path / 'new.db')], capture_output=True,
                            text=True, timeout=30)
    assert denied.returncode != 0 and not (tmp_path / 'new.db').exists()
    assert control.status()['phase'] == 'IDLE'
