"""本次生词修复上线的单项状态对账，仍保持维护与来源冻结。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0 | 2026-10-17 | Codex | 绑定部署、维护版本、源代码、媒体和已受理回执后准确收尾 |
"""
from pathlib import Path
import hashlib
import json

from config.settings import settings
from video_processing.core.deployment import project_lock, read_json, write_json, require, DeploymentDenied
from video_processing.core.deployment_host import HostDeployment
from video_processing.core.maintenance_runtime import inspection
from reconcile_dal import PipelineDB, TARGET, PUBLICATION, digest

DEPLOYMENT_ID = "5f5ada3a0f2a4b829716c3f93a11122a"
EXPECTED_VERSION = 65
PACKAGE = Path('/Users/ryusei/.codex/worktrees/cb0e/Video-precessing/output/baiju_guoxi/investment-legends-video/publish_20261017_v1')


def require_control(value, active, unknown):
    require(value["state"] == "MAINTENANCE" and value["version"] == EXPECTED_VERSION,
            "MAINTENANCE_VERSION_DRIFT")
    require(not active and not unknown, "ADMISSION_NOT_IDLE")


def execution_evidence():
    path = PACKAGE / "douyin_execution_result.json"
    value = read_json(path)
    require(value.get("local_id") == TARGET["youtube_id"] and value.get("publication_id") == PUBLICATION["id"]
            and value.get("exit_code") == 6 and value.get("state") == "UNDER_REVIEW"
            and value.get("video_sha256") == PUBLICATION["asset_sha256"], "EXECUTION_EVIDENCE_MISMATCH")
    media = PACKAGE.parent / "renders/investment-legends.mp4"
    require(hashlib.sha256(media.read_bytes()).hexdigest() == PUBLICATION["asset_sha256"], "MEDIA_HASH_CHANGED")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "result": value,
            "media": str(media), "media_sha256": PUBLICATION["asset_sha256"]}


def recover(directory):
    directory = Path(directory).resolve()
    host = HostDeployment(read_json(directory / "plan.json"), directory)
    require(host.plan["id"] == DEPLOYMENT_ID, "WRONG_DEPLOYMENT")
    database = settings.default_output_dir / "pipeline.db"
    receipt = directory / "submission-reconciliation.json"
    intent = directory / "submission-reconciliation-intent.json"
    require(not receipt.exists() and not intent.exists(), "RECONCILIATION_ALREADY_ATTEMPTED")
    with project_lock(host.lock_path):
        host.sources.baseline()
        host.protections()
        host.schedules.frozen(host.plan["schedules"])
        try:
            host.safe()
        except DeploymentDenied as exc:
            require(exc.code == "MAINTENANCE_INSPECTION_REJECTED", "UNEXPECTED_INSPECTION_FAILURE")
        seen = inspection(host.control, evidence=directory / "sources.json")
        require(seen["unknown"] == [{"code": "UNFINISHED_LEDGER"}] and not seen["active"], "INSPECTION_NOT_EXACT_LEDGER")
        require_control(seen, seen["active"], [])
        require(PipelineDB.maintenance_active_work(database) == [{"table": "processed_videos", "count": 1}], "OTHER_ACTIVE_LEDGER")
        evidence = execution_evidence()
        backup = directory / "before-submission-reconciliation.sqlite"
        proof = PipelineDB.maintenance_backup(database, backup)
        write_json(directory / "before-submission-reconciliation-backup.json", proof)
        require(PipelineDB.verify_backup(backup, proof), "BACKUP_INVALID")
        expected = PipelineDB.snapshot(backup)
        require(expected["publication"]["video_path"] == evidence["media"], "UPLOADED_MEDIA_PATH_MISMATCH")
        with host.control._locked():
            value = host.control._read()
            active, unknown = host.control._leases()
            require_control(value, active, unknown)
            host.sources.baseline()
            host.protections()
            host.schedules.frozen(host.plan["schedules"])
            require(execution_evidence() == evidence, "EXECUTION_EVIDENCE_DRIFT")
            write_json(intent, {"deployment": DEPLOYMENT_ID, "maintenance_version": EXPECTED_VERSION,
                               "target": TARGET, "publication": PUBLICATION, "expected_sha256": digest(expected),
                               "backup": proof, "evidence": evidence})
            result = PipelineDB.reconcile(database, expected)
            write_json(receipt, result)
        require(PipelineDB.maintenance_active_work(database) == [], "LEDGER_NOT_IDLE_AFTER")
        checked = host.safe()
        require(checked["safe"], "FINAL_INSPECTION_FAILED")
        return {"reconciled": True, "target": TARGET["youtube_id"], "status": result["after"]["video"]["status"],
                "maintenance": checked["state"], "safe": checked["safe"], "uploaded": False}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(recover(args.directory), ensure_ascii=False))
