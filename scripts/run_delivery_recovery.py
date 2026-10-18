"""消费具名恢复队列；每次最多领取一项，退避等待交由持久账本与巡检。"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from video_processing.core.maintenance import guarded
from video_processing.core.maintenance_child import single_script, run_admitted
from video_processing.core.task_lease import TaskLease, TaskLeaseBusy
from video_processing.db.database import PipelineDB
from video_processing.delivery_recovery import DeliveryRecoveryService, file_fingerprint, notice
from video_processing.telegram_delivery import send_text
from video_processing.utils.retry_policy import backoff_seconds
from video_processing.utils.production_recovery import recovery_arguments, read_outcome
from video_processing.utils.subprocess_env import build_subprocess_env


@guarded("delivery-recovery")
def execute(db):
    row = db.claim_delivery_recovery()
    if not row:
        return 0
    service = DeliveryRecoveryService(db, ROOT)
    rid = row["id"]
    # 通知失败不得让已领取的恢复动作失去结果记录。
    try:
        view = service.view(rid)
        send_text(event_type="recovery.started", priority="P1", cooldown_seconds=0,
                  text=notice(view), db=db, reply_markup=view["reply_markup"])
    except Exception:
        pass
    delay = None
    try:
        payload = json.loads(row["payload_json"])
        if row["kind"] != "EW_PRODUCTION" or not payload.get("allow_retry"):
            raise ValueError("任务不允许自动生产或重传")
        item = payload["request"]
        if file_fingerprint(Path(item["path"])) != item:
            raise ValueError("原失败记录已变化，需人工核验")
        if json.loads(Path(item["path"]).read_text()).get("kind") != "failure":
            raise ValueError("已有交付产物，禁止重做")
        context = payload["production_context"]
        if file_fingerprint(Path(context["path"])) != context:
            raise ValueError("原制作配置已变化，需重新核验")
        arguments = recovery_arguments(Path(context["path"]), ROOT)
        log_path = ROOT / "output" / f"recovery_{rid}_{row['attempts']}.log"
        status_path = log_path.with_suffix(".status.txt")
        with log_path.open("w") as log:
            result = run_admitted([
                str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/run_english_world_daily.py"),
                *arguments,
                "--max-attempts", "1", "--recovery-parent-id", rid,
                "--recovery-status-path", str(status_path),
            ], cwd=ROOT, env=build_subprocess_env(), stdout=log, stderr=log,
                timeout=3 * 60 * 60, check=False)
        message, retryable = read_outcome(status_path, ROOT, result.returncode)
        if retryable:
            # 自动入队已等待第一个区间；执行失败后的下一间隔继续翻倍。
            delay = backoff_seconds(row["attempts"] + 1)
    except Exception as exc:
        message = f"执行中断，需核验已有阶段记录：{type(exc).__name__}: {exc}"
    db.finish_delivery_recovery(rid, result=message, retry_delay=delay)
    view = service.view(rid)
    send_text(event_type="recovery.result", priority="P1", cooldown_seconds=0,
              text=notice(view), db=db, reply_markup=view["reply_markup"])
    return 0


@single_script
def main():
    try:
        with TaskLease(ROOT / "output/delivery_recovery_worker.lock", stage="具名恢复执行者"):
            return execute(PipelineDB())
    except TaskLeaseBusy:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
