# 二级回复 M3 单条 canary：可执行命令与唯一阻塞清单

> 2026-10-17：当前裁定以 `docs/secondary-reply-review-20261017.md` 和根目录 `candidate.json` 为准。本文保留操作流程；历史测试数量与平台结论不代表当前版本已可发送。

编制：Antigravity，2026-10-13。状态：**M3 可执行候选，未达 `M3_READY`**（见 §5 唯一阻塞清单）。
本文命令均已有实现并经隔离测试验证；真实平台部分**未经真实验证**。

## 1. 前置配置（仅 M3 窗口内临时设置，默认全部关闭）

环境变量（由 `src/config/settings.py` 声明，示例见 `.env.example`）：

| 变量 | 说明 |
| --- | --- |
| `WECHAT_REPLY_ACCOUNT_KEY` | 业务账号键（隔离防重/配额/对账），必填 |
| `WECHAT_REPLY_AUTHOR_FINDER_ID` | 当前登录作者原生标识；发送守卫要求请求载荷 `_log_finder_id` 与之一致，不一致网络前中止 |
| `WECHAT_REPLY_APPROVER_TELEGRAM_ID` | 本地人工审批身份（显式配置，不推断）；`..._CHAT_ID` 缺省为 `local-cli:<id>` |
| `ENABLE_WECHAT_SECONDARY_REPLY` / `ENABLE_WECHAT_SECONDARY_REPLY_LIVE_SUBMISSION` | 两个开关均默认 false；`submit` 需两者同时为 true |

数据库默认 `output/pipeline.db`（生产库）；演练请加 `--db-path <临时库>`。入口：`PYTHONPATH=src .venv/bin/python scripts/wechat_secondary_reply.py <子命令>`。

## 2. 命令（单条，无批量、无常驻）

```bash
wxreply() { PYTHONPATH=src .venv/bin/python scripts/wechat_secondary_reply.py "$@"; }

# 0) 状态与停用
wxreply status                    # 开关、停止文件、需要平台对账的 SUBMIT_INTENT/UNCERTAIN 任务
wxreply stop                      # 写停止文件：submit 在访问平台前拒绝
wxreply resume                    # 删除停止文件

# 1) 人工撰写文案导入（唯一文案来源：人工；不是自动生成能力）
wxreply import-draft --post-id "<exportId>" --comment-id "<一级评论原生ID>" \
     --comment-text "<该评论原文>" --zh "<中文>" --en "<English>" --style CASUAL_LIGHT
#   经确定性格式 + 政策终审检查，不合格直接拒绝；评论原文作为审批绑定的源评论快照

# 2) 预检（本地只读，不访问平台）：账号/作品/父评论/正文/哈希/审批绑定/配额/阻断项
wxreply preflight --task-id N

# 3) 本地人工审批：回填 preflight 输出 reply_sha256 前 12 位，证明已核对将发送的正文
wxreply approve --task-id N --confirm-reply-sha12 "<前12位>" --ttl-minutes 60
#   绑定：审批人、chat、作品/评论、源评论快照、草稿版本、正文哈希、有效期；一次性 token 原子消费

# 4) 单条提交（真实发送；仅在获得具体授权的窗口内）
ENABLE_WECHAT_SECONDARY_REPLY=true ENABLE_WECHAT_SECONDARY_REPLY_LIVE_SUBMISSION=true \
  wxreply submit --task-id N --video-title "<仅导航提示>" --evidence-dir "<证据目录>"
#   终审 → 作者回复复核 → 配额+持久意图（同事务） → 守卫放行唯一出站 → 全新会话回读 → 凭据 JSON + 刷新后截图

# 5) 平台对账（只读访问真实平台；SUBMIT_INTENT/UNCERTAIN 重启后只能走这里，submit 会 NOT_CLAIMABLE）
wxreply reconcile-platform --task-id N --confirm-readonly-platform-access
#   本地列表检视（不是平台对账）：wxreply --reconcile
```

## 3. 已验证的内容与证据层级

| 层级 | 内容 | 状态 |
| --- | --- | --- |
| 隔离测试 | CLI 子命令→统一编排→平台替身：导入/预检/审批/提交/重复提交/开关与停止/平台对账/不重发 | 通过（`test_secondary_reply_cli_real_entry.py`） |
| 隔离 Chromium | 实际 CLI→统一编排→浏览器端口→夹具网络：导入→审批→提交→全新会话回读→凭据 | 通过（`test_secondary_reply_orchestrated_browser.py::test_cli_entry_single_item_through_browser_port`） |
| 真实只读验证 | 无。仅有历史回执证明 `create_comment` 端点载荷含 `_log_finder_id`、返回新 `commentId`、`rootCommentId`/`replyCommentId` 等于目标一级评论 ID | **未做新的真实只读验证** |
| 人工评审 | 材料已导出：`secondary_reply_human_review_sheet.md`（结论列为空） | **待人评** |
| 真实发送 / 公众可见 | 无 | **未发生** |

## 4. 单条 canary 操作方案（待授权，当前不执行）

1. 你提供：作品 exportId、目标一级评论 ID 与原文、人工撰写的中英文案、执行窗口、`finder_id`、账号键。
2. 先做只读样本采集（§5-1）并据此校准适配器；校准前不得提交。
3. `import-draft` → `preflight` → 你核对输出并 `approve`（回填哈希）→ `preflight` 确认 `ok=true`。
4. 临时打开两个开关，执行 `submit`，立刻关闭开关（或 `stop`）。
5. 你在管理端与手机端核对：回复在正确父评论下、作者为本账号、文案一致；将结论记入凭据备注。
6. 出现 `UNCERTAIN`/守卫拦截/限流提示：停止，只做 `reconcile-platform`，不重发，不扩大。

成功判据：平台业务成功回执 + 全新会话回读同作者同文 + 凭据与刷新后截图已保存 + 人工核对一致。

## 5. 当前剩余交付阻断（2026-10-13 Codex 接手核查）

唯一未关闭项为真实平台适配及只读证据。用户已授权只读验证，无需再次索取同一授权；本轮宿主 Browser Use 站点安全策略拒绝访问视频号页面，并明确禁止通过其他浏览器、原始 CDP 或脚本绕过。这是访问边界，不是平台验证失败，也不能记为验证通过。

恢复合规访问后，在同一次验证中完成：

1. 使用既有登录态和会话锁，只读确认当前作者原生身份及业务账号绑定；不输出 Cookie、Token 或认证存储。
2. 对一个作品核对原生作品 ID、一级评论 ID 与原文；验证真实 DOM/API 对应关系。不得以数组位置或同名同文替代原生身份。
3. 验证含作者二级回复的样本与折叠、分页完整性；未穷尽时返回 UNKNOWN，不得据此判断作者尚未回复。
4. 以脱敏字段结构校准适配器，补入合成夹具回归，再用全新只读会话验证；记录时间、代码提交、样本范围、证据路径和限制。
5. 上述均通过后，准备单条试运行的具体账号、作品、父评论和回复正文，由用户确认真实发送；保持默认开关关闭。

已关闭的两个代码项：本地 preflight/status 使用只读数据库连接；本地审批在入口、绑定及消费事务内校验当前账号。见 `test_secondary_reply_m3_blockers.py`。

本地人工审批和人工文案导入已是本阶段认可的单条路径；Telegram 真实传输、自动文案生成和批量人评不增加为本次单条试运行的交付阻断。具体试运行正文仍须人工确认。
