"""本地分析门面：一致性只读快照、复用诊断、原子报告与执行失败回执。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 不触发业务、网络与外部消息；用实际代码摘要证明本次运行采用。 |
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from ..db.database import PipelineDB
from ..funnel_diagnosis.service import get_funnel_diagnosis_payload
from .analysis import BJ, build_analysis, digest
from .store import ReviewStore, atomic_json


def implementation_sha() -> str:
    root = Path(__file__).resolve().parents[3]
    names = ["scripts/daily_ops_report.py", "scripts/improvement_review.py",
             "src/video_processing/db/improvement_reporting.py", "src/video_processing/db/database.py",
             "src/video_processing/funnel_diagnosis/service.py", "src/video_processing/funnel_diagnosis/rules.py",
             "src/video_processing/core/runtime_probe.py"]
    names += [str(p.relative_to(root)) for p in Path(__file__).parent.glob("*.py")]
    import hashlib
    return digest({name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sorted(names)})


def collect_analysis(db_path: Path, output: Path, now: datetime) -> dict:
    """WAL 通过 SQLite backup 纳入副本；只在副本创建 read_only 实例。"""
    if now.tzinfo is None:
        raise ValueError("分析截止时间必须带时区")
    today = now.astimezone(BJ).replace(hour=0, minute=0, second=0, microsecond=0)
    since = (today - timedelta(days=7)).astimezone(timezone.utc).isoformat()
    # 精确创建的临时目录只包含本次一致性副本，离开后回收；不读写业务表。
    with tempfile.TemporaryDirectory(prefix=".improvement-snapshot-", dir=output) as directory:
        snapshot = Path(directory) / "pipeline.db"
        PipelineDB.maintenance_backup(db_path, snapshot)
        db = PipelineDB(str(snapshot), read_only=True)
        events = db.get_improvement_failure_events(since, now.astimezone(timezone.utc).isoformat())
        diagnosis = get_funnel_diagnosis_payload(db, output, window="all")
        result = build_analysis(diagnosis, events, now)
        result["source"] = "SQLite read-only consistent backup + existing diagnosis/runtime observations"
        result["snapshot_cutoff_note"] = "数据库为单一一致性副本；运行态为其后的只读观测，非同时刻事务。"
        return result


def run_report(db_path: Path, output: Path, *, refresh: bool = False, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    store = ReviewStore(output / "improvement")
    try:
        with store.locked():
            previous = store.read()
            if not refresh and previous and previous["analysis"]["report_day"] == now.astimezone(BJ).date().isoformat():
                return dict(state="ALREADY_RECORDED", pointer=str(store.root / "current.json"))
            try:
                analysis = collect_analysis(db_path, output, now)
                report = store.merge(analysis, implementation_sha())
                atomic_json(store.root / "last_attempt.json", dict(state="COMPLETE", observed_at=now.isoformat(), report=str(report)))
                return dict(state="COMPLETE", report=str(report), issues=len(analysis["issues"]),
                            implementation_sha=implementation_sha())
            except Exception as exc:
                # 不以空分析覆盖旧成功报告。只记录异常类型，防止凭据进入日志。
                atomic_json(store.root / "last_attempt.json", dict(state="UNAVAILABLE", observed_at=now.isoformat(),
                            error_type=type(exc).__name__, last_valid_at=previous["analysis"]["observed_at"] if previous else None))
                raise
    except BlockingIOError:
        return dict(state="SKIPPED_OVERLAP")
