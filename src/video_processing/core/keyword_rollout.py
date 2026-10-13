"""阶段配置采用适配器：只在已排空、已备份的原生 adopt 步骤写非秘密文件。

依赖：deployment_host → 本模块 → config.keyword_rollout / deployment；不访问密钥。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-14 | Codex | 配置与部署日志身份绑定、漂移关闭和维护启动回读 |
"""
from pathlib import Path
import time

from config.keyword_rollout import FIELDS, validate_transition, expected_protections, protection_values
from .deployment import Deployment, require, read_json, write_json


def values(config):
    return {name: getattr(config, name) for name in FIELDS}


def verify_loaded(config, *, complete=False):
    """验证实际加载的配置仍匹配文件、计划及事务日志；返回是否采用了阶段协议。"""
    require(not config._topic_rollout_error, "KEYWORD_PROFILE_INVALID")
    record = config._topic_rollout_record
    if record is None:
        require(not config.topic_rollout_path.exists(), "KEYWORD_PROFILE_DRIFT")
        return False
    require(not config.topic_rollout_path.is_symlink() and read_json(config.topic_rollout_path) == record,
            "KEYWORD_PROFILE_DRIFT")
    after = validate_transition(record["transition"], time.time(), fresh=False)
    require(values(config) == after, "KEYWORD_EFFECTIVE_CONFIG_DRIFT")
    directory = Path(record["directory"])
    require(directory.is_absolute() and not directory.resolve().is_relative_to(config.project_root.resolve()),
            "KEYWORD_RECEIPT_PATH_INVALID")
    plan = read_json(directory / "plan.json")
    require(plan["id"] == record["deployment_id"] and plan["root"] == str(config.project_root)
            and plan.get("keyword_transition") == record["transition"], "KEYWORD_PLAN_IDENTITY_MISMATCH")
    require(protection_values(config) == expected_protections(plan["protections"], record["transition"],
            time.time(), fresh=False), "KEYWORD_PROTECTION_DRIFT")
    journal = Deployment(plan, directory, None).status()
    require("adopt" in journal["done"] or journal["pending"] == "adopt", "KEYWORD_ADOPTION_UNCONFIRMED")
    if complete:
        require(journal["state"] == "COMPLETE", "KEYWORD_DEPLOYMENT_INCOMPLETE")
    return True


class KeywordTransition:
    def __init__(self, plan, directory, config):
        self.plan, self.directory, self.config = plan, Path(directory), config
        self.transition = plan.get("keyword_transition")

    def protections(self, observed, *, after=False, fresh=False):
        expected = self.plan["protections"]
        if after:
            expected = expected_protections(expected, self.transition, time.time(), fresh=fresh)
        require(observed == expected, "PROTECTION_DRIFT")
        if after:
            require(verify_loaded(self.config), "KEYWORD_ADOPTION_UNCONFIRMED")
        else:
            require(self.config.topic_rollout_snapshot() == self.plan["keyword_profile_before"],
                    "KEYWORD_PROFILE_DRIFT")
            verify_loaded(self.config)
        return expected

    def apply(self):
        """调用者负责原生来源/排空/备份检查，本方法额外绑定当前事务位置。"""
        validate_transition(self.transition, time.time(), fresh=True)
        journal = Deployment(self.plan, self.directory, None).status()
        require(journal["pending"] == "adopt" and journal["done"] == ["baseline", "freeze", "stop", "backup"],
                "KEYWORD_ADOPT_ORDER_INVALID")
        from .maintenance import gate
        state = gate().status()
        require(state["state"] == "MAINTENANCE" and not state["active"] and not state["unknown"],
                "KEYWORD_MAINTENANCE_REQUIRED")
        require(self.config.topic_rollout_snapshot() == self.plan["keyword_profile_before"], "KEYWORD_PROFILE_DRIFT")
        verify_loaded(self.config)
        record = dict(transition=self.transition, deployment_id=self.plan["id"], directory=str(self.directory.resolve()))
        write_json(self.directory / "keyword-profile-before.json", self.config._topic_rollout_record)
        write_json(self.config.topic_rollout_path, record)
        self.config.reload_topic_rollout()
        require(verify_loaded(self.config), "KEYWORD_ADOPTION_UNCONFIRMED")
