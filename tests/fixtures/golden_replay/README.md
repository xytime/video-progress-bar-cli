# Golden Replay Dataset (M6.2)

## 1. 宗旨与定位 (Purpose)
本目录保存 `Video-precessing` 核心流水线与发布通道的**离线可执行黄金回放数据集 (Executable Golden Replay Dataset)**。
其目标是在单体 `PipelineDB` 与 `PipelineManager` 重构过程中，提供可离线、无外部副作用、跨执行高度确定（Deterministic）的状态与行为比对基准。

## 2. 核心架构与加载机制 (Loader & Execution Architecture)
- **非二进制持久化**：不存储长期 SQLite 物理 `.db` 二进制文件，避免平台兼容性与不可逆脏状态。
- **声明式初态 (Declarative State)**：每个 Scenario 包含 `initial_db.json`，在隔离测试运行时动态加载注入至全新的临时 SQLite 文件库。
- **环境隔离 (Zero External Side Effects)**：所有测试在沙盒隔离环境中执行，严禁拉起真实浏览器、禁止发起真实外部平台 HTTP/API 请求、禁止向 Telegram 发送通知。

## 3. 版本化体系 (Versioning Specification)
- `dataset_version`: 数据集总版本（语义化版本，随测试集合演进升级，当前 `1.0.0`）。
- `schema_version`: 数据契约规范格式版本（当前 `1.0.0`）。
- `scenario_version`: 单个场景期望定义版本。
- **黄金文件不可篡改原则 (No Auto-Golden Bias)**：
  - 严禁提供任何 `--update-golden` 或自动覆盖脚本。
  - 当生产行为发生非预期改动导致 Replay 失败时，**测试必须报错挂起**，绝不允许自动更新期望来掩盖回归。
  - 若需求变更确需更新期望，必须生成 candidate diff，经过人工逐行安全评审后显式确认。

## 4. 规范化比对规则 (Normalization Rules)
比对执行观察值（Observation）与黄金契约（Contract Expected Observation）时，字段严格遵循四级规则：
1. **`EXACT`**：必须完全字面相等（如 `status`、`publication.state`、`attempts_count`、`folded` 判定）。
2. **`NORMALIZED`**：去除机器/环境易变特征后比对（如 ISO 8601 时间戳正则化为 `<TIMESTAMP>`、临时文件路径标准化为 `<TEMP_PATH>`）。
3. **`IGNORED`**：纯执行耗时或非确定性诊断文本（如 `duration_ms`、内存地址、系统子进程内部 PID）。
4. **`SEMANTIC-MATCH`**：语义结构或布尔状态等价（如 UUID 格式合法性校验、JSON Schema 约束满足）。

## 5. 如何执行回放 (How to Replay)
通过隔离测试运行器执行回放测试：
```bash
# 执行全部黄金回放场景（自动运行 Run A 与 Run B 并执行归一化比对）
.venv/bin/python scripts/run_isolated_tests.py -- -q tests/unit/test_golden_replay_dataset.py
```
