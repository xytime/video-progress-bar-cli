# 视频号二级回复 (Author Secondary Reply) M0-M2 规格补丁与边界表

## 1. 范围与默认选择
- **人工审批版**: 仅 PUBLISHED 且原生作品 ID (`export_id` / `objectId`) 唯一绑定的一级观众评论进行一次作者二级回复。
- **不递归、不自动置顶、不处理历史未知任务、不执行点赞/删除/举报/拉黑**。
- **长度方案 A**:
  - 中文 <= 75 Unicode 码点 (NFC)
  - 英文 <= 150 Unicode 码点 (NFC)
  - 合并 (`zh\nen`) <= 230 Unicode 码点 (NFC)
  - 无最小字数限制
  - 两个非空字段间恰好一个换行 `\n`，字段内无换行，无标签、无 Emoji、无分隔线
  - 非法控制字符直接拒绝并报告，不默默改变获批正文
- **意图与风格**:
  - 意图：`REPLY`（建议回复）、`SKIP`（忽略/无需回复）、`MANUAL`（需人工接管处理）
  - 风格偏好：`MACRO` (宏观视角), `PHILOSOPHICAL` (哲理思辨), `HUMOROUS` (幽默互动), `PRAGMATIC` (务实严谨)
- **Telegram 审批**:
  - 单一显式配置审批人及私聊目标 (`wechat_reply_approver_telegram_id`, `wechat_reply_approver_chat_id`)
  - 审批人必须在 `telegram_admin_ids` 白名单内；未配置则保持 PENDING_REVIEW，不广播、不暗中回退“第一管理员”
  - 服务端随机 Token 绑定，一次性消费，防止重放与篡改
- **运营配额与时段**:
  - 账号滚动 60 分钟上限 10 条（首评与二级回复共计）
  - 单视频累计最多 3 条系统作者二级回复（首评不计入这 3 条，且永不在午夜重置）
  - 上海本地时间 08:30 <= time < 23:00 允许真实提交，数据库存 UTC
  - 最小提交间隔 15 秒（可配置运营预算）

## 2. 观察支持与未知平台路径表 (Fail-Closed Matrix)

| 场景 / 结构 | 历史观察样本事实 | 系统行为与处理策略 | 状态 / 结果 |
|---|---|---|---|
| 一级评论列表单页 (`comment/comment_list`) | 观察到 `comment[]`, `commentCount`, `downContinueFlag=0` | 正常解析一级观众评论与首评 | SUPPORTED |
| 一级评论分页 (`downContinueFlag=1`) | 仅观察到 `downContinueFlag=0`，未观察到真实翻页请求参数契约 | 支持标记有更多，但未验证分页契约前不自动深翻；仅处理当前页已确认评论 | SAFE_PARTIAL |
| 一级观众评论二级回复列表为空 (`levelTwoComment: []`) | 观察到 5 条样本中 4 条为空，1 条已有观众二级回复 | 认定该一级评论尚未有作者二级回复（需进一步核对） | SUPPORTED |
| 一级评论已有观众二级回复 (`levelTwoComment` 非空，无作者) | 观察到 jia 评论下有 Dinah9105 观众回复 | 允许作者对该一级评论回复 (`replyCommentId = rootCommentId`) | SUPPORTED |
| 一级评论已有作者二级回复 (`levelTwoComment` 中含作者 username) | 微信回执与平台回读表明作者回复在 `levelTwoComment` | 识别为 AUTHOR_ALREADY_REPLIED，跳过生成或标记已回复 | SUPPORTED |
| 二级回复折叠/分页 (`levelTwoComment` 分页或 continuation) | 历史样本中 `levelTwoComment` 均为完整列表或空，未观察到二级分页 | 若发现未知折叠/分页标记且无法排除作者回复，返回 INCOMPLETE/UNSUPPORTED，拒绝提交 | FAIL_CLOSED |
| 二级回复提交端点 (`comment/create_comment`) | 观察到 3 条 201 成功回执，参数含 `exportId`, `rootCommentId`, `replyCommentId`, `content`, `_log_finder_id` | 严格按观察到的白名单结构构造请求 | SUPPORTED |
| 跨作品 / 错误 exportId 提交 | 错误作品卡片或 exportId 不匹配 | 网络发送前由 Request Guard 强校验拦截，硬熔断 | FAIL_CLOSED (BLOCKED) |
| 错 rootCommentId / replyCommentId | 目标 ID 与正在回复的 DOM/数据不一致 | 网络发送前拦截并标记 FAILED | FAIL_CLOSED (BLOCKED) |
| 提交后无响应 / 崩溃 / 页面假死 | 历史未观察，可能由于网络中断 | 提交意图 (SUBMIT_INTENT) 已落盘，转入 UNCERTAIN，仅允许只读对账，严禁重发 | SAFE_RECONCILE |
| 重名观众同内容不同 ID | 评论区存在两个同名用户发布相同内容 | 必须严格依赖原生 `commentId` 绑定，DOM 若无法确定原生 ID 则拒绝点击 | FAIL_CLOSED (REFUSE_AMBIGUOUS) |
