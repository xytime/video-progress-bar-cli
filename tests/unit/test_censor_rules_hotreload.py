"""审查词库外部化热加载 (🅰️ 进化) 回归测试

锁定 censor_engine v1.8.0 的设计契约：

1. 行为等价：flag 开启 + 由默认词库生成的 JSON ⇔ flag 关闭（硬编码默认），逐字一致。
2. 热加载：编辑外部 JSON（mtime 变化）后，新增/删除的词即时生效，无需重启。
3. 安全底线（绝不静默关闭审查）：
   - 文件缺失   → 回退默认，P0 仍拦截；
   - JSON 损坏  → 回退默认，P0 仍拦截；
   - P0 被清空  → 判非法并回退默认，P0 仍拦截（防误清空政治红线）。
4. flag 关闭时永远用默认，外部文件存在也不读。

# Modification History
| Version | Date       | Author          | Description                                |
|---------|------------|-----------------|--------------------------------------------|
| 1.0.0   | 2026-06-22 | Claude_Opus_4.8 | 初始创建：锁定词库热加载 + 安全回退契约     |
"""

import os
import sys
import copy
import json

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from video_processing import censor_engine
from config.settings import settings


@pytest.fixture(autouse=True)
def _reset_rules_cache():
    """每个用例前后清空模块级缓存，避免跨用例污染。"""
    censor_engine._rules_cache.update(mtime=None, blocklist=None, channel_policy=None)
    yield
    censor_engine._rules_cache.update(mtime=None, blocklist=None, channel_policy=None)


def _default_rules_copy() -> dict:
    """从默认规则取一份深拷贝（经 JSON 往返，绝不污染模块 _DEFAULT_*）。"""
    return json.loads(json.dumps(censor_engine.dump_default_rules()))


def _write_rules(path, data: dict, mtime: float = None):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _point_to(monkeypatch, path, enabled=True):
    monkeypatch.setattr(settings, "enable_external_censor_rules", enabled)
    # censor_rules_path 是 computed_field（类级 property）→ 在类上替换为定值
    monkeypatch.setattr(type(settings), "censor_rules_path", path, raising=False)


# ── 1. 行为等价 ───────────────────────────────────────────────────────────────

def test_flag_off_uses_builtin_defaults(monkeypatch, tmp_path):
    """flag 关闭：即便外部文件存在也走硬编码默认。"""
    _write_rules(tmp_path / "censor_rules.json", _default_rules_copy())
    _point_to(monkeypatch, tmp_path / "censor_rules.json", enabled=False)
    assert censor_engine._load_external_rules()[0] is censor_engine._DEFAULT_BLOCKLIST


def test_external_default_json_matches_builtin(monkeypatch, tmp_path):
    """flag 开启 + 由默认生成的 JSON：拦截行为与默认逐字一致。"""
    p = tmp_path / "censor_rules.json"
    _write_rules(p, _default_rules_copy())
    _point_to(monkeypatch, p)

    # P0 命中（中英双通道）
    assert censor_engine.check_text(en_text="a video about falun gong").hit is True
    assert censor_engine.check_text(zh_text="讨论法轮功的历史").level == "P0"
    # 干净文本放行
    assert censor_engine.check_text(en_text="a laptop review").hit is False


# ── 2. 热加载 ─────────────────────────────────────────────────────────────────

def test_hot_reload_on_mtime_change(monkeypatch, tmp_path):
    p = tmp_path / "censor_rules.json"
    base = _default_rules_copy()

    # v1：新增一个自定义违禁词
    v1 = copy.deepcopy(base)
    v1["blocklist"]["P0"]["en"].append("zzbannedtest")
    _write_rules(p, v1, mtime=1_000_000.0)
    _point_to(monkeypatch, p)
    assert censor_engine.check_text(en_text="here is zzbannedtest word").hit is True

    # v2：移除该词，并推进 mtime → 应即时失效（证明按 mtime 重载）
    _write_rules(p, base, mtime=1_000_100.0)
    assert censor_engine.check_text(en_text="here is zzbannedtest word").hit is False
    # 原有默认词仍然拦截
    assert censor_engine.check_text(en_text="falun gong").hit is True


# ── 3. 安全底线：任何失败都不得静默关闭审查 ─────────────────────────────────────

def test_missing_file_falls_back_to_defaults(monkeypatch, tmp_path):
    _point_to(monkeypatch, tmp_path / "does_not_exist.json")
    assert censor_engine._load_external_rules()[0] is censor_engine._DEFAULT_BLOCKLIST
    assert censor_engine.check_text(en_text="falun gong").hit is True  # P0 仍生效


def test_corrupt_json_falls_back_to_defaults(monkeypatch, tmp_path):
    p = tmp_path / "censor_rules.json"
    p.write_text("{ this is not valid json ", encoding="utf-8")
    _point_to(monkeypatch, p)
    assert censor_engine._load_external_rules()[0] is censor_engine._DEFAULT_BLOCKLIST
    assert censor_engine.check_text(en_text="falun gong").hit is True


def test_empty_p0_is_rejected_and_falls_back(monkeypatch, tmp_path):
    """P0 被（误）清空 → 判文件非法 → 回退默认，政治红线绝不失效。"""
    p = tmp_path / "censor_rules.json"
    bad = _default_rules_copy()
    bad["blocklist"]["P0"]["zh"] = []
    bad["blocklist"]["P0"]["en"] = []
    _write_rules(p, bad)
    _point_to(monkeypatch, p)
    assert censor_engine._load_external_rules()[0] is censor_engine._DEFAULT_BLOCKLIST
    assert censor_engine.check_text(en_text="falun gong").hit is True


def test_validate_accepts_default_dump():
    """dump_default_rules() 自身必须通过校验（防默认结构与校验规则脱节）。"""
    bl, cp = censor_engine._validate_rules(_default_rules_copy())
    assert set(("P0", "P1", "P2")).issubset(bl.keys())
    assert cp["action"] == censor_engine.ACTION_CHANNEL_POLICY
