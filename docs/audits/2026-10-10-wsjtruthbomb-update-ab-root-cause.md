# Wall Street Truthbombs 更新与 A/B 生产断流调查

调查日期：2026-10-10，Asia/Shanghai。作者：Codex（具体模型身份未知）。

范围：只读检查实际主目录调度、日志、数据库、心跳与已有平台回执；离线内存复现。没有修改运行配置、生产数据库，没有触发制作、投稿、互动或消息发送。

## 结论

频道发现和普通制作仍在运行。无法持续观察 A/B 来自三个相互独立的缺口：

1. AI 封面完成路径绕过实验入队，是新视频没有对应 B 的直接代码根因。
2. 普通视频号作品精确回查保持关闭，已提交记录不能自动收敛为公开或拒绝；看板呈现停更，且后续配对的 A 公开确认依赖仍需验证。
3. 实验指标只支持原生 ID 绑定的人工导入，没有自动采集；当前既没有完整配对，也没有指标快照。

不能据此认定所有已提交作品仍在审核，或已经公开。平台实际当前公开状态未在本次另行实时核查。

## 当前运行证据

实际生产目录为 `/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing`，本聊天目录为独立 detached worktree。

- 安装的 cron 每 30 分钟启动频道监控，核心频道内部按每小时轮询；每分钟启动既有发布巡航。
- `output/monitor_health.json` 在 13:30:43 记录目标频道 `UCTK_cv-y88CScoudcXnS1Ew` 状态 `ok`。最近一轮刷新退休金、车贷、私人信贷三个视频，并非监控停摆。
- `r9-_2YJMhmQ`（BURNING THE SEED CORN）已发现、评分 80、完成字幕/渲染/封面，10 月 10 日 05:03 取得视频号原生提交 ID。提交后截图中目标卡片仍为“处理中”；这只是提交时证据。
- 对应原生 ID：`export/UzFfBgAAxKCmXAlgdxWtk8zT4DCaLhgfDyyCOEf4ggSuXhFPyA`。
- 证据：`output/wechat_evidence/r9-_2YJMhmQ/1791579689259352000/submission_receipt.json`、`post_list_after_submission.png`，以及 `output/ready_publications.log` 05:01–05:03 的上传日志。
- 二创执行者是按需短进程，心跳采用 `d32eb028a2ac02500402de4230b97b7ae416f0e7`，实验 ACTIVE，外部策划授权 true。进程列表瞬时看不到短进程不能证明执行者失效。
- 常驻普通发布执行者 PID 33886 采用 `c77dbeda7e2ff23eab07babf9ee04f305f86e192`，心跳 IDLE；其版本早于当前主干，需在后续修复采用验收时核对重载。

## 根因一：封面异步完成漏掉配对登记

正常加工结束通过 `PipelineManager._mark_ready_and_enqueue_wallstreet()` 将 A 就绪与 B 纳入持久队列。

但当前运行启用了 AI 封面异步队列：

1. `_prepare_single_video()` 创建封面任务，写 `AI_COVER_PENDING` 后提前返回。
2. `scripts/reconcile_ai_cover_queue.py:258` 完成封面后只调用 `db.mark_ai_cover_resolved()` 并唤醒普通发布执行者。
3. `src/video_processing/db/database.py:3495` 的方法只将任务改为 `PENDING / preparation_ready=1`，没有调用实验登记。
4. 普通发布执行者调用 `_process_single_video(..., submission_only=True)`；该路径进入 `_submit_ready_video()`，不再经过加工结束的实验登记方法。
5. A 已经提交之后，`enroll_wallstreet_video()` 的既有投稿保护又禁止普通自动纳入，因此后续常规运行不能自行补回漏掉的配对。

实际新视频 `r9-_2YJMhmQ` 的就绪时间晚于实验激活时间，但实验账本没有它。当前只存在 `h7rY4nSB2tM` 的一条 `B_ONLY`，没有任何 `PAIRED`。

离线复现直接使用维护代码中的 `mark_ai_cover_resolved()` 与 `WallstreetExperimentDAL`，复制真实视频属性及表结构到内存；模拟提交前 `AI_COVER_PENDING`，生产数据库以 `mode=ro` 打开：

```json
{
  "cover_resolved": true,
  "pair_count_after_actual_cover_resolution": 0,
  "eligible_if_enrollment_called": true,
  "pair_count_after_explicit_enrollment": 1,
  "version_publication_count": 4
}
```

复现输出保存在 `/private/tmp/wsjtruthbomb-rca-reproduction-20261010.json`。这是调用路径复现，不代表完成生产修复或平台配对验收。

## 根因二：公开状态回查关闭，停更与未确认混在一起

运行日志明确输出 `视频号精确回查已关闭（WECHAT_REVIEW_MAX_PER_RUN=0）`；`reconcile_wechat_under_review()` 直接返回。

这是历史原生 ID 身份校准问题后的保护措施，见 `docs/publication-gap-2026-09-24.md` 与 `docs/workorders/wechat-native-id-reconciliation.md`，不能简单打开开关并把历史提交全部标为公开。

数据库观察：

- 普通目标频道最新 `PUBLISHED` 对应源日期 2026-09-20。
- 9 月以来目标频道普通微信账本：26 条 PUBLISHED、18 条 SUBMITTED_BOUND、3 条 SUBMITTED_UNBOUND、1 条 UNCERTAIN。
- 10 月 7 日私人信贷与 10 月 9 日退休金已有投稿回执，但均未收敛为公开确认。
- 独立 B 执行者采用自己的强身份回读，车贷 B 在两个平台均已有 PUBLISHED 及原生 ID 证据；普通 A 和独立 B 的状态闭环并不一致。

配对 B 的提交还要求同平台 A 确认 PUBLISHED 后等待 6 小时。未来恢复入组后，应验收 A 的独立实验回读能正确完成，不能仅依赖普通账本状态或提交时间。

## 根因三：观察数据路径尚未自动化

`scripts/run_wallstreet_ab.py` 暴露 `--import-metrics`，报告明确标记 `metric_capture=native_id_bound_import`。

- `wallstreet_pairs`：1 条 B_ONLY，0 条 PAIRED。
- `wallstreet_metric_snapshots`：0 条。
- `published_video_daily_metrics`：0 条。
- 规格与上线报告已说明自动后台指标抓取未实现；24/72/168 小时的快照需要导入。

因此“二创成片已单条发布”和“可以持续观察 A/B”没有形成同一交付闭环。目前没有数据可以判断 A/B 优劣。

## 单条样本与次要问题

车贷 `h7rY4nSB2tM`：B 已有视频号及抖音强身份发布证据，普通 A 被 `publication_review_required=1` 阻止，且样本模式为 B_ONLY；不能计为完整配对，也不能擅自解除复核闸补发 A。

`MpEPbDCsSE0` 存在 YouTube 下载认证失败；`mJvMJeXPrZk` 留在 METADATA_PENDING。这些是单条异常，不能解释最新完整制作视频为什么没有 B。

运行日志还存在其他作品导致的抖音回查/动作熔断，最新普通视频抖音记录仍为 QUEUED。这是双平台交付的额外阻塞，需要按现有熔断证据处理，不能用重试最新作品绕过。

## 推荐修复顺序与验收

1. 统一所有 A 就绪入口：AI 封面正常完成和回执恢复也必须在允许普通投稿前原子登记实验配对，带齐 B 输入；重复调度保持幂等。增加覆盖封面异步完成→配对→普通发布的集成回归。
2. 对已漏配、已提交的新视频制定具名恢复方案，复用既有 A 的原生 ID 和收据；不删除投稿账本、不重传 A、不擅自纳入全部历史作品。
3. 验收配对 A 的强身份只读回查和 6 小时依赖，再验证同源 A/B 双平台独立作品 ID。普通看板回查的历史身份风险需分别校准。
4. 明确指标观察交付：先实现可审计的定时快照采集或定时提醒/导入流程；缺失保持缺失，不补零。不以 worker 存活或单条 B 发布作为实验完成。
5. 在合适空闲时采用修复并核对所有常驻执行者版本；验收至少一组真实新视频经 AI 封面完成后自动进入 PAIRED，A/B 各自公开回读，以及真实作品级指标。

本轮只完成调查及内存复现；上述修复、恢复与采集均尚未执行。

## 2026-10-10 后续修复与真实验收

以上为修复前只读调查快照；下述操作得到用户“修复漏入队、打通并验证真实运行，已有提交不要重复发布”的明确授权。自动指标采集仅提供具体提案。

### 已采用修复

- AI 封面正常完成与已有 resolution 恢复都使用同一 DAL 入口，A 就绪与配对登记在同一事务中完成；失败同时回滚。仅该频道、实验激活后的合格任务入队，重复调用不新建 B。
- 对退休金 `r9-_2YJMhmQ` 具名补回 pair 2，复用既有普通 A，保留源片/字幕输入。历史 B_ONLY、其他频道及复核闸保持原语义。
- 普通 A 的强公开回读同步普通发布账本与看板；修复抖音普通 A 原生 ID 字段名称。
- 同次提交回执捕获原生 `objectNonce`，跨会话只允许原提交回执的唯一精确 nonce 关联；无回执、无 nonce、错原 ID 或歧义继续未知，不重传。全局历史回查开关仍为 0。
- 已发表 DOM 日期与同原生 ID 的 `createTime` 按浏览器时区逐分钟一致时采用平台公开时间；仅首次观察公开时刻保留不确定性，之后可由强平台证据校准，不能反向降级。
- 真实退休金 ASR 使用繁体，原有限转换表导致指读对齐不足 90%；接入固定版本 OpenCC 做逐字符简繁归一化，保留显示文本和索引，未降低 90% 内容匹配门槛。真实语音识别与编码已继续运行。

生产主干提交：`b32f1a9`（漏入队）、`ee11a68`（真实 ASR）、`0f46978`（身份及审计）、`c789564`（API/DOM 时间合并）、`8baf95d`（时间校准）。常驻普通发布进程仅在 IDLE、互斥锁保护下重载；未中断正在下载或二创编码的进程。

### 普通 A 原生身份恢复

原始提交 ID 跨会话失效且旧回执未保存 nonce，自动匹配拒绝绑定。用户核对完整微信原生预览 `https://weixin.qq.com/sph/AGEsKHYqO`，明确答复“确认是此前提交的退休金普通版”。随后独立后台回查新原生 ID：

`export/UzFfBgAAxJalIFwjXhWtk8zT4DCalpRHQcxEuegGICtVw5dBmQ`

后台同 ID 的已发表、处理完成、公开枚举与可见发布时间均满足；平台公开时间为 2026-10-10 05:04:18（Asia/Shanghai）。已原子恢复两本账的当前 ID，并将普通 A 置为 PUBLISHED。原提交回执未修改，`wallstreet_identity_recoveries` 保存新旧 ID、人工确认及证据路径；此次没有新增 A 提交尝试。

证据：`output/wallstreet_ab/recovery-r9-20261010/confirmed-native-a/management_readback.json`、`management_published.png`、`operator_identity_recovery.json`。人工核对用于身份关联，平台公开状态和时间来自随后独立原生 ID 回读，二者不能混作自动匹配证明。

### 抖音剩余约束

普通 A 的抖音发布实体 657 保留 QUEUED，attempt_count=0，external_post_id=null。此前具名正常 claim 因每日 20 条额度用满被拒绝（18 条普通、2 条英语世界）；当时未尝试上传、未重置、未提高上限。后续用户只特批退休金这一组 A/B 两条验证额度，操作记录见下节。抖音 B 必须等同平台 A 确认公开至少六小时。

不能把视频号闭环完成、队列保留或绿色测试写成两平台完整配对都已完成。新视频经修复后的 AI 封面路径自动纳入已由事务回归验证；本次真实样本是对漏单的具名恢复，尚不是下一条全新源视频自动入队的运行样本。

指标提案：`docs/workorders/2026-10-10-wallstreet-ab-metrics-proposal.md`。自动采集未上线，当前没有可比的 24/72/168 小时完整配对指标。

### 二创成片与上传前登录恢复

退休金 B 的完整成片已真实生成并通过既有全源完整性与投稿包验证：1080×1920、30fps、733.286009 秒，其中源视频 703.333333 秒，另含二创导读及结尾。成片 SHA256 为 `817ab3de21ad9433fdbb5d8856866617c17de81b0d111464c5464c236a02ef66`，pair 2 READY，render attempts=2。证据位于 `output/wallstreet_ab/2/insight-editorial-mobile-2/` 的 `editorial.receipt.json`、`package.json` 和预览图；这些仅证明制作和既有门槛，不等同于独立事实核查全部通过。

14:28 的 B 投稿器在登录阶段返回专用退出码 2，日志没有进入 Uploading video，未生成提交回执。它是一次投稿器调用，不是第二条平台作品。14:33 仅登录刷新成功，经新上下文确认发表页正向控件有效。随后采用 `b1901c3`：只允许同一 B/微信/attempt token、无原生 ID、专用登录退出码 2 的记录恢复 WAITING，保留 attempt_count；自动恢复冷却 30 分钟，结果未知及已有回执不会恢复。当前一次人工具名恢复使用日志哈希与退出证据，允许立即继续，没有重置普通 A。

该恢复新增隔离验收 27 项通过，证据 `/private/tmp/video-pytest-ha8j_p62`。14:39 巡航采用 `b1901c3` 后重新领取，14:39:50 开始真实上传，14:40:21 上传完成；平台是否接受和公开须另看后续原生回执及独立管理页回读。

频道监控最新证据 `output/monitor_health.json`：2026-10-10 14:32:52，目标频道 status=ok。

### 视频号真实配对公开与抖音继续验证

退休金 B 在 14:40:49 获得平台受理，14:41 同会话唯一新原生 ID 与短标题交叉捕获成功，原回执同时保存 `platform_object_nonce=3832449011576987149`。随后独立浏览器上下文只读核查确认 PUBLISHED、EXACT_OBJECT_ID，平台公开时间 2026-10-10 14:40:46；A 的 05:04:18 到 B 的公开间隔超过六小时。

B 原生 ID：`export/UzFfBgAAxJalYD11Qkusk8zT4DCazU1dhC1Ia99sawE4swBo2A`。

独立证据：`output/wallstreet_ab/2/readback/4-independent-1791614510/management_readback.json` 与 `management_published.png`。B 的两次投稿器调用中，一次明确在上传前登录失败，实际平台提交只有一次；普通 A 原有提交次数保持 1，历史车贷 B 两平台尝试次数均未增加。

用户明确答复“仅特批退休金这组 A/B 两条验证额度”。保持全局每日上限 20，只在具名普通 A 发布实体 657 的一次领取使用 21；记录在 `output/wallstreet_ab/recovery-r9-20261010/normal-douyin/pair-only-quota-approval.json`，并保留 B 六小时依赖。

普通 A 的抖音真实提交获受理，attempt_count=1。真实运行发现其受理不返回原生 ID，旧二创回查跳过无 ID 的 A；已采用 `0d5cf1a` 进行只读交接修复：仅普通账本已有提交且状态 UNDER_REVIEW/PUBLISHED 可按抖音既有唯一完整正文匹配契约取得原生 ID，未提交队列仍禁止进入；后续公开强回读同步普通账本，ID 冲突拒绝覆盖。14:46 回查获得 `7694926235595492649`，API_EXACT_DESCRIPTION，状态 UNDER_REVIEW。不会重新上传普通 A；B 当前 WAITING、attempt_count=0，等待同平台 A 确认公开再计六小时。

生产主干包括同期 TED 改动的隔离回归：162 passed，真实 Chromium 浏览器隔离探针通过，证据 `/private/tmp/video-pytest-0fdpkql9`。随后无 ID 抖音交接修复定向验收 29 passed，证据 `/private/tmp/video-pytest-dykwp_n8`。工作树 `git diff --check` 通过。不能把这两次重叠测试相加成独立用例总数。

截至 14:47，视频号一组 PAIRED 已真实完成，抖音普通 A 已提交且仍在审核、B 等待；双平台全部公开验收尚未完成。自动指标采集仅为具体方案，未实施，未伪造观察快照。

### 后续自动验收已安排

用户明确选择“自动继续核验并通知结果”。本聊天 heartbeat “退休金 A/B 发布验收”（automationId `a-b`）已创建并回读为应用卡片，ACTIVE，每 30 分钟继续。它只核验本组，并按既有巡航、强身份、提交保护和六小时条件推进；正常审核、时间未到和状态不变时保持安静，全部公开或异常需要动作时才通知，完成后暂停本次验收 heartbeat。既有生产 cron 未改动，自动指标采集未启用。

代码和此前证据已推送至 origin/main `06d849f366fbe9935ca21925c38a28e09f46531a`。最终只读核对：退休金普通微信提交次数 1、普通抖音提交次数 1；历史车贷 B 两平台 PUBLISHED，各自提交次数 1，未重复发布。新二创执行者心跳已实际采用 `0d5cf1a`；普通执行者采用 `fc29710`（含此前身份及漏入队修复，后续新修复由独立二创短进程加载）。文档提交不等同于进程代码更新。
