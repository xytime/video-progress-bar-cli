---
created_by: Claude_Sonnet_4.6_Thinking_planning
created_at: 2026-05-21T17:05:00+08:00
---

# Version History

| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 初始创建项目工程宪法 |
| 1.1.0 | 2026-07-27 | Codex | 将平台发布前内容审查提升为第一原则，覆盖新发、补发、迁移和重试 |

---

# CONTRIBUTING — 工程宪法

> **地基必须牢固。** 本文档是项目唯一的工程规范来源。所有贡献者（包括 AI）必须遵守。

---

## 核心原则

### 1. 平台发布前内容审查优先

**任何平台发布动作之前，必须先通过统一内容审查闸门。**

适用范围包括但不限于：

- 新片同步发布
- 历史补发 / 历史迁移
- 登录恢复后的重试
- `UNDER_REVIEW` 之外任何可能重新触发上传或提交的任务
- 未来新增的视频平台

硬性规则：

- 调用浏览器上传器执行公开提交之前，必须先复跑内容安全审查。
- 审查输入必须覆盖该平台实际投递的标题、文案，以及开启字幕审查时的字幕正文。
- 审查命中时必须 fail-closed：取消或挂起平台任务，禁止调用上传器，禁止自动切换下一条不确定任务。
- 只读审核回查只能使用 `--verify-only`，不得带 `--publish` 或视频文件。
- 新增平台或新增补发入口时，必须有单测证明“审查命中时 uploader 没有被调用”。

如果你发现某个补发、迁移、重试或新平台入口能绕过上传前审查，**停下来，先修这个问题。**

---

### 2. 架构依赖图优先

**在编写任何新模块之前，必须先画出它的依赖关系。**

- 依赖关系必须是**单向的（DAG）**，严禁循环依赖
- 核心领域层（`db/`、`core/`）不得反向依赖外层模块（`scripts/`、`cli/`）
- 依赖方向只允许：`scripts/cli` → `pipeline_manager` → `db/processors/utils` → `config`

```
scripts/ cli/
    ↓
pipeline_manager.py
    ↓
db/ processors/ core/ utils/
    ↓
config/settings.py
```

如果你发现需要在 `db/` 里 `import` 任何来自 `scripts/` 或 `cli/` 的东西，**停下来，重新设计。**

---

### 3. 配置单一真相来源（Single Source of Truth）

**所有环境变量必须且只能在 `src/config/settings.py` 中声明。**

```python
# ✅ 正确：通过全局 settings 单例读取
from config.settings import settings
api_key = settings.gemini_api_key

# ❌ 违规：在业务模块中直接读取环境变量
api_key = os.getenv("GEMINI_API_KEY")
api_key = os.environ.get("GEMINI_API_KEY")
```

新增环境变量时的流程：
1. 在 `settings.py` 中声明带类型注解的字段
2. 在 `.env.example` 中添加对应的示例键
3. 业务模块通过 `settings.xxx` 访问

---

### 4. 数据访问层封装（DAL Encapsulation）

**所有 SQL 操作必须封装在 `PipelineDB` 的方法内。**

```python
# ✅ 正确：调用 DAL 方法
self.db.update_video_score(youtube_id, score)
targets = self.db.get_high_score_pending_videos(min_score=75)

# ❌ 违规：在业务模块中打开连接执行裸 SQL
with self.db.get_connection() as conn:
    conn.execute("UPDATE processed_videos SET score = ? ...", ...)
```

新增数据操作时的流程：
1. 在 `database.py` 的 `PipelineDB` 类中新增方法
2. 方法必须有完整的类型注解和 docstring
3. 调用方只能使用方法，不得直接访问数据库连接

---

### 5. 测试耦合度红线（Mock Gate）

**如果为一个模块写测试需要 Mock 超过 3 个外部对象，必须停止并重新设计该模块。**

这不是建议，而是物理事实：**难以测试的代码 = 高耦合的代码。**

```python
# 🚨 触发红线：需要 Mock 4+ 个对象
def test_process_video():
    mock_db = Mock()          # 1
    mock_requests = Mock()    # 2
    mock_subprocess = Mock()  # 3
    mock_gemini = Mock()      # 4  ← 超出限制，重新设计！
```

解决方案：引入应用服务层（Application Service Layer）或门面模式（Facade Pattern），将依赖注入点减少到 ≤ 3 个。

---

### 6. 修改历史追踪

**新建文件或重大修改（≥10 行逻辑改动）时，必须在文件 docstring 中维护 Modification History 表。**

```python
"""模块描述

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | YYYY-MM-DD | Model_Name | 初始创建 |
| 1.1.0 | YYYY-MM-DD | Model_Name | 功能描述 |
"""
```

---

## 不属于本宪法的内容

本文档**不强制要求**以下内容，这些属于个人或 AI 的风格自由：

- 具体的代码格式（留给 `ruff` / `black` 处理）
- 注释的语言（中文或英文均可）
- 函数的长短（只要不违反上述原则）

---

## 违规处理

发现违规代码时的处理方式：

1. **平台发布绕过上传前审查** → 立即停止发布能力并修复，不允许合并
2. **配置泄漏** (`os.getenv` 在非 `settings.py` 的文件中) → 立即修复，列入 PR 阻断条件
3. **SQL 泄漏** (在 `PipelineDB` 外直接调用 `get_connection()`) → 立即修复
4. **循环依赖** → 立即修复，不允许合并
5. **Mock 超限** → 在 PR review 中标记为 Architecture Concern，但允许合并（附改进 Issue）
