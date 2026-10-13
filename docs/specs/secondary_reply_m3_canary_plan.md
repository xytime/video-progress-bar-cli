# 二级回复 M3 单条 canary：可执行命令与唯一阻塞清单

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
CLI="PYTHONPATH=src .venv/bin/python scripts/wechat_secondary_reply.py"

# 0) 状态与停用
$CLI status                    # 开关、停止文件、需要平台对账的 SUBMIT_INTENT/UNCERTAIN 任务
$CLI stop                      # 写停止文件：submit 在访问平台前拒绝
$CLI resume                    # 删除停止文件

# 1) 人工撰写文案导入（唯一文案来源：人工；不是自动生成能力）
$CLI import-draft --post-id "<exportId>" --comment-id "<一级评论原生ID>" \
     --comment-text "<该评论原文>" --zh "<中文>" --en "<English>" [--style CASUAL]
#   经确定性格式 + 政策终审检查，不合格直接拒绝；评论原文作为审批绑定的源评论快照

# 2) 预检（本地只读，不访问平台）：账号/作品/父评论/正文/哈希/审批绑定/配额/阻断项
$CLI preflight --task-id N

# 3) 本地人工审批：回填 preflight 输出 reply_sha256 前 12 位，证明已核对将发送的正文
$CLI approve --task-id N --confirm-reply-sha12 <前12位> [--ttl-minutes 60]
#   绑定：审批人、chat、作品/评论、源评论快照、草稿版本、正文哈希、有效期；一次性 token 原子消费

# 4) 单条提交（真实发送；仅在获得具体授权的窗口内）
ENABLE_WECHAT_SECONDARY_REPLY=true ENABLE_WECHAT_SECONDARY_REPLY_LIVE_SUBMISSION=true \
  $CLI submit --task-id N --video-title "<仅导航提示>" [--evidence-dir DIR]
#   终审 → 作者回复复核 → 配额+持久意图（同事务） → 守卫放行唯一出站 → 全新会话回读 → 凭据 JSON + 刷新后截图

# 5) 平台对账（只读访问真实平台；SUBMIT_INTENT/UNCERTAIN 重启后只能走这里，submit 会 NOT_CLAIMABLE）
$CLI reconcile-platform --task-id N --confirm-readonly-platform-access
#   本地列表检视（不是平台对账）：$CLI --reconcile
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

## 5. 唯一集中阻塞清单（缺任一即不得标 M3_READY）

1. **真实页面/接口样本缺失（需新增只读授权）**：适配器的页面选择器（作品详情区的作品标识、`data-comment-id`、`data-author-id`、二级回复容器、折叠/分页）均来自夹具；真实微信页面是否具备这些标识未知，适配器在缺失时失败关闭，因此真实页面上当前走不通。二级回复分页与完整性判断同样没有含二级回复的真实分页样本。
   - **权限需求（一次性）**：授权使用已有登录态，只读打开评论管理页，对 1 个指定作品导出脱敏 DOM 结构摘要与 `comment_list` 接口响应（仅字段结构与合成化 ID，不含 Cookie/Token/头像/他人昵称原文）；动作：只读导航与展开评论，不点击回复/提交；预期证据：`data-*`/类名结构表、含二级回复与分页字段的脱敏 JSON。
2. **`account_key` 与 `finder_id` 的可信绑定**：目前为配置声明 + 发送载荷 `_log_finder_id` 一致性校验（来自真实会话）；尚无只读读取“当前登录作者原生标识”的实现与样本验证（可合并进 1 的只读采集）。
3. **本地人工审批的操作者身份**由本机运行者与配置共同声明，未做独立身份验证；若要求 Telegram 审批，真实传输未实现（仅 fake）。本候选选择本地人工审批满足“绑定”，不宣称 Telegram 就绪。
4. **文案来源**：人工撰写导入路径可用；自动生成未交付，规则 provider 仍仅限 fixture，真实 provider 无工具/凭据隔离证明。
5. **人评结论**：材料已备，结论未填。
