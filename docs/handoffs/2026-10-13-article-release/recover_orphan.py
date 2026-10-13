"""人工授权的一次性孤儿隔离，维护及调度保持冻结；无自动恢复/重试/发布。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0 | 2026-10-13 | Codex | 绑定维护版本、原部署计划、备份与单项隔离 |
"""
from pathlib import Path
from config.settings import settings
from video_processing.core.deployment import project_lock, read_json, write_json, require, DeploymentDenied
from video_processing.core.deployment_host import HostDeployment
from video_processing.core.maintenance_runtime import inspection
from repair_dal import PipelineDB, TARGET, digest

EXPECTED_VERSION = 9


def require_control(value, active, unknown):
    require(value["state"] == "MAINTENANCE" and value["version"] == EXPECTED_VERSION,
            "MAINTENANCE_VERSION_DRIFT")
    require(not active and not unknown, "ADMISSION_NOT_IDLE")


def recover(directory):
    directory = Path(directory).resolve()
    host = HostDeployment(read_json(directory / "plan.json"), directory)
    database = settings.default_output_dir / "pipeline.db"
    expected = PipelineDB.repair_snapshot(directory / "ledger-inspection.sqlite")
    require(expected is not None, "EXPECTED_RECORD_MISSING")
    receipt = directory / "orphan-recovery.json"
    require(not receipt.exists() and not (directory / "orphan-recovery-intent.json").exists(), "RECOVERY_ALREADY_ATTEMPTED")
    with project_lock(host.lock_path):
        host.sources.baseline()
        host.protections()
        host.schedules.frozen(host.plan["schedules"])
        # 使用原适配器产生当时的真实来源证据，只接受精确的单一账本拒绝。
        try:
            host.safe()
        except DeploymentDenied as exc:
            require(exc.code == "MAINTENANCE_INSPECTION_REJECTED", "UNEXPECTED_INSPECTION_FAILURE")
        seen = inspection(host.control, evidence=directory / "sources.json")
        require(seen["unknown"] == [{"code": "UNFINISHED_LEDGER"}] and not seen["active"], "INSPECTION_NOT_EXACT_ORPHAN")
        require_control(seen, seen["active"], [])
        require(PipelineDB.maintenance_active_work(database) == [{"table": "processed_videos", "count": 1}], "OTHER_ACTIVE_LEDGER")
        backup = directory / "before-orphan-recovery.sqlite"
        proof = PipelineDB.maintenance_backup(database, backup)
        write_json(directory / "before-orphan-recovery-backup.json", proof)
        require(PipelineDB.maintenance_verify_backup(backup, proof), "BACKUP_INVALID")
        require(PipelineDB.repair_snapshot(backup) == expected, "BACKUP_RECORD_DRIFT")
        # 持维护互斥直到事务及回执完成，不能趁恢复切换 RUNNING 或领取新任务。
        with host.control._locked():
            value = host.control._read()
            active, unknown = host.control._leases()
            require_control(value, active, unknown)
            host.sources.baseline()
            host.schedules.frozen(host.plan["schedules"])
            write_json(directory / "orphan-recovery-intent.json", {"target": TARGET, "maintenance_version": EXPECTED_VERSION,
                       "expected_sha256": digest(expected), "backup": proof})
            result = PipelineDB.hold_authorized_orphan(database, expected)
            write_json(receipt, result)
        require(PipelineDB.maintenance_active_work(database) == [], "LEDGER_NOT_IDLE_AFTER")
        checked = host.safe()
        require(checked["safe"], "FINAL_INSPECTION_FAILED")
        return {"recovered": True, "target": TARGET["youtube_id"], "status": result["after"]["status"],
                "publication_review_required": 1, "retry_count": result["after"]["retry_count"],
                "maintenance": checked["state"], "safe": checked["safe"]}


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(recover(args.directory), ensure_ascii=False))
