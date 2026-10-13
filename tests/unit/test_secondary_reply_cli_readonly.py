"""R7：CLI 只读模式在打开任何可写连接之前决策；不建库、不迁移、不写盘。"""
import importlib.util
import sys
from pathlib import Path

import pytest

from video_processing.db.database import PipelineDB

ROOT = Path(__file__).resolve().parents[2]


def _load_cli():
    spec = importlib.util.spec_from_file_location("wechat_secondary_reply_cli", ROOT / "scripts" / "wechat_secondary_reply.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _snapshot(directory: Path):
    return {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in directory.iterdir()}


@pytest.mark.parametrize("flag", ["--dry-run", "--reconcile"])
def test_missing_db_is_refused_and_not_created(tmp_path, monkeypatch, flag):
    cli = _load_cli()
    monkeypatch.setattr(cli, "DEFAULT_DB_PATH", tmp_path / "output" / "pipeline.db")
    monkeypatch.setattr(sys, "argv", ["x", flag])
    assert cli.main() == 2
    assert not (tmp_path / "output").exists()  # 目录与数据库都不得被创建


@pytest.mark.parametrize("flag", ["--dry-run", "--reconcile"])
def test_existing_db_is_not_modified(tmp_path, monkeypatch, flag, capsys):
    db_file = tmp_path / "pipeline.db"
    PipelineDB(str(db_file))
    # 清理 WAL 副产物，保证为已检查点的库
    for suffix in ("-wal", "-shm"):
        f = Path(str(db_file) + suffix)
        if f.exists() and f.stat().st_size == 0:
            f.unlink()
    before = _snapshot(tmp_path)
    cli = _load_cli()
    monkeypatch.setattr(cli, "DEFAULT_DB_PATH", db_file)
    monkeypatch.setattr(sys, "argv", ["x", flag])
    rc = cli.main()
    assert rc in (0, 2)
    assert _snapshot(tmp_path) == before


def test_legacy_invocation_never_sends_even_with_both_flags_on(monkeypatch):
    cli = _load_cli()
    monkeypatch.setattr(cli.settings, "enable_wechat_secondary_reply", True)
    monkeypatch.setattr(cli.settings, "enable_wechat_secondary_reply_live_submission", True)
    monkeypatch.setattr(sys, "argv", ["x"])
    assert cli.main() == 2  # 仅打印用法；真实发送只能经 submit 子命令（见 test_secondary_reply_cli_real_entry）
