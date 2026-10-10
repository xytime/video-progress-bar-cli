# 视频号原生 ID 回查工单

状态：待后续专项处理（当前不阻塞投递）

## 当前约定

- 上传器跳转作品列表或获得提交受理信号后，立即写入本地 `wechat_publications` 账本并将任务置为 `SUBMITTED_UNBOUND`。
- `SUBMITTED_UNBOUND` 是终态：禁止通用重试、自动补发、删除或重置为待处理。
- 运营界面将其展示为“本地已受理”，而不是“已公开发布”。
- `WECHAT_REVIEW_MAX_PER_RUN=0` 保持关闭；当前不按标题、时间或其他弱特征去匹配视频号后台原生 ID。

## 未来工单验收条件

只有在能证明一对一匹配时才允许启用后台回查，至少需要同次提交捕获的原生 `post_id` 或平台返回的稳定标识。标题、封面、发布时间和列表排序均不可单独作为绑定依据。任何回查失败或歧义必须保留 `SUBMITTED_UNBOUND`，绝不可触发重传。

## 2026-10-03 收尾调查

- 补发和正常自动投稿已经恢复，封面完整 RGBA 精确回读在真实页面差异为 0；不是所有发布阶段都被本工单阻塞。
- 已修复管理页原生组件读取：可见 `.post-feed-item` 的 `post.objectId` 与同卡片 `.bandage-list` 独立状态绑定；唯一 `exportId` 直接关联也可回查。新版 `shortTitle` 列表仅接受唯一项。97 项隔离单元及真实 Chromium 回归通过。
- `SfNypZIb0H4` 的原提交回执 ID 为 `export/UzFfBgAAxO-lfHlhXUmlk8zT4DCaL-2Komfbo4GS1TJIRtQfqg`；最新后台记录 `objectId` 与 `exportId` 都为 `export/UzFfBgAAxNGkdDpUKEmlk8zT4DCaZKs-TJguejpjnSjnqGCZvw`。两次后台重读 ID 一致，但没有平台证据将原回执 ID 直接关联到新 ID。
- 页面对应内容的审核标签已经消失；这不是原回执 ID 的严格公开证明。账本继续保留 `SUBMITTED_BOUND`，不改为 `PUBLISHED`，不重传。
- `WECHAT_REVIEW_MAX_PER_RUN=0` 继续保持关闭。后续须取得跨场景稳定标识或按原 ID 请求得到的平台直接关联，再校准明确的公开状态；不得以数字状态 1、播放量、完整文案或截图替代该身份契约。
- 证据：`output/wechat_evidence/SfNypZIb0H4/closure_export_fields/management_identity_snapshot_0.json`、`management_identity_snapshot_1.json`、`management_uncertain.png`；测试证据 `/private/tmp/video-pytest-6mxjq_x0`。

## 2026-10-10 华尔街具名恢复与后续回执

新提交回执开始保留同次提交已绑定作品的原生 `objectNonce`。跨会话 ID 变化时，只有原回执的原 ID 匹配且 nonce 在当前后台唯一精确命中，才允许保持原身份继续只读回查；无 nonce 的历史记录仍不自动匹配。

退休金 `r9-_2YJMhmQ` 的旧回执没有 nonce。用户核对完整原生预览 `https://weixin.qq.com/sph/AGEsKHYqO` 后确认是原普通版；独立后台精确回查当前原生 ID 确认为公开。此具名人工恢复原子更新两本账的当前 ID，保留原回执及独立新旧 ID 审计，不提高历史回查开关、不发第二份普通版。证据位于 `output/wallstreet_ab/recovery-r9-20261010/confirmed-native-a/`。

平台时间仅在同原生 ID 的已发表 DOM 日期与原生 `createTime` 一致时采用。跨会话身份与公开状态是两道独立门槛；数字状态值、播放量与相似文案仍不单独证明公开或归属。
