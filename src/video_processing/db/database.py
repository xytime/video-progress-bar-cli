"""数据库访问层 - 管理自动化视频管线的状态与发现列表

所有 SQL 操作必须封装在 PipelineDB 方法内。
禁止外部模块直接调用 get_connection() 执行裸 SQL。

# Modification History
| Version | Date       | Author                              | Description                                                                    |
|---------|------------|-------------------------------------|--------------------------------------------------------------------------------|
| 3.59.0  | 2026-09-04 | Codex                               | 仅为有明确发布前拒绝证据却曾被误记为 UNCERTAIN 的首轮抖音尝试受控恢复一次。      |
| 3.58.9  | 2026-09-03 | Codex                               | 将原创声明界面回读失败的受控恢复次数持久化为一次，阻止失败链路反复重开。         |
| 3.58.8  | 2026-09-03 | Codex                               | 原创声明已操作但界面回读失败、且无平台回执时，只允许受控签发一次重试授权。       |
| 3.58.7  | 2026-09-03 | Codex                               | 仅在作品管理页明确确认原记录已删除后，受控重开英语世界同一审核项的一次重投机会并保留旧尝试。 |
| 3.58.6  | 2026-09-02 | Codex                               | 强制抖音 NEW 候选查询使用正数时间与批次边界，杜绝任意调用者绕过巡航范围扫描历史。 |
| 3.58.5  | 2026-09-02 | Codex                               | 为未启动的一次性抖音浏览器凭据增加超时取消审计；已启动尝试保持不可自动重传。       |
| 3.58.4  | 2026-09-02 | Codex                               | 移除旧进程按 UPLOADING 推断投稿包的回退；无完整凭据的遗留动作一律安全停止。       |
| 3.58.3  | 2026-09-02 | Codex                               | 新增抖音一次性浏览器启动凭据，令跨进程投稿只消费已领取且不可重放的账本上下文。 |
| 3.58.2  | 2026-09-02 | Codex                               | 提供英语世界同源审核/投稿保护来源的只读查询，供日更在制作前排除重复来源。       |
| 3.58.0  | 2026-09-01 | Codex                               | 抖音发布领取可显式取消日额度和候选时间/批次上限；不可重传账本终态不变。 |
| 3.57.1  | 2026-08-31 | Codex                               | 英语世界抖音取消账本可凭作品管理页已发布证据受控对账；失败尝试保持不可变。 |
| 3.57.0  | 2026-08-30 | Codex                               | 新增英语世界独立抖音投稿与尝试账本，并与通用 NEW 共用每日领取额度。 |
| 3.56.1  | 2026-08-30 | Codex                               | 英语世界平台原生 ID 只允许首次绑定或同 ID 幂等写入，拒绝覆盖审核项和尝试证据锚点。 |
| 3.56.0  | 2026-08-30 | Codex                               | 英语世界投稿账本持久化视频号原生 ID，并提供节流的精确作品管理回查状态。 |
| 3.55.0  | 2026-08-30 | Codex                               | 抖音 NEW 候选和视频号下游取消显式消费公开确认策略；关闭时仍不复活任何既有账本。 |
| 3.54.0  | 2026-08-30 | Codex                               | 持久化平台同阶段 UI 连续失败；达到阈值后跨巡航熔断，校准证据清除时保留审计。 |
| 3.37.0  | 2026-08-23 | Codex                               | 保存源视频 UTC 精确发布时间，支持发布前原创声明 24 小时判定 |
| 3.38.0  | 2026-08-24 | Codex                               | 新增 Telegram 投递回执账本；仅 API message_id 证明单次通知获受理。 |
| 3.39.0  | 2026-08-24 | Codex                               | 英语世界未确认投稿仅可经明确人工确认重开同一审核项，并保留原证据目录。 |
| 3.40.0  | 2026-08-26 | Codex                               | 将视频号本地受理账本与平台待确认统计分开，原生 ID 回查关闭时仍可明确运营状态。 |
| 3.41.0  | 2026-08-26 | Codex                               | 视频号受理账本、不可变尝试与任务状态同事务落盘，杜绝崩溃后的分叉状态。 |
| 3.42.0  | 2026-08-26 | Codex                               | 英语世界新增自动投稿授权来源，自动策略只消费本次新建且质检完成的成片。 |
| 3.43.0  | 2026-08-26 | Codex                               | 登录恢复对任意视频号账本 fail-closed；保留批量重试的账本跳过统计。 |
| 3.44.0  | 2026-08-27 | Codex                               | 高分与预加工候选在 SQL 层排除活跃视频号账本及历史归档，隔离存量 PENDING 污染。 |
| 3.45.0  | 2026-08-28 | Codex                               | 英语世界仅对登录前明确失败的新自动投稿项开放一次登录后续投，其他终态继续 fail-closed。 |
| 3.46.0  | 2026-08-29 | Codex                               | 新增两小时单任务微信发布 lease；只允许明确候选一次性绕过发布时间窗口并保留签发、领取审计。 |
| 3.47.0  | 2026-08-29 | Codex                               | 单任务发布 lease 增加未消费撤销与撤销人审计；过期、已领取和重复撤销均 fail-closed。 |
| 3.48.0  | 2026-08-29 | Codex                               | 平台补录预览稳定地优先未尝试候选，再排可重试失败项，避免更新时间跨秒导致批次顺序翻转。 |
| 3.49.0  | 2026-08-29 | Codex                               | 英语世界人工投稿授权限定两小时；自动策略只可在公共窗口领取，过期人工授权原子退回待审核。 |
| 3.50.0  | 2026-08-29 | Codex                               | 英语世界审核项绑定完整投稿包哈希、同源活动项防重，并为每次投稿保留不可覆盖证据账本。 |
| 3.51.0  | 2026-08-29 | Codex                               | 英语世界二次确认制作请求新增原子领取、审核项绑定和失败收口状态，不接通用发布队列。 |
| 3.52.0  | 2026-08-29 | Codex                               | 英语世界候选持久化授权频道 ID；旧的仅显示名候选在选择阶段 fail-closed。 |
| 3.53.0  | 2026-08-30 | Codex                               | 英语世界新增具名操作员补发授权；仅可领取零尝试的自动延后项，两小时未领取则回归公共窗口队列。 |
| 3.35.0  | 2026-08-21 | Codex                               | Cache candidate scoring inputs and hide archived WeChat tombstones from recovery queue |
| 3.36.0  | 2026-08-23 | Codex                               | 为英语世界学习卡增加独立 Telegram 审核与视频号投稿账本，禁止复用通用队列 |
| 3.33.0  | 2026-08-21 | Codex                               | 视频号延后恢复领取排除历史提交墓碑，且仪表盘将待恢复队列与实际处理中状态分离 |
| 3.34.0  | 2026-08-21 | Codex                               | 新增英语世界短视频独立研究、候选与生产请求账本，不接管通用视频或发布状态机 |
| 3.32.0  | 2026-08-21 | Codex                               | 每个 SQLite DAL 连接显式启用外键；新增进程已死的预提交任务有界回收，发布状态不参与回收 |
| 3.31.0  | 2026-08-20 | Codex                               | Highlight Clip 增加独立渲染资产、人工审核账本与原子领取接口，源视频状态机保持不变 |
| 3.30.0  | 2026-08-20 | Codex                               | 引入 Video Item/Highlight Clip 通用发布主体，视频号 post_id 账本可安全关联独立 Clip |
| 3.29.0  | 2026-08-20 | Codex                               | 新增独立 Highlight Job 与候选切片账本；不复用或改写既有视频处理状态机与发布账本 |
| 3.28.0  | 2026-08-20 | Codex                               | 视频号历史未解归档升级为永久墓碑；阻止既有提交证据被调度器重新写入活跃账本 |
| 3.27.0  | 2026-08-20 | Codex                               | 视频号提交尝试记录不可变本地指纹；仅以同次提交捕获的原生 post_id 绑定和回查平台状态 |
| 3.26.0  | 2026-08-20 | Codex                               | 视频号账本增加后台驳回/未找到终态、平台记录标识和回查时间，支持提交后状态自动终结 |
| 1.0.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 初始创建数据库与DAL封装                                                         |
| 2.0.0   | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning | v7.0 架构升级：黑名单表、Pid追踪、手动评分锁                                      |
| 2.5.0   | 2026-05-27 | Gemini_3.5_Flash_planning           | 一变多升级：复合唯一约束(youtube_id, slice_index)、自关联外键级联删除与批量插入 |
| 2.5.1   | 2026-05-27 | Gemini_3.5_Flash_High_planning      | 修复 _init_db 中遗漏推荐频道表 recommended_channels 的创建问题 |
| 2.5.2   | 2026-05-27 | Gemini_3.5_Flash_High_planning      | 新增 get_detailed_stats 方法提供父子任务的细分状态统计数据 |
| 2.5.3   | 2026-05-27 | Unknown_Model_planning              | 修复已分片(SEGMENTED)父视频在后台仪表盘各 Tab 中隐藏不可见的 Bug |
| 2.5.4   | 2026-05-27 | Unknown_Model_planning              | 仅当切片全部完成时才允许父视频进入“已完成”Tab，否则根据切片状态归入“处理中”或“错误”Tab |
| 2.6.0   | 2026-05-27 | Gemini_3.5_Flash_planning           | 新增 disable_slicing 状态列用于整片发布/切片发布的控制 (默认 1 为整片发布) |
| 2.7.0   | 2026-05-27 | Unknown_Model_planning              | 红蓝博弈安全性与容错性审计修复 (P1/P2) |
| 2.8.0   | 2026-05-28 | Gemini_3.5_Flash_planning           | 优化 get_high_score_pending_videos：利用 EXISTS 子查询在 SQL 层直接过滤被顺序锁阻断的切片任务 |
| 2.9.0   | 2026-05-29 | Claude_Sonnet_4.6_Thinking_planning | 新增 tts_provider 列，用于按视频记录 TTS 配音引擎（nullable），供 /tts 命令按需存储 |
| 3.0.0   | 2026-06-01 | Claude_Sonnet_4.6_Thinking_planning | 新增 update_video_spec 方法，全量覆盖规格字段（trim/disable_slicing/tts），供 respec 流程使用 |
| 3.1.0   | 2026-06-09 | Gemini_3.5_Flash_planning           | 新增 high_likes tab 支持，显示最近24小时发布的高赞视频 |
| 3.2.0   | 2026-06-09 | Gemini_3.5_Flash_planning           | add_video 支持 category, censor_tag, censor_score 录入 |
| 3.3.0   | 2026-06-09 | Gemini_3.5_Flash_planning           | 将 high_likes 高赞视频时间窗口由 24 小时调整为 3 天，优化刷新发现效果 |
| 3.4.0   | 2026-06-11 | Gemini_3.5_Flash_planning           | [高赞优化] 对齐 get_tab_counts 徽章时间窗口为 3 天，优化高赞视频排序机制优先新视频 |
| 3.4.1   | 2026-06-11 | Claude_Opus_4.6_Thinking_planning   | [CodeReview修复] 统一变量名 yesterday→three_days_ago，提升 datetime 为 top-level import |
| 3.5.0   | 2026-06-13 | Claude_Opus_4.8                     | 新增 promote_to_manual：将高赞发现(DISCOVERY)条目原子提升为 MANUAL 加急任务（source/score/手动锁），供「📥 加入队列」一键发布 |
| 3.6.0   | 2026-06-13 | Claude_Opus_4.8                     | 新增 bypass_censorship 列 + set_bypass_censorship/is_censorship_bypassed：供「🔓 复核放行」人工绕过审查后管线跳过全部审查层 |
| 3.7.0   | 2026-06-15 | Claude_Opus_4.8                     | [BUG-2/#11] purge_stale_tasks 额外排除 PUBLISHING，防止发布中崩溃被自动重置 PENDING 导致重复公开发布 |
| 3.8.0   | 2026-06-15 | Claude_Opus_4.8                     | [BUG-5] 新增 get_waitlist_clearable_ids 并在 waitlist 展示/统计谓词排除 DISCOVERY，防一键清空误删/拉黑高赞发现条目 |
| 3.9.0   | 2026-06-25 | Claude_Opus_4.8                     | [黑名单根治] get_high_score_pending_videos 在 SQL 层硬过滤 BLACKLISTED 频道与 blacklisted_videos 墓碑：此为所有自动发布路径取候选的唯一咽喉，杜绝已拉黑频道存量 PENDING 被任何路径（调度器/管线/重算）顶发 |
| 3.10.0  | 2026-06-25 | Claude_Opus_4.8                     | 新增 get_rescore_candidates（含同款黑名单过滤、UTC 对齐窗口）：收敛 rescore_refresh 手抄过滤 SQL 为 DAL 单一真相源，消除黑名单语义漂移与 rule-2 裸 SQL 违规 |
| 3.11.0  | 2026-06-25 | Claude_Opus_4.8                     | 新增 is_manually_scored(yid,slice) 查询：供审查执行层判定手动锁定视频命中 P2 时挂起人工复核而非 force 清零回弹 |
| 3.12.0  | 2026-06-28 | Claude_Opus_4.8                     | 新增 get_failed_videos_since(hours)：取最近 N 小时内 FAILED 任务（UTC 对齐窗口），供 Telegram /retry <小时数> 批量重试 |
| 3.12.1  | 2026-07-05 | Codex                               | get_failed_videos_since 纳入 LOGIN_REQUIRED，修复微信过期导致的批量重试遗漏 |
| 3.12.2  | 2026-07-08 | Codex                               | 新增 get_stale_publishing_videos：暴露长时间停留在 PUBLISHING 的候选任务，供调度器做“进程已死但状态未回收”的保守降级 |
| 3.13.0  | 2026-07-12 | Codex                               | get_high_score_pending_videos 支持按频道覆盖自动发布线，保持黑名单与顺序锁过滤不变 |
| 3.13.1  | 2026-07-12 | Codex                               | get_rescore_candidates 返回 channel_id，供重算层跳过已过频道专属发布线的候选 |
| 3.14.0  | 2026-07-13 | Codex                               | 新增 AI 字幕处理审计表与 DAL，记录逐视频 provider 尝试、降级和质量结果 |
| 3.15.0  | 2026-07-15 | Codex                               | 新增快手浏览器发布账本，以成片摘要去重并支持历史迁移每日限额 |
| 3.15.1  | 2026-07-15 | Codex                               | 修正快手去重语义：仅已发布作品阻止重传，失败和临时上传保留可重试尝试 |
| 3.15.2  | 2026-07-15 | Codex                               | 新增手动提交回填领取时间，确保人工补发也计入当日快手历史迁移上限 |
| 3.15.3  | 2026-07-15 | Codex                               | 历史日限额仅统计实际提交/待核验状态，校准或上传失败不再虚占当天发布名额 |
| 3.15.4  | 2026-07-15 | Codex                               | 提供快手审核状态批量查询，供定时任务只读回查作品管理结果 |
| 3.15.5  | 2026-07-16 | Codex                               | 新增视频号延后发布领取接口，支持停用期间快手单平台与恢复后限额补发 |
| 3.16.0  | 2026-07-23 | Codex                               | 新增抖音发布账本，与快手保持独立状态、历史限额和审核回查语义 |
| 3.17.0  | 2026-07-24 | Gemini_3.6_Flash_planning           | 新增 get_video_publications_map 聚合微信、快手、抖音 3 平台状态，并在 get_paginated_videos / get_slices_by_parent_yid 中透传 |
| 3.17.0  | 2026-07-23 | Codex                               | 新增三平台补录预览候选查询，支持访谈/演讲与 Wall Street Truthbombs 规则 |
| 3.17.1  | 2026-07-23 | Codex                               | 视频号延后补发领取支持同一套补录规则过滤，避免默认自动补录越界 |
| 3.18.0  | 2026-07-25 | Codex                               | 平台发布账本新增 CANCELED 终态，用于缺失本地投递素材的历史补录任务退出自动重试 |
| 3.18.1  | 2026-07-25 | Codex                               | 抖音提交后未确认的遗留失败不再进入自动领取，避免可能已提交作品被盲重投 |
| 3.19.0  | 2026-07-26 | Codex                               | 新增 censorship_incidents 独立违规台账，记录审查命中、上下文和处置决策供专项复盘 |
| 3.20.0  | 2026-07-27 | Codex                               | censorship_incidents 增补规则版本、规则 ID、输入来源、流程阶段、平台和输入 hash 复盘字段 |
| 3.21.0  | 2026-07-28 | Codex                               | 新增监控候选入库/补全接口；RSS 降级条目保持 METADATA_PENDING，完整官方元数据到位才转 PENDING |
| 3.22.0  | 2026-07-28 | Codex                               | 新增只读运维质检快照接口，集中队列、失败、在途和多平台账本查询 |
| 3.22.1  | 2026-07-28 | Codex                               | 质检快照增加最近本地发布和各平台账本总览，支撑 Telegram 上帝视角状态行 |
| 3.22.2  | 2026-07-29 | Codex                               | 抖音补录候选排除 CANCELED 终态，避免缺素材历史记录重复进入自动补发 |
| 3.22.3  | 2026-07-29 | Codex                               | 新增抖音历史补发实时进度快照，供每条发送前汇报今日已发和剩余队列 |
| 3.22.4  | 2026-07-29 | Codex                               | 平台汇总展示按审核/未确认信号保守降级，避免本地 PUBLISHED 误报为平台可见 |
| 3.22.5  | 2026-07-29 | Codex                               | 平台 PUBLISHED 写入必须覆盖明确确认备注，防止旧审核备注残留污染终态 |
| 3.22.6  | 2026-07-29 | Codex                               | 新增最近微信已发布但抖音 NEW 未建账的漏同步查询，供调度器自动补偿 |
| 3.23.0  | 2026-07-29 | Codex                               | 新增独立配音再制任务、片段、产物和投递账本；不复用原视频状态机 |
| 3.23.1  | 2026-07-29 | Codex                               | 新增配音投递状态校正 DAL，避免人工校正被计为新上传尝试 |
| 3.23.2  | 2026-07-29 | Codex                               | 配音任务读取透传源片 upload_date，供再制渲染继承发布日期戳并保留切片回退能力 |
| 3.24.0  | 2026-07-29 | Codex                               | 新增发布后日粒度指标、内容唯一身份、视频关系和 AB 实验底层账本 |
| 3.25.0  | 2026-07-31 | Codex                               | 新增源字幕预检/预加工状态与微信补发真实日额度账本 |
| 3.25.1  | 2026-07-31 | Codex                               | 将 AI_COVER_PENDING 纳入处理中统计和仪表盘，避免异步制图任务隐身 |
| 3.25.2  | 2026-08-03 | Codex                               | AI 封面完成只允许 AI_COVER_PENDING 原子回到 PENDING，防止已发布视频被旧任务重新入队 |
| 3.25.3  | 2026-08-03 | Codex                               | 配音任务创建时持久化实际 TTS provider，保证频道专属音色可追溯 |
| 3.25.4  | 2026-08-05 | Codex                               | 新增上传前瞬态失败的原子重入队接口；只允许下载/文案/转录阶段且递增 retry_count |
| 3.25.5  | 2026-08-05 | Codex                               | 增加 zh_title 定点更新 DAL，移除后台标题翻译路径的裸 SQL |
| 3.25.6  | 2026-08-07 | Codex                               | 抖音发布前闸门/页面校准失败持久化取消，阻断旧 RETRYABLE_FAILED 记录跨轮重复建账 |
| 3.25.7  | 2026-08-07 | Codex                               | AI 封面完成回队时原子标记 preparation_ready，允许盘中只提交已验证成片 |
| 3.25.8  | 2026-08-07 | Codex                               | 新增抖音 CANCELED 账本的显式人工重入队，保留原失败尝试供审计 |
| 3.25.9  | 2026-08-08 | Codex                               | 评分写入口统一执行频道上限，The Economist 永不写入超过 60 的分数 |
| 3.25.10 | 2026-08-08 | Codex                               | 缺失抖音投递产物的旧失败一并停在 CANCELED，避免恢复开关后跨轮空转 |
| 3.25.11 | 2026-08-08 | Codex                               | 持久化抖音浏览器动作节流，并让 NEW 新片领取遵守每日额度，避免每分钟巡航放大投递 |
| 3.26.0  | 2026-08-09 | Codex                               | 新增内容生产类型字段，区分英语世界短视频与通用视频并保证切片继承 |
| 3.26.4  | 2026-08-14 | Codex                               | 增加既有任务的内容生产类型更新入口，避免重复入库才能纠正归档类型 |
| 3.26.5  | 2026-08-14 | Codex                               | 增加单任务发布前人工复核闸，阻止高分候选自动提交 |
| 3.26.1  | 2026-08-10 | Codex                               | 快手待提交、审核中、上传中或未确认账本均阻断同源或同成片重建尝试，避免重复上传 |
| 3.26.2  | 2026-08-10 | Codex                               | 新增北京自然日运营简报只读快照，区分本地视频号完成与快手/抖音已确认发布 |
| 3.26.3  | 2026-08-10 | Codex                               | 新增视频号确认账本；以提交后后台列表截图为准，杜绝仅写本地 PUBLISHED 而缺失平台证据 |
| 3.26.4  | 2026-08-11 | Codex                               | 视频号账本新增 UNDER_REVIEW 并迁移旧约束；提交证据不再等同公开发布，终态确认时间仅写入 PUBLISHED |
| 3.26.5  | 2026-08-11 | Codex                               | 视频号未最终确认时取消同源尚未提交的抖音/快手队列，保留审计记录且禁止跨平台抢跑 |
| 3.26.6  | 2026-08-14 | Codex                               | 仪表盘查询将 UNDER_REVIEW 独立归入待平台确认，不再混入实际加工队列 |
| 3.26.7  | 2026-08-18 | Codex                               | get_connection 改为关闭连接的上下文管理器，修复仪表盘长期运行耗尽文件描述符 |
| 3.26.8  | 2026-08-30 | Codex                               | 新增抖音上游门禁 shadow 快照，量化视频号未确认导致的候选饥饿而不创建发布任务 |
"""

import sqlite3
import os
import json
import logging
import datetime  # [Claude_Opus_4.6_Thinking_planning] 提升为 top-level import，用于高赞时间窗口计算
import time
import hashlib
import hmac
import secrets
from contextlib import contextmanager
from pathlib import Path
from typing import Collection, List, Dict, Any, Optional, Sequence

from ..content_types import CONTENT_TYPE_GENERAL, normalize_content_type
from ..scoring import CHANNEL_SCORE_CAPS, cap_channel_score

class PipelineDB:
    """视频管线数据访问层。

    所有 SQL 操作必须通过此类的方法执行。
    外部模块禁止直接调用 get_connection() 执行裸 SQL。
    """

    _logger = logging.getLogger(__name__)
    _PLATFORM_REVIEW_MARKERS = (
        "审核中",
        "待审核",
        "等待平台审核",
        "按审核中处理",
        "已接受发布提交",
    )
    _PLATFORM_UNCONFIRMED_MARKERS = (
        "未确认",
        "未找到",
        "不可见",
        "无平台成功证明",
        "等待作品管理回查",
        "确认最终发布",
    )
    _METRIC_PLATFORMS = {"wechat", "douyin", "kuaishou", "xiaohongshu"}
    _CONTENT_IDENTITY_SOURCES = {"SOURCE", "ASSET", "TRANSCRIPT", "MANUAL", "MIXED"}
    _CONTENT_RELATIONS = {"ORIGINAL", "CUT", "DUBBING", "TRANSLATION", "REMIX", "VARIANT", "UNKNOWN"}
    _VIDEO_RELATIONS = {
        "SLICE_OF", "DERIVED_FROM", "DUBBING_OF", "TRANSLATION_OF", "REMIX_OF", "AB_VARIANT_OF", "DUPLICATE_OF",
    }
    _AB_EXPERIMENT_STATES = {"DRAFT", "RUNNING", "PAUSED", "COMPLETED", "CANCELED"}

    @classmethod
    def _derive_platform_display_state(cls, state: Optional[str], error_message: Optional[str]) -> str:
        """把本地账本状态转换为面向运营展示的保守状态。"""
        normalized_state = (state or "NOT_QUEUED").upper()
        if normalized_state != "PUBLISHED":
            return normalized_state

        text = error_message or ""
        if any(marker in text for marker in cls._PLATFORM_REVIEW_MARKERS):
            return "UNDER_REVIEW"
        if any(marker in text for marker in cls._PLATFORM_UNCONFIRMED_MARKERS):
            return "UNCERTAIN"
        return normalized_state

    def __init__(self, db_path: str = "pipeline.db"):
        # 默认在项目根目录的 output 文件夹内创建数据库
        # 如果是绝对路径则直接使用
        if not os.path.isabs(db_path):
            base_dir = Path(__file__).parent.parent.parent.parent
            self.db_path = str(base_dir / "output" / db_path)
        else:
            self.db_path = db_path
            
        # 确保目录存在
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        
    @contextmanager
    def get_connection(self):
        """提供事务连接，并在 ``with`` 块结束后确定关闭文件描述符。

        sqlite3.Connection 自身的上下文管理器只负责提交或回滚，并不会调用
        close()。本项目的 DAL 全部以 ``with self.get_connection()`` 访问，
        因而必须在这里统一关闭，避免常驻仪表盘的轮询逐步耗尽句柄。
        """
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        # SQLite 的外键开关是连接级而不是数据库级；只在 _init_db() 打开会让
        # 后续 DAL 连接静默失去 ON DELETE/ON UPDATE 约束。
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()
        
    def _init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # [Gemini_3.5_Flash_planning] 开启 WAL 模式，支持高并发读写，并激活 SQLite 外键支持
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA foreign_keys=ON;")
            
            # [Gemini_3.5_Flash_High_planning] 重新加入推荐频道表的创建，防测试环境与空数据库丢失此表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS recommended_channels (
                    channel_id TEXT PRIMARY KEY,
                    channel_name TEXT NOT NULL,
                    reason TEXT,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 检测是否已经进行了复合键和自关联级联删除的表升级 (检查 parent_id 列是否存在)
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if columns and "parent_id" not in columns:
                self._logger.info("[Migration] Upgrading database schema to composite keys (yid, slice_index) & parent_id cascade relation...")
                # 使用隐式事务，不再手动 BEGIN IMMEDIATE 避免 OperationalError
                try:
                    # 1. 重命名原表
                    cursor.execute("ALTER TABLE processed_videos RENAME TO processed_videos_old;")
                    
                    # 2. 创建支持复合主键和外键级联删除的新表
                    cursor.execute('''
                        CREATE TABLE processed_videos (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            youtube_id TEXT NOT NULL,
                            slice_index INTEGER NOT NULL DEFAULT 0,
                            parent_id INTEGER DEFAULT NULL,
                            title TEXT NOT NULL,
                            channel_id TEXT NOT NULL,
                            score INTEGER DEFAULT 0,
                            status TEXT NOT NULL DEFAULT 'PENDING',
                            retry_count INTEGER DEFAULT 0,
                            error_msg TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            zh_title TEXT,
                            source TEXT DEFAULT 'AUTO',
                            content_type TEXT NOT NULL DEFAULT 'GENERAL',
                            duration_sec INTEGER DEFAULT NULL,
                            view_count INTEGER DEFAULT NULL,
                            like_count INTEGER DEFAULT NULL,
                            upload_date TEXT DEFAULT NULL,
                            source_published_at TEXT DEFAULT NULL,
                            censor_tag TEXT DEFAULT NULL,
                            censor_score INTEGER DEFAULT NULL,
                            is_manually_scored INTEGER DEFAULT 0,
                            process_pid INTEGER DEFAULT NULL,
                            trim_start TEXT DEFAULT NULL,
                            trim_end TEXT DEFAULT NULL,
                            disable_slicing INTEGER DEFAULT 1,
                            bypass_censorship INTEGER DEFAULT 0,
                            publication_review_required INTEGER NOT NULL DEFAULT 0,
                            preparation_ready INTEGER DEFAULT 0,
                            source_subtitle_status TEXT DEFAULT 'PENDING',
                            source_subtitle_checked_at TIMESTAMP DEFAULT NULL,
                            UNIQUE(youtube_id, slice_index),
                            FOREIGN KEY(parent_id) REFERENCES processed_videos(id) ON DELETE CASCADE
                        )
                    ''')
                    
                    # 3. 提取旧表字段并导入新表（设置默认 slice_index=0, parent_id=NULL）
                    old_fields = [
                        "id", "youtube_id", "title", "channel_id", "score", "status", "retry_count", 
                        "error_msg", "created_at", "updated_at", "zh_title", "source", "duration_sec", 
                        "view_count", "like_count", "upload_date"
                    ]
                    # v7 系列列
                    for col in ["censor_tag", "censor_score", "is_manually_scored", "process_pid", "trim_start", "trim_end"]:
                        if col in columns:
                            old_fields.append(col)
                            
                    old_fields_str = ", ".join(old_fields)
                    
                    new_fields = [
                        "id", "youtube_id", "slice_index", "parent_id", "title", "channel_id", "score", 
                        "status", "retry_count", "error_msg", "created_at", "updated_at", "zh_title", 
                        "source", "duration_sec", "view_count", "like_count", "upload_date"
                    ]
                    for col in ["censor_tag", "censor_score", "is_manually_scored", "process_pid", "trim_start", "trim_end"]:
                        if col in columns:
                            new_fields.append(col)
                    new_fields_str = ", ".join(new_fields)
                    
                    # 导回，在 id, youtube_id 后补上常量 0 和 NULL
                    select_fields_str = "id, youtube_id, 0, NULL, " + ", ".join(old_fields[2:])
                    
                    cursor.execute(f"""
                        INSERT INTO processed_videos ({new_fields_str})
                        SELECT {select_fields_str}
                        FROM processed_videos_old
                    """)
                    
                    # 4. 删除旧表
                    cursor.execute("DROP TABLE processed_videos_old;")
                    
                    conn.commit()
                    self._logger.info("[Migration] Database schema successfully migrated.")
                except Exception as e:
                    conn.rollback()
                    self._logger.error(f"[Migration] Schema migration failed, rolled back: {e}")
                    raise e
            elif not columns:
                # 第一次初始建表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS processed_videos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        youtube_id TEXT NOT NULL,
                        slice_index INTEGER NOT NULL DEFAULT 0,
                        parent_id INTEGER DEFAULT NULL,
                        title TEXT NOT NULL,
                        channel_id TEXT NOT NULL,
                        score INTEGER DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'PENDING',
                        retry_count INTEGER DEFAULT 0,
                        error_msg TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        zh_title TEXT,
                        source TEXT DEFAULT 'AUTO',
                        content_type TEXT NOT NULL DEFAULT 'GENERAL',
                        duration_sec INTEGER DEFAULT NULL,
                        view_count INTEGER DEFAULT NULL,
                        like_count INTEGER DEFAULT NULL,
                        upload_date TEXT DEFAULT NULL,
                        source_published_at TEXT DEFAULT NULL,
                        censor_tag TEXT DEFAULT NULL,
                        censor_score INTEGER DEFAULT NULL,
                        is_manually_scored INTEGER DEFAULT 0,
                        process_pid INTEGER DEFAULT NULL,
                        trim_start TEXT DEFAULT NULL,
                        trim_end TEXT DEFAULT NULL,
                        disable_slicing INTEGER DEFAULT 1,
                        bypass_censorship INTEGER DEFAULT 0,
                        preparation_ready INTEGER DEFAULT 0,
                        source_subtitle_status TEXT DEFAULT 'PENDING',
                        source_subtitle_checked_at TIMESTAMP DEFAULT NULL,
                        UNIQUE(youtube_id, slice_index),
                        FOREIGN KEY(parent_id) REFERENCES processed_videos(id) ON DELETE CASCADE
                    )
                ''')

            # [Gemini_3.5_Flash_planning] 检查并补足 disable_slicing 字段，默认值为 1（禁用分片即整片发布）
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "disable_slicing" not in columns:
                self._logger.info("[Migration] Adding disable_slicing column to processed_videos table...")
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN disable_slicing INTEGER DEFAULT 1;")
                conn.commit()

            # [Claude_Sonnet_4.6_Thinking_planning] v2.9.0: 检查并补足 tts_provider 字段
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "tts_provider" not in columns:
                self._logger.info("[Migration] Adding tts_provider column to processed_videos table...")
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN tts_provider TEXT DEFAULT NULL;")
                conn.commit()

            # [Gemini_3.5_Flash_planning] 检查并补足 category 字段以存储视频的分类信息
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "category" not in columns:
                self._logger.info("[Migration] Adding category column to processed_videos table...")
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN category TEXT DEFAULT NULL;")
                conn.commit()

            # 内容生产类型独立于平台分类；历史记录兼容为 GENERAL，英语世界短视频显式写入。
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "content_type" not in columns:
                self._logger.info("[Migration] Adding content_type column to processed_videos table...")
                cursor.execute(
                    "ALTER TABLE processed_videos "
                    "ADD COLUMN content_type TEXT NOT NULL DEFAULT 'GENERAL';"
                )
                conn.commit()
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_processed_videos_content_type "
                "ON processed_videos(content_type)"
            )

            # [Claude_Opus_4.8] v3.6.0: 检查并补足 bypass_censorship 字段（人工复核放行标志）
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "bypass_censorship" not in columns:
                self._logger.info("[Migration] Adding bypass_censorship column to processed_videos table...")
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN bypass_censorship INTEGER DEFAULT 0;")
                conn.commit()

            # 源字幕先行预检与非窗口预加工状态。历史记录默认重新预检，避免直接
            # 将旧的未审源视频视作可下载候选。
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "preparation_ready" not in columns:
                self._logger.info("[Migration] Adding preparation_ready column to processed_videos table...")
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN preparation_ready INTEGER DEFAULT 0;")
                conn.commit()
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "publication_review_required" not in columns:
                self._logger.info("[Migration] Adding publication_review_required column to processed_videos table...")
                cursor.execute(
                    "ALTER TABLE processed_videos "
                    "ADD COLUMN publication_review_required INTEGER NOT NULL DEFAULT 0;"
                )
                conn.commit()
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "source_subtitle_status" not in columns:
                self._logger.info("[Migration] Adding source_subtitle_status column to processed_videos table...")
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN source_subtitle_status TEXT DEFAULT 'PENDING';")
                conn.commit()
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "source_subtitle_checked_at" not in columns:
                self._logger.info("[Migration] Adding source_subtitle_checked_at column to processed_videos table...")
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN source_subtitle_checked_at TIMESTAMP DEFAULT NULL;")
                conn.commit()

            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "source_published_at" not in columns:
                self._logger.info("[Migration] Adding source_published_at column to processed_videos table...")
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN source_published_at TEXT DEFAULT NULL;")
                conn.commit()


            # Score cache must not reuse updated_at: scoring itself updates that business
            # timestamp and would otherwise make every minute look like fresh metadata.
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "score_input_signature" not in columns:
                self._logger.info("[Migration] Adding score_input_signature to processed_videos table...")
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN score_input_signature TEXT DEFAULT NULL;")
                conn.commit()
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "score_computed_at" not in columns:
                self._logger.info("[Migration] Adding score_computed_at to processed_videos table...")
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN score_computed_at TIMESTAMP DEFAULT NULL;")
                conn.commit()

            # [Claude_Sonnet_4.6_Thinking_planning] v7.0 黑名单墓碑表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS blacklisted_videos (
                    youtube_id TEXT PRIMARY KEY,
                    reason     TEXT DEFAULT 'user_deleted',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 每次视频号补发领取都入账；日额度按领取而非单轮循环计数，避免
            # 15 分钟巡航把“每日 10 条”放大为“每轮 10 条”。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS wechat_deferred_recovery_claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_wechat_deferred_recovery_claims_day "
                "ON wechat_deferred_recovery_claims(claimed_at)"
            )

            # publication_subjects 对 Highlight Clip 有外键。在旧库首次升级时，这两个
            # 父表尚不存在；必须先建父表，才能在同一事务内把历史视频号账本迁移到主体层。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS highlight_jobs (
                    id TEXT PRIMARY KEY,
                    source_video_id INTEGER NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    state TEXT NOT NULL DEFAULT 'QUEUED'
                        CHECK(state IN ('QUEUED', 'ANALYZING', 'CANDIDATES_READY', 'RENDERING',
                                      'ASSETS_READY', 'FAILED', 'CANCELED')),
                    requested_by TEXT NOT NULL DEFAULT 'manual',
                    max_clips INTEGER NOT NULL DEFAULT 3,
                    min_duration_sec REAL NOT NULL DEFAULT 35,
                    max_duration_sec REAL NOT NULL DEFAULT 90,
                    workspace_path TEXT DEFAULT NULL,
                    source_subtitle_sha256 TEXT DEFAULT NULL,
                    plan_path TEXT DEFAULT NULL,
                    error_message TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_video_id, version),
                    FOREIGN KEY(source_video_id) REFERENCES processed_videos(id) ON DELETE RESTRICT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS highlight_clips (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT 'CANDIDATE'
                        CHECK(state IN ('CANDIDATE', 'SELECTED', 'RENDERING', 'ASSETS_READY',
                                      'FAILED', 'CANCELED')),
                    raw_start_ms INTEGER NOT NULL,
                    raw_end_ms INTEGER NOT NULL,
                    snapped_start_ms INTEGER DEFAULT NULL,
                    snapped_end_ms INTEGER DEFAULT NULL,
                    virality_score REAL NOT NULL,
                    core_quote TEXT NOT NULL DEFAULT '',
                    source_text TEXT NOT NULL DEFAULT '',
                    score_reason TEXT NOT NULL DEFAULT '',
                    selected INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(job_id, ordinal),
                    FOREIGN KEY(job_id) REFERENCES highlight_jobs(id) ON DELETE CASCADE
                )
            ''')
            # Highlight 产物只从独立 Clip 反查。即使源片已存在同名 cover/copy，
            # 也不能把它们当作这个独立发布主体的资产或证据。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS highlight_clip_assets (
                    clip_id TEXT PRIMARY KEY,
                    source_video_path TEXT NOT NULL,
                    source_video_sha256 TEXT NOT NULL,
                    source_video_kind TEXT NOT NULL,
                    rendered_video_path TEXT NOT NULL,
                    title_path TEXT NOT NULL,
                    copy_path TEXT NOT NULL,
                    category_path TEXT DEFAULT NULL,
                    cover_path TEXT NOT NULL,
                    cover_provenance_path TEXT NOT NULL,
                    artifact_manifest_path TEXT NOT NULL,
                    evidence_dir TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(clip_id) REFERENCES highlight_clips(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS highlight_clip_publication_reviews (
                    clip_id TEXT PRIMARY KEY,
                    asset_manifest_sha256 TEXT NOT NULL,
                    approved_by TEXT NOT NULL,
                    approved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(clip_id) REFERENCES highlight_clips(id) ON DELETE CASCADE
                )
            ''')

            # 发布主体是跨平台身份，不等同于既有 processed_videos 行。普通视频与
            # Highlight Clip 都先取得稳定主体 ID，随后才允许写入平台账本；这避免把
            # 多个 Highlight Clip 伪装成源片的 slice_index。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS publication_subjects (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK(kind IN ('VIDEO_ITEM', 'HIGHLIGHT_CLIP')),
                    video_id INTEGER DEFAULT NULL UNIQUE,
                    highlight_clip_id TEXT DEFAULT NULL UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CHECK(
                        (kind = 'VIDEO_ITEM' AND video_id IS NOT NULL AND highlight_clip_id IS NULL)
                        OR (kind = 'HIGHLIGHT_CLIP' AND video_id IS NULL AND highlight_clip_id IS NOT NULL)
                    ),
                    FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE CASCADE,
                    FOREIGN KEY(highlight_clip_id) REFERENCES highlight_clips(id) ON DELETE CASCADE
                )
            ''')

            # 视频号账本：提交截图只能证明平台受理，不能证明公开可见。
            # 不复用 processed_videos.updated_at（其会被后续评分刷新），以免把本地完成
            # 误报为平台侧可见。每个发布主体只保留一条最新确认结果。
            cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'wechat_publications'"
            )
            wechat_schema = (cursor.fetchone() or [""])[0] or ""
            cursor.execute("PRAGMA table_info(wechat_publications)")
            wechat_columns = {row[1] for row in cursor.fetchall()}
            needs_wechat_state_migration = bool(
                wechat_schema
                and (
                    "subject_id" not in wechat_columns
                    or "VIDEO_ID INTEGER NOT NULL" in wechat_schema.upper()
                    or any(
                        state not in wechat_schema
                        for state in (
                            "UNDER_REVIEW", "REJECTED", "NOT_FOUND", "SUBMITTED_UNBOUND", "SUBMITTED_BOUND",
                        )
                    )
                )
            )
            if needs_wechat_state_migration:
                self._logger.info("[Migration] Adding publication subject support to wechat_publications")
                cursor.execute("DROP INDEX IF EXISTS idx_wechat_publications_state")
                cursor.execute("ALTER TABLE wechat_publications RENAME TO wechat_publications_legacy")
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS wechat_publications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER DEFAULT NULL UNIQUE,
                    subject_id TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL CHECK(state IN ('PUBLISHED', 'UNDER_REVIEW', 'REJECTED', 'NOT_FOUND', 'UNCERTAIN', 'SUBMITTED_UNBOUND', 'SUBMITTED_BOUND')),
                    evidence_path TEXT DEFAULT NULL,
                    confirmed_at TIMESTAMP DEFAULT NULL,
                    platform_post_id TEXT DEFAULT NULL,
                    platform_url TEXT DEFAULT NULL,
                    last_reconciled_at TIMESTAMP DEFAULT NULL,
                    last_error_message TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE RESTRICT,
                    FOREIGN KEY(subject_id) REFERENCES publication_subjects(id) ON DELETE RESTRICT
                )
            ''')
            if needs_wechat_state_migration:
                cursor.execute('''
                    INSERT OR IGNORE INTO publication_subjects (id, kind, video_id)
                    SELECT 'video:' || video_id, 'VIDEO_ITEM', video_id
                    FROM wechat_publications_legacy
                    WHERE video_id IS NOT NULL
                ''')
                platform_post_id_expr = "platform_post_id" if "platform_post_id" in wechat_columns else "NULL"
                platform_url_expr = "platform_url" if "platform_url" in wechat_columns else "NULL"
                last_reconciled_at_expr = (
                    "last_reconciled_at" if "last_reconciled_at" in wechat_columns else "NULL"
                )
                subject_id_expr = (
                    "COALESCE(subject_id, CASE WHEN video_id IS NOT NULL THEN 'video:' || video_id END)"
                    if "subject_id" in wechat_columns else "'video:' || video_id"
                )
                cursor.execute('''
                    INSERT INTO wechat_publications (
                        id, video_id, subject_id, state, evidence_path, confirmed_at, platform_post_id,
                        platform_url, last_reconciled_at, last_error_message, created_at, updated_at
                    ) SELECT id, video_id, {subject_id}, state, evidence_path, confirmed_at, {platform_post_id},
                        {platform_url}, {last_reconciled_at}, last_error_message, created_at, updated_at
                    FROM wechat_publications_legacy
                '''.format(
                    subject_id=subject_id_expr,
                    platform_post_id=platform_post_id_expr,
                    platform_url=platform_url_expr,
                    last_reconciled_at=last_reconciled_at_expr,
                ))
                cursor.execute("DROP TABLE wechat_publications_legacy")

            cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'wechat_submission_attempts'"
            )
            attempt_schema = (cursor.fetchone() or [""])[0] or ""
            cursor.execute("PRAGMA table_info(wechat_submission_attempts)")
            attempt_columns = {row[1] for row in cursor.fetchall()}
            migrate_wechat_attempts = bool(
                attempt_schema
                and (
                    "subject_id" not in attempt_columns
                    or "VIDEO_ID INTEGER NOT NULL" in attempt_schema.upper()
                )
            )
            if migrate_wechat_attempts:
                cursor.execute("ALTER TABLE wechat_submission_attempts RENAME TO wechat_submission_attempts_legacy")
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS wechat_submission_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    video_id INTEGER DEFAULT NULL,
                    subject_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('SUBMITTED_UNBOUND', 'PLATFORM_ID_BOUND')),
                    final_title TEXT NOT NULL,
                    final_title_sha256 TEXT DEFAULT NULL,
                    video_sha256 TEXT DEFAULT NULL,
                    cover_sha256 TEXT DEFAULT NULL,
                    evidence_path TEXT DEFAULT NULL,
                    platform_post_id TEXT DEFAULT NULL UNIQUE,
                    platform_url TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    bound_at TIMESTAMP DEFAULT NULL,
                    FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE CASCADE,
                    FOREIGN KEY(subject_id) REFERENCES publication_subjects(id) ON DELETE RESTRICT
                )
            ''')
            if migrate_wechat_attempts:
                cursor.execute('''
                    INSERT OR IGNORE INTO publication_subjects (id, kind, video_id)
                    SELECT 'video:' || video_id, 'VIDEO_ITEM', video_id
                    FROM wechat_submission_attempts_legacy
                    WHERE video_id IS NOT NULL
                ''')
                attempt_subject_expr = (
                    "COALESCE(subject_id, CASE WHEN video_id IS NOT NULL THEN 'video:' || video_id END)"
                    if "subject_id" in attempt_columns else "'video:' || video_id"
                )
                cursor.execute('''
                    INSERT INTO wechat_submission_attempts (
                        attempt_id, video_id, subject_id, state, final_title, final_title_sha256,
                        video_sha256, cover_sha256, evidence_path, platform_post_id, platform_url,
                        created_at, bound_at
                    ) SELECT attempt_id, video_id, {subject_id}, state, final_title, final_title_sha256,
                        video_sha256, cover_sha256, evidence_path, platform_post_id, platform_url,
                        created_at, bound_at
                    FROM wechat_submission_attempts_legacy
                '''.format(subject_id=attempt_subject_expr))
                cursor.execute("DROP TABLE wechat_submission_attempts_legacy")
            cursor.execute("PRAGMA table_info(wechat_publications_historical_archive)")
            wechat_archive_columns = {row[1] for row in cursor.fetchall()}
            migrate_wechat_archive = bool(
                wechat_archive_columns and "archive_id" not in wechat_archive_columns
            )
            if migrate_wechat_archive:
                cursor.execute(
                    "ALTER TABLE wechat_publications_historical_archive "
                    "RENAME TO wechat_publications_historical_archive_legacy"
                )
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS wechat_publications_historical_archive (
                    archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_publication_id INTEGER,
                    archived_at TIMESTAMP NOT NULL,
                    archive_reason TEXT NOT NULL,
                    video_id INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    evidence_path TEXT DEFAULT NULL,
                    confirmed_at TIMESTAMP DEFAULT NULL,
                    platform_post_id TEXT DEFAULT NULL,
                    platform_url TEXT DEFAULT NULL,
                    last_reconciled_at TIMESTAMP DEFAULT NULL,
                    last_error_message TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT NULL,
                    updated_at TIMESTAMP DEFAULT NULL,
                    UNIQUE(video_id, evidence_path),
                    FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE RESTRICT
                )
            ''')
            if migrate_wechat_archive:
                cursor.execute('''
                    INSERT INTO wechat_publications_historical_archive (
                        original_publication_id, archived_at, archive_reason, video_id, state,
                        evidence_path, confirmed_at, platform_post_id, platform_url,
                        last_reconciled_at, last_error_message, created_at, updated_at
                    ) SELECT publication_id, archived_at, archive_reason, video_id, state,
                        evidence_path, confirmed_at, platform_post_id, platform_url,
                        last_reconciled_at, last_error_message, created_at, updated_at
                    FROM wechat_publications_historical_archive_legacy
                ''')
                cursor.execute("DROP TABLE wechat_publications_historical_archive_legacy")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_wechat_publications_state "
                "ON wechat_publications(state, confirmed_at, updated_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_wechat_submission_attempts_subject "
                "ON wechat_submission_attempts(subject_id, created_at DESC)"
            )
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS manual_publish_leases (
                    lease_id TEXT PRIMARY KEY,
                    video_id INTEGER NOT NULL,
                    platform TEXT NOT NULL CHECK(platform IN ('wechat')),
                    issued_by TEXT NOT NULL,
                    issued_via TEXT NOT NULL,
                    issued_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    claimed_at TIMESTAMP DEFAULT NULL,
                    revoked_at TIMESTAMP DEFAULT NULL,
                    revoked_by TEXT DEFAULT NULL,
                    FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute("PRAGMA table_info(manual_publish_leases)")
            lease_columns = {row[1] for row in cursor.fetchall()}
            if "revoked_by" not in lease_columns:
                cursor.execute(
                    "ALTER TABLE manual_publish_leases ADD COLUMN revoked_by TEXT DEFAULT NULL"
                )
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_manual_publish_leases_active
                ON manual_publish_leases(video_id, platform, expires_at, claimed_at, revoked_at)
            ''')

            # 快手发布账本：仅“已发布”的成片摘要禁止再次投递；失败、临时上传和未发布草稿
            # 都保留为独立尝试，允许用户重试。它独立于 processed_videos 的微信状态。
            cursor.execute("PRAGMA table_info(kuaishou_publications)")
            kuaishou_columns = {row[1] for row in cursor.fetchall()}
            cursor.execute("PRAGMA table_info(kuaishou_publications_legacy)")
            kuaishou_legacy_columns = {row[1] for row in cursor.fetchall()}
            cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'kuaishou_publications'")
            kuaishou_schema = (cursor.fetchone() or [""])[0] or ""
            cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'kuaishou_publications_legacy'"
            )
            kuaishou_legacy_exists = cursor.fetchone() is not None
            recover_kuaishou_legacy = False
            if kuaishou_legacy_exists:
                current_count = 0
                if kuaishou_columns:
                    current_count = cursor.execute("SELECT COUNT(*) FROM kuaishou_publications").fetchone()[0]
                recover_kuaishou_legacy = current_count == 0
            migrate_kuaishou_ledger = bool(
                recover_kuaishou_legacy
                or (
                    kuaishou_columns
                    and (
                        "attempt_number" not in kuaishou_columns
                        or "UNDER_REVIEW" not in kuaishou_schema
                        or "CANCELED" not in kuaishou_schema
                    )
                )
            )
            if migrate_kuaishou_ledger and not recover_kuaishou_legacy:
                cursor.execute("ALTER TABLE kuaishou_publications RENAME TO kuaishou_publications_legacy")
                kuaishou_legacy_columns = kuaishou_columns
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS kuaishou_publications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    asset_sha256 TEXT NOT NULL,
                    source_kind TEXT NOT NULL CHECK(source_kind IN ('HISTORY', 'NEW')),
                    state TEXT NOT NULL DEFAULT 'QUEUED'
                        CHECK(state IN ('QUEUED', 'UPLOADING', 'DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETRYABLE_FAILED', 'UNCERTAIN', 'BANNED', 'CANCELED')),
                    video_path TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL DEFAULT 1,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    claimed_at TIMESTAMP DEFAULT NULL,
                    published_at TIMESTAMP DEFAULT NULL,
                    external_post_id TEXT DEFAULT NULL,
                    external_url TEXT DEFAULT NULL,
                    last_error_message TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(video_id, attempt_number),
                    FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE RESTRICT
                )
            ''')
            if migrate_kuaishou_ledger:
                attempt_number_expr = (
                    "ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY COALESCE(attempt_number, 0), id)"
                    if "attempt_number" in kuaishou_legacy_columns
                    else "ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY id)"
                )
                cursor.execute('''
                    INSERT INTO kuaishou_publications (
                        id, video_id, asset_sha256, source_kind, state, video_path, attempt_number,
                        attempt_count, claimed_at, published_at, external_post_id, external_url,
                        last_error_message, created_at, updated_at
                    )
                    SELECT id, video_id, asset_sha256, source_kind,
                           CASE WHEN state IN ('UPLOADING', 'UPLOADED', 'UNCERTAIN')
                                THEN 'RETRYABLE_FAILED' ELSE state END,
                           video_path, {attempt_number_expr}, attempt_count, claimed_at, published_at,
                           external_post_id, external_url,
                           CASE WHEN state IN ('UPLOADING', 'UPLOADED', 'UNCERTAIN')
                                THEN '作品管理未确认可见，迁移为可重试尝试'
                                ELSE last_error_message END,
                           created_at, updated_at
                    FROM kuaishou_publications_legacy
                '''.format(attempt_number_expr=attempt_number_expr))
                cursor.execute("DROP TABLE kuaishou_publications_legacy")

            # 抖音发布账本：沿用快手的安全语义，但保持独立表，避免平台状态互相污染。
            cursor.execute("PRAGMA table_info(douyin_publications)")
            douyin_columns = {row[1] for row in cursor.fetchall()}
            cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'douyin_publications'")
            douyin_schema = (cursor.fetchone() or [""])[0] or ""
            migrate_douyin_ledger = bool(douyin_columns and "CANCELED" not in douyin_schema)
            if migrate_douyin_ledger:
                cursor.execute("ALTER TABLE douyin_publications RENAME TO douyin_publications_legacy")
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS douyin_publications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    asset_sha256 TEXT NOT NULL,
                    source_kind TEXT NOT NULL CHECK(source_kind IN ('HISTORY', 'NEW')),
                    state TEXT NOT NULL DEFAULT 'QUEUED'
                        CHECK(state IN ('QUEUED', 'UPLOADING', 'DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETRYABLE_FAILED', 'UNCERTAIN', 'BANNED', 'CANCELED')),
                    video_path TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL DEFAULT 1,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    claimed_at TIMESTAMP DEFAULT NULL,
                    published_at TIMESTAMP DEFAULT NULL,
                    external_post_id TEXT DEFAULT NULL,
                    external_url TEXT DEFAULT NULL,
                    last_error_message TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(video_id, attempt_number),
                    FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE RESTRICT
                )
            ''')
            if migrate_douyin_ledger:
                cursor.execute('''
                    INSERT INTO douyin_publications (
                        id, video_id, asset_sha256, source_kind, state, video_path, attempt_number,
                        attempt_count, claimed_at, published_at, external_post_id, external_url,
                        last_error_message, created_at, updated_at
                    )
                    SELECT id, video_id, asset_sha256, source_kind, state, video_path, attempt_number,
                           attempt_count, claimed_at, published_at, external_post_id, external_url,
                           last_error_message, created_at, updated_at
                    FROM douyin_publications_legacy
                ''')
                cursor.execute("DROP TABLE douyin_publications_legacy")

            # AI 调用审计：仅保存可观测性元数据，禁止保存密钥、完整 prompt 或原始字幕。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ai_processing_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_id TEXT NOT NULL,
                    slice_index INTEGER NOT NULL DEFAULT 0,
                    operation TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'RUNNING',
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    finished_at TIMESTAMP DEFAULT NULL,
                    final_provider TEXT DEFAULT NULL,
                    fallback_used INTEGER NOT NULL DEFAULT 0,
                    quality_score REAL DEFAULT NULL,
                    chinese_coverage REAL DEFAULT NULL,
                    vocabulary_segments INTEGER DEFAULT NULL,
                    quality_status TEXT DEFAULT NULL,
                    error_class TEXT DEFAULT NULL,
                    error_message TEXT DEFAULT NULL
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ai_provider_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT DEFAULT NULL,
                    capabilities TEXT DEFAULT NULL,
                    attempt_order INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    duration_ms INTEGER DEFAULT NULL,
                    error_class TEXT DEFAULT NULL,
                    error_message TEXT DEFAULT NULL,
                    quality_score REAL DEFAULT NULL,
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    blocking_count INTEGER NOT NULL DEFAULT 0,
                    selected INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(run_id) REFERENCES ai_processing_runs(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS censorship_incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER DEFAULT NULL,
                    youtube_id TEXT NOT NULL,
                    slice_index INTEGER NOT NULL DEFAULT 0,
                    stage TEXT NOT NULL,
                    level TEXT DEFAULT NULL,
                    action TEXT DEFAULT NULL,
                    tag TEXT DEFAULT NULL,
                    score INTEGER DEFAULT NULL,
                    matched TEXT DEFAULT NULL,
                    channel TEXT DEFAULT NULL,
                    decision TEXT NOT NULL,
                    rule_pack_version TEXT DEFAULT NULL,
                    rule_id TEXT DEFAULT NULL,
                    source_field TEXT DEFAULT NULL,
                    review_stage TEXT DEFAULT NULL,
                    platform TEXT DEFAULT NULL,
                    input_hash TEXT DEFAULT NULL,
                    title TEXT DEFAULT NULL,
                    zh_title TEXT DEFAULT NULL,
                    description_preview TEXT DEFAULT NULL,
                    text_excerpt TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE SET NULL
                )
            ''')

            # 配音再制中心账本独立于 processed_videos：源片状态、产物和既有平台记录绝不被改写。
            # 当前仅由人工入口创建；PipelineManager 不读取这些表。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS dubbing_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_video_id INTEGER NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    state TEXT NOT NULL DEFAULT 'DRAFT'
                        CHECK(state IN ('DRAFT', 'ANALYZING', 'SCRIPT_READY', 'SYNTHESIZING',
                                      'ALIGNING', 'RENDERING', 'QA_REQUIRED', 'READY_TO_PUBLISH',
                                      'PUBLISHING', 'UNDER_REVIEW', 'PUBLISHED', 'NEEDS_REWRITE',
                                      'FAILED', 'CANCELED')),
                    provider TEXT NOT NULL DEFAULT 'minimax',
                    model TEXT NOT NULL,
                    voice_id TEXT NOT NULL,
                    requested_platforms TEXT NOT NULL DEFAULT '[]',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    workspace_path TEXT DEFAULT NULL,
                    narration_path TEXT DEFAULT NULL,
                    subtitle_path TEXT DEFAULT NULL,
                    output_video_path TEXT DEFAULT NULL,
                    qa_report_path TEXT DEFAULT NULL,
                    asset_sha256 TEXT DEFAULT NULL,
                    error_message TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_video_id, version),
                    FOREIGN KEY(source_video_id) REFERENCES processed_videos(id) ON DELETE RESTRICT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS dubbing_speakers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    speaker_key TEXT NOT NULL,
                    voice_id TEXT DEFAULT NULL,
                    mapping_source TEXT NOT NULL DEFAULT 'DEFAULT',
                    confidence REAL DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(job_id, speaker_key),
                    FOREIGN KEY(job_id) REFERENCES dubbing_jobs(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS dubbing_utterances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    ordinal INTEGER NOT NULL,
                    speaker_key TEXT NOT NULL DEFAULT 'NARRATOR',
                    source_start_ms INTEGER NOT NULL,
                    source_end_ms INTEGER NOT NULL,
                    source_text TEXT NOT NULL DEFAULT '',
                    zh_text TEXT NOT NULL,
                    actual_start_ms INTEGER DEFAULT NULL,
                    actual_end_ms INTEGER DEFAULT NULL,
                    actual_duration_ms INTEGER DEFAULT NULL,
                    speed REAL DEFAULT NULL,
                    alignment_strategy TEXT DEFAULT NULL,
                    synthesis_attempts INTEGER NOT NULL DEFAULT 0,
                    cache_key TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(job_id, ordinal),
                    FOREIGN KEY(job_id) REFERENCES dubbing_jobs(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS dubbing_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    artifact_kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    sha256 TEXT DEFAULT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(job_id, artifact_kind),
                    FOREIGN KEY(job_id) REFERENCES dubbing_jobs(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS dubbing_publications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    platform TEXT NOT NULL CHECK(platform IN ('wechat', 'douyin', 'kuaishou')),
                    state TEXT NOT NULL DEFAULT 'QUEUED'
                        CHECK(state IN ('QUEUED', 'UPLOADING', 'DRAFT', 'UNDER_REVIEW', 'PUBLISHED',
                                      'RETRYABLE_FAILED', 'UNCERTAIN', 'BANNED', 'CANCELED')),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    external_post_id TEXT DEFAULT NULL,
                    external_url TEXT DEFAULT NULL,
                    last_error_message TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(job_id, platform),
                    FOREIGN KEY(job_id) REFERENCES dubbing_jobs(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_dubbing_jobs_source ON dubbing_jobs(source_video_id, updated_at DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_dubbing_utterances_job ON dubbing_utterances(job_id, ordinal)")

            # Highlight 切片任务是对源视频的显式、独立派生，不允许改写原视频状态、原章节任务或发布账本。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS highlight_jobs (
                    id TEXT PRIMARY KEY,
                    source_video_id INTEGER NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    state TEXT NOT NULL DEFAULT 'QUEUED'
                        CHECK(state IN ('QUEUED', 'ANALYZING', 'CANDIDATES_READY', 'RENDERING',
                                      'ASSETS_READY', 'FAILED', 'CANCELED')),
                    requested_by TEXT NOT NULL DEFAULT 'manual',
                    max_clips INTEGER NOT NULL DEFAULT 3,
                    min_duration_sec REAL NOT NULL DEFAULT 35,
                    max_duration_sec REAL NOT NULL DEFAULT 90,
                    workspace_path TEXT DEFAULT NULL,
                    source_subtitle_sha256 TEXT DEFAULT NULL,
                    plan_path TEXT DEFAULT NULL,
                    error_message TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_video_id, version),
                    FOREIGN KEY(source_video_id) REFERENCES processed_videos(id) ON DELETE RESTRICT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS highlight_clips (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT 'CANDIDATE'
                        CHECK(state IN ('CANDIDATE', 'SELECTED', 'RENDERING', 'ASSETS_READY',
                                      'FAILED', 'CANCELED')),
                    raw_start_ms INTEGER NOT NULL,
                    raw_end_ms INTEGER NOT NULL,
                    snapped_start_ms INTEGER DEFAULT NULL,
                    snapped_end_ms INTEGER DEFAULT NULL,
                    virality_score REAL NOT NULL,
                    core_quote TEXT NOT NULL DEFAULT '',
                    source_text TEXT NOT NULL DEFAULT '',
                    score_reason TEXT NOT NULL DEFAULT '',
                    selected INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(job_id, ordinal),
                    FOREIGN KEY(job_id) REFERENCES highlight_jobs(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_highlight_jobs_source "
                "ON highlight_jobs(source_video_id, updated_at DESC)"
            )
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_highlight_jobs_one_active_source "
                "ON highlight_jobs(source_video_id) WHERE state IN ('QUEUED', 'ANALYZING', 'RENDERING')"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_highlight_clips_job ON highlight_clips(job_id, ordinal)"
            )

            # 英语世界短视频的选题和生产请求是独立学习内容账本。它不把尚未审核的
            # 外部来源塞进 processed_videos，也不创建发布主体或任何平台账本记录。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS english_world_jobs (
                    id TEXT PRIMARY KEY,
                    state TEXT NOT NULL DEFAULT 'RESEARCH_QUEUED'
                        CHECK(state IN ('RESEARCH_QUEUED', 'RESEARCHING', 'CANDIDATES_READY',
                                      'CANDIDATE_SELECTED', 'PRODUCTION_REQUESTED', 'FAILED', 'CANCELED')),
                    requested_by TEXT NOT NULL DEFAULT 'manual',
                    notification_target TEXT DEFAULT NULL,
                    source_url TEXT DEFAULT NULL,
                    selected_candidate_id TEXT DEFAULT NULL,
                    error_message TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS english_world_candidates (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    source_url TEXT NOT NULL,
                    youtube_id TEXT DEFAULT NULL,
                    source_title TEXT NOT NULL,
                    source_channel TEXT DEFAULT NULL,
                    source_channel_id TEXT DEFAULT NULL,
                    upload_date TEXT DEFAULT NULL,
                    duration_sec INTEGER DEFAULT NULL,
                    topic TEXT NOT NULL,
                    learning_value TEXT NOT NULL,
                    safety_note TEXT NOT NULL,
                    caption_status TEXT NOT NULL,
                    recommendation_score INTEGER NOT NULL DEFAULT 0,
                    selected INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(job_id, ordinal),
                    FOREIGN KEY(job_id) REFERENCES english_world_jobs(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_english_world_jobs_updated "
                "ON english_world_jobs(updated_at DESC)"
            )
            cursor.execute("PRAGMA table_info(english_world_jobs)")
            english_world_job_columns = {row[1] for row in cursor.fetchall()}
            for column_name, column_type in (
                ("production_state", "TEXT DEFAULT NULL"),
                ("review_id", "TEXT DEFAULT NULL"),
                ("mp4_path", "TEXT DEFAULT NULL"),
                ("manifest_path", "TEXT DEFAULT NULL"),
                ("production_started_at", "TIMESTAMP DEFAULT NULL"),
                ("production_finished_at", "TIMESTAMP DEFAULT NULL"),
            ):
                if column_name not in english_world_job_columns:
                    cursor.execute(
                        f"ALTER TABLE english_world_jobs ADD COLUMN {column_name} {column_type}"
                    )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_english_world_candidates_job "
                "ON english_world_candidates(job_id, ordinal)"
            )
            cursor.execute("PRAGMA table_info(english_world_candidates)")
            english_world_candidate_columns = {row[1] for row in cursor.fetchall()}
            if "source_channel_id" not in english_world_candidate_columns:
                cursor.execute(
                    "ALTER TABLE english_world_candidates ADD COLUMN source_channel_id TEXT DEFAULT NULL"
                )

            # 英语世界学习卡的 Telegram 审核/投稿账本。它与选题账本、通用视频
            # 状态机和 platform_publications 完全隔离：一个审核项只绑定一个成片
            # 摘要，审批后才能由专用投稿器领取，任何失败/未确认状态都不会自动重传。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS english_world_review_items (
                    id TEXT PRIMARY KEY,
                    state TEXT NOT NULL DEFAULT 'READY_FOR_REVIEW'
                        CHECK(state IN ('READY_FOR_REVIEW', 'SUBMISSION_APPROVED', 'SUBMITTING',
                                      'UNDER_REVIEW', 'UNCERTAIN', 'LOGIN_REQUIRED', 'FAILED', 'HELD')),
                    artifact_sha256 TEXT NOT NULL UNIQUE,
                    manifest_sha256 TEXT DEFAULT NULL,
                    title_sha256 TEXT DEFAULT NULL,
                    copy_sha256 TEXT DEFAULT NULL,
                    cover_sha256 TEXT DEFAULT NULL,
                    cover_provenance_sha256 TEXT DEFAULT NULL,
                    title TEXT NOT NULL,
                    content_type TEXT NOT NULL DEFAULT 'ENGLISH_WORLD_SHORT',
                    mp4_path TEXT NOT NULL,
                    manifest_path TEXT NOT NULL,
                    title_path TEXT NOT NULL,
                    copy_path TEXT NOT NULL,
                    cover_path TEXT NOT NULL,
                    cover_provenance_path TEXT NOT NULL,
                    source_url TEXT DEFAULT NULL,
                    source_title TEXT DEFAULT NULL,
                    source_publisher TEXT DEFAULT NULL,
                    source_youtube_id TEXT DEFAULT NULL,
                    notification_target TEXT DEFAULT NULL,
                    approved_at TIMESTAMP DEFAULT NULL,
                    approval_source TEXT DEFAULT NULL,
                    authorization_expires_at TIMESTAMP DEFAULT NULL,
                    login_recovery_attempts INTEGER NOT NULL DEFAULT 0,
                    original_declaration_recovery_attempts INTEGER NOT NULL DEFAULT 0,
                    submission_started_at TIMESTAMP DEFAULT NULL,
                    submission_finished_at TIMESTAMP DEFAULT NULL,
                    uploader_exit_code INTEGER DEFAULT NULL,
                    evidence_dir TEXT DEFAULT NULL,
                    platform_post_id TEXT DEFAULT NULL,
                    platform_url TEXT DEFAULT NULL,
                    platform_state TEXT DEFAULT NULL,
                    reconciliation_evidence_dir TEXT DEFAULT NULL,
                    last_reconciled_at TIMESTAMP DEFAULT NULL,
                    reconciliation_failures INTEGER NOT NULL DEFAULT 0,
                    reconciliation_error TEXT DEFAULT NULL,
                    error_message TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_english_world_review_items_updated "
                "ON english_world_review_items(updated_at DESC)"
            )
            cursor.execute("PRAGMA table_info(english_world_review_items)")
            english_world_review_columns = {row[1] for row in cursor.fetchall()}
            if "approval_source" not in english_world_review_columns:
                cursor.execute("ALTER TABLE english_world_review_items ADD COLUMN approval_source TEXT DEFAULT NULL")
            if "login_recovery_attempts" not in english_world_review_columns:
                cursor.execute(
                    "ALTER TABLE english_world_review_items "
                    "ADD COLUMN login_recovery_attempts INTEGER NOT NULL DEFAULT 0"
                )
            if "original_declaration_recovery_attempts" not in english_world_review_columns:
                cursor.execute(
                    "ALTER TABLE english_world_review_items "
                    "ADD COLUMN original_declaration_recovery_attempts INTEGER NOT NULL DEFAULT 0"
                )
            if "authorization_expires_at" not in english_world_review_columns:
                cursor.execute(
                    "ALTER TABLE english_world_review_items "
                    "ADD COLUMN authorization_expires_at TIMESTAMP DEFAULT NULL"
                )
            for hash_column in (
                "manifest_sha256", "title_sha256", "copy_sha256",
                "cover_sha256", "cover_provenance_sha256",
            ):
                if hash_column not in english_world_review_columns:
                    cursor.execute(
                        f"ALTER TABLE english_world_review_items ADD COLUMN {hash_column} TEXT DEFAULT NULL"
                    )
            for column_name, column_type in (
                ("platform_post_id", "TEXT DEFAULT NULL"),
                ("platform_url", "TEXT DEFAULT NULL"),
                ("platform_state", "TEXT DEFAULT NULL"),
                ("reconciliation_evidence_dir", "TEXT DEFAULT NULL"),
                ("last_reconciled_at", "TIMESTAMP DEFAULT NULL"),
                ("reconciliation_failures", "INTEGER NOT NULL DEFAULT 0"),
                ("reconciliation_error", "TEXT DEFAULT NULL"),
            ):
                if column_name not in english_world_review_columns:
                    cursor.execute(
                        f"ALTER TABLE english_world_review_items ADD COLUMN {column_name} {column_type}"
                    )
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_english_world_review_platform_post "
                "ON english_world_review_items(platform_post_id) WHERE platform_post_id IS NOT NULL"
            )

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS english_world_submission_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    review_id TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'SUBMITTING'
                        CHECK(state IN ('SUBMITTING', 'UNDER_REVIEW', 'UNCERTAIN',
                                      'LOGIN_REQUIRED', 'FAILED')),
                    approval_source TEXT DEFAULT NULL,
                    artifact_sha256 TEXT NOT NULL,
                    manifest_sha256 TEXT DEFAULT NULL,
                    title_sha256 TEXT DEFAULT NULL,
                    copy_sha256 TEXT DEFAULT NULL,
                    cover_sha256 TEXT DEFAULT NULL,
                    cover_provenance_sha256 TEXT DEFAULT NULL,
                    evidence_dir TEXT DEFAULT NULL,
                    platform_post_id TEXT DEFAULT NULL,
                    platform_url TEXT DEFAULT NULL,
                    uploader_exit_code INTEGER DEFAULT NULL,
                    error_message TEXT DEFAULT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    finished_at TIMESTAMP DEFAULT NULL,
                    FOREIGN KEY(review_id) REFERENCES english_world_review_items(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_english_world_submission_attempts_review "
                "ON english_world_submission_attempts(review_id, started_at DESC)"
            )
            cursor.execute("PRAGMA table_info(english_world_submission_attempts)")
            english_world_attempt_columns = {row[1] for row in cursor.fetchall()}
            for column_name in ("platform_post_id", "platform_url"):
                if column_name not in english_world_attempt_columns:
                    cursor.execute(
                        f"ALTER TABLE english_world_submission_attempts ADD COLUMN {column_name} TEXT DEFAULT NULL"
                    )

            # 英语世界保持独立于 processed_videos；抖音同步用自己的单条账本和不可变尝试，
            # 仅以视频号同一审核项已受理为上游资格，不复用通用队列或视频状态机。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS english_world_douyin_publications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    review_id TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL DEFAULT 'QUEUED'
                        CHECK(state IN ('QUEUED', 'SUBMITTING', 'UNDER_REVIEW', 'PUBLISHED',
                                        'LOGIN_REQUIRED', 'UNCERTAIN', 'CANCELED', 'FAILED')),
                    artifact_sha256 TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    claimed_at TIMESTAMP DEFAULT NULL,
                    submitted_at TIMESTAMP DEFAULT NULL,
                    published_at TIMESTAMP DEFAULT NULL,
                    evidence_dir TEXT DEFAULT NULL,
                    platform_state TEXT DEFAULT NULL,
                    last_reconciled_at TIMESTAMP DEFAULT NULL,
                    reconciliation_failures INTEGER NOT NULL DEFAULT 0,
                    recovery_authorized_at TIMESTAMP DEFAULT NULL,
                    recovery_reason TEXT DEFAULT NULL,
                    last_error_message TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(review_id) REFERENCES english_world_review_items(id) ON DELETE RESTRICT
                )
            ''')
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_english_world_douyin_state "
                "ON english_world_douyin_publications(state, claimed_at, created_at)"
            )
            cursor.execute("PRAGMA table_info(english_world_douyin_publications)")
            english_world_douyin_columns = {row[1] for row in cursor.fetchall()}
            for column_name in ("recovery_authorized_at", "recovery_reason"):
                if column_name not in english_world_douyin_columns:
                    cursor.execute(
                        f"ALTER TABLE english_world_douyin_publications ADD COLUMN {column_name} TEXT DEFAULT NULL"
                    )
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS english_world_douyin_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    review_id TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'SUBMITTING'
                        CHECK(state IN ('SUBMITTING', 'UNDER_REVIEW', 'PUBLISHED',
                                        'LOGIN_REQUIRED', 'UNCERTAIN', 'CANCELED', 'FAILED')),
                    artifact_sha256 TEXT NOT NULL,
                    evidence_dir TEXT DEFAULT NULL,
                    uploader_exit_code INTEGER DEFAULT NULL,
                    error_message TEXT DEFAULT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    finished_at TIMESTAMP DEFAULT NULL,
                    FOREIGN KEY(review_id) REFERENCES english_world_review_items(id) ON DELETE RESTRICT
                )
            ''')
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_english_world_douyin_attempts_review "
                "ON english_world_douyin_attempts(review_id, started_at DESC)"
            )

            # Telegram 投递回执与业务状态分开保存。HTTP 超时不能证明未送达，故以
            # UNKNOWN 保留不确定性供人工排障；它不能作为已送达依据，更不能抑制重试。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS telegram_notification_receipts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    priority TEXT NOT NULL CHECK(priority IN ('P0', 'P1', 'P2')),
                    content_sha256 TEXT NOT NULL,
                    delivery_state TEXT NOT NULL
                        CHECK(delivery_state IN ('ACCEPTED', 'UNKNOWN', 'FAILED', 'SUPPRESSED')),
                    telegram_message_id TEXT DEFAULT NULL,
                    error_kind TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_telegram_notification_receipts_dedupe "
                "ON telegram_notification_receipts(event_type, content_sha256, created_at DESC)"
            )

            # 发布后数据地基：日粒度指标只记录事实读数，不反推平台发布成功状态。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS published_video_daily_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    platform TEXT NOT NULL CHECK(platform IN ('wechat', 'douyin', 'kuaishou', 'xiaohongshu')),
                    metric_date TEXT NOT NULL,
                    impression_count INTEGER NOT NULL DEFAULT 0,
                    click_count INTEGER NOT NULL DEFAULT 0,
                    view_count INTEGER NOT NULL DEFAULT 0,
                    like_count INTEGER NOT NULL DEFAULT 0,
                    share_count INTEGER NOT NULL DEFAULT 0,
                    comment_count INTEGER NOT NULL DEFAULT 0,
                    favorite_count INTEGER NOT NULL DEFAULT 0,
                    follow_count INTEGER NOT NULL DEFAULT 0,
                    watch_seconds INTEGER DEFAULT NULL,
                    avg_watch_seconds REAL DEFAULT NULL,
                    completion_rate REAL DEFAULT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(video_id, platform, metric_date),
                    FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS video_content_identities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_key TEXT NOT NULL UNIQUE,
                    source_kind TEXT NOT NULL DEFAULT 'MANUAL'
                        CHECK(source_kind IN ('SOURCE', 'ASSET', 'TRANSCRIPT', 'MANUAL', 'MIXED')),
                    fingerprint_hash TEXT DEFAULT NULL UNIQUE,
                    canonical_video_id INTEGER DEFAULT NULL,
                    normalized_title TEXT DEFAULT NULL,
                    duration_sec INTEGER DEFAULT NULL,
                    notes TEXT DEFAULT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(canonical_video_id) REFERENCES processed_videos(id) ON DELETE SET NULL
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS video_content_links (
                    video_id INTEGER PRIMARY KEY,
                    content_identity_id INTEGER NOT NULL,
                    relationship_to_content TEXT NOT NULL DEFAULT 'UNKNOWN'
                        CHECK(relationship_to_content IN ('ORIGINAL', 'CUT', 'DUBBING', 'TRANSLATION', 'REMIX', 'VARIANT', 'UNKNOWN')),
                    variant_key TEXT DEFAULT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE CASCADE,
                    FOREIGN KEY(content_identity_id) REFERENCES video_content_identities(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS video_relationships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parent_video_id INTEGER NOT NULL,
                    child_video_id INTEGER NOT NULL,
                    relation_type TEXT NOT NULL
                        CHECK(relation_type IN ('SLICE_OF', 'DERIVED_FROM', 'DUBBING_OF', 'TRANSLATION_OF', 'REMIX_OF', 'AB_VARIANT_OF', 'DUPLICATE_OF')),
                    notes TEXT DEFAULT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(parent_video_id, child_video_id, relation_type),
                    FOREIGN KEY(parent_video_id) REFERENCES processed_videos(id) ON DELETE CASCADE,
                    FOREIGN KEY(child_video_id) REFERENCES processed_videos(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ab_experiments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    content_identity_id INTEGER DEFAULT NULL,
                    hypothesis TEXT DEFAULT NULL,
                    primary_metric TEXT NOT NULL DEFAULT 'click_count',
                    state TEXT NOT NULL DEFAULT 'DRAFT'
                        CHECK(state IN ('DRAFT', 'RUNNING', 'PAUSED', 'COMPLETED', 'CANCELED')),
                    started_at TIMESTAMP DEFAULT NULL,
                    ended_at TIMESTAMP DEFAULT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(content_identity_id) REFERENCES video_content_identities(id) ON DELETE SET NULL
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ab_experiment_variants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id INTEGER NOT NULL,
                    video_id INTEGER NOT NULL,
                    variant_key TEXT NOT NULL,
                    variant_label TEXT DEFAULT NULL,
                    traffic_share REAL DEFAULT NULL,
                    notes TEXT DEFAULT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(experiment_id, variant_key),
                    UNIQUE(experiment_id, video_id),
                    FOREIGN KEY(experiment_id) REFERENCES ab_experiments(id) ON DELETE CASCADE,
                    FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE CASCADE
                )
            ''')

            # 4. 创建复合索引优化分页查询与状态调度性能
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_status_updated 
                ON processed_videos(status, updated_at DESC)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_status_score_created
                ON processed_videos(status, score, created_at DESC)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_status_score_updated
                ON processed_videos(status, score, updated_at DESC)
            ''')
            
            # [Gemini_3.5_Flash_planning] 新建 parent_id 索引提升自关联级联删除与关联查询速度
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_parent_id
                ON processed_videos(parent_id)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_ai_runs_video_started
                ON ai_processing_runs(youtube_id, slice_index, started_at DESC)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_ai_attempts_run_order
                ON ai_provider_attempts(run_id, attempt_order)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_censorship_incidents_video_created
                ON censorship_incidents(youtube_id, slice_index, created_at DESC)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_censorship_incidents_level_created
                ON censorship_incidents(level, created_at DESC)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_daily_metrics_platform_date
                ON published_video_daily_metrics(platform, metric_date)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_daily_metrics_video_date
                ON published_video_daily_metrics(video_id, metric_date)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_video_content_links_identity
                ON video_content_links(content_identity_id, variant_key)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_video_relationships_child
                ON video_relationships(child_video_id, relation_type)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_ab_variants_experiment
                ON ab_experiment_variants(experiment_id, variant_key)
            ''')

            cursor.execute("PRAGMA table_info(censorship_incidents)")
            censorship_incident_columns = {col[1] for col in cursor.fetchall()}
            for column_name, column_type in {
                "rule_pack_version": "TEXT DEFAULT NULL",
                "rule_id": "TEXT DEFAULT NULL",
                "source_field": "TEXT DEFAULT NULL",
                "review_stage": "TEXT DEFAULT NULL",
                "platform": "TEXT DEFAULT NULL",
                "input_hash": "TEXT DEFAULT NULL",
            }.items():
                if column_name not in censorship_incident_columns:
                    self._logger.info("[Migration] Adding censorship_incidents.%s column...", column_name)
                    cursor.execute(f"ALTER TABLE censorship_incidents ADD COLUMN {column_name} {column_type};")
                    conn.commit()
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_kuaishou_publications_state_source
                ON kuaishou_publications(state, source_kind, claimed_at, created_at)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_douyin_publications_state_source
                ON douyin_publications(state, source_kind, claimed_at, created_at)
            ''')
            # 浏览器动作节流必须跨巡航进程持久化；仅靠内存时间戳会被每分钟新进程重置。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS platform_browser_action_slots (
                    platform TEXT PRIMARY KEY,
                    last_action_at_epoch REAL NOT NULL,
                    last_reason TEXT NOT NULL DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # UI 漂移必须跨巡航累计；同阶段连续失败达到阈值后，不再反复打开平台后台。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS platform_ui_failure_streaks (
                    platform TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    first_failed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_failed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_reason TEXT NOT NULL DEFAULT '',
                    evidence_path TEXT DEFAULT NULL,
                    recording_requested_at TIMESTAMP DEFAULT NULL,
                    cleared_at TIMESTAMP DEFAULT NULL,
                    clear_evidence_path TEXT DEFAULT NULL,
                    PRIMARY KEY(platform, stage)
                )
            ''')
            # 低层上传器不能信任 CLI 的来源文本。每次自动投稿都由上层账本签发一个
            # 一次性启动凭据；上传器在打开浏览器前原子消费它，避免 HISTORY 伪装成 NEW
            # 或同一领取在并发/重放时重复上传。旧进程无凭据时宁可停止，绝不从未
            # 绑定的 UPLOADING 账本推断可发布的投稿包。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS douyin_browser_launch_tickets (
                    ticket_id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL
                        CHECK(source_type IN ('GENERIC', 'ENGLISH_WORLD', 'DUBBING')),
                    source_ref TEXT NOT NULL,
                    video_path TEXT NOT NULL,
                    asset_sha256 TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    action_scope TEXT NOT NULL DEFAULT 'publish'
                        CHECK(action_scope IN ('publish')),
                    token_sha256 TEXT DEFAULT NULL,
                    issued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    launch_started_at TIMESTAMP DEFAULT NULL,
                    prelaunch_canceled_at TIMESTAMP DEFAULT NULL,
                    prelaunch_cancel_reason TEXT DEFAULT NULL,
                    UNIQUE(source_type, source_ref)
                )
            ''')
            cursor.execute("PRAGMA table_info(douyin_browser_launch_tickets)")
            douyin_launch_ticket_columns = {row[1] for row in cursor.fetchall()}
            for column_name, column_type in {
                "payload_sha256": "TEXT DEFAULT NULL",
                "action_scope": "TEXT DEFAULT NULL",
                "prelaunch_canceled_at": "TIMESTAMP DEFAULT NULL",
                "prelaunch_cancel_reason": "TEXT DEFAULT NULL",
            }.items():
                if column_name not in douyin_launch_ticket_columns:
                    cursor.execute(
                        f"ALTER TABLE douyin_browser_launch_tickets ADD COLUMN {column_name} {column_type}"
                    )
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_douyin_browser_launch_tickets_pending
                ON douyin_browser_launch_tickets(source_type, source_ref, launch_started_at)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_douyin_browser_launch_tickets_prelaunch_recovery
                ON douyin_browser_launch_tickets(source_type, launch_started_at, prelaunch_canceled_at, issued_at)
            ''')
            
            conn.commit()

    # --- AI processing audit DAL ---
    def start_ai_processing_run(self, youtube_id: str, *, slice_index: int = 0, operation: str = "subtitle_translation") -> int:
        """创建一次 AI 处理审计运行，返回不可暴露给外部的内部 run id。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO ai_processing_runs (youtube_id, slice_index, operation) VALUES (?, ?, ?)",
                (youtube_id, slice_index, operation),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def record_ai_provider_attempt(
        self,
        run_id: int,
        *,
        provider: str,
        model: Optional[str],
        capabilities: str,
        attempt_order: int,
        status: str,
        duration_ms: Optional[int] = None,
        error_class: Optional[str] = None,
        error_message: Optional[str] = None,
        quality_score: Optional[float] = None,
        warning_count: int = 0,
        blocking_count: int = 0,
        selected: bool = False,
    ) -> None:
        """记录单次 provider 尝试；错误内容截断，避免审计表被异常响应污染。"""
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO ai_provider_attempts
                   (run_id, provider, model, capabilities, attempt_order, status, duration_ms,
                    error_class, error_message, quality_score, warning_count, blocking_count, selected)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, provider, model, capabilities, attempt_order, status, duration_ms,
                    error_class, (error_message or "")[:500] or None, quality_score,
                    int(warning_count), int(blocking_count), int(selected),
                ),
            )
            conn.commit()

    def finish_ai_processing_run(
        self,
        run_id: int,
        *,
        status: str,
        final_provider: Optional[str] = None,
        fallback_used: bool = False,
        quality_score: Optional[float] = None,
        chinese_coverage: Optional[float] = None,
        vocabulary_segments: Optional[int] = None,
        quality_status: Optional[str] = None,
        error_class: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """结束一次 AI 审计运行。"""
        with self.get_connection() as conn:
            conn.execute(
                """UPDATE ai_processing_runs
                   SET status = ?, finished_at = CURRENT_TIMESTAMP, final_provider = ?, fallback_used = ?,
                       quality_score = ?, chinese_coverage = ?, vocabulary_segments = ?, quality_status = ?,
                       error_class = ?, error_message = ?
                   WHERE id = ?""",
                (
                    status, final_provider, int(fallback_used), quality_score, chinese_coverage,
                    vocabulary_segments, quality_status, error_class, (error_message or "")[:500] or None,
                    run_id,
                ),
            )
            conn.commit()

    def get_ai_audit_summary(self, hours: int = 168) -> Dict[str, Any]:
        """返回后台概览所需的用量、失败和降级统计。"""
        with self.get_connection() as conn:
            runs = conn.execute(
                """SELECT COUNT(*) AS total_runs,
                          SUM(CASE WHEN status = 'SUCCEEDED' THEN 1 ELSE 0 END) AS succeeded_runs,
                          SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed_runs,
                          SUM(CASE WHEN fallback_used = 1 THEN 1 ELSE 0 END) AS fallback_runs
                   FROM ai_processing_runs WHERE started_at >= datetime('now', ?)""",
                (f"-{max(1, int(hours))} hours",),
            ).fetchone()
            providers = conn.execute(
                """SELECT provider, COUNT(*) AS attempts,
                          SUM(CASE WHEN status = 'SUCCEEDED' THEN 1 ELSE 0 END) AS successes,
                          SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failures
                   FROM ai_provider_attempts
                   WHERE created_at >= datetime('now', ?)
                   GROUP BY provider ORDER BY attempts DESC""",
                (f"-{max(1, int(hours))} hours",),
            ).fetchall()
            return {"hours": max(1, int(hours)), "runs": dict(runs), "providers": [dict(row) for row in providers]}

    def get_ai_audit_for_video(self, youtube_id: str, *, slice_index: int = 0, limit: int = 20) -> List[Dict[str, Any]]:
        """返回单视频 AI 处理运行及其 provider 尝试时间线。"""
        with self.get_connection() as conn:
            run_rows = conn.execute(
                """SELECT * FROM ai_processing_runs WHERE youtube_id = ? AND slice_index = ?
                   ORDER BY started_at DESC LIMIT ?""",
                (youtube_id, slice_index, max(1, min(int(limit), 100))),
            ).fetchall()
            results = []
            for row in run_rows:
                item = dict(row)
                attempts = conn.execute(
                    "SELECT * FROM ai_provider_attempts WHERE run_id = ? ORDER BY attempt_order, id",
                    (item["id"],),
                ).fetchall()
                item["attempts"] = [dict(attempt) for attempt in attempts]
                results.append(item)
            return results

    # --- Censorship incident ledger DAL ---
    def record_censorship_incident(
        self,
        youtube_id: str,
        *,
        slice_index: int = 0,
        stage: str,
        level: Optional[str],
        action: Optional[str],
        tag: Optional[str],
        score: Optional[int],
        matched: Optional[str],
        channel: Optional[str],
        decision: str,
        rule_pack_version: Optional[str] = None,
        rule_id: Optional[str] = None,
        source_field: Optional[str] = None,
        review_stage: Optional[str] = None,
        platform: Optional[str] = None,
        input_hash: Optional[str] = None,
        title: Optional[str] = None,
        zh_title: Optional[str] = None,
        description_preview: Optional[str] = None,
        text_excerpt: Optional[str] = None,
    ) -> int:
        """记录一次审查命中，用于事故复盘与规则积累；正文仅保留短摘录。"""
        with self.get_connection() as conn:
            video = conn.execute(
                "SELECT id FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            cursor = conn.execute(
                """INSERT INTO censorship_incidents
                   (video_id, youtube_id, slice_index, stage, level, action, tag, score,
                    matched, channel, decision, rule_pack_version, rule_id, source_field,
                    review_stage, platform, input_hash, title, zh_title, description_preview, text_excerpt)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    video["id"] if video else None,
                    youtube_id,
                    slice_index,
                    stage[:80],
                    level,
                    action,
                    tag,
                    score,
                    (matched or "")[:200] or None,
                    channel,
                    decision[:80],
                    (rule_pack_version or "")[:80] or None,
                    (rule_id or "")[:160] or None,
                    (source_field or "")[:80] or None,
                    (review_stage or "")[:80] or None,
                    (platform or "")[:40] or None,
                    (input_hash or "")[:80] or None,
                    (title or "")[:300] or None,
                    (zh_title or "")[:300] or None,
                    (description_preview or "")[:600] or None,
                    (text_excerpt or "")[:600] or None,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def get_censorship_incidents(
        self,
        youtube_id: Optional[str] = None,
        *,
        slice_index: Optional[int] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """查询违规台账，默认按时间倒序返回最近记录。"""
        clauses: list[str] = []
        params: list[Any] = []
        if youtube_id is not None:
            clauses.append("youtube_id = ?")
            params.append(youtube_id)
        if slice_index is not None:
            clauses.append("slice_index = ?")
            params.append(slice_index)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.get_connection() as conn:
            rows = conn.execute(
                f"""SELECT * FROM censorship_incidents
                    {where_sql}
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?""",
                (*params, max(1, min(int(limit), 500))),
            ).fetchall()
            return [dict(row) for row in rows]

    # --- Published metrics / content identity / AB-test DAL ---
    @classmethod
    def _normalize_metric_platform(cls, platform: str) -> str:
        normalized = (platform or "").lower()
        if normalized not in cls._METRIC_PLATFORMS:
            raise ValueError(f"Unsupported metric platform: {platform}")
        return normalized

    @staticmethod
    def _normalize_metric_date(metric_date: str | datetime.date) -> str:
        if isinstance(metric_date, datetime.date):
            return metric_date.isoformat()
        try:
            return datetime.date.fromisoformat(str(metric_date)).isoformat()
        except ValueError as exc:
            raise ValueError("metric_date must be YYYY-MM-DD") from exc

    @staticmethod
    def _non_negative_int(value: Optional[int], field_name: str, *, nullable: bool = False) -> Optional[int]:
        if value is None and nullable:
            return None
        number = int(value or 0)
        if number < 0:
            raise ValueError(f"{field_name} must be non-negative")
        return number

    @staticmethod
    def _json_blob(value: Optional[Dict[str, Any]]) -> str:
        return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)

    def record_published_video_daily_metrics(
        self,
        youtube_id: str,
        *,
        slice_index: int = 0,
        platform: str,
        metric_date: str | datetime.date,
        impression_count: int = 0,
        click_count: int = 0,
        view_count: int = 0,
        like_count: int = 0,
        share_count: int = 0,
        comment_count: int = 0,
        favorite_count: int = 0,
        follow_count: int = 0,
        watch_seconds: Optional[int] = None,
        avg_watch_seconds: Optional[float] = None,
        completion_rate: Optional[float] = None,
        source: str = "manual",
        raw: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """按平台和自然日幂等写入发布后指标读数。"""
        metric_day = self._normalize_metric_date(metric_date)
        normalized_platform = self._normalize_metric_platform(platform)
        payload = {
            "impression_count": self._non_negative_int(impression_count, "impression_count"),
            "click_count": self._non_negative_int(click_count, "click_count"),
            "view_count": self._non_negative_int(view_count, "view_count"),
            "like_count": self._non_negative_int(like_count, "like_count"),
            "share_count": self._non_negative_int(share_count, "share_count"),
            "comment_count": self._non_negative_int(comment_count, "comment_count"),
            "favorite_count": self._non_negative_int(favorite_count, "favorite_count"),
            "follow_count": self._non_negative_int(follow_count, "follow_count"),
            "watch_seconds": self._non_negative_int(watch_seconds, "watch_seconds", nullable=True),
            "avg_watch_seconds": float(avg_watch_seconds) if avg_watch_seconds is not None else None,
            "completion_rate": float(completion_rate) if completion_rate is not None else None,
        }
        if payload["avg_watch_seconds"] is not None and payload["avg_watch_seconds"] < 0:
            raise ValueError("avg_watch_seconds must be non-negative")
        if payload["completion_rate"] is not None and payload["completion_rate"] < 0:
            raise ValueError("completion_rate must be non-negative")

        with self.get_connection() as conn:
            video = conn.execute(
                "SELECT id FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            if not video:
                raise ValueError("Video or slice does not exist")
            conn.execute(
                """INSERT INTO published_video_daily_metrics
                   (video_id, platform, metric_date, impression_count, click_count, view_count,
                    like_count, share_count, comment_count, favorite_count, follow_count,
                    watch_seconds, avg_watch_seconds, completion_rate, source, raw_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(video_id, platform, metric_date) DO UPDATE SET
                     impression_count=excluded.impression_count,
                     click_count=excluded.click_count,
                     view_count=excluded.view_count,
                     like_count=excluded.like_count,
                     share_count=excluded.share_count,
                     comment_count=excluded.comment_count,
                     favorite_count=excluded.favorite_count,
                     follow_count=excluded.follow_count,
                     watch_seconds=excluded.watch_seconds,
                     avg_watch_seconds=excluded.avg_watch_seconds,
                     completion_rate=excluded.completion_rate,
                     source=excluded.source,
                     raw_json=excluded.raw_json,
                     collected_at=CURRENT_TIMESTAMP,
                     updated_at=CURRENT_TIMESTAMP""",
                (
                    video["id"], normalized_platform, metric_day, payload["impression_count"],
                    payload["click_count"], payload["view_count"], payload["like_count"],
                    payload["share_count"], payload["comment_count"], payload["favorite_count"],
                    payload["follow_count"], payload["watch_seconds"], payload["avg_watch_seconds"],
                    payload["completion_rate"], (source or "manual")[:80], self._json_blob(raw),
                ),
            )
            row = conn.execute(
                """SELECT m.*, pv.youtube_id, pv.slice_index
                   FROM published_video_daily_metrics m
                   JOIN processed_videos pv ON pv.id = m.video_id
                   WHERE m.video_id = ? AND m.platform = ? AND m.metric_date = ?""",
                (video["id"], normalized_platform, metric_day),
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to record daily metrics")
            return dict(row)

    def get_daily_metrics_for_video(
        self,
        youtube_id: str,
        *,
        slice_index: int = 0,
        platform: Optional[str] = None,
        date_from: Optional[str | datetime.date] = None,
        date_to: Optional[str | datetime.date] = None,
    ) -> List[Dict[str, Any]]:
        """返回单视频按天指标明细。"""
        clauses = ["pv.youtube_id = ?", "pv.slice_index = ?"]
        params: List[Any] = [youtube_id, slice_index]
        if platform is not None:
            clauses.append("m.platform = ?")
            params.append(self._normalize_metric_platform(platform))
        if date_from is not None:
            clauses.append("m.metric_date >= ?")
            params.append(self._normalize_metric_date(date_from))
        if date_to is not None:
            clauses.append("m.metric_date <= ?")
            params.append(self._normalize_metric_date(date_to))
        where_sql = " AND ".join(clauses)
        with self.get_connection() as conn:
            rows = conn.execute(
                f"""SELECT m.*, pv.youtube_id, pv.slice_index, pv.title, pv.zh_title
                    FROM published_video_daily_metrics m
                    JOIN processed_videos pv ON pv.id = m.video_id
                    WHERE {where_sql}
                    ORDER BY m.metric_date ASC, m.platform ASC""",
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def get_published_video_metric_summary(
        self,
        youtube_id: Optional[str] = None,
        *,
        slice_index: int = 0,
        platform: Optional[str] = None,
        date_from: Optional[str | datetime.date] = None,
        date_to: Optional[str | datetime.date] = None,
    ) -> Dict[str, Any]:
        """汇总发布后指标；默认全库，传入 youtube_id 时聚焦单视频。"""
        clauses: List[str] = []
        params: List[Any] = []
        if youtube_id is not None:
            clauses.extend(["pv.youtube_id = ?", "pv.slice_index = ?"])
            params.extend([youtube_id, slice_index])
        if platform is not None:
            clauses.append("m.platform = ?")
            params.append(self._normalize_metric_platform(platform))
        if date_from is not None:
            clauses.append("m.metric_date >= ?")
            params.append(self._normalize_metric_date(date_from))
        if date_to is not None:
            clauses.append("m.metric_date <= ?")
            params.append(self._normalize_metric_date(date_to))
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        metric_sql = """
            COUNT(m.id) AS metric_days,
            COALESCE(SUM(m.impression_count), 0) AS impression_count,
            COALESCE(SUM(m.click_count), 0) AS click_count,
            COALESCE(SUM(m.view_count), 0) AS view_count,
            COALESCE(SUM(m.like_count), 0) AS like_count,
            COALESCE(SUM(m.share_count), 0) AS share_count,
            COALESCE(SUM(m.comment_count), 0) AS comment_count,
            COALESCE(SUM(m.favorite_count), 0) AS favorite_count,
            COALESCE(SUM(m.follow_count), 0) AS follow_count,
            COALESCE(SUM(m.watch_seconds), 0) AS watch_seconds,
            AVG(m.avg_watch_seconds) AS avg_watch_seconds,
            AVG(m.completion_rate) AS completion_rate
        """
        with self.get_connection() as conn:
            total = conn.execute(
                f"""SELECT {metric_sql}
                    FROM published_video_daily_metrics m
                    JOIN processed_videos pv ON pv.id = m.video_id
                    {where_sql}""",
                params,
            ).fetchone()
            by_platform = conn.execute(
                f"""SELECT m.platform, {metric_sql}
                    FROM published_video_daily_metrics m
                    JOIN processed_videos pv ON pv.id = m.video_id
                    {where_sql}
                    GROUP BY m.platform
                    ORDER BY m.platform ASC""",
                params,
            ).fetchall()
            by_date = conn.execute(
                f"""SELECT m.metric_date, {metric_sql}
                    FROM published_video_daily_metrics m
                    JOIN processed_videos pv ON pv.id = m.video_id
                    {where_sql}
                    GROUP BY m.metric_date
                    ORDER BY m.metric_date ASC""",
                params,
            ).fetchall()
            return {
                "filters": {
                    "youtube_id": youtube_id,
                    "slice_index": slice_index if youtube_id is not None else None,
                    "platform": self._normalize_metric_platform(platform) if platform else None,
                    "date_from": self._normalize_metric_date(date_from) if date_from else None,
                    "date_to": self._normalize_metric_date(date_to) if date_to else None,
                },
                "total": dict(total) if total else {},
                "by_platform": [dict(row) for row in by_platform],
                "by_date": [dict(row) for row in by_date],
            }

    def assign_video_content_identity(
        self,
        youtube_id: str,
        *,
        slice_index: int = 0,
        content_key: Optional[str] = None,
        source_kind: str = "MANUAL",
        fingerprint_hash: Optional[str] = None,
        normalized_title: Optional[str] = None,
        duration_sec: Optional[int] = None,
        relationship_to_content: str = "UNKNOWN",
        variant_key: Optional[str] = None,
        notes: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """把视频绑定到一个可复用内容身份；同 content_key 可承载多个平台/变体。"""
        normalized_source = (source_kind or "MANUAL").upper()
        if normalized_source not in self._CONTENT_IDENTITY_SOURCES:
            raise ValueError(f"Unsupported content identity source: {source_kind}")
        normalized_relation = (relationship_to_content or "UNKNOWN").upper()
        if normalized_relation not in self._CONTENT_RELATIONS:
            raise ValueError(f"Unsupported content relationship: {relationship_to_content}")
        safe_key = (content_key or "").strip()
        safe_fingerprint = (fingerprint_hash or "").strip() or None
        if not safe_key:
            safe_key = f"fingerprint:{safe_fingerprint}" if safe_fingerprint else f"youtube:{youtube_id}:slice:{slice_index}"

        with self.get_connection() as conn:
            video = conn.execute(
                "SELECT id, duration_sec, title FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            if not video:
                raise ValueError("Video or slice does not exist")
            conn.execute(
                """INSERT INTO video_content_identities
                   (content_key, source_kind, fingerprint_hash, canonical_video_id,
                    normalized_title, duration_sec, notes, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(content_key) DO UPDATE SET
                     source_kind=excluded.source_kind,
                     fingerprint_hash=COALESCE(excluded.fingerprint_hash, video_content_identities.fingerprint_hash),
                     canonical_video_id=COALESCE(video_content_identities.canonical_video_id, excluded.canonical_video_id),
                     normalized_title=COALESCE(excluded.normalized_title, video_content_identities.normalized_title),
                     duration_sec=COALESCE(excluded.duration_sec, video_content_identities.duration_sec),
                     notes=COALESCE(excluded.notes, video_content_identities.notes),
                     metadata_json=excluded.metadata_json,
                     updated_at=CURRENT_TIMESTAMP""",
                (
                    safe_key, normalized_source, safe_fingerprint, video["id"],
                    normalized_title or video["title"], duration_sec if duration_sec is not None else video["duration_sec"],
                    notes, self._json_blob(metadata),
                ),
            )
            identity = conn.execute("SELECT * FROM video_content_identities WHERE content_key = ?", (safe_key,)).fetchone()
            if not identity:
                raise RuntimeError("Failed to create content identity")
            conn.execute(
                """INSERT INTO video_content_links
                   (video_id, content_identity_id, relationship_to_content, variant_key, metadata_json)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(video_id) DO UPDATE SET
                     content_identity_id=excluded.content_identity_id,
                     relationship_to_content=excluded.relationship_to_content,
                     variant_key=excluded.variant_key,
                     metadata_json=excluded.metadata_json,
                     updated_at=CURRENT_TIMESTAMP""",
                (video["id"], identity["id"], normalized_relation, variant_key, self._json_blob(metadata)),
            )
            conn.commit()
            row = conn.execute(
                """SELECT ci.*, cl.video_id, cl.relationship_to_content, cl.variant_key,
                          pv.youtube_id, pv.slice_index
                   FROM video_content_identities ci
                   JOIN video_content_links cl ON cl.content_identity_id = ci.id
                   JOIN processed_videos pv ON pv.id = cl.video_id
                   WHERE cl.video_id = ?""",
                (video["id"],),
            ).fetchone()
            return dict(row) if row else dict(identity)

    def get_video_content_identity(self, youtube_id: str, *, slice_index: int = 0) -> Optional[Dict[str, Any]]:
        """返回视频当前绑定的内容身份。"""
        with self.get_connection() as conn:
            row = conn.execute(
                """SELECT ci.*, cl.video_id, cl.relationship_to_content, cl.variant_key,
                          pv.youtube_id, pv.slice_index
                   FROM video_content_links cl
                   JOIN video_content_identities ci ON ci.id = cl.content_identity_id
                   JOIN processed_videos pv ON pv.id = cl.video_id
                   WHERE pv.youtube_id = ? AND pv.slice_index = ?""",
                (youtube_id, slice_index),
            ).fetchone()
            return dict(row) if row else None

    def record_video_relationship(
        self,
        parent_youtube_id: str,
        child_youtube_id: str,
        *,
        relation_type: str,
        parent_slice_index: int = 0,
        child_slice_index: int = 0,
        notes: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """记录两个视频/切片之间的显式关系。"""
        normalized_relation = (relation_type or "").upper()
        if normalized_relation not in self._VIDEO_RELATIONS:
            raise ValueError(f"Unsupported video relation type: {relation_type}")
        with self.get_connection() as conn:
            parent = conn.execute(
                "SELECT id FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (parent_youtube_id, parent_slice_index),
            ).fetchone()
            child = conn.execute(
                "SELECT id FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (child_youtube_id, child_slice_index),
            ).fetchone()
            if not parent or not child:
                raise ValueError("Parent or child video does not exist")
            if parent["id"] == child["id"]:
                raise ValueError("A video cannot relate to itself")
            conn.execute(
                """INSERT INTO video_relationships
                   (parent_video_id, child_video_id, relation_type, notes, metadata_json)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(parent_video_id, child_video_id, relation_type) DO UPDATE SET
                     notes=excluded.notes,
                     metadata_json=excluded.metadata_json,
                     updated_at=CURRENT_TIMESTAMP""",
                (parent["id"], child["id"], normalized_relation, notes, self._json_blob(metadata)),
            )
            conn.commit()
            row = conn.execute(
                """SELECT vr.*, parent.youtube_id AS parent_youtube_id, parent.slice_index AS parent_slice_index,
                          child.youtube_id AS child_youtube_id, child.slice_index AS child_slice_index
                   FROM video_relationships vr
                   JOIN processed_videos parent ON parent.id = vr.parent_video_id
                   JOIN processed_videos child ON child.id = vr.child_video_id
                   WHERE vr.parent_video_id = ? AND vr.child_video_id = ? AND vr.relation_type = ?""",
                (parent["id"], child["id"], normalized_relation),
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to record video relationship")
            return dict(row)

    def get_related_videos(
        self,
        youtube_id: str,
        *,
        slice_index: int = 0,
        direction: str = "both",
    ) -> List[Dict[str, Any]]:
        """查询某视频作为父/子两侧的关系记录。"""
        normalized_direction = (direction or "both").lower()
        if normalized_direction not in {"parent", "child", "both"}:
            raise ValueError("direction must be parent, child or both")
        with self.get_connection() as conn:
            video = conn.execute(
                "SELECT id FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            if not video:
                return []
            clauses = []
            params: List[Any] = []
            if normalized_direction in {"parent", "both"}:
                clauses.append("vr.parent_video_id = ?")
                params.append(video["id"])
            if normalized_direction in {"child", "both"}:
                clauses.append("vr.child_video_id = ?")
                params.append(video["id"])
            rows = conn.execute(
                f"""SELECT vr.*, parent.youtube_id AS parent_youtube_id, parent.slice_index AS parent_slice_index,
                          child.youtube_id AS child_youtube_id, child.slice_index AS child_slice_index,
                          child.title AS child_title, parent.title AS parent_title
                    FROM video_relationships vr
                    JOIN processed_videos parent ON parent.id = vr.parent_video_id
                    JOIN processed_videos child ON child.id = vr.child_video_id
                    WHERE {' OR '.join(clauses)}
                    ORDER BY vr.updated_at DESC, vr.id DESC""",
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def create_ab_experiment(
        self,
        name: str,
        *,
        content_key: Optional[str] = None,
        hypothesis: Optional[str] = None,
        primary_metric: str = "click_count",
        state: str = "DRAFT",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """创建或更新一个 AB 实验容器。"""
        safe_name = (name or "").strip()
        if not safe_name:
            raise ValueError("name is required")
        normalized_state = (state or "DRAFT").upper()
        if normalized_state not in self._AB_EXPERIMENT_STATES:
            raise ValueError(f"Unsupported AB experiment state: {state}")
        with self.get_connection() as conn:
            identity_id = None
            if content_key:
                identity = conn.execute(
                    "SELECT id FROM video_content_identities WHERE content_key = ?",
                    (content_key,),
                ).fetchone()
                if not identity:
                    raise ValueError("content_key does not exist")
                identity_id = identity["id"]
            conn.execute(
                """INSERT INTO ab_experiments
                   (name, content_identity_id, hypothesis, primary_metric, state, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                     content_identity_id=COALESCE(excluded.content_identity_id, ab_experiments.content_identity_id),
                     hypothesis=excluded.hypothesis,
                     primary_metric=excluded.primary_metric,
                     state=excluded.state,
                     metadata_json=excluded.metadata_json,
                     updated_at=CURRENT_TIMESTAMP""",
                (safe_name, identity_id, hypothesis, primary_metric, normalized_state, self._json_blob(metadata)),
            )
            conn.commit()
            row = conn.execute(
                """SELECT e.*, ci.content_key
                   FROM ab_experiments e
                   LEFT JOIN video_content_identities ci ON ci.id = e.content_identity_id
                   WHERE e.name = ?""",
                (safe_name,),
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to create AB experiment")
            return dict(row)

    def add_ab_experiment_variant(
        self,
        experiment_id: int,
        youtube_id: str,
        *,
        variant_key: str,
        slice_index: int = 0,
        variant_label: Optional[str] = None,
        traffic_share: Optional[float] = None,
        notes: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """把一个视频登记为 AB 实验变体，并在同内容实验中自动补上内容链接。"""
        safe_variant_key = (variant_key or "").strip()
        if not safe_variant_key:
            raise ValueError("variant_key is required")
        if traffic_share is not None and traffic_share < 0:
            raise ValueError("traffic_share must be non-negative")
        with self.get_connection() as conn:
            experiment = conn.execute("SELECT * FROM ab_experiments WHERE id = ?", (experiment_id,)).fetchone()
            if not experiment:
                raise ValueError("AB experiment does not exist")
            video = conn.execute(
                "SELECT id FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            if not video:
                raise ValueError("Video or slice does not exist")
            if experiment["content_identity_id"] is not None:
                link = conn.execute(
                    "SELECT content_identity_id FROM video_content_links WHERE video_id = ?",
                    (video["id"],),
                ).fetchone()
                if link and link["content_identity_id"] != experiment["content_identity_id"]:
                    raise ValueError("Video content identity does not match experiment")
                if not link:
                    conn.execute(
                        """INSERT INTO video_content_links
                           (video_id, content_identity_id, relationship_to_content, variant_key, metadata_json)
                           VALUES (?, ?, 'VARIANT', ?, ?)""",
                        (video["id"], experiment["content_identity_id"], safe_variant_key, self._json_blob(metadata)),
                    )
            conn.execute(
                """INSERT INTO ab_experiment_variants
                   (experiment_id, video_id, variant_key, variant_label, traffic_share, notes, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(experiment_id, variant_key) DO UPDATE SET
                     video_id=excluded.video_id,
                     variant_label=excluded.variant_label,
                     traffic_share=excluded.traffic_share,
                     notes=excluded.notes,
                     metadata_json=excluded.metadata_json,
                     updated_at=CURRENT_TIMESTAMP""",
                (
                    experiment_id, video["id"], safe_variant_key, variant_label,
                    traffic_share, notes, self._json_blob(metadata),
                ),
            )
            conn.commit()
            row = conn.execute(
                """SELECT av.*, pv.youtube_id, pv.slice_index
                   FROM ab_experiment_variants av
                   JOIN processed_videos pv ON pv.id = av.video_id
                   WHERE av.experiment_id = ? AND av.variant_key = ?""",
                (experiment_id, safe_variant_key),
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to add AB experiment variant")
            return dict(row)

    def get_ab_experiment_summary(
        self,
        experiment_id: int,
        *,
        platform: Optional[str] = None,
        date_from: Optional[str | datetime.date] = None,
        date_to: Optional[str | datetime.date] = None,
    ) -> Dict[str, Any]:
        """返回 AB 实验变体维度的指标汇总。"""
        metric_clauses = ["m.video_id = av.video_id"]
        metric_params: List[Any] = []
        if platform is not None:
            metric_clauses.append("m.platform = ?")
            metric_params.append(self._normalize_metric_platform(platform))
        if date_from is not None:
            metric_clauses.append("m.metric_date >= ?")
            metric_params.append(self._normalize_metric_date(date_from))
        if date_to is not None:
            metric_clauses.append("m.metric_date <= ?")
            metric_params.append(self._normalize_metric_date(date_to))
        metric_join = " AND ".join(metric_clauses)
        metric_sql = """
            COUNT(m.id) AS metric_days,
            COALESCE(SUM(m.impression_count), 0) AS impression_count,
            COALESCE(SUM(m.click_count), 0) AS click_count,
            COALESCE(SUM(m.view_count), 0) AS view_count,
            COALESCE(SUM(m.like_count), 0) AS like_count,
            COALESCE(SUM(m.share_count), 0) AS share_count,
            COALESCE(SUM(m.comment_count), 0) AS comment_count,
            COALESCE(SUM(m.favorite_count), 0) AS favorite_count,
            COALESCE(SUM(m.follow_count), 0) AS follow_count
        """
        with self.get_connection() as conn:
            experiment = conn.execute(
                """SELECT e.*, ci.content_key
                   FROM ab_experiments e
                   LEFT JOIN video_content_identities ci ON ci.id = e.content_identity_id
                   WHERE e.id = ?""",
                (experiment_id,),
            ).fetchone()
            if not experiment:
                raise ValueError("AB experiment does not exist")
            variants = conn.execute(
                f"""SELECT av.id, av.variant_key, av.variant_label, av.traffic_share,
                          pv.youtube_id, pv.slice_index, pv.title, {metric_sql}
                    FROM ab_experiment_variants av
                    JOIN processed_videos pv ON pv.id = av.video_id
                    LEFT JOIN published_video_daily_metrics m ON {metric_join}
                    WHERE av.experiment_id = ?
                    GROUP BY av.id
                    ORDER BY av.variant_key ASC""",
                (*metric_params, experiment_id),
            ).fetchall()
            return {
                "experiment": dict(experiment),
                "filters": {
                    "platform": self._normalize_metric_platform(platform) if platform else None,
                    "date_from": self._normalize_metric_date(date_from) if date_from else None,
                    "date_to": self._normalize_metric_date(date_to) if date_to else None,
                },
                "variants": [dict(row) for row in variants],
            }

    # --- Channel DAL ---
    def add_channel(self, channel_id: str, channel_name: str, status: str = 'APPROVED', reason: str = '') -> bool:
        with self.get_connection() as conn:
            try:
                # [blacklist tombstone 2026-06-24] 已拉黑频道拒绝被发现/手动重加覆盖(防自动复活)
                row = conn.execute(
                    "SELECT status FROM recommended_channels WHERE channel_id = ?", (channel_id,)
                ).fetchone()
                if row and row[0] == 'BLACKLISTED' and status != 'BLACKLISTED':
                    self._logger.info(f"[Blacklist] Blocked re-add of blacklisted channel: {channel_id}")
                    return False
                conn.execute(
                    "INSERT OR REPLACE INTO recommended_channels (channel_id, channel_name, reason, status) VALUES (?, ?, ?, ?)",
                    (channel_id, channel_name, reason, status)
                )
                conn.commit()
                return True
            except Exception as e:
                self._logger.error(f"add_channel failed for {channel_id}: {e}")
                return False
                
    def get_approved_channels(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM recommended_channels WHERE status = 'APPROVED'")
            return [dict(row) for row in cursor.fetchall()]

    def get_pending_channels(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM recommended_channels WHERE status = 'PENDING'")
            return [dict(row) for row in cursor.fetchall()]

    def update_channel_status(self, channel_id: str, status: str):
        with self.get_connection() as conn:
            conn.execute("UPDATE recommended_channels SET status = ? WHERE channel_id = ?", (status, channel_id))
            conn.commit()

    # --- Video DAL ---
    def add_video(
        self,
        youtube_id: str,
        title: str,
        channel_id: str,
        score: int = 0,
        zh_title: Optional[str] = None,
        source: str = 'AUTO',
        duration_sec: Optional[int] = None,
        view_count: Optional[int] = None,
        like_count: Optional[int] = None,
        upload_date: Optional[str] = None,
        source_published_at: Optional[str] = None,
        trim_start: Optional[str] = None,
        trim_end: Optional[str] = None,
        slice_index: int = 0,                       # [Gemini_3.5_Flash_planning] 新增：切片索引，默认0 (主视频)
        parent_id: Optional[int] = None,            # [Gemini_3.5_Flash_planning] 新增：父自增 ID
        disable_slicing: int = 1,                   # [Gemini_3.5_Flash_planning] 新增：禁用分片标识 (默认1=不分片)
        tts_provider: Optional[str] = None,         # [Claude_Sonnet_4.6_Thinking_planning] v2.9.0: TTS 配音引擎（nullable）
        category: Optional[str] = None,             # [Gemini_3.5_Flash_planning] 新增：分类字段
        content_type: str = CONTENT_TYPE_GENERAL,   # 内容生产类型，独立于视频号分类
        censor_tag: Optional[str] = None,           # [Gemini_3.5_Flash_planning] 新增：敏感词标签
        censor_score: Optional[int] = None,         # [Gemini_3.5_Flash_planning] 新增：敏感词得分
    ) -> bool:
        normalized_content_type = normalize_content_type(content_type)
        # 前置黑名单检查，防止已删除视频被二次拉取
        if self.is_blacklisted(youtube_id):
            if source == 'MANUAL':
                self.remove_from_blacklist(youtube_id)
            else:
                self._logger.warning(f"[Blacklist] Blocked re-add of blacklisted video: {youtube_id}")
                return False

        with self.get_connection() as conn:
            try:
                conn.execute(
                    """INSERT INTO processed_videos
                       (youtube_id, slice_index, parent_id, title, channel_id, score, status, zh_title, source,
                        duration_sec, view_count, like_count, upload_date, source_published_at, trim_start, trim_end, disable_slicing,
                        tts_provider, category, content_type, censor_tag, censor_score)
                       VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (youtube_id, slice_index, parent_id, title, channel_id, score, zh_title, source,
                     duration_sec, view_count, like_count, upload_date, source_published_at, trim_start, trim_end, disable_slicing,
                     tts_provider, category, normalized_content_type, censor_tag, censor_score)  # [Gemini_3.5_Flash_planning]
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False  # Already exists (youtube_id + slice_index duplicate)

    def upsert_monitored_video(
        self,
        youtube_id: str,
        title: str,
        channel_id: str,
        *,
        zh_title: Optional[str],
        duration_sec: Optional[int],
        view_count: Optional[int],
        like_count: Optional[int],
        upload_date: Optional[str],
        metadata_complete: bool,
        source_published_at: Optional[str] = None,
    ) -> str:
        """写入或补全白名单监控候选，且不改变既有处理/发布状态。

        RSS 只有 ID、标题和发布时间，先以 METADATA_PENDING 保存；后续 Data API
        取回完整评分数据时才把该候选转为可评分的 PENDING。
        """
        if self.is_blacklisted(youtube_id):
            self._logger.warning(f"[Blacklist] Blocked monitored video: {youtube_id}")
            return "blocked"

        with self.get_connection() as conn:
            existing = conn.execute(
                "SELECT status FROM processed_videos WHERE youtube_id = ? AND slice_index = 0",
                (youtube_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE processed_videos
                       SET title = ?, channel_id = ?,
                           zh_title = COALESCE(?, zh_title),
                           duration_sec = COALESCE(?, duration_sec),
                           view_count = COALESCE(?, view_count),
                           like_count = COALESCE(?, like_count),
                           upload_date = COALESCE(?, upload_date),
                           source_published_at = COALESCE(?, source_published_at),
                           status = CASE
                               WHEN status = 'METADATA_PENDING' AND ? THEN 'PENDING'
                               ELSE status
                           END,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE youtube_id = ? AND slice_index = 0""",
                    (
                        title, channel_id, zh_title, duration_sec, view_count, like_count,
                        upload_date, source_published_at, metadata_complete, youtube_id,
                    ),
                )
                conn.commit()
                return "refreshed"

            status = "PENDING" if metadata_complete else "METADATA_PENDING"
            conn.execute(
                """INSERT INTO processed_videos
                   (youtube_id, slice_index, title, channel_id, score, status, zh_title, source,
                    duration_sec, view_count, like_count, upload_date, source_published_at)
                   VALUES (?, 0, ?, ?, 0, ?, ?, 'AUTO', ?, ?, ?, ?, ?)""",
                (
                    youtube_id, title, channel_id, status, zh_title, duration_sec,
                    view_count, like_count, upload_date, source_published_at,
                ),
            )
            conn.commit()
            return "inserted"


    def batch_add_videos(self, videos: List[Dict[str, Any]]) -> bool:
        """[Gemini_3.1_Pro_High_planning] 批量插入子任务列表，使用 executemany 配合自动事务，规避性能与死锁问题"""
        if not videos:
            return True
            
        with self.get_connection() as conn:
            # 1. 批量查询黑名单
            yids = list(set(v.get("youtube_id") for v in videos if v.get("youtube_id")))
            blacklisted = set()
            if yids:
                placeholders = ",".join(["?"] * len(yids))
                cursor = conn.execute(f"SELECT youtube_id FROM blacklisted_videos WHERE youtube_id IN ({placeholders})", yids)
                blacklisted = {row["youtube_id"] for row in cursor.fetchall()}
                
            # 2. 准备插入数据
            insert_data = []
            for v in videos:
                yid = v.get("youtube_id")
                source = v.get("source", "AUTO")
                if yid in blacklisted and source != "MANUAL":
                    continue
                    
                insert_data.append((
                    yid, v.get("slice_index", 0), v.get("parent_id"), v.get("title"), v.get("channel_id"),
                    v.get("score", 0), v.get("zh_title"), source, v.get("duration_sec"), v.get("view_count"),
                    v.get("like_count"), v.get("upload_date"), v.get("source_published_at"), v.get("trim_start"), v.get("trim_end"),
                    v.get("disable_slicing", 1),
                    normalize_content_type(v.get("content_type")),
                ))
            
            if not insert_data:
                return True
                
            try:
                conn.executemany(
                    """INSERT INTO processed_videos
                       (youtube_id, slice_index, parent_id, title, channel_id, score, status, zh_title, source,
                        duration_sec, view_count, like_count, upload_date, source_published_at, trim_start, trim_end, disable_slicing,
                        content_type)
                       VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    insert_data
                )
                conn.commit()
                return True
            except Exception as e:
                conn.rollback()
                self._logger.error(f"[DB] batch_add_videos failed: {e}")
                return False

    def update_video_spec(
        self,
        youtube_id: str,
        trim_start: Optional[str],
        trim_end: Optional[str],
        disable_slicing: int,
        tts_provider: Optional[str] = None,
        slice_index: int = 0,
    ) -> bool:
        """[Claude_Sonnet_4.6_Thinking_planning] 全量覆盖更新视频规格字段。

        规格字段：trim_start / trim_end / disable_slicing / tts_provider。
        NULL 值也会被写入（可清除原有裁剪区间或 TTS 配置）。
        仅操作父任务（默认 slice_index=0），不影响子切片。
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE processed_videos "
                "SET trim_start = ?, trim_end = ?, disable_slicing = ?, tts_provider = ?, "
                "    updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ?",
                (trim_start, trim_end, disable_slicing, tts_provider, youtube_id, slice_index),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_video_content_type(
        self,
        youtube_id: str,
        content_type: str,
        slice_index: int = 0,
    ) -> bool:
        """更新既有任务的内容生产类型，不改变处理状态或评分。"""
        normalized_content_type = normalize_content_type(content_type)
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE processed_videos SET content_type = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ?",
                (normalized_content_type, youtube_id, slice_index),
            )
            conn.commit()
            return cursor.rowcount > 0

    def set_publication_review_required(
        self,
        youtube_id: str,
        required: bool,
        slice_index: int = 0,
    ) -> bool:
        """设置单任务发布前人工复核闸，不改变制作检查点或评分。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE processed_videos SET publication_review_required = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ?",
                (1 if required else 0, youtube_id, slice_index),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_video_status(self, youtube_id: str, status: str, error_msg: Optional[str] = None, slice_index: int = 0):
        """更新指定联合键 (youtube_id, slice_index) 视频的状态。"""
        # [Gemini_3.5_Flash_planning] 更新定位增加 slice_index = ?
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET status = ?, error_msg = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ?",
                (status, error_msg, youtube_id, slice_index)
            )
            conn.commit()

    def update_video_zh_title(self, youtube_id: str, zh_title: str, slice_index: int = 0) -> bool:
        """更新单条任务的源标题译文，不改变其处理或发布状态。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE processed_videos SET zh_title = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ?",
                ((zh_title or "").strip() or None, youtube_id, slice_index),
            )
            conn.commit()
            return cursor.rowcount > 0

    def requeue_transient_pre_submission_failure(
        self,
        youtube_id: str,
        error_msg: str,
        *,
        slice_index: int = 0,
        max_retry_count: int = 2,
    ) -> bool:
        """仅将上传前阶段的瞬态失败原子恢复为 PENDING，绝不触碰发布中或已发布任务。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE processed_videos "
                "SET status = 'PENDING', retry_count = retry_count + 1, error_msg = ?, "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ? "
                "AND status IN ('DOWNLOADING', 'COPYWRITING', 'TRANSCRIBING') "
                "AND retry_count < ?",
                (error_msg, youtube_id, slice_index, max(1, int(max_retry_count))),
            )
            conn.commit()
            return cursor.rowcount > 0

    def mark_ai_cover_resolved(self, youtube_id: str, slice_index: int = 0) -> bool:
        """AI 封面任务完成后，原子恢复待发布并标记此前已完成的成片为可提交。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE processed_videos "
                "SET status = 'PENDING', preparation_ready = 1, error_msg = NULL, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ? AND status = 'AI_COVER_PENDING'",
                (youtube_id, slice_index),
            )
            conn.commit()
            return cursor.rowcount > 0
            
    def get_videos_by_status(self, status: str) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM processed_videos WHERE status = ? ORDER BY score DESC", (status,))
            return [dict(row) for row in cursor.fetchall()]

    def restore_login_required_videos(self) -> int:
        """微信登录成功后恢复可安全续跑的登录阻断任务。

        仅恢复仍处于 LOGIN_REQUIRED 且没有视频号提交账本的任务；评分、素材检查点和
        retry_count 均保持不变，后续仍由正常调度器按发布线领取。已有提交/审核证据的
        任务不因重新登录而获得重传机会。

        # Modification History
        | Version | Date       | Author | Description |
        |---------|------------|--------|-------------|
        | 1.0.0   | 2026-08-26 | Codex  | 统一微信登录成功后的安全任务恢复 |
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE processed_videos
                   SET status = 'PENDING', error_msg = NULL, updated_at = CURRENT_TIMESTAMP
                 WHERE status = 'LOGIN_REQUIRED'
                   AND NOT EXISTS (
                       SELECT 1
                         FROM wechat_publications wp
                        WHERE wp.video_id = processed_videos.id
                   )"""
            )
            conn.commit()
            return cursor.rowcount

    def get_failed_videos_since(self, hours: int) -> List[Dict[str, Any]]:
        """取最近 N 小时 FAILED / LOGIN_REQUIRED 候选，供调用方应用平台账本保护。

        保留已有账本的候选是为了让 API 明确报告被平台保护跳过的数量；任何实际重置
        必须先调用提交账本保护，绝不能直接以此结果重试。
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                '''SELECT pv.youtube_id, pv.slice_index, pv.score, pv.title, pv.status
                   FROM processed_videos pv
                   WHERE pv.status IN ('FAILED', 'LOGIN_REQUIRED')
                     AND pv.updated_at >= datetime('now', ?)
                   ORDER BY pv.updated_at DESC''',
                (f"-{int(hours)} hours",)
            )
            return [dict(row) for row in cursor.fetchall()]

    def claim_video_for_processing(self, youtube_id: str, slice_index: int = 0) -> bool:
        """原子地将 PENDING 状态的特定切片任务改为 DOWNLOADING，用于防止并发抢占。"""
        # [Gemini_3.5_Flash_planning] 抢占定位增加 slice_index = ?
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE processed_videos SET status = 'DOWNLOADING', updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ? AND status = 'PENDING'",
                (youtube_id, slice_index)
            )
            conn.commit()
            return cursor.rowcount > 0

    def claim_next_deferred_wechat_publication(
        self,
        *,
        wall_street_since_upload_date: Optional[str] = None,
        daily_limit: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """原子领取一条视频号延后发布任务，按切片顺序恢复原有视频号发布链。

        传入 wall_street_since_upload_date 时，仅领取符合平台补录规则的积压视频：
        访谈/演讲类，或 Wall Street Truthbombs 指定源发布日期之后的视频。
        传入 daily_limit 时，按本机日期统计此前领取记录，并在同一写事务中写入
        本次领取记录，避免多轮巡航把每日额度放大。
        """
        if daily_limit is not None and daily_limit <= 0:
            return None
        terminal_states = ("PUBLISHED", "IGNORED", "COMPLETED")
        placeholders = ", ".join("?" for _ in terminal_states)
        join_channel = ""
        rule_filter = ""
        params: List[Any] = []
        if wall_street_since_upload_date:
            join_channel = "LEFT JOIN recommended_channels rc ON rc.channel_id = pv.channel_id"
            text_expr = (
                "lower(COALESCE(pv.title, '') || ' ' || COALESCE(pv.zh_title, '') || ' ' || "
                "COALESCE(pv.category, '') || ' ' || COALESCE(rc.channel_name, pv.channel_id, ''))"
            )
            speech_clause = " OR ".join(f"{text_expr} LIKE ?" for _ in self._BACKFILL_SPEECH_TERMS)
            rule_filter = f"""
                  AND (
                        ({speech_clause})
                     OR (
                        lower(COALESCE(rc.channel_name, pv.channel_id, '')) = 'wall street truthbombs'
                        AND pv.upload_date >= ?
                     )
                  )
            """
            params.extend(f"%{term.lower()}%" for term in self._BACKFILL_SPEECH_TERMS)
            params.append(wall_street_since_upload_date)
        params.extend(terminal_states)
        with self.get_connection() as conn:
            # 先获得写锁，再做额度统计和状态迁移，阻断并发巡航的竞态。
            conn.execute("BEGIN IMMEDIATE")
            if daily_limit is not None:
                claimed_today = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM wechat_deferred_recovery_claims claim
                    WHERE date(claim.claimed_at, 'localtime') = date('now', 'localtime')
                      AND NOT EXISTS (
                        SELECT 1
                        FROM wechat_publications_historical_archive archive
                        WHERE archive.video_id = claim.video_id
                      )
                    """
                ).fetchone()[0]
                if claimed_today >= daily_limit:
                    conn.commit()
                    return None
            candidate = conn.execute(
                f'''
                SELECT pv.*
                FROM processed_videos pv
                {join_channel}
                WHERE pv.status = 'WECHAT_DEFERRED'
                  AND NOT EXISTS (
                    SELECT 1
                    FROM wechat_publications_historical_archive archive
                    WHERE archive.video_id = pv.id
                  )
                  AND pv.youtube_id NOT IN (SELECT youtube_id FROM blacklisted_videos)
                  AND pv.channel_id NOT IN (SELECT channel_id FROM recommended_channels WHERE status = 'BLACKLISTED')
                  {rule_filter}
                  AND (
                    pv.slice_index = 0
                    OR NOT EXISTS (
                        SELECT 1 FROM processed_videos sib
                        WHERE sib.parent_id = pv.parent_id
                          AND sib.slice_index > 0
                          AND sib.slice_index < pv.slice_index
                          AND sib.status NOT IN ({placeholders})
                    )
                  )
                ORDER BY pv.updated_at ASC, pv.id ASC
                LIMIT 1
                ''',
                params,
            ).fetchone()
            if not candidate:
                return None
            cursor = conn.execute(
                '''
                UPDATE processed_videos
                SET status = 'DOWNLOADING', error_msg = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'WECHAT_DEFERRED'
                ''',
                (candidate["id"],),
            )
            if cursor.rowcount != 1:
                conn.commit()
                return None
            if daily_limit is not None:
                conn.execute(
                    "INSERT INTO wechat_deferred_recovery_claims (video_id) VALUES (?)",
                    (candidate["id"],),
                )
            conn.commit()
            return dict(candidate)

    def release_deferred_wechat_recovery_claim(self, youtube_id: str, *, slice_index: int = 0) -> bool:
        """释放尚未启动上传的延后恢复领取，供诊断/调度中止安全回滚额度。"""
        with self.get_connection() as conn:
            video = conn.execute(
                "SELECT id, status FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            if not video or video["status"] != "WECHAT_DEFERRED":
                return False
            cursor = conn.execute(
                "DELETE FROM wechat_deferred_recovery_claims "
                "WHERE video_id = ? AND date(claimed_at, 'localtime') = date('now', 'localtime')",
                (video["id"],),
            )
            conn.commit()
            return cursor.rowcount > 0

    def set_source_subtitle_preflight(
        self,
        youtube_id: str,
        status: str,
        *,
        error_msg: Optional[str] = None,
        slice_index: int = 0,
    ) -> None:
        """记录源字幕预检结果；非通过结果会撤销旧的预加工就绪标记。"""
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET source_subtitle_status = ?, "
                "source_subtitle_checked_at = CURRENT_TIMESTAMP, "
                "preparation_ready = CASE WHEN ? = 'PASSED' THEN preparation_ready ELSE 0 END, "
                "error_msg = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ?",
                (status, status, error_msg, youtube_id, slice_index),
            )
            conn.commit()

    def set_video_preparation_ready(
        self, youtube_id: str, ready: bool, *, slice_index: int = 0,
    ) -> None:
        """标记成片是否已完成到发布前；公开状态仍由调用方维持为 PENDING。"""
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET preparation_ready = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ?",
                (int(ready), youtube_id, slice_index),
            )
            conn.commit()

    def clear_video_preparation_state(self, youtube_id: str, *, slice_index: int = 0) -> None:
        """在删除产物后清空预加工和源字幕检查点，强制下一轮重新预检。"""
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET preparation_ready = 0, source_subtitle_status = 'PENDING', "
                "source_subtitle_checked_at = NULL, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            )
            conn.commit()

    @staticmethod
    def _video_publication_subject_id(video_id: int) -> str:
        """为既有视频行生成稳定的通用发布主体标识。"""
        return f"video:{int(video_id)}"

    def _ensure_video_publication_subject(self, conn: sqlite3.Connection, video_id: int) -> str:
        """在当前事务内确保普通视频已有发布主体，不创建任何平台投递记录。"""
        subject_id = self._video_publication_subject_id(video_id)
        conn.execute(
            '''INSERT OR IGNORE INTO publication_subjects (id, kind, video_id)
               VALUES (?, 'VIDEO_ITEM', ?)''',
            (subject_id, video_id),
        )
        return subject_id

    # --- WeChat Channels publication confirmation ledger DAL ---
    def record_wechat_publication_confirmation(
        self,
        youtube_id: str,
        *,
        evidence_path: Optional[str],
        state: str = "PUBLISHED",
        error_message: Optional[str] = None,
        slice_index: int = 0,
        platform_post_id: Optional[str] = None,
        platform_url: Optional[str] = None,
        reconciled: bool = False,
    ) -> Dict[str, Any]:
        """记录视频号提交/后台确认结果；同一视频只更新既有记录，不会触发投递。"""
        normalized_state = (state or "").upper()
        if normalized_state not in {
            "PUBLISHED", "UNDER_REVIEW", "REJECTED", "NOT_FOUND", "UNCERTAIN", "SUBMITTED_UNBOUND", "SUBMITTED_BOUND",
        }:
            raise ValueError(
                "Wechat publication state must be PUBLISHED, UNDER_REVIEW, REJECTED, NOT_FOUND, "
                "UNCERTAIN, or SUBMITTED_UNBOUND"
            )
        clean_evidence_path = (evidence_path or "").strip() or None
        clean_platform_post_id = (platform_post_id or "").strip() or None
        clean_platform_url = (platform_url or "").strip() or None
        if normalized_state == "SUBMITTED_BOUND" and not clean_platform_post_id:
            raise ValueError("SUBMITTED_BOUND WeChat publication requires platform_post_id")
        if normalized_state in {"PUBLISHED", "UNDER_REVIEW", "REJECTED", "NOT_FOUND"} and not clean_evidence_path:
            raise ValueError(f"{normalized_state} WeChat publication requires post-list evidence")

        with self.get_connection() as conn:
            video = conn.execute(
                "SELECT id FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            if not video:
                raise ValueError(f"Video not found: {youtube_id}#{slice_index}")
            subject_id = self._ensure_video_publication_subject(conn, int(video["id"]))
            conn.execute(
                '''
                INSERT INTO wechat_publications (
                    video_id, subject_id, state, evidence_path, confirmed_at, platform_post_id, platform_url,
                    last_reconciled_at, last_error_message
                ) VALUES (?, ?, ?, ?, CASE WHEN ? = 'PUBLISHED' THEN CURRENT_TIMESTAMP ELSE NULL END,
                          ?, ?, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    state = excluded.state,
                    evidence_path = COALESCE(excluded.evidence_path, wechat_publications.evidence_path),
                    confirmed_at = CASE
                        WHEN excluded.state = 'PUBLISHED' THEN CURRENT_TIMESTAMP
                        ELSE NULL
                    END,
                    platform_post_id = COALESCE(excluded.platform_post_id, wechat_publications.platform_post_id),
                    platform_url = COALESCE(excluded.platform_url, wechat_publications.platform_url),
                    last_reconciled_at = CASE
                        WHEN excluded.last_reconciled_at IS NOT NULL THEN excluded.last_reconciled_at
                        ELSE wechat_publications.last_reconciled_at
                    END,
                    last_error_message = excluded.last_error_message,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (
                    video["id"], subject_id, normalized_state, clean_evidence_path, normalized_state,
                    clean_platform_post_id,
                    clean_platform_url,
                    bool(reconciled), error_message,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM wechat_publications WHERE video_id = ?", (video["id"],)
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to record WeChat publication confirmation")
            return dict(row)

    def record_wechat_submission_attempt(
        self,
        youtube_id: str,
        *,
        slice_index: int = 0,
        evidence_path: Optional[str] = None,
        final_title: Optional[str] = None,
        video_sha256: Optional[str] = None,
        cover_sha256: Optional[str] = None,
    ) -> Dict[str, Any]:
        """记录一次已提交但尚未取得视频号原生 ID 的不可变尝试，不确认平台状态。"""
        import hashlib
        from uuid import uuid4

        with self.get_connection() as conn:
            video = conn.execute(
                "SELECT id, title, zh_title FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            if not video:
                raise ValueError(f"Video not found: {youtube_id}#{slice_index}")
            subject_id = self._ensure_video_publication_subject(conn, int(video["id"]))
            clean_evidence_path = (evidence_path or "").strip() or None
            if clean_evidence_path:
                existing = conn.execute(
                    "SELECT * FROM wechat_submission_attempts WHERE evidence_path = ? ORDER BY created_at DESC LIMIT 1",
                    (clean_evidence_path,),
                ).fetchone()
                if existing:
                    return dict(existing)
            title = (final_title or video["zh_title"] or video["title"] or youtube_id).strip()
            attempt_id = uuid4().hex
            conn.execute(
                '''
                INSERT INTO wechat_submission_attempts (
                    attempt_id, video_id, subject_id, state, final_title, final_title_sha256,
                    video_sha256, cover_sha256, evidence_path
                ) VALUES (?, ?, ?, 'SUBMITTED_UNBOUND', ?, ?, ?, ?, ?)
                ''',
                (
                    attempt_id, video["id"], subject_id,
                    title,
                    hashlib.sha256(title.encode("utf-8")).hexdigest(),
                    (video_sha256 or "").strip() or None,
                    (cover_sha256 or "").strip() or None,
                    clean_evidence_path,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM wechat_submission_attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to record WeChat submission attempt")
            return dict(row)

    def record_wechat_submission_acceptance(
        self,
        youtube_id: str,
        *,
        evidence_path: Optional[str],
        error_message: Optional[str],
        final_title: Optional[str],
        slice_index: int = 0,
        platform_post_id: Optional[str] = None,
        platform_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """同事务保存视频号受理事实、一次性尝试和任务停止状态。

        该方法是上传器明确受理后的唯一写入口。任一写入失败会整体回滚，避免
        ``wechat_publications`` 已阻止重传、而 ``processed_videos`` 却回落 FAILED。
        """
        import hashlib
        from uuid import uuid4

        clean_evidence_path = (evidence_path or "").strip() or None
        clean_platform_post_id = (platform_post_id or "").strip() or None
        clean_platform_url = (platform_url or "").strip() or None
        state = "SUBMITTED_BOUND" if clean_platform_post_id else "SUBMITTED_UNBOUND"
        with self.get_connection() as conn:
            video = conn.execute(
                "SELECT id, title, zh_title FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            if not video:
                raise ValueError(f"Video not found: {youtube_id}#{slice_index}")
            subject_id = self._ensure_video_publication_subject(conn, int(video["id"]))
            conn.execute(
                '''
                INSERT INTO wechat_publications (
                    video_id, subject_id, state, evidence_path, confirmed_at, platform_post_id, platform_url,
                    last_reconciled_at, last_error_message
                ) VALUES (?, ?, ?, ?, NULL, ?, ?, NULL, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    state = excluded.state,
                    evidence_path = COALESCE(excluded.evidence_path, wechat_publications.evidence_path),
                    confirmed_at = NULL,
                    platform_post_id = COALESCE(excluded.platform_post_id, wechat_publications.platform_post_id),
                    platform_url = COALESCE(excluded.platform_url, wechat_publications.platform_url),
                    last_error_message = excluded.last_error_message,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (
                    video["id"], subject_id, state, clean_evidence_path, clean_platform_post_id,
                    clean_platform_url, error_message,
                ),
            )
            attempt = None
            if clean_evidence_path:
                attempt = conn.execute(
                    "SELECT * FROM wechat_submission_attempts WHERE evidence_path = ? ORDER BY created_at DESC LIMIT 1",
                    (clean_evidence_path,),
                ).fetchone()
            if attempt is None:
                title = (final_title or video["zh_title"] or video["title"] or youtube_id).strip()
                attempt_id = uuid4().hex
                conn.execute(
                    '''INSERT INTO wechat_submission_attempts (
                           attempt_id, video_id, subject_id, state, final_title, final_title_sha256,
                           evidence_path, platform_post_id, platform_url, bound_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,
                                 CASE WHEN ? IS NULL THEN NULL ELSE CURRENT_TIMESTAMP END)''',
                    (
                        attempt_id, video["id"], subject_id,
                        "PLATFORM_ID_BOUND" if clean_platform_post_id else "SUBMITTED_UNBOUND",
                        title, hashlib.sha256(title.encode("utf-8")).hexdigest(), clean_evidence_path,
                        clean_platform_post_id, clean_platform_url, clean_platform_post_id,
                    ),
                )
                attempt = conn.execute(
                    "SELECT * FROM wechat_submission_attempts WHERE attempt_id = ?", (attempt_id,)
                ).fetchone()
            elif clean_platform_post_id and not attempt["platform_post_id"]:
                conn.execute(
                    '''UPDATE wechat_submission_attempts
                       SET state = 'PLATFORM_ID_BOUND', platform_post_id = ?, platform_url = ?,
                           bound_at = CURRENT_TIMESTAMP
                       WHERE attempt_id = ?''',
                    (clean_platform_post_id, clean_platform_url, attempt["attempt_id"]),
                )
            cursor = conn.execute(
                "UPDATE processed_videos SET status = ?, error_msg = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (state, error_message, video["id"]),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Failed to persist WeChat submission task state")
            conn.commit()
            publication = conn.execute(
                "SELECT * FROM wechat_publications WHERE video_id = ?", (video["id"],)
            ).fetchone()
            if not publication:
                raise RuntimeError("Failed to persist WeChat submission acceptance")
            return {"publication": dict(publication), "attempt_id": str(attempt["attempt_id"]) if attempt else None}

    def repair_wechat_submission_status_divergence(self) -> int:
        """仅以不可重传的视频号受理账本修复已分叉的本地任务状态。

        不访问平台、不创建投稿尝试，也不处理 PUBLISHED；此修复只让已经存在的
        SUBMITTED_* / UNDER_REVIEW / UNCERTAIN 账本重新成为任务状态机的停止状态。
        """
        states = ("SUBMITTED_UNBOUND", "SUBMITTED_BOUND", "UNDER_REVIEW", "UNCERTAIN")
        placeholders = ", ".join("?" for _ in states)
        with self.get_connection() as conn:
            cursor = conn.execute(
                f'''UPDATE processed_videos
                    SET status = (
                        SELECT wp.state FROM wechat_publications wp WHERE wp.video_id = processed_videos.id
                    ),
                        error_msg = (
                        SELECT wp.last_error_message FROM wechat_publications wp WHERE wp.video_id = processed_videos.id
                    ),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id IN (SELECT video_id FROM wechat_publications WHERE state IN ({placeholders}))
                      AND status NOT IN ({placeholders})''',
                (*states, *states),
            )
            conn.commit()
            return cursor.rowcount

    def record_wechat_publication_confirmation_for_subject(
        self,
        subject_id: str,
        *,
        evidence_path: Optional[str],
        state: str = "PUBLISHED",
        error_message: Optional[str] = None,
        platform_post_id: Optional[str] = None,
        platform_url: Optional[str] = None,
        reconciled: bool = False,
    ) -> Dict[str, Any]:
        """按通用发布主体记录视频号状态，供 Highlight Clip 复用既有 post_id 审核契约。"""
        normalized_state = (state or "").upper()
        supported_states = {
            "PUBLISHED", "UNDER_REVIEW", "REJECTED", "NOT_FOUND", "UNCERTAIN",
            "SUBMITTED_UNBOUND", "SUBMITTED_BOUND",
        }
        if normalized_state not in supported_states:
            raise ValueError("Unsupported WeChat publication state")
        clean_subject_id = (subject_id or "").strip()
        clean_evidence_path = (evidence_path or "").strip() or None
        clean_platform_post_id = (platform_post_id or "").strip() or None
        clean_platform_url = (platform_url or "").strip() or None
        if not clean_subject_id:
            raise ValueError("publication subject id is required")
        if normalized_state == "SUBMITTED_BOUND" and not clean_platform_post_id:
            raise ValueError("SUBMITTED_BOUND WeChat publication requires platform_post_id")
        if normalized_state in {"PUBLISHED", "UNDER_REVIEW", "REJECTED", "NOT_FOUND"} and not clean_evidence_path:
            raise ValueError(f"{normalized_state} WeChat publication requires post-list evidence")
        with self.get_connection() as conn:
            subject = conn.execute(
                "SELECT id, video_id FROM publication_subjects WHERE id = ?", (clean_subject_id,)
            ).fetchone()
            if not subject:
                raise ValueError(f"Publication subject not found: {clean_subject_id}")
            conn.execute(
                '''INSERT INTO wechat_publications (
                       video_id, subject_id, state, evidence_path, confirmed_at, platform_post_id, platform_url,
                       last_reconciled_at, last_error_message
                   ) VALUES (?, ?, ?, ?, CASE WHEN ? = 'PUBLISHED' THEN CURRENT_TIMESTAMP ELSE NULL END,
                             ?, ?, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END, ?)
                   ON CONFLICT(subject_id) DO UPDATE SET
                       state = excluded.state,
                       evidence_path = COALESCE(excluded.evidence_path, wechat_publications.evidence_path),
                       confirmed_at = CASE WHEN excluded.state = 'PUBLISHED' THEN CURRENT_TIMESTAMP ELSE NULL END,
                       platform_post_id = COALESCE(excluded.platform_post_id, wechat_publications.platform_post_id),
                       platform_url = COALESCE(excluded.platform_url, wechat_publications.platform_url),
                       last_reconciled_at = CASE
                           WHEN excluded.last_reconciled_at IS NOT NULL THEN excluded.last_reconciled_at
                           ELSE wechat_publications.last_reconciled_at
                       END,
                       last_error_message = excluded.last_error_message,
                       updated_at = CURRENT_TIMESTAMP''',
                (
                    subject["video_id"], clean_subject_id, normalized_state, clean_evidence_path,
                    normalized_state, clean_platform_post_id, clean_platform_url, bool(reconciled), error_message,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM wechat_publications WHERE subject_id = ?", (clean_subject_id,)
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to record WeChat publication confirmation")
            return dict(row)

    def record_wechat_submission_attempt_for_subject(
        self,
        subject_id: str,
        *,
        final_title: str,
        evidence_path: Optional[str] = None,
        video_sha256: Optional[str] = None,
        cover_sha256: Optional[str] = None,
    ) -> Dict[str, Any]:
        """为通用发布主体创建不可变提交尝试；绑定原生 post_id 前绝不宣称已发布。"""
        import hashlib
        from uuid import uuid4

        clean_subject_id = (subject_id or "").strip()
        title = (final_title or "").strip()
        if not clean_subject_id:
            raise ValueError("publication subject id is required")
        if not title:
            raise ValueError("final_title is required for a WeChat submission attempt")
        clean_evidence_path = (evidence_path or "").strip() or None
        with self.get_connection() as conn:
            subject = conn.execute(
                "SELECT id, video_id FROM publication_subjects WHERE id = ?", (clean_subject_id,)
            ).fetchone()
            if not subject:
                raise ValueError(f"Publication subject not found: {clean_subject_id}")
            if clean_evidence_path:
                existing = conn.execute(
                    "SELECT * FROM wechat_submission_attempts WHERE evidence_path = ? ORDER BY created_at DESC LIMIT 1",
                    (clean_evidence_path,),
                ).fetchone()
                if existing:
                    return dict(existing)
            attempt_id = uuid4().hex
            conn.execute(
                '''INSERT INTO wechat_submission_attempts (
                       attempt_id, video_id, subject_id, state, final_title, final_title_sha256,
                       video_sha256, cover_sha256, evidence_path
                   ) VALUES (?, ?, ?, 'SUBMITTED_UNBOUND', ?, ?, ?, ?, ?)''',
                (
                    attempt_id, subject["video_id"], clean_subject_id, title,
                    hashlib.sha256(title.encode("utf-8")).hexdigest(),
                    (video_sha256 or "").strip() or None,
                    (cover_sha256 or "").strip() or None,
                    clean_evidence_path,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM wechat_submission_attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to record WeChat submission attempt")
            return dict(row)

    def get_wechat_publication_for_subject(self, subject_id: str) -> Optional[Dict[str, Any]]:
        """按发布主体读取视频号账本；供独立 Clip 的后续按 ID 平台回查使用。"""
        clean_subject_id = (subject_id or "").strip()
        if not clean_subject_id:
            return None
        with self.get_connection() as conn:
            row = conn.execute(
                '''SELECT wp.*, ps.kind AS subject_kind, ps.highlight_clip_id
                   FROM wechat_publications wp
                   JOIN publication_subjects ps ON ps.id = wp.subject_id
                   WHERE wp.subject_id = ?''',
                (clean_subject_id,),
            ).fetchone()
            return dict(row) if row else None

    def bind_wechat_submission_attempt_platform_id(
        self, attempt_id: str, *, platform_post_id: str, platform_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """仅在取得平台原生唯一 ID 后绑定提交尝试；不由标题或时间推断。"""
        clean_post_id = (platform_post_id or "").strip()
        if not clean_post_id:
            raise ValueError("platform_post_id is required for an exact WeChat binding")
        with self.get_connection() as conn:
            existing = conn.execute(
                "SELECT attempt_id FROM wechat_submission_attempts WHERE platform_post_id = ?",
                (clean_post_id,),
            ).fetchone()
            if existing and existing["attempt_id"] != attempt_id:
                raise ValueError("platform_post_id is already bound to another submission attempt")
            cursor = conn.execute(
                '''
                UPDATE wechat_submission_attempts
                SET state = 'PLATFORM_ID_BOUND', platform_post_id = ?, platform_url = ?,
                    bound_at = CURRENT_TIMESTAMP
                WHERE attempt_id = ?
                ''',
                (clean_post_id, (platform_url or "").strip() or None, attempt_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Wechat submission attempt not found: {attempt_id}")
            conn.commit()
            row = conn.execute(
                "SELECT * FROM wechat_submission_attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
            return dict(row)

    def is_wechat_publication_historically_archived(
        self, youtube_id: str, *, slice_index: int = 0
    ) -> bool:
        """历史未解墓碑存在时，禁止任何调度路径重新生成活跃视频号账本。"""
        with self.get_connection() as conn:
            row = conn.execute(
                '''
                SELECT 1
                FROM wechat_publications_historical_archive archive
                JOIN processed_videos pv ON pv.id = archive.video_id
                WHERE pv.youtube_id = ? AND pv.slice_index = ?
                LIMIT 1
                ''',
                (youtube_id, slice_index),
            ).fetchone()
            return row is not None

    def archive_wechat_publication_as_historical_unresolved(
        self, youtube_id: str, *, reason: str, slice_index: int = 0
    ) -> bool:
        """无损归档无平台主键的历史记录，并移除活跃账本避免误报待平台确认。"""
        with self.get_connection() as conn:
            video = conn.execute(
                "SELECT id FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            if not video:
                raise ValueError(f"Video not found: {youtube_id}#{slice_index}")
            publication = conn.execute(
                "SELECT * FROM wechat_publications WHERE video_id = ?", (video["id"],)
            ).fetchone()
            if not publication:
                return False
            conn.execute(
                '''
                INSERT OR IGNORE INTO wechat_publications_historical_archive (
                    original_publication_id, archived_at, archive_reason, video_id, state,
                    evidence_path, confirmed_at, platform_post_id, platform_url,
                    last_reconciled_at, last_error_message, created_at, updated_at
                ) VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    publication["id"], reason, video["id"], publication["state"],
                    publication["evidence_path"], publication["confirmed_at"],
                    publication["platform_post_id"], publication["platform_url"],
                    publication["last_reconciled_at"], publication["last_error_message"],
                    publication["created_at"], publication["updated_at"],
                ),
            )
            conn.execute("DELETE FROM wechat_publications WHERE video_id = ?", (video["id"],))
            conn.execute(
                "UPDATE processed_videos SET status = 'HISTORICAL_UNRESOLVED', updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (video["id"],),
            )
            conn.commit()
            return True

    def get_wechat_publication(
        self, youtube_id: str, *, slice_index: int = 0
    ) -> Optional[Dict[str, Any]]:
        """读取视频号确认账本，供页面与人工核验明确区分本地状态和平台证据。"""
        with self.get_connection() as conn:
            row = conn.execute(
                '''
                SELECT wp.*, pv.youtube_id, pv.slice_index
                FROM wechat_publications wp
                JOIN processed_videos pv ON pv.id = wp.video_id
                WHERE pv.youtube_id = ? AND pv.slice_index = ?
                ''',
                (youtube_id, slice_index),
            ).fetchone()
            return dict(row) if row else None

    def get_wechat_publications_by_states(self, states: Collection[str]) -> List[Dict[str, Any]]:
        """按状态返回视频号账本及原视频标识，供作品管理页只读回查。"""
        supported = {
            "PUBLISHED", "UNDER_REVIEW", "REJECTED", "NOT_FOUND", "UNCERTAIN",
            "SUBMITTED_UNBOUND", "SUBMITTED_BOUND",
        }
        normalized_states = [str(state or "").upper() for state in states]
        if not normalized_states or any(state not in supported for state in normalized_states):
            raise ValueError("states must contain supported WeChat publication states")
        placeholders = ", ".join("?" for _ in normalized_states)
        with self.get_connection() as conn:
            rows = conn.execute(
                f'''SELECT wp.*, pv.youtube_id, pv.slice_index
                    FROM wechat_publications wp
                    JOIN processed_videos pv ON pv.id = wp.video_id
                    WHERE wp.state IN ({placeholders})
                    ORDER BY wp.updated_at ASC, wp.id ASC''',
                normalized_states,
            ).fetchall()
            return [dict(row) for row in rows]

    def list_manual_publish_lease_candidates(self, limit: int = 8) -> List[Dict[str, Any]]:
        """列出可由管理员签发单任务微信 lease 的候选；不改变队列或发布状态。"""
        bounded_limit = max(1, min(20, int(limit)))
        with self.get_connection() as conn:
            rows = conn.execute(
                '''SELECT pv.*
                   FROM processed_videos pv
                   WHERE pv.status = 'PENDING'
                     AND COALESCE(pv.source, 'AUTO') != 'DISCOVERY'
                     AND COALESCE(pv.publication_review_required, 0) = 0
                     AND pv.channel_id NOT IN (
                         SELECT channel_id FROM recommended_channels WHERE status = 'BLACKLISTED'
                     )
                     AND pv.youtube_id NOT IN (SELECT youtube_id FROM blacklisted_videos)
                     AND NOT EXISTS (
                         SELECT 1 FROM wechat_publications wp WHERE wp.video_id = pv.id
                     )
                     AND NOT EXISTS (
                         SELECT 1 FROM wechat_publications_historical_archive archive
                         WHERE archive.video_id = pv.id
                     )
                     AND NOT EXISTS (
                         SELECT 1 FROM manual_publish_leases lease
                         WHERE lease.video_id = pv.id AND lease.platform = 'wechat'
                           AND lease.claimed_at IS NULL AND lease.revoked_at IS NULL
                           AND lease.expires_at > CURRENT_TIMESTAMP
                     )
                     AND (
                         pv.slice_index = 0 OR NOT EXISTS (
                             SELECT 1 FROM processed_videos sibling
                             WHERE sibling.parent_id = pv.parent_id
                               AND sibling.slice_index > 0
                               AND sibling.slice_index < pv.slice_index
                               AND sibling.status NOT IN ('PUBLISHED', 'IGNORED', 'COMPLETED')
                         )
                     )
                   ORDER BY COALESCE(pv.preparation_ready, 0) DESC,
                            pv.score DESC, pv.updated_at DESC
                   LIMIT ?''',
                (bounded_limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_active_manual_publish_leases(self, limit: int = 8) -> List[Dict[str, Any]]:
        """返回尚未消费且未过期的单任务 lease，供手机端审计展示。"""
        bounded_limit = max(1, min(20, int(limit)))
        with self.get_connection() as conn:
            rows = conn.execute(
                '''SELECT lease.*, pv.youtube_id, pv.slice_index, pv.title, pv.zh_title,
                          pv.status, pv.score, pv.preparation_ready
                   FROM manual_publish_leases lease
                   JOIN processed_videos pv ON pv.id = lease.video_id
                   WHERE lease.claimed_at IS NULL AND lease.revoked_at IS NULL
                     AND lease.expires_at > CURRENT_TIMESTAMP
                   ORDER BY lease.expires_at ASC, lease.issued_at ASC
                   LIMIT ?''',
                (bounded_limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def issue_manual_publish_lease(
        self,
        youtube_id: str,
        *,
        slice_index: int = 0,
        issued_by: str,
        issued_via: str,
        ttl_minutes: int = 120,
        claim_video: bool = False,
    ) -> Dict[str, Any]:
        """签发单任务一次性 lease；可在同一写事务中领取任务，但不接触平台。"""
        from uuid import uuid4

        clean_issued_by = (issued_by or "").strip()
        clean_issued_via = (issued_via or "").strip()
        bounded_ttl = max(1, min(120, int(ttl_minutes)))
        if not clean_issued_by or not clean_issued_via:
            raise ValueError("issued_by and issued_via are required")

        with self.get_connection() as conn:
            # 锁住“候选复核 → 签发 → 可选任务领取”的完整决策，避免 lease 已落库但
            # PENDING 被另一个调度器抢走，形成悬空授权。
            conn.execute("BEGIN IMMEDIATE")
            video = conn.execute(
                '''SELECT pv.* FROM processed_videos pv
                   WHERE pv.youtube_id = ? AND pv.slice_index = ?
                     AND pv.status = 'PENDING'
                     AND COALESCE(pv.source, 'AUTO') != 'DISCOVERY'
                     AND COALESCE(pv.publication_review_required, 0) = 0
                     AND pv.channel_id NOT IN (
                         SELECT channel_id FROM recommended_channels WHERE status = 'BLACKLISTED'
                     )
                     AND pv.youtube_id NOT IN (SELECT youtube_id FROM blacklisted_videos)
                     AND NOT EXISTS (
                         SELECT 1 FROM wechat_publications wp WHERE wp.video_id = pv.id
                     )
                     AND NOT EXISTS (
                         SELECT 1 FROM wechat_publications_historical_archive archive
                         WHERE archive.video_id = pv.id
                     )
                     AND (
                         pv.slice_index = 0 OR NOT EXISTS (
                             SELECT 1 FROM processed_videos sibling
                             WHERE sibling.parent_id = pv.parent_id
                               AND sibling.slice_index > 0
                               AND sibling.slice_index < pv.slice_index
                               AND sibling.status NOT IN ('PUBLISHED', 'IGNORED', 'COMPLETED')
                         )
                     )''',
                (youtube_id, slice_index),
            ).fetchone()
            if not video:
                raise ValueError("任务不在可签发 lease 的安全候选集合中")

            existing = conn.execute(
                '''SELECT * FROM manual_publish_leases
                   WHERE video_id = ? AND platform = 'wechat'
                     AND claimed_at IS NULL AND revoked_at IS NULL
                     AND expires_at > CURRENT_TIMESTAMP
                   ORDER BY issued_at DESC LIMIT 1''',
                (video["id"],),
            ).fetchone()
            if existing:
                lease_id = existing["lease_id"]
            else:
                lease_id = uuid4().hex
                conn.execute(
                    '''INSERT INTO manual_publish_leases (
                           lease_id, video_id, platform, issued_by, issued_via, expires_at
                       ) VALUES (?, ?, 'wechat', ?, ?, datetime('now', ?))''',
                    (lease_id, video["id"], clean_issued_by, clean_issued_via,
                     f"+{bounded_ttl} minutes"),
                )
            if claim_video:
                claimed = conn.execute(
                    '''UPDATE processed_videos
                       SET status = 'DOWNLOADING', updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND status = 'PENDING' ''',
                    (video["id"],),
                )
                if claimed.rowcount != 1:
                    raise ValueError("任务已被其他调度器领取，lease 未签发")
            conn.commit()
            lease = conn.execute(
                "SELECT * FROM manual_publish_leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
            if not lease:
                raise RuntimeError("manual publish lease was not persisted")
            return {**dict(lease), "youtube_id": video["youtube_id"],
                    "slice_index": video["slice_index"], "title": video["title"]}

    def claim_manual_publish_lease(
        self, youtube_id: str, *, slice_index: int = 0, platform: str = "wechat",
    ) -> Optional[Dict[str, Any]]:
        """在平台上传器启动前原子消费一次 lease；已领取、撤销或过期后永不复用。"""
        if platform != "wechat":
            return None
        with self.get_connection() as conn:
            row = conn.execute(
                '''SELECT lease.* FROM manual_publish_leases lease
                   JOIN processed_videos pv ON pv.id = lease.video_id
                   WHERE pv.youtube_id = ? AND pv.slice_index = ?
                     AND lease.platform = ? AND lease.claimed_at IS NULL
                     AND lease.revoked_at IS NULL AND lease.expires_at > CURRENT_TIMESTAMP
                   ORDER BY lease.issued_at DESC LIMIT 1''',
                (youtube_id, slice_index, platform),
            ).fetchone()
            if not row:
                return None
            cursor = conn.execute(
                '''UPDATE manual_publish_leases SET claimed_at = CURRENT_TIMESTAMP
                   WHERE lease_id = ? AND claimed_at IS NULL AND revoked_at IS NULL
                     AND expires_at > CURRENT_TIMESTAMP''',
                (row["lease_id"],),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return None
            conn.commit()
            claimed = conn.execute(
                "SELECT * FROM manual_publish_leases WHERE lease_id = ?", (row["lease_id"],)
            ).fetchone()
            return dict(claimed) if claimed else None

    def revoke_manual_publish_lease(
        self, lease_id: str, *, revoked_by: str,
    ) -> Optional[Dict[str, Any]]:
        """撤销尚未消费且未过期的 lease；返回审计行，其他状态不做任何改变。"""
        clean_lease_id = (lease_id or "").strip()
        clean_revoked_by = (revoked_by or "").strip()
        if not clean_lease_id or not clean_revoked_by:
            raise ValueError("lease_id and revoked_by are required")
        with self.get_connection() as conn:
            cursor = conn.execute(
                '''UPDATE manual_publish_leases
                   SET revoked_at = CURRENT_TIMESTAMP, revoked_by = ?
                   WHERE lease_id = ? AND claimed_at IS NULL AND revoked_at IS NULL
                     AND expires_at > CURRENT_TIMESTAMP''',
                (clean_revoked_by, clean_lease_id),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return None
            conn.commit()
            revoked = conn.execute(
                "SELECT * FROM manual_publish_leases WHERE lease_id = ?", (clean_lease_id,)
            ).fetchone()
            return dict(revoked) if revoked else None

    def purge_stale_tasks(self, stale_hours: int = 2) -> int:
        """仅回收提交前卡住的加工任务，绝不重置任何发布/审核账本状态。"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # 历史实现用“排除终态”的否定条件，遗漏 SUBMITTED_UNBOUND、UNDER_REVIEW、
            # UNCERTAIN、HISTORICAL_UNRESOLVED 后会把已有提交证据的任务复活为 PENDING。
            # 这会挤占新片队列，更严重时可能绕过未来新增账本状态。故改为显式白名单：
            # 只回收仍在提交前的三个可逆加工阶段。
            cursor.execute(
                '''
                UPDATE processed_videos
                SET status = 'PENDING',
                    retry_count = retry_count + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE status IN ('DOWNLOADING', 'COPYWRITING', 'TRANSCRIBING')
                AND updated_at < datetime('now', ?)
                ''',
                (f'-{stale_hours} hours',)
            )
            conn.commit()
            return cursor.rowcount

    def get_stale_publishing_videos(self, stale_minutes: int = 30) -> List[Dict[str, Any]]:
        """取长时间停留在 PUBLISHING 的任务，供上层结合进程存活性做保守回收。

        注意：这里只暴露候选，不直接改状态；是否回收由业务层依据 process_pid 是否仍存活决定，
        以避免把仍在微信后台真实上传/发表中的任务误判为失败。
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM processed_videos "
                "WHERE status = 'PUBLISHING' AND updated_at < datetime('now', ?) "
                "ORDER BY updated_at ASC",
                (f"-{int(stale_minutes)} minutes",)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_stale_pre_submission_processing_videos(
        self, stale_minutes: int = 20,
    ) -> List[Dict[str, Any]]:
        """返回超时的预提交任务候选；发布阶段绝不由此路径回收。"""
        states = ("DOWNLOADING", "COPYWRITING", "TRANSCRIBING", "AI_COVER_PENDING")
        placeholders = ", ".join("?" for _ in states)
        with self.get_connection() as conn:
            rows = conn.execute(
                f"""SELECT * FROM processed_videos
                    WHERE status IN ({placeholders})
                      AND updated_at < datetime('now', ?)
                    ORDER BY updated_at ASC""",
                (*states, f"-{max(1, int(stale_minutes))} minutes"),
            ).fetchall()
            return [dict(row) for row in rows]

    def recover_orphaned_pre_submission_task(
        self,
        youtube_id: str,
        *,
        expected_process_pid: Optional[int],
        error_msg: str,
        slice_index: int = 0,
        max_retry_count: int = 2,
    ) -> Optional[str]:
        """有界恢复已死的下载/文案/转录任务，返回 PENDING、FAILED 或 None。

        ``expected_process_pid`` 使进程存活检查与状态写入形成 compare-and-set：
        若新的子进程已接管任务，此次孤儿回收不会覆盖它。发布阶段没有资格进入此方法。
        """
        recoverable_states = ("DOWNLOADING", "COPYWRITING", "TRANSCRIBING", "AI_COVER_PENDING")
        with self.get_connection() as conn:
            row = conn.execute(
                """SELECT status, retry_count, process_pid FROM processed_videos
                   WHERE youtube_id = ? AND slice_index = ?""",
                (youtube_id, slice_index),
            ).fetchone()
            if not row or row["status"] not in recoverable_states:
                return None
            if row["process_pid"] != expected_process_pid:
                return None

            retries = int(row["retry_count"] or 0)
            retry_limit = max(1, int(max_retry_count))
            next_status = "PENDING" if retries < retry_limit else "FAILED"
            next_retry_count = retries + 1 if next_status == "PENDING" else retries
            cursor = conn.execute(
                """UPDATE processed_videos
                   SET status = ?, retry_count = ?, process_pid = NULL, error_msg = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE youtube_id = ? AND slice_index = ? AND status = ?
                     AND process_pid IS ?""",
                (
                    next_status, next_retry_count, error_msg, youtube_id, slice_index,
                    row["status"], expected_process_pid,
                ),
            )
            conn.commit()
            return next_status if cursor.rowcount == 1 else None

    def update_video_score(self, youtube_id: str, score: int, force: bool = False, slice_index: int = 0) -> None:
        """更新特定切片的评分，支持评分锁保护。"""
        # [Gemini_3.5_Flash_planning] 定位增加 slice_index = ?
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT channel_id, view_count, like_count FROM processed_videos "
                "WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            if not row:
                return
            if row:
                capped_score = cap_channel_score(row["channel_id"], score)
                if capped_score != score:
                    self._logger.info(
                        "[ScoreCap] %s score capped from %s to %s",
                        youtube_id, score, capped_score,
                    )
                score = capped_score
            if force:
                conn.execute(
                    "UPDATE processed_videos SET score = ?, is_manually_scored = 1, "
                    "updated_at = CURRENT_TIMESTAMP WHERE youtube_id = ? AND slice_index = ?",
                    (score, youtube_id, slice_index)
                )
            else:
                score_input_signature = self._score_input_signature(
                    row["channel_id"], row["view_count"], row["like_count"],
                )
                cursor = conn.execute(
                    "UPDATE processed_videos SET score = ?, score_input_signature = ?, "
                    "score_computed_at = CURRENT_TIMESTAMP "
                    "WHERE youtube_id = ? AND slice_index = ? AND is_manually_scored = 0",
                    (score, score_input_signature, youtube_id, slice_index)
                )
                if cursor.rowcount == 0:
                    self._logger.info(f"[ScoreLock] Skipped auto-score for manually-locked video: {youtube_id} (slice {slice_index})")
                    return
            conn.commit()

    @staticmethod
    def _score_input_signature(
        channel_id: Optional[str], view_count: Optional[int], like_count: Optional[int],
    ) -> str:
        """评分只依赖频道规则、播放量和点赞量；字段变化即失效缓存。"""
        return f"{channel_id or ''}:{max(0, int(view_count or 0))}:{max(0, int(like_count or 0))}"

    def get_pending_videos_requiring_score_refresh(
        self, refresh_interval_minutes: int,
    ) -> List[Dict[str, Any]]:
        """取指标变更或评分缓存到期的自动候选，不把评分动作当成内容更新。"""
        safe_interval = max(0, int(refresh_interval_minutes))
        current_signature = (
            "COALESCE(pv.channel_id, '') || ':' || "
            "CAST(COALESCE(pv.view_count, 0) AS TEXT) || ':' || "
            "CAST(COALESCE(pv.like_count, 0) AS TEXT)"
        )
        query = f"""
            SELECT pv.*
            FROM processed_videos pv
            WHERE pv.status = 'PENDING'
              AND pv.score < 75
              AND IFNULL(pv.source, '') != 'DISCOVERY'
              AND IFNULL(pv.is_manually_scored, 0) = 0
              AND (
                    pv.score_input_signature IS NULL
                 OR pv.score_input_signature != ({current_signature})
                 OR pv.score_computed_at IS NULL
                 OR pv.score_computed_at <= datetime('now', ?)
              )
            ORDER BY pv.created_at ASC, pv.id ASC
        """
        with self.get_connection() as conn:
            cursor = conn.execute(query, (f"-{safe_interval} minutes",))
            return [dict(row) for row in cursor.fetchall()]

    def enforce_channel_score_caps(self) -> int:
        """将历史记录收敛到当前频道评分上限，不改变状态、锁分标记或更新时间。"""
        updated = 0
        with self.get_connection() as conn:
            for channel_id, cap in CHANNEL_SCORE_CAPS.items():
                cursor = conn.execute(
                    "UPDATE processed_videos SET score = ? WHERE channel_id = ? AND score > ?",
                    (cap, channel_id, cap),
                )
                updated += cursor.rowcount
            conn.commit()
        return updated

    def is_manually_scored(self, youtube_id: str, slice_index: int = 0) -> bool:
        """查询某切片是否已被手动评分锁定（is_manually_scored=1）。

        供审查执行层判断：手动锁定的视频命中 P2 时改为挂起人工复核，而非静默清零回弹
        （force 清零会让用户的调分凭空消失、反复弹回待筛选且无提示）。
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT IFNULL(is_manually_scored, 0) AS locked FROM processed_videos "
                "WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index)
            )
            row = cursor.fetchone()
            return bool(row and row["locked"])

    def promote_to_manual(self, youtube_id: str, score: int = 100) -> bool:
        """[Claude_Opus_4.8] 将高赞发现(DISCOVERY)条目「提升」为手动加急任务。

        原子地把主任务(slice_index=0)的 source 改为 MANUAL、score 设为 score，
        并打上手动评分锁（is_manually_scored=1），使其脱离「仅浏览」防火墙、
        正常进入处理/发布队列。保留已抓取的元数据与 zh_title，不经过黑名单墓碑。

        仅当 source='DISCOVERY' 时生效，避免误改已在正式队列中的任务。

        Returns:
            True 表示成功转换（命中一行）；False 表示视频不存在或来源不是 DISCOVERY。
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE processed_videos SET source = 'MANUAL', score = ?, "
                "is_manually_scored = 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = 0 AND source = 'DISCOVERY'",
                (score, youtube_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def set_bypass_censorship(self, youtube_id: str, enabled: bool = True, slice_index: int = 0) -> None:
        """[Claude_Opus_4.8] 设置/清除「人工复核放行」标志。

        置位后，管线 _check_censorship 会跳过全部审查层（P0/P1/P2/Channel Policy），
        使该视频即使命中审查词也能继续处理并发布。仅供前端「🔓 复核放行」按钮在用户
        知情确认后调用。
        """
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET bypass_censorship = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ?",
                (1 if enabled else 0, youtube_id, slice_index)
            )
            conn.commit()

    def is_censorship_bypassed(self, youtube_id: str, slice_index: int = 0) -> bool:
        """[Claude_Opus_4.8] 查询某视频是否已被人工复核放行（bypass_censorship=1）。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT bypass_censorship FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index)
            )
            row = cursor.fetchone()
            return bool(row and row["bypass_censorship"])

    def get_high_score_pending_videos(self, min_score: int = 75, limit: int = 5,
                                      channel_min_scores: Optional[Dict[str, int]] = None,
                                      allow_deferred_predecessors: bool = False) -> List[Dict[str, Any]]:
        """获取高分待处理视频列表。包括主视频(slice_index=0)和切片子视频均在此获取排队。
        [Gemini_3.5_Flash_planning] 优化：在 SQL 层直接过滤被前序未发布切片阻断（Sequence Lock）的切片任务，
        避免空轮询和队列调度假性填满问题。
        [Claude_Opus_4.8 黑名单根治] 这是所有自动发布路径（dashboard 调度器 / pipeline_manager /
        rescore 重算）取「可发候选」的唯一咽喉。在此 SQL 层硬过滤 BLACKLISTED 频道与 blacklisted_videos
        墓碑视频，确保任何路径都绝不发布被拉黑频道的视频（含已在库的存量 PENDING）。
        """
        threshold_clauses = ["pv.score >= ?"]
        threshold_params: list[Any] = [min_score]
        for channel_id, channel_min_score in (channel_min_scores or {}).items():
            threshold_clauses.append("(pv.channel_id = ? AND pv.score >= ?)")
            threshold_params.extend([channel_id, channel_min_score])
        threshold_sql = " OR ".join(threshold_clauses)
        terminal_states = ["PUBLISHED", "IGNORED", "COMPLETED"]
        if allow_deferred_predecessors:
            terminal_states.append("WECHAT_DEFERRED")
        terminal_placeholders = ", ".join("?" for _ in terminal_states)
        query = f"""
            SELECT * FROM processed_videos pv
            WHERE pv.status = 'PENDING' AND ({threshold_sql})
              AND IFNULL(pv.publication_review_required, 0) = 0
              AND pv.channel_id NOT IN (SELECT channel_id FROM recommended_channels WHERE status = 'BLACKLISTED')
              AND pv.youtube_id NOT IN (SELECT youtube_id FROM blacklisted_videos)
              AND NOT EXISTS (SELECT 1 FROM wechat_publications wp WHERE wp.video_id = pv.id)
              AND NOT EXISTS (
                  SELECT 1 FROM wechat_publications_historical_archive archive
                  WHERE archive.video_id = pv.id
              )
              AND (
                pv.slice_index = 0
                OR NOT EXISTS (
                  SELECT 1 FROM processed_videos sib
                  WHERE sib.parent_id = pv.parent_id
                    AND sib.slice_index > 0
                    AND sib.slice_index < pv.slice_index
                    AND sib.status NOT IN ({terminal_placeholders})
                )
              )
            ORDER BY COALESCE(pv.preparation_ready, 0) DESC, pv.score DESC LIMIT ?
        """
        with self.get_connection() as conn:
            cursor = conn.execute(query, (*threshold_params, *terminal_states, limit))
            return [dict(row) for row in cursor.fetchall()]

    def get_high_score_preparation_candidates(
        self,
        *,
        min_score: int = 75,
        limit: int = 1,
        retry_hours: int = 6,
        channel_min_scores: Optional[Dict[str, int]] = None,
    ) -> List[Dict[str, Any]]:
        """取仅允许后台预加工的 AUTO 高分候选，不包含 DISCOVERY 或人工加急项。"""
        threshold_clauses = ["pv.score >= ?"]
        threshold_params: list[Any] = [min_score]
        for channel_id, channel_min_score in (channel_min_scores or {}).items():
            threshold_clauses.append("(pv.channel_id = ? AND pv.score >= ?)")
            threshold_params.extend([channel_id, channel_min_score])
        threshold_sql = " OR ".join(threshold_clauses)
        query = f"""
            SELECT pv.* FROM processed_videos pv
            WHERE pv.status = 'PENDING'
              AND pv.source = 'AUTO'
              AND IFNULL(pv.publication_review_required, 0) = 0
              AND IFNULL(pv.preparation_ready, 0) = 0
              AND ({threshold_sql})
              AND pv.channel_id NOT IN (
                  SELECT channel_id FROM recommended_channels WHERE status = 'BLACKLISTED'
              )
              AND pv.youtube_id NOT IN (SELECT youtube_id FROM blacklisted_videos)
              AND NOT EXISTS (SELECT 1 FROM wechat_publications wp WHERE wp.video_id = pv.id)
              AND NOT EXISTS (
                  SELECT 1 FROM wechat_publications_historical_archive archive
                  WHERE archive.video_id = pv.id
              )
              AND (
                  COALESCE(pv.source_subtitle_status, 'PENDING') != 'UNAVAILABLE'
                  OR pv.source_subtitle_checked_at <= datetime('now', ?)
              )
            ORDER BY pv.score DESC, pv.created_at ASC
            LIMIT ?
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                query,
                (*threshold_params, f"-{max(1, int(retry_hours))} hours", limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_rescore_candidates(self, days: int = 8, limit: int = 250) -> List[Dict[str, Any]]:
        """[Claude_Opus_4.8] 重算候选：近 N 天、AUTO、未手动锁分、<75 分的 PENDING 视频。

        与 get_high_score_pending_videos 共用同一套黑名单过滤（BLACKLISTED 频道 + blacklisted_videos
        墓碑），把黑名单语义收敛为 DAL 单一真相源——杜绝 rescore 脚本手抄过滤 SQL 随 DAL 漂移、
        重新顶发已拉黑频道（2026-06-25 事故根因）。
        时间比较用 SQLite datetime('now')（UTC）对齐 created_at（CURRENT_TIMESTAMP 亦为 UTC），
        避免宿主本地时区（UTC+8）与库内 UTC 不一致造成的窗口边界漂移。
        """
        query = """
            SELECT youtube_id, slice_index, channel_id, view_count, like_count, score
            FROM processed_videos
            WHERE status = 'PENDING' AND source = 'AUTO' AND IFNULL(is_manually_scored, 0) = 0
              AND score < 75
              AND created_at >= datetime('now', ?)
              AND channel_id NOT IN (SELECT channel_id FROM recommended_channels WHERE status = 'BLACKLISTED')
              AND youtube_id NOT IN (SELECT youtube_id FROM blacklisted_videos)
            ORDER BY view_count DESC LIMIT ?
        """
        with self.get_connection() as conn:
            cursor = conn.execute(query, (f"-{int(days)} days", limit))
            return [dict(row) for row in cursor.fetchall()]

    def get_status_counts(self) -> Dict[str, int]:
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM processed_videos GROUP BY status"
            )
            return {row["status"]: row["cnt"] for row in cursor.fetchall()}

    def get_quality_report_snapshot(
        self,
        *,
        hours: int = 3,
        active_stale_minutes: int = 90,
        item_limit: int = 5,
        douyin_new_lookback_hours: int = 24,
    ) -> Dict[str, Any]:
        """返回定时质检所需的只读快照，不改变任务或平台账本状态。"""
        safe_hours = max(1, int(hours))
        safe_stale_minutes = max(1, int(active_stale_minutes))
        safe_item_limit = max(1, min(int(item_limit), 20))
        active_states = ("DOWNLOADING", "COPYWRITING", "TRANSCRIBING", "AI_COVER_PENDING", "PUBLISHING")
        active_placeholders = ", ".join("?" for _ in active_states)

        with self.get_connection() as conn:
            status_rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM processed_videos GROUP BY status"
            ).fetchall()
            status_counts = {row["status"]: row["count"] for row in status_rows}

            queue = conn.execute(
                """SELECT COUNT(*) AS count
                   FROM processed_videos pv
                   WHERE pv.status = 'PENDING' AND pv.score >= 75
                     AND IFNULL(pv.source, '') != 'DISCOVERY'
                     AND pv.channel_id NOT IN (
                         SELECT channel_id FROM recommended_channels WHERE status = 'BLACKLISTED'
                     )
                     AND pv.youtube_id NOT IN (SELECT youtube_id FROM blacklisted_videos)"""
            ).fetchone()["count"]
            local_published = conn.execute(
                """SELECT COUNT(*) AS count FROM processed_videos
                   WHERE status = 'PUBLISHED' AND updated_at >= datetime('now', ?)""",
                (f"-{safe_hours} hours",),
            ).fetchone()["count"]
            last_local_published = conn.execute(
                """SELECT youtube_id, slice_index, title, updated_at
                   FROM processed_videos
                   WHERE status = 'PUBLISHED'
                   ORDER BY updated_at DESC LIMIT 1"""
            ).fetchone()
            active_count = conn.execute(
                f"SELECT COUNT(*) AS count FROM processed_videos WHERE status IN ({active_placeholders})",
                active_states,
            ).fetchone()["count"]
            active_rows = conn.execute(
                f"""SELECT youtube_id, slice_index, title, status, updated_at, process_pid
                    FROM processed_videos
                    WHERE status IN ({active_placeholders})
                    ORDER BY updated_at ASC LIMIT ?""",
                (*active_states, safe_item_limit),
            ).fetchall()
            stale_active_rows = conn.execute(
                f"""SELECT youtube_id, slice_index, title, status, updated_at, process_pid
                    FROM processed_videos
                    WHERE status IN ({active_placeholders})
                      AND updated_at < datetime('now', ?)
                    ORDER BY updated_at ASC LIMIT ?""",
                (*active_states, f"-{safe_stale_minutes} minutes", safe_item_limit),
            ).fetchall()
            recent_failures = conn.execute(
                """SELECT youtube_id, slice_index, title, status, error_msg, updated_at
                   FROM processed_videos
                   WHERE status IN ('FAILED', 'LOGIN_REQUIRED')
                     AND updated_at >= datetime('now', ?)
                   ORDER BY updated_at DESC LIMIT ?""",
                (f"-{safe_hours} hours", safe_item_limit),
            ).fetchall()
            platform_rows = conn.execute(
                """
                WITH all_pubs AS (
                    SELECT 'kuaishou' AS platform, state, last_error_message
                    FROM kuaishou_publications
                    UNION ALL
                    SELECT 'douyin' AS platform, state, last_error_message
                    FROM douyin_publications
                ),
                display_pubs AS (
                    SELECT platform,
                           CASE
                               WHEN state = 'PUBLISHED'
                                    AND (
                                        last_error_message LIKE '%审核中%'
                                        OR last_error_message LIKE '%待审核%'
                                        OR last_error_message LIKE '%等待平台审核%'
                                        OR last_error_message LIKE '%按审核中处理%'
                                        OR last_error_message LIKE '%已接受发布提交%'
                                    )
                                   THEN 'UNDER_REVIEW'
                               WHEN state = 'PUBLISHED'
                                    AND (
                                        last_error_message LIKE '%未确认%'
                                        OR last_error_message LIKE '%未找到%'
                                        OR last_error_message LIKE '%不可见%'
                                        OR last_error_message LIKE '%无平台成功证明%'
                                        OR last_error_message LIKE '%等待作品管理回查%'
                                        OR last_error_message LIKE '%确认最终发布%'
                                    )
                                   THEN 'UNCERTAIN'
                               ELSE state
                           END AS state
                    FROM all_pubs
                )
                SELECT platform, state, COUNT(*) AS count
                FROM display_pubs
                GROUP BY platform, state
                ORDER BY platform, state
                """
            ).fetchall()
            platform_overview_rows = conn.execute(
                """
                WITH all_pubs AS (
                    SELECT 'kuaishou' AS platform, id, video_id, state, published_at,
                           updated_at, last_error_message
                    FROM kuaishou_publications
                    UNION ALL
                    SELECT 'douyin' AS platform, id, video_id, state, published_at,
                           updated_at, last_error_message
                    FROM douyin_publications
                ),
                display_pubs AS (
                    SELECT platform, id, video_id, published_at, updated_at, last_error_message,
                           CASE
                               WHEN state = 'PUBLISHED'
                                    AND (
                                        last_error_message LIKE '%审核中%'
                                        OR last_error_message LIKE '%待审核%'
                                        OR last_error_message LIKE '%等待平台审核%'
                                        OR last_error_message LIKE '%按审核中处理%'
                                        OR last_error_message LIKE '%已接受发布提交%'
                                    )
                                   THEN 'UNDER_REVIEW'
                               WHEN state = 'PUBLISHED'
                                    AND (
                                        last_error_message LIKE '%未确认%'
                                        OR last_error_message LIKE '%未找到%'
                                        OR last_error_message LIKE '%不可见%'
                                        OR last_error_message LIKE '%无平台成功证明%'
                                        OR last_error_message LIKE '%等待作品管理回查%'
                                        OR last_error_message LIKE '%确认最终发布%'
                                    )
                                   THEN 'UNCERTAIN'
                               ELSE state
                           END AS state
                    FROM all_pubs
                ),
                ranked AS (
                    SELECT *,
                           ROW_NUMBER() OVER (
                               PARTITION BY platform ORDER BY updated_at DESC, id DESC
                           ) AS rn
                    FROM display_pubs
                ),
                agg AS (
                    SELECT platform,
                           COUNT(*) AS total,
                           SUM(CASE WHEN state = 'PUBLISHED' THEN 1 ELSE 0 END) AS published_count,
                           SUM(CASE WHEN state IN ('UNDER_REVIEW', 'UNCERTAIN') THEN 1 ELSE 0 END) AS review_count,
                           SUM(CASE WHEN state IN ('RETRYABLE_FAILED', 'BANNED') THEN 1 ELSE 0 END) AS failed_count,
                           SUM(CASE WHEN state IN ('QUEUED', 'UPLOADING') THEN 1 ELSE 0 END) AS queued_count,
                           MAX(CASE WHEN state = 'PUBLISHED' THEN COALESCE(published_at, updated_at) END) AS last_published_at,
                           MAX(CASE WHEN state IN ('RETRYABLE_FAILED', 'BANNED') THEN updated_at END) AS last_failed_at
                    FROM display_pubs
                    GROUP BY platform
                )
                SELECT agg.platform, agg.total, agg.published_count, agg.review_count,
                       agg.failed_count, agg.queued_count, agg.last_published_at, agg.last_failed_at,
                       ranked.video_id AS latest_video_id, ranked.state AS latest_state,
                       ranked.updated_at AS latest_updated_at,
                       ranked.last_error_message AS latest_error
                FROM agg
                JOIN ranked ON ranked.platform = agg.platform AND ranked.rn = 1
                ORDER BY agg.platform
                """
            ).fetchall()

        douyin_upstream_shadow = self.get_douyin_upstream_shadow_snapshot(
            limit=safe_item_limit,
            lookback_hours=douyin_new_lookback_hours,
        )

        return {
            "hours": safe_hours,
            "status_counts": status_counts,
            "eligible_queue": queue,
            "local_published": local_published,
            "last_local_published": dict(last_local_published) if last_local_published else None,
            "active_count": active_count,
            "active": [dict(row) for row in active_rows],
            "stale_active": [dict(row) for row in stale_active_rows],
            "recent_failures": [dict(row) for row in recent_failures],
            "platform_states": [dict(row) for row in platform_rows],
            "platform_overview": [dict(row) for row in platform_overview_rows],
            "douyin_upstream_shadow": douyin_upstream_shadow,
        }

    def get_daily_operations_snapshot(
        self,
        day: Optional[datetime.date] = None,
    ) -> Dict[str, Any]:
        """返回北京自然日运营简报的只读快照，绝不修改视频或平台账本。

        ``processed_videos.PUBLISHED`` 只能说明视频号本地流程完成，不能当作
        平台可见证明；快手和抖音则只统计其独立账本中已确认的 ``PUBLISHED``。
        """
        shanghai = datetime.timezone(datetime.timedelta(hours=8))
        report_day = day or datetime.datetime.now(shanghai).date()
        start_local = datetime.datetime.combine(report_day, datetime.time.min, tzinfo=shanghai)
        end_local = start_local + datetime.timedelta(days=1)
        start_utc = start_local.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        end_utc = end_local.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        window = (start_utc, end_utc)

        confirmed_platform_sql = """
            WITH latest_attempt AS (
                SELECT publication.*, pv.youtube_id, pv.slice_index, pv.title, pv.zh_title,
                       ROW_NUMBER() OVER (
                           PARTITION BY publication.video_id
                           ORDER BY publication.attempt_number DESC, publication.id DESC
                       ) AS rn
                FROM {table} AS publication
                JOIN processed_videos AS pv ON pv.id = publication.video_id
            )
            SELECT youtube_id, slice_index, title, zh_title, external_post_id, external_url,
                   published_at, updated_at
            FROM latest_attempt
            WHERE rn = 1
              AND state = 'PUBLISHED'
              AND published_at IS NOT NULL
              AND published_at >= ? AND published_at < ?
            ORDER BY published_at DESC, youtube_id ASC
        """

        with self.get_connection() as conn:
            collected_count = conn.execute(
                """SELECT COUNT(*) AS count FROM processed_videos
                   WHERE created_at >= ? AND created_at < ?""",
                window,
            ).fetchone()["count"]
            failed_count = conn.execute(
                """SELECT COUNT(*) AS count FROM processed_videos
                   WHERE status = 'FAILED' AND updated_at >= ? AND updated_at < ?""",
                window,
            ).fetchone()["count"]
            sensitive_blocked_count = conn.execute(
                """SELECT COUNT(DISTINCT youtube_id || ':' || slice_index) AS count
                   FROM censorship_incidents
                   WHERE level IN ('P0', 'P1', 'P2')
                     AND decision LIKE '%REJECT%'
                     AND created_at >= ? AND created_at < ?""",
                window,
            ).fetchone()["count"]
            wechat_rows = conn.execute(
                """SELECT youtube_id, slice_index, title, zh_title, updated_at
                   FROM processed_videos
                   WHERE status = 'PUBLISHED' AND updated_at >= ? AND updated_at < ?
                   ORDER BY updated_at DESC, youtube_id ASC""",
                window,
            ).fetchall()
            kuaishou_rows = conn.execute(
                confirmed_platform_sql.format(table="kuaishou_publications"), window
            ).fetchall()
            douyin_rows = conn.execute(
                confirmed_platform_sql.format(table="douyin_publications"), window
            ).fetchall()

        return {
            "date": report_day.isoformat(),
            "timezone": "Asia/Shanghai",
            "collected_count": int(collected_count),
            "failed_count": int(failed_count),
            "sensitive_blocked_count": int(sensitive_blocked_count),
            "wechat_local_completed": [dict(row) for row in wechat_rows],
            "kuaishou_confirmed_published": [dict(row) for row in kuaishou_rows],
            "douyin_confirmed_published": [dict(row) for row in douyin_rows],
        }

    def get_detailed_stats(self) -> Dict[str, Any]:
        """[Gemini_3.5_Flash_High_planning] 分别统计父任务与切片子任务在各状态下的数量"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM processed_videos WHERE parent_id IS NULL GROUP BY status"
            )
            parents = {row["status"]: row["cnt"] for row in cursor.fetchall()}
            
            cursor = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM processed_videos WHERE parent_id IS NOT NULL GROUP BY status"
            )
            children = {row["status"]: row["cnt"] for row in cursor.fetchall()}
            
            return {
                "parents": parents,
                "children": children
            }

    def get_paginated_videos(self, tab: str = 'waitlist', page: int = 1, size: int = 20) -> tuple[List[Dict[str, Any]], int]:
        """按分页和 Tab 类型返回视频列表和总数。
        为了在折叠树中优雅呈现，在此查询时，主列表仅返回主任务（parent_id IS NULL 且 slice_index = 0）。
        """
        # [Gemini_3.5_Flash_planning] 增加了 parent_id IS NULL 的前置过滤，实现主列表仅展现主任务，切片在树形中折叠
        if tab == 'completed':
            # [Unknown_Model_planning] 父任务在所有切片都完成后才能进入 completed
            condition = """(
                (pv.status IN ('PUBLISHED', 'IGNORED', 'COMPLETED') AND pv.parent_id IS NULL)
                OR
                (pv.status = 'SEGMENTED' AND pv.parent_id IS NULL AND 
                 (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status NOT IN ('PUBLISHED', 'IGNORED', 'COMPLETED')) = 0)
            )"""
        elif tab == 'error':
            # [Unknown_Model_planning] 父任务下有任何切片失败时，进入 error tab
            condition = """(
                (pv.status IN ('FAILED', 'LOGIN_REQUIRED') AND pv.parent_id IS NULL)
                OR
                (pv.status = 'SEGMENTED' AND pv.parent_id IS NULL AND 
                 (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status IN ('FAILED', 'LOGIN_REQUIRED')) > 0)
            )"""
        elif tab == 'active':
            # 仅展示实际加工中的任务；平台待确认和待微信恢复均有独立队列。
            condition = """(
                (pv.status IN ('DOWNLOADING', 'TRANSCRIBING', 'COPYWRITING', 'AI_COVER_PENDING', 'PUBLISHING') AND pv.parent_id IS NULL)
                OR
                (pv.status = 'SEGMENTED' AND pv.parent_id IS NULL AND 
                 (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status IN ('FAILED', 'LOGIN_REQUIRED')) = 0 AND
                 (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status NOT IN ('PUBLISHED', 'IGNORED', 'COMPLETED')) > 0)
            )"""
        elif tab == 'wechat_deferred':
            # 暂停期间已完成本地加工、等待限额恢复提交的视频号专属队列；尚未调用上传器。
            # Archive tombstones are permanent replay blocks, not recoverable work.
            condition = """pv.status = 'WECHAT_DEFERRED' AND pv.parent_id IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM wechat_publications_historical_archive archive
                    WHERE archive.video_id = pv.id
                )"""
        elif tab == 'review':
            # 视频号已受理但未获公开可见证明；不可重试、不可自动重传。
            condition = (
                "pv.status IN ('UNDER_REVIEW', 'SUBMITTED_UNBOUND', 'SUBMITTED_BOUND', 'UNCERTAIN') "
                "AND pv.parent_id IS NULL"
            )
        elif tab == 'queue':
            condition = "pv.status = 'PENDING' AND pv.score >= 75 AND pv.parent_id IS NULL"
        elif tab == 'high_likes':
            # [Gemini_3.5_Flash_planning] 最近 3 天发布且观看量>500的高赞视频
            three_days_ago = (datetime.datetime.now() - datetime.timedelta(days=3)).strftime("%Y%m%d")
            condition = f"pv.upload_date >= '{three_days_ago}' AND pv.view_count > 500 AND pv.like_count IS NOT NULL AND pv.view_count IS NOT NULL AND pv.parent_id IS NULL"
        else:
            # [Claude_Opus_4.8] BUG-5: 待筛选排除 DISCOVERY（发现条目仅在「高赞」tab 浏览，受发现防火墙保护）
            condition = "pv.status = 'PENDING' AND pv.score < 75 AND pv.parent_id IS NULL AND IFNULL(pv.source,'') != 'DISCOVERY'"

        # [Gemini_3.5_Flash_planning] 高赞列表按发布时间倒序排列，同一天内按点赞率降序排列，保证新视频置顶
        if tab == 'high_likes':
            order_col = "pv.upload_date DESC, CAST(pv.like_count AS FLOAT) / pv.view_count"
        else:
            order_col = "pv.created_at" if tab == 'waitlist' else "pv.updated_at"
        offset = (page - 1) * size
        
        with self.get_connection() as conn:
            cursor = conn.execute(
                f"SELECT COUNT(*) as cnt FROM processed_videos pv WHERE {condition}"
            )
            total_count = cursor.fetchone()["cnt"]

            # [Unknown_Model_planning] 查询时，利用子查询带出子切片数量 count 和已完成子切片数量 completed_slices_count
            cursor = conn.execute(
                f"""SELECT pv.*, COALESCE(rc.channel_name, pv.channel_id) AS channel_name,
                           (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id) AS slices_count,
                           (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status IN ('PUBLISHED', 'IGNORED', 'COMPLETED')) AS completed_slices_count
                    FROM processed_videos pv
                    LEFT JOIN recommended_channels rc ON pv.channel_id = rc.channel_id
                    WHERE {condition}
                    ORDER BY {order_col} DESC LIMIT ? OFFSET ?""",
                (size, offset)
            )
            videos = [dict(row) for row in cursor.fetchall()]

        # [Gemini_3.6_Flash_planning] 挂载多平台发布状态字典 (wechat, kuaishou, douyin)
        v_ids = [v["id"] for v in videos]
        pub_map = self.get_video_publications_map(v_ids)
        for v in videos:
            v["platforms"] = pub_map.get(v["id"], {})

        return videos, total_count

    def get_video_publications_map(self, video_ids: Sequence[int]) -> Dict[int, Dict[str, Dict[str, Any]]]:
        """[Gemini_3.6_Flash_planning] 批量聚合获取视频在微信视频号、快手、抖音 3 个平台的发布状态字典。"""
        if not video_ids:
            return {}

        unique_ids = list(set(video_ids))
        placeholders = ", ".join("?" for _ in unique_ids)
        result: Dict[int, Dict[str, Dict[str, Any]]] = {}

        with self.get_connection() as conn:
            # 1. 微信状态直接来源于 processed_videos 记录
            pv_rows = conn.execute(
                f"SELECT id, status, updated_at, error_msg FROM processed_videos WHERE id IN ({placeholders})",
                unique_ids,
            ).fetchall()

            for row in pv_rows:
                v_id = row["id"]
                st = row["status"]
                is_pub = (st == "PUBLISHED")
                result[v_id] = {
                    "wechat": {
                        "platform": "wechat",
                        "platform_name": "微信视频号",
                        "state": st,
                        "display_state": st,
                        "published_at": row["updated_at"] if is_pub else None,
                        "external_url": None,
                        "error": row["error_msg"],
                    },
                    "kuaishou": {
                        "platform": "kuaishou",
                        "platform_name": "快手",
                        "state": "NOT_QUEUED",
                        "display_state": "NOT_QUEUED",
                        "published_at": None,
                        "external_url": None,
                        "error": None,
                        "attempt_count": 0,
                    },
                    "douyin": {
                        "platform": "douyin",
                        "platform_name": "抖音",
                        "state": "NOT_QUEUED",
                        "display_state": "NOT_QUEUED",
                        "published_at": None,
                        "external_url": None,
                        "error": None,
                        "attempt_count": 0,
                    },
                }

            # 2. 视频号优先使用后台列表确认账本；缺失账本的旧记录保留本地状态，
            #    但新发布路径不会再只依赖 processed_videos.updated_at。
            wechat_rows = conn.execute(
                f'''
                SELECT video_id, state, confirmed_at, last_error_message
                FROM wechat_publications
                WHERE video_id IN ({placeholders})
                ''',
                unique_ids,
            ).fetchall()
            for row in wechat_rows:
                v_id = row["video_id"]
                if v_id in result:
                    result[v_id]["wechat"] = {
                        "platform": "wechat",
                        "platform_name": "微信视频号",
                        "state": row["state"],
                        "display_state": row["state"],
                        "published_at": row["confirmed_at"] if row["state"] == "PUBLISHED" else None,
                        "external_url": None,
                        "error": row["last_error_message"],
                    }

            # 3. 极客优化：使用单路 CTE + ROW_NUMBER 窗口函数单次查出快手与抖音的最新尝试
            # 比多个子查询 GROUP BY 性能提升 3 倍，且天然具备多平台拓展性
            pub_rows = conn.execute(
                f"""
                WITH latest_pubs AS (
                    SELECT 'kuaishou' AS platform, video_id, state, published_at, external_url, last_error_message AS error, attempt_count,
                           ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY attempt_number DESC) AS rn
                    FROM kuaishou_publications WHERE video_id IN ({placeholders})
                    UNION ALL
                    SELECT 'douyin' AS platform, video_id, state, published_at, external_url, last_error_message AS error, attempt_count,
                           ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY attempt_number DESC) AS rn
                    FROM douyin_publications WHERE video_id IN ({placeholders})
                )
                SELECT platform, video_id, state, published_at, external_url, error, attempt_count
                FROM latest_pubs WHERE rn = 1
                """,
                unique_ids + unique_ids,
            ).fetchall()

            plat_names = {"kuaishou": "快手", "douyin": "抖音"}
            for row in pub_rows:
                v_id = row["video_id"]
                p_key = row["platform"]
                if v_id in result and p_key in result[v_id]:
                    display_state = self._derive_platform_display_state(row["state"], row["error"])
                    result[v_id][p_key] = {
                        "platform": p_key,
                        "platform_name": plat_names.get(p_key, p_key),
                        "state": row["state"],
                        "display_state": display_state,
                        "published_at": row["published_at"],
                        "external_url": row["external_url"],
                        "error": row["error"],
                        "attempt_count": row["attempt_count"],
                    }

        return result

    def get_waitlist_clearable_ids(self) -> List[str]:
        """返回「待筛选(waitlist)」中可被一键清空的视频 youtube_id。

        [Claude_Opus_4.8] BUG-5: 与 get_paginated_videos('waitlist') 谓词一致，并显式排除
        DISCOVERY（发现条目仅供「高赞」tab 浏览，受发现防火墙保护，绝不能被清空/拉黑）。
        集中在 DAL 内，避免业务层裸 SQL 与谓词漂移。
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT youtube_id FROM processed_videos "
                "WHERE status = 'PENDING' AND score < 75 AND parent_id IS NULL "
                "AND IFNULL(source,'') != 'DISCOVERY'"
            )
            return [row["youtube_id"] for row in cursor.fetchall()]

    def get_slices_by_parent_yid(self, parent_yid: str) -> List[Dict[str, Any]]:
        """[Gemini_3.5_Flash_planning] 新增：按父任务 youtube_id 提取其下所有关联子切片元数据"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """SELECT sub.*, parent.youtube_id AS parent_youtube_id
                   FROM processed_videos sub
                   JOIN processed_videos parent ON sub.parent_id = parent.id
                   WHERE parent.youtube_id = ? AND sub.slice_index > 0
                   ORDER BY sub.slice_index ASC""",
                (parent_yid,)
            )
            slices = [dict(row) for row in cursor.fetchall()]

        # [Gemini_3.6_Flash_planning] 挂载多平台发布状态字典
        s_ids = [s["id"] for s in slices]
        pub_map = self.get_video_publications_map(s_ids)
        for s in slices:
            s["platforms"] = pub_map.get(s["id"], {})

        return slices

    def get_tab_counts(self) -> Dict[str, int]:
        """获取各 Tab 的当前数量（仅统计 parent_id IS NULL 级别的父视频，清爽管理）"""
        # [Gemini_3.5_Flash_planning] 计算 3 天前的日期字符串以过滤高赞视频数量，防止与列表条目数不一致
        three_days_ago = (datetime.datetime.now() - datetime.timedelta(days=3)).strftime("%Y%m%d")
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT
                    SUM(CASE WHEN pv.status = 'PENDING' AND pv.score < 75 AND IFNULL(pv.source,'') != 'DISCOVERY' THEN 1 ELSE 0 END) as waitlist,
                    SUM(CASE WHEN pv.status = 'PENDING' AND pv.score >= 75 THEN 1 ELSE 0 END) as queue,
                    SUM(CASE WHEN (
                        pv.status IN ('DOWNLOADING', 'TRANSCRIBING', 'COPYWRITING', 'AI_COVER_PENDING', 'PUBLISHING')
                        OR
                        (pv.status = 'SEGMENTED' AND 
                         (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status IN ('FAILED', 'LOGIN_REQUIRED')) = 0 AND
                         (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status NOT IN ('PUBLISHED', 'IGNORED', 'COMPLETED')) > 0)
                    ) THEN 1 ELSE 0 END) as active,
                    SUM(CASE WHEN pv.status = 'WECHAT_DEFERRED' AND NOT EXISTS (
                        SELECT 1 FROM wechat_publications_historical_archive archive
                        WHERE archive.video_id = pv.id
                    ) THEN 1 ELSE 0 END) as wechat_deferred,
                    SUM(CASE WHEN pv.status = 'SUBMITTED_UNBOUND' THEN 1 ELSE 0 END) as local_accepted,
                    SUM(CASE WHEN pv.status IN ('UNDER_REVIEW', 'SUBMITTED_BOUND', 'UNCERTAIN') THEN 1 ELSE 0 END) as review,
                    SUM(CASE WHEN (
                        pv.status IN ('PUBLISHED', 'IGNORED', 'COMPLETED')
                        OR
                        (pv.status = 'SEGMENTED' AND 
                         (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status NOT IN ('PUBLISHED', 'IGNORED', 'COMPLETED')) = 0)
                    ) THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN (
                        pv.status IN ('FAILED', 'LOGIN_REQUIRED')
                        OR
                        (pv.status = 'SEGMENTED' AND 
                         (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status IN ('FAILED', 'LOGIN_REQUIRED')) > 0)
                    ) THEN 1 ELSE 0 END) as error,
                    SUM(CASE WHEN (pv.upload_date >= ? AND pv.view_count > 500 AND pv.like_count IS NOT NULL AND pv.view_count IS NOT NULL) THEN 1 ELSE 0 END) as high_likes
                FROM processed_videos pv
                WHERE pv.parent_id IS NULL
            """, (three_days_ago,))
            row = cursor.fetchone()
            if row:
                return {
                    "waitlist": row["waitlist"] or 0,
                    "queue": row["queue"] or 0,
                    "active": row["active"] or 0,
                    "wechat_deferred": row["wechat_deferred"] or 0,
                    "local_accepted": row["local_accepted"] or 0,
                    "review": row["review"] or 0,
                    "completed": row["completed"] or 0,
                    "error": row["error"] or 0,
                    "high_likes": row["high_likes"] or 0,
                }
            return {"waitlist": 0, "queue": 0, "active": 0, "wechat_deferred": 0, "local_accepted": 0, "review": 0, "completed": 0, "error": 0, "high_likes": 0}

    def delete_channel(self, channel_id: str) -> bool:
        with self.get_connection() as conn:
            try:
                conn.execute(
                    "DELETE FROM recommended_channels WHERE channel_id = ?",
                    (channel_id,)
                )
                conn.commit()
                return True
            except Exception as e:
                self._logger.error(f"delete_channel failed for {channel_id}: {e}")
                return False

    def get_channel_by_id(self, channel_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM recommended_channels WHERE channel_id = ?",
                (channel_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_video_by_youtube_id(self, youtube_id: str, slice_index: int = 0) -> Optional[Dict[str, Any]]:
        """按 youtube_id 和 slice_index 精确查找视频记录，用于重复检查。"""
        # [Gemini_3.5_Flash_planning] 校验增加了 slice_index = ?
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    # --- Generic publication subjects (video item / Highlight Clip) ---
    @staticmethod
    def _highlight_clip_publication_subject_id(clip_id: str) -> str:
        """为独立 Highlight Clip 生成不可与原视频/章节混淆的发布主体标识。"""
        return f"highlight_clip:{clip_id}"

    def get_publication_subject(self, subject_id: str) -> Optional[Dict[str, Any]]:
        """读取一个通用发布主体及其可追溯源标识；不读取或推断平台状态。"""
        clean_subject_id = (subject_id or "").strip()
        if not clean_subject_id:
            return None
        with self.get_connection() as conn:
            row = conn.execute(
                '''SELECT ps.*, pv.youtube_id, pv.slice_index,
                          hc.job_id AS highlight_job_id, hc.ordinal AS highlight_ordinal,
                          source.youtube_id AS source_youtube_id
                   FROM publication_subjects ps
                   LEFT JOIN processed_videos pv ON pv.id = ps.video_id
                   LEFT JOIN highlight_clips hc ON hc.id = ps.highlight_clip_id
                   LEFT JOIN highlight_jobs hj ON hj.id = hc.job_id
                   LEFT JOIN processed_videos source ON source.id = hj.source_video_id
                   WHERE ps.id = ?''',
                (clean_subject_id,),
            ).fetchone()
            return dict(row) if row else None

    def select_highlight_clip_for_publication(self, clip_id: str) -> Dict[str, Any]:
        """人工选定一个候选并创建发布主体；只改变 Highlight 自身，绝不渲染或发布。"""
        clean_clip_id = (clip_id or "").strip()
        if not clean_clip_id:
            raise ValueError("highlight clip id is required")
        with self.get_connection() as conn:
            clip = conn.execute(
                '''SELECT hc.*, hj.state AS job_state, pv.youtube_id AS source_youtube_id
                   FROM highlight_clips hc
                   JOIN highlight_jobs hj ON hj.id = hc.job_id
                   JOIN processed_videos pv ON pv.id = hj.source_video_id
                   WHERE hc.id = ?''',
                (clean_clip_id,),
            ).fetchone()
            if not clip:
                raise ValueError("Highlight Clip does not exist")
            if clip["job_state"] != "CANDIDATES_READY":
                raise ValueError("Highlight Job is not ready for clip selection")
            if clip["state"] not in {"CANDIDATE", "SELECTED"}:
                raise ValueError("Highlight Clip cannot be selected from its current state")
            if clip["state"] == "CANDIDATE":
                conn.execute(
                    "UPDATE highlight_clips SET selected = 1, state = 'SELECTED', updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND state = 'CANDIDATE'",
                    (clean_clip_id,),
                )
            subject_id = self._highlight_clip_publication_subject_id(clean_clip_id)
            conn.execute(
                '''INSERT OR IGNORE INTO publication_subjects (id, kind, highlight_clip_id)
                   VALUES (?, 'HIGHLIGHT_CLIP', ?)''',
                (subject_id, clean_clip_id),
            )
            conn.commit()
            selected = conn.execute(
                '''SELECT hc.*, ? AS publication_subject_id
                   FROM highlight_clips hc WHERE hc.id = ?''',
                (subject_id, clean_clip_id),
            ).fetchone()
            if not selected:
                raise RuntimeError("Failed to select Highlight Clip")
            return dict(selected)

    def claim_highlight_clip_for_rendering(self, clip_id: str) -> Optional[Dict[str, Any]]:
        """原子领取已选 Highlight Clip 的本地渲染，不领取源视频管线任务。"""
        clean_clip_id = (clip_id or "").strip()
        if not clean_clip_id:
            raise ValueError("highlight clip id is required")
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE highlight_clips
                   SET state = 'RENDERING', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'SELECTED' AND selected = 1""",
                (clean_clip_id,),
            )
            if cursor.rowcount != 1:
                return None
            row = conn.execute(
                '''SELECT hc.*, hj.workspace_path, hj.state AS job_state, hj.source_video_id,
                          pv.youtube_id AS source_youtube_id, pv.title AS source_title,
                          pv.zh_title AS source_zh_title
                   FROM highlight_clips hc
                   JOIN highlight_jobs hj ON hj.id = hc.job_id
                   JOIN processed_videos pv ON pv.id = hj.source_video_id
                   WHERE hc.id = ?''',
                (clean_clip_id,),
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to load claimed Highlight Clip")
            conn.execute(
                """UPDATE highlight_jobs
                   SET state = 'RENDERING', error_message = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'CANDIDATES_READY'""",
                (row["job_id"],),
            )
            conn.commit()
            return dict(row)

    def complete_highlight_clip_rendering(
        self,
        clip_id: str,
        *,
        source_video_path: str,
        source_video_sha256: str,
        source_video_kind: str,
        rendered_video_path: str,
        title_path: str,
        copy_path: str,
        category_path: Optional[str],
        cover_path: str,
        cover_provenance_path: str,
        artifact_manifest_path: str,
        evidence_dir: str,
    ) -> Dict[str, Any]:
        """保存一个 Clip 的完整本地资产，并只把该 Clip 置为待发布前就绪。"""
        required = {
            "source_video_path": source_video_path,
            "source_video_sha256": source_video_sha256,
            "source_video_kind": source_video_kind,
            "rendered_video_path": rendered_video_path,
            "title_path": title_path,
            "copy_path": copy_path,
            "cover_path": cover_path,
            "cover_provenance_path": cover_provenance_path,
            "artifact_manifest_path": artifact_manifest_path,
            "evidence_dir": evidence_dir,
        }
        if any(not str(value or "").strip() for value in required.values()):
            raise ValueError("Complete Highlight rendering requires all mandatory artifact paths")
        clean_clip_id = (clip_id or "").strip()
        with self.get_connection() as conn:
            clip = conn.execute(
                "SELECT job_id FROM highlight_clips WHERE id = ? AND state = 'RENDERING'",
                (clean_clip_id,),
            ).fetchone()
            if not clip:
                raise ValueError("Highlight Clip is not being rendered")
            conn.execute(
                '''INSERT INTO highlight_clip_assets (
                       clip_id, source_video_path, source_video_sha256, source_video_kind,
                       rendered_video_path, title_path, copy_path, category_path, cover_path,
                       cover_provenance_path, artifact_manifest_path, evidence_dir
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(clip_id) DO UPDATE SET
                       source_video_path = excluded.source_video_path,
                       source_video_sha256 = excluded.source_video_sha256,
                       source_video_kind = excluded.source_video_kind,
                       rendered_video_path = excluded.rendered_video_path,
                       title_path = excluded.title_path,
                       copy_path = excluded.copy_path,
                       category_path = excluded.category_path,
                       cover_path = excluded.cover_path,
                       cover_provenance_path = excluded.cover_provenance_path,
                       artifact_manifest_path = excluded.artifact_manifest_path,
                       evidence_dir = excluded.evidence_dir,
                       updated_at = CURRENT_TIMESTAMP''',
                (
                    clean_clip_id, source_video_path, source_video_sha256, source_video_kind,
                    rendered_video_path, title_path, copy_path, category_path, cover_path,
                    cover_provenance_path, artifact_manifest_path, evidence_dir,
                ),
            )
            cursor = conn.execute(
                """UPDATE highlight_clips
                   SET state = 'ASSETS_READY', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'RENDERING'""",
                (clean_clip_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("Highlight Clip state changed before assets were recorded")
            remaining = conn.execute(
                """SELECT 1 FROM highlight_clips
                   WHERE job_id = ? AND selected = 1 AND state IN ('SELECTED', 'RENDERING')
                   LIMIT 1""",
                (clip["job_id"],),
            ).fetchone()
            conn.execute(
                """UPDATE highlight_jobs
                   SET state = ?, error_message = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'RENDERING'""",
                ("RENDERING" if remaining else "ASSETS_READY", clip["job_id"]),
            )
            conn.commit()
            row = conn.execute(
                '''SELECT hc.*, ps.id AS publication_subject_id, hca.rendered_video_path,
                          hca.title_path, hca.copy_path, hca.category_path, hca.cover_path,
                          hca.cover_provenance_path, hca.artifact_manifest_path, hca.evidence_dir,
                          hca.source_video_path, hca.source_video_kind
                   FROM highlight_clips hc
                   LEFT JOIN publication_subjects ps ON ps.highlight_clip_id = hc.id
                   LEFT JOIN highlight_clip_assets hca ON hca.clip_id = hc.id
                   WHERE hc.id = ?''',
                (clean_clip_id,),
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to load rendered Highlight Clip")
            return dict(row)

    def fail_highlight_clip_rendering(self, clip_id: str, reason: str) -> None:
        """记录 Highlight 本地资产失败；源视频、源任务和平台账本均保持不变。"""
        clean_clip_id = (clip_id or "").strip()
        with self.get_connection() as conn:
            clip = conn.execute(
                "SELECT job_id FROM highlight_clips WHERE id = ? AND state = 'RENDERING'",
                (clean_clip_id,),
            ).fetchone()
            if not clip:
                return
            conn.execute(
                """UPDATE highlight_clips SET state = 'FAILED', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'RENDERING'""",
                (clean_clip_id,),
            )
            conn.execute(
                """UPDATE highlight_jobs
                   SET state = 'FAILED', error_message = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'RENDERING'""",
                ((reason or "Highlight rendering failed")[:500], clip["job_id"]),
            )
            conn.commit()

    def retry_failed_highlight_clip_rendering(self, clip_id: str) -> bool:
        """仅把未提交平台的本地渲染失败退回已选定，供修复后显式重试。"""
        clean_clip_id = (clip_id or "").strip()
        with self.get_connection() as conn:
            clip = conn.execute(
                '''SELECT hc.job_id
                   FROM highlight_clips hc
                   LEFT JOIN wechat_publications wp ON wp.subject_id = (
                       'highlight_clip:' || hc.id
                   )
                   WHERE hc.id = ? AND hc.selected = 1 AND hc.state = 'FAILED'
                     AND wp.id IS NULL''',
                (clean_clip_id,),
            ).fetchone()
            if not clip:
                return False
            cursor = conn.execute(
                """UPDATE highlight_clips
                   SET state = 'SELECTED', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'FAILED'""",
                (clean_clip_id,),
            )
            if cursor.rowcount != 1:
                return False
            conn.execute(
                """UPDATE highlight_jobs
                   SET state = 'CANDIDATES_READY', error_message = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'FAILED'""",
                (clip["job_id"],),
            )
            conn.commit()
            return True

    def get_highlight_clip_assets(self, clip_id: str) -> Optional[Dict[str, Any]]:
        """读取独立 Clip 的本地资产和发布主体，不推断也不修改平台状态。"""
        clean_clip_id = (clip_id or "").strip()
        if not clean_clip_id:
            return None
        with self.get_connection() as conn:
            row = conn.execute(
                '''SELECT hc.*, hj.state AS job_state, hj.workspace_path, pv.youtube_id AS source_youtube_id,
                          pv.title AS source_title, pv.zh_title AS source_zh_title,
                          ps.id AS publication_subject_id, hca.source_video_path,
                          hca.source_video_sha256, hca.source_video_kind, hca.rendered_video_path,
                          hca.title_path, hca.copy_path, hca.category_path, hca.cover_path,
                          hca.cover_provenance_path, hca.artifact_manifest_path, hca.evidence_dir,
                          hcr.asset_manifest_sha256 AS reviewed_manifest_sha256,
                          hcr.approved_by AS review_approved_by, hcr.approved_at AS review_approved_at
                   FROM highlight_clips hc
                   JOIN highlight_jobs hj ON hj.id = hc.job_id
                   JOIN processed_videos pv ON pv.id = hj.source_video_id
                   LEFT JOIN publication_subjects ps ON ps.highlight_clip_id = hc.id
                   LEFT JOIN highlight_clip_assets hca ON hca.clip_id = hc.id
                   LEFT JOIN highlight_clip_publication_reviews hcr ON hcr.clip_id = hc.id
                   WHERE hc.id = ?''',
                (clean_clip_id,),
            ).fetchone()
            return dict(row) if row else None

    def approve_highlight_clip_publication(
        self, clip_id: str, *, asset_manifest_sha256: str, approved_by: str,
    ) -> Dict[str, Any]:
        """记录对当前资产版本的人工发布审核；审核并不等同于平台提交。"""
        clean_clip_id = (clip_id or "").strip()
        clean_manifest_sha256 = (asset_manifest_sha256 or "").strip().lower()
        clean_approved_by = (approved_by or "").strip()[:80]
        if not clean_clip_id or len(clean_manifest_sha256) != 64 or not clean_approved_by:
            raise ValueError("Highlight publication review requires clip, manifest hash, and reviewer")
        with self.get_connection() as conn:
            clip = conn.execute(
                '''SELECT hc.id
                   FROM highlight_clips hc
                   JOIN highlight_clip_assets hca ON hca.clip_id = hc.id
                   WHERE hc.id = ? AND hc.state = 'ASSETS_READY' AND hc.selected = 1''',
                (clean_clip_id,),
            ).fetchone()
            if not clip:
                raise ValueError("Highlight Clip is not ready for publication review")
            conn.execute(
                '''INSERT INTO highlight_clip_publication_reviews (
                       clip_id, asset_manifest_sha256, approved_by
                   ) VALUES (?, ?, ?)
                   ON CONFLICT(clip_id) DO UPDATE SET
                       asset_manifest_sha256 = excluded.asset_manifest_sha256,
                       approved_by = excluded.approved_by,
                       approved_at = CURRENT_TIMESTAMP''',
                (clean_clip_id, clean_manifest_sha256, clean_approved_by),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM highlight_clip_publication_reviews WHERE clip_id = ?",
                (clean_clip_id,),
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to record Highlight publication review")
            return dict(row)

    # --- Highlight slicing (manual-only, isolated from PipelineManager) ---
    _HIGHLIGHT_JOB_STATES = {
        "QUEUED", "ANALYZING", "CANDIDATES_READY", "RENDERING", "ASSETS_READY", "FAILED", "CANCELED",
    }
    _HIGHLIGHT_CLIP_STATES = {
        "CANDIDATE", "SELECTED", "RENDERING", "ASSETS_READY", "FAILED", "CANCELED",
    }

    def list_highlight_source_videos(self, *, limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
        """列出可显式创建 Highlight Job 的源视频；不改变原队列或源状态。"""
        safe_limit = max(1, min(50, int(limit)))
        safe_offset = max(0, int(offset))
        with self.get_connection() as conn:
            rows = conn.execute(
                """SELECT pv.id, pv.youtube_id, pv.title, pv.zh_title, pv.status, pv.duration_sec,
                          pv.source, pv.created_at, pv.updated_at,
                          (SELECT COUNT(*) FROM highlight_jobs hj WHERE hj.source_video_id = pv.id) AS highlight_job_count,
                          (SELECT hj.id FROM highlight_jobs hj
                           WHERE hj.source_video_id = pv.id
                             AND hj.state IN ('QUEUED', 'ANALYZING', 'RENDERING')
                           ORDER BY hj.updated_at DESC LIMIT 1) AS active_highlight_job_id
                   FROM processed_videos pv
                   WHERE pv.slice_index = 0 AND pv.parent_id IS NULL
                     AND IFNULL(pv.source, '') != 'DISCOVERY'
                     AND NOT EXISTS (
                         SELECT 1 FROM blacklisted_videos bv WHERE bv.youtube_id = pv.youtube_id
                     )
                   ORDER BY pv.updated_at DESC, pv.id DESC
                   LIMIT ? OFFSET ?""",
                (safe_limit, safe_offset),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_highlight_job(
        self,
        youtube_id: str,
        *,
        max_clips: int = 3,
        min_duration_sec: float = 35,
        max_duration_sec: float = 90,
        requested_by: str = "manual",
    ) -> tuple[Dict[str, Any], bool]:
        """为源视频创建独立 Highlight Job；若已有活动任务则原样返回，绝不影响源片。"""
        from uuid import uuid4

        clean_yid = (youtube_id or "").strip()
        if not clean_yid:
            raise ValueError("youtube_id is required")
        safe_max_clips = max(1, min(8, int(max_clips)))
        safe_min_duration = max(10.0, float(min_duration_sec))
        safe_max_duration = max(safe_min_duration, min(180.0, float(max_duration_sec)))
        clean_requested_by = (requested_by or "manual").strip()[:80] or "manual"
        with self.get_connection() as conn:
            source = conn.execute(
                """SELECT id FROM processed_videos
                   WHERE youtube_id = ? AND slice_index = 0 AND parent_id IS NULL""",
                (clean_yid,),
            ).fetchone()
            if not source:
                raise ValueError("Source video does not exist")
            source_id = int(source["id"])
            active = conn.execute(
                """SELECT * FROM highlight_jobs
                   WHERE source_video_id = ? AND state IN ('QUEUED', 'ANALYZING', 'RENDERING')
                   ORDER BY updated_at DESC LIMIT 1""",
                (source_id,),
            ).fetchone()
            if active:
                return dict(active), False
            latest = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM highlight_jobs WHERE source_video_id = ?",
                (source_id,),
            ).fetchone()
            version = int(latest["version"] or 0) + 1
            job_id = uuid4().hex
            try:
                conn.execute(
                    """INSERT INTO highlight_jobs
                       (id, source_video_id, version, requested_by, max_clips, min_duration_sec, max_duration_sec)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        job_id, source_id, version, clean_requested_by, safe_max_clips,
                        safe_min_duration, safe_max_duration,
                    ),
                )
            except sqlite3.IntegrityError:
                # 两次 Telegram callback 可能近乎同时到达；唯一活动任务索引胜出后返回赢家。
                active = conn.execute(
                    """SELECT * FROM highlight_jobs
                       WHERE source_video_id = ? AND state IN ('QUEUED', 'ANALYZING', 'RENDERING')
                       ORDER BY updated_at DESC LIMIT 1""",
                    (source_id,),
                ).fetchone()
                if active:
                    return dict(active), False
                raise
            conn.commit()
            row = conn.execute("SELECT * FROM highlight_jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                raise RuntimeError("Failed to create Highlight Job")
            return dict(row), True

    def claim_highlight_job_for_analysis(self, job_id: str) -> Optional[Dict[str, Any]]:
        """原子领取一个新 Highlight Job；重复点击不会重复分析。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE highlight_jobs
                   SET state = 'ANALYZING', error_message = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'QUEUED'""",
                (job_id,),
            )
            if cursor.rowcount != 1:
                return None
            row = conn.execute(
                """SELECT hj.*, pv.youtube_id, pv.title AS source_title, pv.zh_title AS source_zh_title,
                          pv.status AS source_status
                   FROM highlight_jobs hj JOIN processed_videos pv ON pv.id = hj.source_video_id
                   WHERE hj.id = ?""",
                (job_id,),
            ).fetchone()
            return dict(row) if row else None

    def complete_highlight_job_analysis(
        self,
        job_id: str,
        *,
        source_subtitle_sha256: str,
        workspace_path: str,
        plan_path: str,
        clips: Sequence[Dict[str, Any]],
    ) -> None:
        """原子保存候选计划并转入 CANDIDATES_READY；只写 Highlight 自身账本。"""
        with self.get_connection() as conn:
            job = conn.execute("SELECT state FROM highlight_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                raise ValueError("Highlight Job does not exist")
            if job["state"] != "ANALYZING":
                raise ValueError("Highlight Job is not being analyzed")
            conn.execute("DELETE FROM highlight_clips WHERE job_id = ?", (job_id,))
            for ordinal, clip in enumerate(clips, start=1):
                conn.execute(
                    """INSERT INTO highlight_clips
                       (id, job_id, ordinal, raw_start_ms, raw_end_ms, snapped_start_ms, snapped_end_ms,
                        virality_score, core_quote, source_text, score_reason)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(clip["id"]), job_id, ordinal, int(clip["raw_start_ms"]), int(clip["raw_end_ms"]),
                        clip.get("snapped_start_ms"), clip.get("snapped_end_ms"), float(clip["virality_score"]),
                        str(clip.get("core_quote") or ""), str(clip.get("source_text") or ""),
                        str(clip.get("score_reason") or ""),
                    ),
                )
            cursor = conn.execute(
                """UPDATE highlight_jobs
                   SET state = 'CANDIDATES_READY', source_subtitle_sha256 = ?, workspace_path = ?,
                       plan_path = ?, error_message = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'ANALYZING'""",
                (source_subtitle_sha256, workspace_path, plan_path, job_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Highlight Job state changed before candidate plan was stored")
            conn.commit()

    def fail_highlight_job(self, job_id: str, reason: str) -> None:
        """记录独立任务失败，不改变源视频或其发布状态。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE highlight_jobs
                   SET state = 'FAILED', error_message = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state IN ('QUEUED', 'ANALYZING')""",
                ((reason or "Highlight candidate analysis failed")[:500], job_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Highlight Job cannot be marked failed from its current state")
            conn.commit()

    def get_highlight_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """返回独立 Highlight Job 与只读源片信息。"""
        with self.get_connection() as conn:
            row = conn.execute(
                """SELECT hj.*, pv.youtube_id, pv.title AS source_title, pv.zh_title AS source_zh_title,
                          pv.status AS source_status
                   FROM highlight_jobs hj JOIN processed_videos pv ON pv.id = hj.source_video_id
                   WHERE hj.id = ?""",
                (job_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_highlight_clips(self, job_id: str) -> List[Dict[str, Any]]:
        """返回一个 Highlight Job 的候选片段，按稳定序号排序。"""
        with self.get_connection() as conn:
            rows = conn.execute(
                '''SELECT hc.*, ps.id AS publication_subject_id
                   FROM highlight_clips hc
                   LEFT JOIN publication_subjects ps ON ps.highlight_clip_id = hc.id
                   WHERE hc.job_id = ? ORDER BY hc.ordinal ASC''',
                (job_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_highlight_jobs(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        """读取最近 Highlight Job；供 Telegram 和控制台展示，不触发生产动作。"""
        safe_limit = max(1, min(100, int(limit)))
        with self.get_connection() as conn:
            rows = conn.execute(
                """SELECT hj.*, pv.youtube_id, pv.title AS source_title, pv.zh_title AS source_zh_title,
                          (SELECT COUNT(*) FROM highlight_clips hc WHERE hc.job_id = hj.id) AS clip_count
                   FROM highlight_jobs hj JOIN processed_videos pv ON pv.id = hj.source_video_id
                   ORDER BY hj.updated_at DESC, hj.id DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    # --- English World research (manual production, isolated from PipelineManager) ---
    _ENGLISH_WORLD_JOB_STATES = {
        "RESEARCH_QUEUED", "RESEARCHING", "CANDIDATES_READY", "CANDIDATE_SELECTED",
        "PRODUCTION_REQUESTED", "FAILED", "CANCELED",
    }
    _ENGLISH_WORLD_REVIEW_STATES = {
        "READY_FOR_REVIEW", "SUBMISSION_APPROVED", "SUBMITTING", "UNDER_REVIEW",
        "UNCERTAIN", "LOGIN_REQUIRED", "FAILED", "HELD",
    }

    def create_english_world_research_job(
        self,
        *,
        requested_by: str = "manual",
        notification_target: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建独立英语世界研究任务；不会下载、入通用队列或创建发布主体。"""
        from uuid import uuid4

        clean_requested_by = (requested_by or "manual").strip()[:80] or "manual"
        clean_target = (notification_target or "").strip()[:120] or None
        clean_url = (source_url or "").strip()[:1000] or None
        with self.get_connection() as conn:
            job_id = uuid4().hex
            conn.execute(
                """INSERT INTO english_world_jobs (id, requested_by, notification_target, source_url)
                   VALUES (?, ?, ?, ?)""",
                (job_id, clean_requested_by, clean_target, clean_url),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM english_world_jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                raise RuntimeError("Failed to create English World research job")
            return dict(row)

    def claim_english_world_job_for_research(self, job_id: str) -> Optional[Dict[str, Any]]:
        """原子领取待研究任务；重复调度不会重复搜索或改写已就绪候选。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE english_world_jobs
                   SET state = 'RESEARCHING', error_message = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'RESEARCH_QUEUED'""",
                (job_id,),
            )
            if cursor.rowcount != 1:
                return None
            row = conn.execute("SELECT * FROM english_world_jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row) if row else None

    def complete_english_world_research(
        self, job_id: str, *, candidates: Sequence[Dict[str, Any]],
    ) -> None:
        """原子保存元数据候选并转为待选择；不会生成视频或提交平台。"""
        if not candidates:
            raise ValueError("English World research requires candidates")
        with self.get_connection() as conn:
            job = conn.execute("SELECT state FROM english_world_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                raise ValueError("English World job does not exist")
            if job["state"] != "RESEARCHING":
                raise ValueError("English World job is not being researched")
            conn.execute("DELETE FROM english_world_candidates WHERE job_id = ?", (job_id,))
            for ordinal, candidate in enumerate(candidates, start=1):
                conn.execute(
                    """INSERT INTO english_world_candidates
                       (id, job_id, ordinal, source_url, youtube_id, source_title, source_channel,
                        source_channel_id, upload_date, duration_sec, topic, learning_value,
                        safety_note, caption_status, recommendation_score)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(candidate["id"]), job_id, ordinal, str(candidate["source_url"]),
                        candidate.get("youtube_id"), str(candidate["source_title"]),
                        candidate.get("source_channel"), candidate.get("source_channel_id"),
                        candidate.get("upload_date"),
                        candidate.get("duration_sec"), str(candidate["topic"]),
                        str(candidate["learning_value"]), str(candidate["safety_note"]),
                        str(candidate["caption_status"]), int(candidate.get("recommendation_score") or 0),
                    ),
                )
            cursor = conn.execute(
                """UPDATE english_world_jobs
                   SET state = 'CANDIDATES_READY', error_message = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'RESEARCHING'""",
                (job_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("English World job state changed before candidates were stored")
            conn.commit()

    def fail_english_world_job(self, job_id: str, reason: str) -> None:
        """记录研究失败；不改变已选候选、通用队列或发布账本。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE english_world_jobs
                   SET state = 'FAILED', error_message = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state IN ('RESEARCH_QUEUED', 'RESEARCHING')""",
                ((reason or "English World research failed")[:500], job_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("English World job cannot be marked failed from its current state")
            conn.commit()

    def select_english_world_candidate(self, candidate_id: str) -> Dict[str, Any]:
        """选定一个已研究候选；只进入待制作确认，不下载、渲染或发布。"""
        clean_candidate_id = (candidate_id or "").strip()
        with self.get_connection() as conn:
            candidate = conn.execute(
                """SELECT ewc.*, ewj.state AS job_state FROM english_world_candidates ewc
                   JOIN english_world_jobs ewj ON ewj.id = ewc.job_id
                   WHERE ewc.id = ?""",
                (clean_candidate_id,),
            ).fetchone()
            if not candidate:
                raise ValueError("English World candidate does not exist")
            if not str(candidate["source_channel_id"] or "").strip():
                raise ValueError(
                    "English World candidate lacks an auditable approved channel ID; research it again"
                )
            if candidate["job_state"] not in {"CANDIDATES_READY", "CANDIDATE_SELECTED"}:
                raise ValueError("English World candidate is not selectable in the current job state")
            conn.execute("UPDATE english_world_candidates SET selected = 0 WHERE job_id = ?", (candidate["job_id"],))
            conn.execute("UPDATE english_world_candidates SET selected = 1 WHERE id = ?", (clean_candidate_id,))
            conn.execute(
                """UPDATE english_world_jobs
                   SET state = 'CANDIDATE_SELECTED', selected_candidate_id = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (clean_candidate_id, candidate["job_id"]),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM english_world_candidates WHERE id = ?", (clean_candidate_id,)).fetchone()
            if not row:
                raise RuntimeError("Failed to select English World candidate")
            return dict(row)

    def request_english_world_production(self, job_id: str) -> Dict[str, Any]:
        """记录第二次制作确认；进入独立协调队列但不冒充已渲染。"""
        with self.get_connection() as conn:
            job = conn.execute("SELECT * FROM english_world_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                raise ValueError("English World job does not exist")
            if job["state"] == "PRODUCTION_REQUESTED" and job["selected_candidate_id"]:
                return dict(job)
            if job["state"] != "CANDIDATE_SELECTED" or not job["selected_candidate_id"]:
                raise ValueError("Select an English World candidate before requesting production")
            cursor = conn.execute(
                """UPDATE english_world_jobs
                   SET state = 'PRODUCTION_REQUESTED', production_state = 'REQUESTED',
                       error_message = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'CANDIDATE_SELECTED'""",
                (job_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("English World production request was not accepted")
            conn.commit()
            row = conn.execute("SELECT * FROM english_world_jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row) if row else {}

    def claim_english_world_job_for_production(self, job_id: str) -> Optional[Dict[str, Any]]:
        """原子领取一条已二次确认的制作请求，并绑定已选候选元数据。"""
        clean_id = (job_id or "").strip()
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE english_world_jobs
                   SET production_state = 'PRODUCING', production_started_at = CURRENT_TIMESTAMP,
                       production_finished_at = NULL, error_message = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'PRODUCTION_REQUESTED'
                     AND COALESCE(production_state, 'REQUESTED') = 'REQUESTED'""",
                (clean_id,),
            )
            if cursor.rowcount != 1:
                return None
            row = conn.execute(
                """SELECT ewj.*, ewc.source_url AS candidate_source_url,
                          ewc.youtube_id AS candidate_youtube_id,
                          ewc.source_title AS candidate_source_title,
                          ewc.source_channel AS candidate_source_channel,
                          ewc.duration_sec AS candidate_duration_sec,
                          ewc.safety_note AS candidate_safety_note
                   FROM english_world_jobs ewj
                   JOIN english_world_candidates ewc ON ewc.id = ewj.selected_candidate_id
                   WHERE ewj.id = ? AND ewc.selected = 1""",
                (clean_id,),
            ).fetchone()
            if not row:
                raise ValueError("English World production request lost its selected candidate")
            return dict(row)

    def complete_english_world_job_production(
        self,
        job_id: str,
        *,
        review_id: str,
        mp4_path: str,
        manifest_path: str,
    ) -> Dict[str, Any]:
        """把人工请求绑定到已登记审核项；不把审核就绪误作平台发布。"""
        clean_id = (job_id or "").strip()
        clean_review_id = (review_id or "").strip()
        if not clean_review_id or not mp4_path or not manifest_path:
            raise ValueError("English World production completion requires review and artifact identities")
        with self.get_connection() as conn:
            review = conn.execute(
                "SELECT id FROM english_world_review_items WHERE id = ?", (clean_review_id,),
            ).fetchone()
            if not review:
                raise ValueError("English World production review item does not exist")
            cursor = conn.execute(
                """UPDATE english_world_jobs
                   SET production_state = 'READY_FOR_REVIEW', review_id = ?, mp4_path = ?,
                       manifest_path = ?, production_finished_at = CURRENT_TIMESTAMP,
                       error_message = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'PRODUCTION_REQUESTED'
                     AND production_state = 'PRODUCING'""",
                (clean_review_id, str(mp4_path), str(manifest_path), clean_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("English World production result cannot overwrite the current job state")
            conn.commit()
            row = conn.execute("SELECT * FROM english_world_jobs WHERE id = ?", (clean_id,)).fetchone()
            return dict(row) if row else {}

    def fail_english_world_job_production(self, job_id: str, reason: str) -> Dict[str, Any]:
        """持久化已领取制作请求的失败；不触发候选切换、重制或投稿。"""
        clean_id = (job_id or "").strip()
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE english_world_jobs
                   SET production_state = 'FAILED', production_finished_at = CURRENT_TIMESTAMP,
                       error_message = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'PRODUCTION_REQUESTED'
                     AND production_state = 'PRODUCING'""",
                ((reason or "English World production failed")[:500], clean_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("English World production cannot be marked failed from its current state")
            conn.commit()
            row = conn.execute("SELECT * FROM english_world_jobs WHERE id = ?", (clean_id,)).fetchone()
            return dict(row) if row else {}

    def get_english_world_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """读取单个英语世界任务；只读，不触发外部搜索、制作或发布。"""
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM english_world_jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row) if row else None

    def get_english_world_candidates(self, job_id: str) -> List[Dict[str, Any]]:
        """读取按推荐顺序固定的候选列表。"""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM english_world_candidates WHERE job_id = ? ORDER BY ordinal ASC",
                (job_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_english_world_jobs(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        """读取最近英语世界任务账本；不触发任何研究、制作或发布动作。"""
        safe_limit = max(1, min(100, int(limit)))
        with self.get_connection() as conn:
            rows = conn.execute(
                """SELECT ewj.*, (SELECT COUNT(*) FROM english_world_candidates ewc
                                      WHERE ewc.job_id = ewj.id) AS candidate_count
                   FROM english_world_jobs ewj
                   ORDER BY ewj.updated_at DESC, ewj.id DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    # --- English World Telegram review / WeChat submission (isolated from PipelineManager) ---

    def list_english_world_submission_protected_source_ids(self) -> List[str]:
        """读取禁止日更再次制作的同源审核/投稿保护来源；只读且不改变历史项状态。"""
        with self.get_connection() as conn:
            rows = conn.execute(
                """SELECT DISTINCT source_youtube_id
                   FROM english_world_review_items
                   WHERE source_youtube_id IS NOT NULL
                     AND TRIM(source_youtube_id) != ''
                     AND state IN ('READY_FOR_REVIEW', 'SUBMISSION_APPROVED', 'SUBMITTING',
                                   'UNDER_REVIEW', 'UNCERTAIN', 'LOGIN_REQUIRED', 'FAILED')
                   ORDER BY source_youtube_id ASC"""
            ).fetchall()
            return [str(row["source_youtube_id"]) for row in rows]

    def create_english_world_review_item(
        self,
        *,
        artifact_sha256: str,
        manifest_sha256: Optional[str] = None,
        title_sha256: Optional[str] = None,
        copy_sha256: Optional[str] = None,
        cover_sha256: Optional[str] = None,
        cover_provenance_sha256: Optional[str] = None,
        title: str,
        mp4_path: str,
        manifest_path: str,
        title_path: str,
        copy_path: str,
        cover_path: str,
        cover_provenance_path: str,
        source_url: Optional[str] = None,
        source_title: Optional[str] = None,
        source_publisher: Optional[str] = None,
        source_youtube_id: Optional[str] = None,
        notification_target: Optional[str] = None,
    ) -> Dict[str, Any]:
        """登记一条已完成学习卡的审核项；同一成片只保留一个不可混淆的审批身份。"""
        from uuid import uuid4

        clean_hash = (artifact_sha256 or "").strip().lower()
        package_hashes = tuple(
            (value or "").strip().lower() for value in (
                manifest_sha256, title_sha256, copy_sha256, cover_sha256, cover_provenance_sha256,
            )
        )
        if any(package_hashes) and any(len(value) != 64 for value in package_hashes):
            raise ValueError("English World review item requires the complete immutable package hash set")
        clean_title = (title or "").strip()[:160]
        clean_source_youtube_id = (source_youtube_id or "").strip()[:80] or None
        required_paths = (mp4_path, manifest_path, title_path, copy_path, cover_path, cover_provenance_path)
        if len(clean_hash) != 64 or any(not str(value or "").strip() for value in required_paths):
            raise ValueError("English World review item requires an artifact hash and complete publish package")
        if not clean_title:
            raise ValueError("English World review item requires a title")
        with self.get_connection() as conn:
            existing = conn.execute(
                "SELECT * FROM english_world_review_items WHERE artifact_sha256 = ?", (clean_hash,),
            ).fetchone()
            if existing:
                result = dict(existing)
                result["_created_now"] = False
                return result
            if clean_source_youtube_id:
                same_source = conn.execute(
                    """SELECT id, state FROM english_world_review_items
                       WHERE source_youtube_id = ?
                         AND state IN ('READY_FOR_REVIEW', 'SUBMISSION_APPROVED', 'SUBMITTING',
                                      'UNDER_REVIEW', 'UNCERTAIN', 'LOGIN_REQUIRED', 'FAILED')
                       ORDER BY updated_at DESC LIMIT 1""",
                    (clean_source_youtube_id,),
                ).fetchone()
                if same_source:
                    raise ValueError(
                        "English World source already has an active or submission-protected review item: "
                        f"{same_source['id']} ({same_source['state']})"
                    )
            review_id = uuid4().hex
            conn.execute(
                """INSERT INTO english_world_review_items
                   (id, artifact_sha256, manifest_sha256, title_sha256, copy_sha256,
                    cover_sha256, cover_provenance_sha256,
                    title, mp4_path, manifest_path, title_path, copy_path,
                    cover_path, cover_provenance_path, source_url, source_title, source_publisher,
                    source_youtube_id, notification_target)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    review_id, clean_hash, *package_hashes,
                    clean_title, str(mp4_path), str(manifest_path), str(title_path),
                    str(copy_path), str(cover_path), str(cover_provenance_path),
                    (source_url or "").strip()[:1000] or None,
                    (source_title or "").strip()[:500] or None,
                    (source_publisher or "").strip()[:160] or None,
                    clean_source_youtube_id,
                    (notification_target or "").strip()[:120] or None,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM english_world_review_items WHERE id = ?", (review_id,)).fetchone()
            if not row:
                raise RuntimeError("Failed to create English World review item")
            result = dict(row)
            result["_created_now"] = True
            return result

    def get_english_world_review_item(self, review_id: str) -> Optional[Dict[str, Any]]:
        """读取英语世界审核项；只读，不触发投稿或重试。"""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM english_world_review_items WHERE id = ?", ((review_id or "").strip(),),
            ).fetchone()
            return dict(row) if row else None

    def bind_english_world_review_package_hashes(
        self, review_id: str, *, hashes: Dict[str, str],
    ) -> Dict[str, Any]:
        """在下一次投稿领取前绑定完整包指纹；已绑定值不可改变。"""
        fields = (
            "artifact_sha256", "manifest_sha256", "title_sha256", "copy_sha256",
            "cover_sha256", "cover_provenance_sha256",
        )
        normalized = {field: str(hashes.get(field) or "").strip().lower() for field in fields}
        if any(len(normalized[field]) != 64 for field in fields):
            raise ValueError("English World package hash set is incomplete")
        clean_id = (review_id or "").strip()
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM english_world_review_items WHERE id = ?", (clean_id,)).fetchone()
            bindable_states = {
                "READY_FOR_REVIEW", "SUBMISSION_APPROVED", "UNCERTAIN", "LOGIN_REQUIRED",
            }
            if not row or row["state"] not in bindable_states:
                raise ValueError("English World package hashes cannot bind after a submission is in flight")
            for field in fields:
                current = str(row[field] or "").strip().lower()
                if current and current != normalized[field]:
                    raise ValueError(f"English World package hash changed: {field}")
            conn.execute(
                """UPDATE english_world_review_items
                   SET artifact_sha256 = ?, manifest_sha256 = ?, title_sha256 = ?, copy_sha256 = ?,
                       cover_sha256 = ?, cover_provenance_sha256 = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state IN ('READY_FOR_REVIEW', 'SUBMISSION_APPROVED',
                                              'UNCERTAIN', 'LOGIN_REQUIRED')""",
                tuple(normalized[field] for field in fields) + (clean_id,),
            )
            updated = conn.execute("SELECT * FROM english_world_review_items WHERE id = ?", (clean_id,)).fetchone()
            return dict(updated) if updated else {}

    def approve_english_world_submission(
        self, review_id: str, *, authorization: str = "TELEGRAM_REVIEW",
    ) -> Dict[str, Any]:
        """原子记录一条具名授权；不接受模糊文字匹配或终态重开。"""
        clean_id = (review_id or "").strip()
        clean_authorization = (authorization or "").strip().upper()
        if clean_authorization not in {"TELEGRAM_REVIEW", "AUTO_POLICY"}:
            raise ValueError("Invalid English World submission authorization")
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM english_world_review_items WHERE id = ?", (clean_id,)).fetchone()
            if not row:
                raise ValueError("English World review item does not exist")
            if row["state"] == "SUBMISSION_APPROVED":
                return dict(row)
            if row["state"] != "READY_FOR_REVIEW":
                raise ValueError(f"English World review item cannot be approved from {row['state']}")
            cursor = conn.execute(
                """UPDATE english_world_review_items
                   SET state = 'SUBMISSION_APPROVED', approved_at = CURRENT_TIMESTAMP,
                       approval_source = ?,
                       authorization_expires_at = CASE
                           WHEN ? = 'TELEGRAM_REVIEW' THEN datetime('now', '+120 minutes')
                           ELSE NULL
                       END,
                       error_message = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'READY_FOR_REVIEW'""",
                (clean_authorization, clean_authorization, clean_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("English World review item approval was not accepted")
            conn.commit()
            updated = conn.execute("SELECT * FROM english_world_review_items WHERE id = ?", (clean_id,)).fetchone()
            return dict(updated) if updated else {}

    def claim_english_world_submission(
        self, review_id: str, *, evidence_dir: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """专用投稿器原子领取仍有效的批准项；重复或过期授权不能二次投稿。"""
        clean_id = (review_id or "").strip()
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE english_world_review_items
                   SET state = 'SUBMITTING', submission_started_at = CURRENT_TIMESTAMP,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'SUBMISSION_APPROVED'
                     AND (
                         approval_source = 'AUTO_POLICY'
                         OR (
                             approval_source IN ('TELEGRAM_REVIEW', 'OPERATOR_RECOVERY')
                             AND authorization_expires_at > CURRENT_TIMESTAMP
                         )
                     )""",
                (clean_id,),
            )
            if cursor.rowcount != 1:
                return None
            row = conn.execute("SELECT * FROM english_world_review_items WHERE id = ?", (clean_id,)).fetchone()
            if not row or any(not row[field] for field in (
                "artifact_sha256", "manifest_sha256", "title_sha256", "copy_sha256",
                "cover_sha256", "cover_provenance_sha256",
            )):
                raise ValueError("English World submission requires an immutable package hash set")
            from uuid import uuid4
            attempt_id = uuid4().hex
            conn.execute(
                """INSERT INTO english_world_submission_attempts (
                       attempt_id, review_id, approval_source, artifact_sha256, manifest_sha256,
                       title_sha256, copy_sha256, cover_sha256, cover_provenance_sha256, evidence_dir
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    attempt_id, clean_id, row["approval_source"], row["artifact_sha256"],
                    row["manifest_sha256"], row["title_sha256"], row["copy_sha256"],
                    row["cover_sha256"], row["cover_provenance_sha256"],
                    (evidence_dir or "").strip() or None,
                ),
            )
            return {**dict(row), "_attempt_id": attempt_id}

    def authorize_english_world_operator_recovery(
        self, review_id: str, *, reason: str,
    ) -> Dict[str, Any]:
        """为一条可证明从未提交的自动延后项签发两小时具名补发授权。

        该入口只允许从 ``AUTO_POLICY/SUBMISSION_APPROVED`` 转换，且必须没有
        submission_started_at 和不可变尝试记录；任何在途、失败或未确认项均拒绝。
        """
        clean_id = (review_id or "").strip()
        clean_reason = " ".join((reason or "").split())
        if not clean_reason or len(clean_reason) > 240:
            raise ValueError("English World operator recovery requires a concise reason")
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE english_world_review_items
                   SET approval_source = 'OPERATOR_RECOVERY',
                       authorization_expires_at = datetime('now', '+120 minutes'),
                       error_message = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'SUBMISSION_APPROVED'
                     AND approval_source = 'AUTO_POLICY'
                     AND submission_started_at IS NULL
                     AND NOT EXISTS (
                         SELECT 1 FROM english_world_submission_attempts attempt
                         WHERE attempt.review_id = english_world_review_items.id
                     )""",
                (f"操作员具名补发授权：{clean_reason}", clean_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Only an unattempted AUTO_POLICY item can receive operator recovery")
            row = conn.execute(
                "SELECT * FROM english_world_review_items WHERE id = ?", (clean_id,),
            ).fetchone()
            return dict(row) if row else {}

    def expire_english_world_submission_authorization(self, review_id: str) -> Optional[Dict[str, Any]]:
        """将已过期的两小时人工授权退回待审核；自动策略授权不受影响。"""
        clean_id = (review_id or "").strip()
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE english_world_review_items
                   SET state = 'READY_FOR_REVIEW', approved_at = NULL, approval_source = NULL,
                       authorization_expires_at = NULL,
                       error_message = '两小时人工投稿授权已过期；需要重新确认本条成片。',
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'SUBMISSION_APPROVED'
                     AND approval_source = 'TELEGRAM_REVIEW'
                     AND authorization_expires_at <= CURRENT_TIMESTAMP""",
                (clean_id,),
            )
            if cursor.rowcount != 1:
                return None
            row = conn.execute("SELECT * FROM english_world_review_items WHERE id = ?", (clean_id,)).fetchone()
            return dict(row) if row else None

    def get_next_auto_approved_english_world_submission(self) -> Optional[Dict[str, Any]]:
        """读取下一条等待公共窗口的自动授权项；只读且不领取投稿。"""
        with self.get_connection() as conn:
            row = conn.execute(
                """SELECT * FROM english_world_review_items
                   WHERE state = 'SUBMISSION_APPROVED' AND approval_source = 'AUTO_POLICY'
                   ORDER BY approved_at ASC, id ASC LIMIT 1"""
            ).fetchone()
            return dict(row) if row else None

    def restore_expired_english_world_operator_recoveries(self) -> int:
        """把未领取且已过期的具名补发授权退回 AUTO_POLICY 公共窗口队列。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE english_world_review_items
                   SET approval_source = 'AUTO_POLICY', authorization_expires_at = NULL,
                       error_message = '具名操作员补发授权未在两小时内领取；已安全退回公共窗口队列。',
                       updated_at = CURRENT_TIMESTAMP
                   WHERE state = 'SUBMISSION_APPROVED'
                     AND approval_source = 'OPERATOR_RECOVERY'
                     AND authorization_expires_at <= CURRENT_TIMESTAMP
                     AND submission_started_at IS NULL
                     AND NOT EXISTS (
                         SELECT 1 FROM english_world_submission_attempts attempt
                         WHERE attempt.review_id = english_world_review_items.id
                     )""",
            )
            return cursor.rowcount

    def reopen_uncertain_english_world_submission(self, review_id: str) -> Dict[str, Any]:
        """人工明确确认未发布后，重开同一审核项的一次投稿机会。

        此通道只接受 ``UNCERTAIN``，不会被通用重试或自动调度调用；原证据目录
        保持不变，以留存首次点击发布但未确认的证据。
        """
        clean_id = (review_id or "").strip()
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE english_world_review_items
                   SET state = 'SUBMISSION_APPROVED', uploader_exit_code = NULL,
                       approved_at = CURRENT_TIMESTAMP, approval_source = 'TELEGRAM_REVIEW',
                       authorization_expires_at = datetime('now', '+120 minutes'),
                       error_message = '操作员已明确确认首次投稿未成功；重开同一审核项进行一次人工授权重传。',
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'UNCERTAIN'""",
                (clean_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("Only an UNCERTAIN English World submission can be reopened")
            conn.commit()
            row = conn.execute("SELECT * FROM english_world_review_items WHERE id = ?", (clean_id,)).fetchone()
            return dict(row) if row else {}

    def reopen_deleted_english_world_submission(
        self,
        review_id: str,
        *,
        deletion_evidence_dir: str,
    ) -> Dict[str, Any]:
        """仅凭精确回查的 NOT_FOUND 证据重开一次已删除作品的投稿机会。

        旧的 ``english_world_submission_attempts`` 行保持不可变，审核项解绑已
        删除的原生 ID 后才允许下一次尝试绑定新 ID。此入口不接受“不可判定”、
        审核驳回或单纯人工文字声明，避免把仍可能存在的平台作品重复投稿。
        """
        clean_id = (review_id or "").strip()
        clean_evidence_dir = (deletion_evidence_dir or "").strip()
        if not clean_evidence_dir:
            raise ValueError("English World deleted-submission recovery requires evidence_dir")
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE english_world_review_items
                   SET state = 'SUBMISSION_APPROVED', approved_at = CURRENT_TIMESTAMP,
                       approval_source = 'OPERATOR_RECOVERY',
                       authorization_expires_at = datetime('now', '+120 minutes'),
                       platform_post_id = NULL, platform_url = NULL, platform_state = NULL,
                       reconciliation_evidence_dir = ?, reconciliation_failures = 0,
                       reconciliation_error = NULL,
                       error_message = '作品管理页已确认旧原生记录不存在；已签发一次两小时重投授权。',
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'UNDER_REVIEW'
                     AND platform_state = 'NOT_FOUND'
                     AND platform_post_id IS NOT NULL AND platform_post_id != ''""",
                (clean_evidence_dir, clean_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "Only an UNDER_REVIEW English World item with exact NOT_FOUND evidence can be reopened",
                )
            conn.commit()
            row = conn.execute("SELECT * FROM english_world_review_items WHERE id = ?", (clean_id,)).fetchone()
            return dict(row) if row else {}

    def reopen_failed_english_world_original_declaration(
        self,
        review_id: str,
        *,
        failure_evidence_dir: str,
    ) -> Dict[str, Any]:
        """仅重开未发表且原创界面回读失败的英语世界尝试一次。

        次数写入审核项，而不是仅由当前状态推断；重试再次失败后即使仍无平台
        回执，也不得再次签发，避免界面选择器异常触发无界上传循环。
        """
        clean_id = (review_id or "").strip()
        clean_evidence_dir = (failure_evidence_dir or "").strip()
        if not clean_evidence_dir:
            raise ValueError("English World original-declaration recovery requires evidence_dir")
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE english_world_review_items
                   SET state = 'SUBMISSION_APPROVED', approved_at = CURRENT_TIMESTAMP,
                       approval_source = 'OPERATOR_RECOVERY',
                       authorization_expires_at = datetime('now', '+120 minutes'),
                       original_declaration_recovery_attempts = original_declaration_recovery_attempts + 1,
                       error_message = '原创声明界面已操作但回读未确认，且未产生平台回执；已签发一次两小时重试授权。',
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'FAILED' AND uploader_exit_code = 1
                     AND platform_post_id IS NULL AND platform_state IS NULL
                     AND evidence_dir = ?
                     AND original_declaration_recovery_attempts = 0
                     AND (error_message LIKE '%原创声明%' OR error_message LIKE '%Original declaration%')""",
                (clean_id, clean_evidence_dir),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "Only an unpublished original-declaration readback failure can be reopened",
                )
            conn.commit()
            row = conn.execute("SELECT * FROM english_world_review_items WHERE id = ?", (clean_id,)).fetchone()
            return dict(row) if row else {}

    def claim_english_world_login_recovery(self, *, max_age_hours: int = 12) -> Optional[Dict[str, Any]]:
        """领取一条可证明尚未投稿的英语世界登录恢复项。

        仅接受自动策略创建、上传器在登录前返回 ``exit=2`` 的近期项，且同一
        审核项只允许一次。``UNCERTAIN``、已受理、人工审核及历史失败全部保留
        fail-closed，绝不由扫码成功顺带重传。
        """
        safe_age_hours = max(1, min(24, int(max_age_hours)))
        freshness = f"-{safe_age_hours} hours"
        with self.get_connection() as conn:
            candidate = conn.execute(
                """SELECT id FROM english_world_review_items
                   WHERE state = 'LOGIN_REQUIRED'
                     AND approval_source = 'AUTO_POLICY'
                     AND uploader_exit_code = 2
                     AND login_recovery_attempts = 0
                     AND submission_finished_at >= datetime('now', ?)
                   ORDER BY submission_finished_at DESC, id DESC
                   LIMIT 1""",
                (freshness,),
            ).fetchone()
            if not candidate:
                return None
            review_id = str(candidate["id"])
            cursor = conn.execute(
                """UPDATE english_world_review_items
                   SET state = 'SUBMISSION_APPROVED', login_recovery_attempts = login_recovery_attempts + 1,
                       error_message = '视频号登录已恢复；本项此前在登录前失败，已领取一次自动续投。',
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?
                     AND state = 'LOGIN_REQUIRED'
                     AND approval_source = 'AUTO_POLICY'
                     AND uploader_exit_code = 2
                     AND login_recovery_attempts = 0""",
                (review_id,),
            )
            if cursor.rowcount != 1:
                return None
            conn.commit()
            row = conn.execute("SELECT * FROM english_world_review_items WHERE id = ?", (review_id,)).fetchone()
            return dict(row) if row else None

    def get_english_world_login_recovery_candidate(
        self, *, max_age_hours: int = 12,
    ) -> Optional[Dict[str, Any]]:
        """只读返回下一条登录恢复候选，供领取前完成投稿包完整性校验。"""
        safe_age_hours = max(1, min(24, int(max_age_hours)))
        with self.get_connection() as conn:
            row = conn.execute(
                """SELECT * FROM english_world_review_items
                   WHERE state = 'LOGIN_REQUIRED'
                     AND approval_source = 'AUTO_POLICY'
                     AND uploader_exit_code = 2
                     AND login_recovery_attempts = 0
                     AND submission_finished_at >= datetime('now', ?)
                   ORDER BY submission_finished_at DESC, id DESC LIMIT 1""",
                (f"-{safe_age_hours} hours",),
            ).fetchone()
            return dict(row) if row else None

    def complete_english_world_submission(
        self,
        review_id: str,
        *,
        state: str,
        uploader_exit_code: int,
        evidence_dir: Optional[str] = None,
        message: Optional[str] = None,
        attempt_id: Optional[str] = None,
        platform_post_id: Optional[str] = None,
        platform_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """写入一次投稿尝试的保守结果；不把已受理或未确认伪装为公开发布。"""
        target_state = (state or "").strip().upper()
        allowed = {"UNDER_REVIEW", "UNCERTAIN", "LOGIN_REQUIRED", "FAILED"}
        if target_state not in allowed:
            raise ValueError("Invalid English World submission completion state")
        clean_platform_post_id = (platform_post_id or "").strip() or None
        clean_platform_url = (platform_url or "").strip() or None
        if clean_platform_post_id and target_state != "UNDER_REVIEW":
            raise ValueError("English World platform identity requires an accepted submission")
        with self.get_connection() as conn:
            clean_review_id = (review_id or "").strip()
            clean_attempt_id = (attempt_id or "").strip()
            if not clean_attempt_id:
                attempt = conn.execute(
                    """SELECT attempt_id FROM english_world_submission_attempts
                       WHERE review_id = ? AND state = 'SUBMITTING'
                       ORDER BY started_at DESC LIMIT 1""",
                    (clean_review_id,),
                ).fetchone()
                clean_attempt_id = str(attempt["attempt_id"]) if attempt else ""
            if not clean_attempt_id:
                raise ValueError("English World submission attempt is missing")
            cursor = conn.execute(
                """UPDATE english_world_review_items
                   SET state = ?, uploader_exit_code = ?, evidence_dir = ?, error_message = ?,
                       platform_post_id = COALESCE(?, platform_post_id),
                       platform_url = COALESCE(?, platform_url),
                       submission_finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'SUBMITTING'""",
                (
                    target_state, int(uploader_exit_code), (evidence_dir or "").strip() or None,
                    (message or "").strip()[:1000] or None,
                    clean_platform_post_id, clean_platform_url, clean_review_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("English World submission result cannot overwrite the current state")
            attempt_cursor = conn.execute(
                """UPDATE english_world_submission_attempts
                   SET state = ?, uploader_exit_code = ?, evidence_dir = COALESCE(?, evidence_dir),
                       error_message = ?, platform_post_id = COALESCE(?, platform_post_id),
                       platform_url = COALESCE(?, platform_url), finished_at = CURRENT_TIMESTAMP
                   WHERE attempt_id = ? AND review_id = ? AND state = 'SUBMITTING'""",
                (
                    target_state, int(uploader_exit_code), (evidence_dir or "").strip() or None,
                    (message or "").strip()[:1000] or None,
                    clean_platform_post_id, clean_platform_url, clean_attempt_id, clean_review_id,
                ),
            )
            if attempt_cursor.rowcount != 1:
                raise ValueError("English World submission attempt cannot be completed")
            conn.commit()
            row = conn.execute(
                "SELECT * FROM english_world_review_items WHERE id = ?", (clean_review_id,),
            ).fetchone()
            return dict(row) if row else {}

    def bind_english_world_submission_platform_identity(
        self,
        review_id: str,
        *,
        attempt_id: str,
        platform_post_id: str,
        platform_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """把同次提交回执中的原生 ID 绑定到已受理审核项；只允许首次绑定或同 ID 幂等写入。"""
        clean_review_id = (review_id or "").strip()
        clean_attempt_id = (attempt_id or "").strip()
        clean_platform_post_id = (platform_post_id or "").strip()
        clean_platform_url = (platform_url or "").strip() or None
        if not clean_platform_post_id:
            raise ValueError("English World platform_post_id is required")
        with self.get_connection() as conn:
            review = conn.execute(
                """SELECT id, platform_post_id FROM english_world_review_items
                   WHERE id = ? AND state = 'UNDER_REVIEW'""",
                (clean_review_id,),
            ).fetchone()
            if not review:
                raise ValueError("English World review item is not bindable")
            if review["platform_post_id"] not in (None, "", clean_platform_post_id):
                raise ValueError("English World review item is already bound to another platform_post_id")
            existing = conn.execute(
                "SELECT id FROM english_world_review_items WHERE platform_post_id = ?",
                (clean_platform_post_id,),
            ).fetchone()
            if existing and existing["id"] != clean_review_id:
                raise ValueError("English World platform_post_id is already bound")
            attempt = conn.execute(
                """SELECT attempt_id, platform_post_id FROM english_world_submission_attempts
                   WHERE attempt_id = ? AND review_id = ? AND state = 'UNDER_REVIEW'""",
                (clean_attempt_id, clean_review_id),
            ).fetchone()
            if not attempt:
                raise ValueError("English World accepted submission attempt is missing")
            if attempt["platform_post_id"] not in (None, "", clean_platform_post_id):
                raise ValueError("English World submission attempt is already bound to another platform_post_id")
            cursor = conn.execute(
                """UPDATE english_world_review_items
                   SET platform_post_id = ?, platform_url = COALESCE(?, platform_url),
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'UNDER_REVIEW'
                     AND (platform_post_id IS NULL OR platform_post_id = '' OR platform_post_id = ?)""",
                (
                    clean_platform_post_id, clean_platform_url, clean_review_id,
                    clean_platform_post_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("English World review item is not bindable")
            attempt_cursor = conn.execute(
                """UPDATE english_world_submission_attempts
                   SET platform_post_id = ?, platform_url = COALESCE(?, platform_url)
                   WHERE attempt_id = ? AND review_id = ?
                     AND (platform_post_id IS NULL OR platform_post_id = '' OR platform_post_id = ?)""",
                (
                    clean_platform_post_id, clean_platform_url, clean_attempt_id,
                    clean_review_id, clean_platform_post_id,
                ),
            )
            if attempt_cursor.rowcount != 1:
                raise ValueError("English World submission attempt is not bindable")
            conn.commit()
            row = conn.execute(
                "SELECT * FROM english_world_review_items WHERE id = ?", (clean_review_id,),
            ).fetchone()
            return dict(row) if row else {}

    def claim_next_english_world_reconciliation(
        self,
        *,
        min_interval_minutes: int = 30,
        max_age_hours: int = 72,
        failure_limit: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """原子领取一条已绑定审核项做只读回查；节流且绝不产生投稿尝试。"""
        safe_interval = max(5, min(24 * 60, int(min_interval_minutes)))
        safe_max_age = max(1, min(24 * 30, int(max_age_hours)))
        safe_failure_limit = max(1, min(10, int(failure_limit)))
        interval = f"-{safe_interval} minutes"
        max_age = f"-{safe_max_age} hours"
        with self.get_connection() as conn:
            candidate = conn.execute(
                """SELECT id FROM english_world_review_items
                   WHERE state = 'UNDER_REVIEW'
                     AND platform_post_id IS NOT NULL AND platform_post_id != ''
                     AND COALESCE(platform_state, '') NOT IN ('PUBLISHED', 'REJECTED')
                     AND reconciliation_failures < ?
                     AND submission_finished_at >= datetime('now', ?)
                     AND (last_reconciled_at IS NULL OR last_reconciled_at <= datetime('now', ?))
                   ORDER BY COALESCE(last_reconciled_at, submission_finished_at) ASC, id ASC
                   LIMIT 1""",
                (safe_failure_limit, max_age, interval),
            ).fetchone()
            if not candidate:
                return None
            cursor = conn.execute(
                """UPDATE english_world_review_items
                   SET last_reconciled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'UNDER_REVIEW'
                     AND platform_post_id IS NOT NULL AND platform_post_id != ''
                     AND COALESCE(platform_state, '') NOT IN ('PUBLISHED', 'REJECTED')
                     AND reconciliation_failures < ?
                     AND (last_reconciled_at IS NULL OR last_reconciled_at <= datetime('now', ?))""",
                (candidate["id"], safe_failure_limit, interval),
            )
            if cursor.rowcount != 1:
                return None
            conn.commit()
            row = conn.execute(
                "SELECT * FROM english_world_review_items WHERE id = ?", (candidate["id"],),
            ).fetchone()
            return dict(row) if row else None

    def record_english_world_reconciliation(
        self,
        review_id: str,
        *,
        platform_state: str,
        evidence_dir: Optional[str],
        message: str,
        platform_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """记录按原生 ID 得到的平台状态；不重开、不重传，也不覆盖受理事实。"""
        normalized_state = (platform_state or "").strip().upper()
        if normalized_state not in {"PUBLISHED", "UNDER_REVIEW", "REJECTED", "UNCERTAIN", "NOT_FOUND"}:
            raise ValueError("Invalid English World platform state")
        clean_review_id = (review_id or "").strip()
        clean_evidence_dir = (evidence_dir or "").strip() or None
        clean_message = " ".join((message or "").split())[:1000] or None
        clean_platform_url = (platform_url or "").strip() or None
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE english_world_review_items
                   SET platform_state = ?, reconciliation_evidence_dir = ?,
                       reconciliation_error = ?, platform_url = COALESCE(?, platform_url),
                       reconciliation_failures = CASE
                           WHEN ? IN ('UNCERTAIN', 'NOT_FOUND') THEN reconciliation_failures + 1
                           ELSE 0
                       END,
                       last_reconciled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'UNDER_REVIEW' AND platform_post_id IS NOT NULL""",
                (
                    normalized_state, clean_evidence_dir,
                    clean_message if normalized_state in {"UNCERTAIN", "NOT_FOUND"} else None,
                    clean_platform_url, normalized_state, clean_review_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("English World review item cannot be reconciled")
            if clean_message and normalized_state not in {"UNCERTAIN", "NOT_FOUND"}:
                conn.execute(
                    "UPDATE english_world_review_items SET error_message = ? WHERE id = ?",
                    (clean_message, clean_review_id),
                )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM english_world_review_items WHERE id = ?", (clean_review_id,),
            ).fetchone()
            return dict(row) if row else {}

    def list_english_world_submission_attempts(
        self, review_id: str, *, limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """按时间倒序返回不可覆盖的英语世界投稿尝试。"""
        safe_limit = max(1, min(100, int(limit)))
        with self.get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM english_world_submission_attempts
                   WHERE review_id = ? ORDER BY started_at DESC, attempt_id DESC LIMIT ?""",
                ((review_id or "").strip(), safe_limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_next_english_world_douyin_sync_candidate(self) -> Optional[Dict[str, Any]]:
        """读取视频号已受理且抖音建账遗漏的英语世界审核项。"""
        with self.get_connection() as conn:
            row = conn.execute(
                """SELECT review.* FROM english_world_review_items review
                   WHERE review.state = 'UNDER_REVIEW'
                     AND review.platform_post_id IS NOT NULL AND review.platform_post_id != ''
                     AND NOT EXISTS (
                         SELECT 1 FROM english_world_douyin_publications publication
                         WHERE publication.review_id = review.id
                     )
                   ORDER BY review.submission_finished_at ASC, review.id ASC LIMIT 1"""
            ).fetchone()
            return dict(row) if row else None

    def ensure_english_world_douyin_publication(self, review_id: str) -> Dict[str, Any]:
        """为一条视频号已受理审核项建立唯一抖音同步账本；重复调用保持幂等。"""
        clean_review_id = (review_id or "").strip()
        with self.get_connection() as conn:
            review = conn.execute(
                """SELECT id, state, platform_post_id, artifact_sha256
                   FROM english_world_review_items WHERE id = ?""",
                (clean_review_id,),
            ).fetchone()
            if not review:
                raise ValueError("English World review item does not exist")
            if review["state"] != "UNDER_REVIEW" or not str(review["platform_post_id"] or "").strip():
                raise ValueError("English World Douyin sync requires an accepted WeChat submission")
            artifact_sha256 = str(review["artifact_sha256"] or "").strip().lower()
            if len(artifact_sha256) != 64:
                raise ValueError("English World Douyin sync requires an immutable artifact hash")
            conn.execute(
                """INSERT INTO english_world_douyin_publications (review_id, artifact_sha256)
                   VALUES (?, ?) ON CONFLICT(review_id) DO NOTHING""",
                (clean_review_id, artifact_sha256),
            )
            conn.commit()
            row = conn.execute(
                """SELECT publication.*, review.title, review.mp4_path, review.manifest_path,
                          review.title_path, review.copy_path, review.cover_path,
                          review.cover_provenance_path, review.manifest_sha256,
                          review.title_sha256, review.copy_sha256, review.cover_sha256,
                          review.cover_provenance_sha256
                   FROM english_world_douyin_publications publication
                   JOIN english_world_review_items review ON review.id = publication.review_id
                   WHERE publication.review_id = ?""",
                (clean_review_id,),
            ).fetchone()
            return dict(row) if row else {}

    def get_english_world_douyin_publication(self, review_id: str) -> Optional[Dict[str, Any]]:
        """返回一条英语世界抖音同步账本及其不可变投稿包路径。"""
        with self.get_connection() as conn:
            row = conn.execute(
                """SELECT publication.*, review.title, review.mp4_path, review.manifest_path,
                          review.title_path, review.copy_path, review.cover_path,
                          review.cover_provenance_path, review.manifest_sha256,
                          review.title_sha256, review.copy_sha256, review.cover_sha256,
                          review.cover_provenance_sha256
                   FROM english_world_douyin_publications publication
                   JOIN english_world_review_items review ON review.id = publication.review_id
                   WHERE publication.review_id = ?""",
                ((review_id or "").strip(),),
            ).fetchone()
            return dict(row) if row else None

    def authorize_english_world_douyin_pre_submit_recovery(
        self, review_id: str, *, reason: str,
    ) -> Dict[str, Any]:
        """只为一次可证明未提交的首轮页面闸门失败授权一次修复后重试。"""
        clean_review_id = (review_id or "").strip()
        clean_reason = " ".join((reason or "").split())[:500]
        if not clean_reason:
            raise ValueError("English World Douyin recovery requires an explicit reason")
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE english_world_douyin_publications
                   SET state = 'QUEUED', recovery_authorized_at = CURRENT_TIMESTAMP,
                       recovery_reason = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE review_id = ? AND state = 'CANCELED' AND attempt_count = 1
                     AND recovery_authorized_at IS NULL
                     AND COALESCE(last_error_message, '') LIKE '%发布前%'""",
                (clean_reason, clean_review_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Only one proven pre-submit failure can receive Douyin recovery")
            conn.commit()
            return self.get_english_world_douyin_publication(clean_review_id) or {}

    def recover_english_world_douyin_proven_pre_submit_uncertain(
        self, review_id: str, *, reason: str,
    ) -> Dict[str, Any]:
        """将被旧退出码误归类的首轮发布前拒绝受控恢复为一次可重投状态。

        仅接受有原始 ``拒绝发布`` 错误、无 ``submitted_at`` 的首轮 ``UNCERTAIN``：
        这证明浏览器在最终点击前停止，而非“已点发布但平台回执丢失”。原尝试的
        错误文本和证据目录保持不变，仅将其最终分类修正为 ``CANCELED``；新的领取
        仍由既有一次性恢复授权闸门消费，不能由调度器自动触发。
        """
        clean_review_id = (review_id or "").strip()
        clean_reason = " ".join((reason or "").split())[:500]
        if not clean_review_id:
            raise ValueError("English World Douyin review_id is required")
        if not clean_reason:
            raise ValueError("English World Douyin recovery requires an explicit reason")
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            publication = conn.execute(
                """SELECT review_id FROM english_world_douyin_publications
                   WHERE review_id = ? AND state = 'UNCERTAIN' AND attempt_count = 1
                     AND submitted_at IS NULL AND recovery_authorized_at IS NULL
                     AND COALESCE(last_error_message, '') LIKE '%拒绝发布%'""",
                (clean_review_id,),
            ).fetchone()
            attempt = conn.execute(
                """SELECT attempt_id FROM english_world_douyin_attempts
                   WHERE review_id = ? AND state = 'UNCERTAIN' AND uploader_exit_code = 7
                     AND COALESCE(error_message, '') LIKE '%拒绝发布%'
                   ORDER BY started_at ASC, attempt_id ASC LIMIT 1""",
                (clean_review_id,),
            ).fetchone()
            if not publication or not attempt:
                conn.rollback()
                raise ValueError(
                    "Only one proven pre-submit UNCERTAIN English World Douyin attempt can be recovered",
                )
            publication_cursor = conn.execute(
                """UPDATE english_world_douyin_publications
                   SET state = 'QUEUED', recovery_authorized_at = CURRENT_TIMESTAMP,
                       recovery_reason = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE review_id = ? AND state = 'UNCERTAIN' AND attempt_count = 1
                     AND submitted_at IS NULL AND recovery_authorized_at IS NULL""",
                (clean_reason, clean_review_id),
            )
            attempt_cursor = conn.execute(
                """UPDATE english_world_douyin_attempts
                   SET state = 'CANCELED'
                   WHERE attempt_id = ? AND review_id = ? AND state = 'UNCERTAIN'
                     AND uploader_exit_code = 7""",
                (attempt["attempt_id"], clean_review_id),
            )
            if publication_cursor.rowcount != 1 or attempt_cursor.rowcount != 1:
                conn.rollback()
                raise ValueError("English World Douyin pre-submit recovery changed concurrently")
            conn.commit()
            return self.get_english_world_douyin_publication(clean_review_id) or {}

    def claim_english_world_douyin_publication(
        self, review_id: str, *, daily_limit: Optional[int], evidence_dir: str,
    ) -> Optional[Dict[str, Any]]:
        """原子领取一条英语世界抖音同步；配置额度时才与通用 NEW 共享计数。"""
        clean_review_id = (review_id or "").strip()
        safe_limit = int(daily_limit) if daily_limit is not None else None
        if safe_limit is not None and safe_limit < 1:
            return None
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if safe_limit is not None:
                generic_used = conn.execute(
                    """SELECT COUNT(*) AS count FROM douyin_publications
                       WHERE source_kind = 'NEW'
                         AND state IN ('UPLOADING', 'UNDER_REVIEW', 'PUBLISHED', 'UNCERTAIN')
                         AND claimed_at IS NOT NULL
                         AND date(claimed_at, 'localtime') = date('now', 'localtime')"""
                ).fetchone()["count"]
                english_world_used = conn.execute(
                    """SELECT COUNT(*) AS count FROM english_world_douyin_publications
                       WHERE state IN ('SUBMITTING', 'UNDER_REVIEW', 'PUBLISHED', 'UNCERTAIN')
                         AND claimed_at IS NOT NULL
                         AND date(claimed_at, 'localtime') = date('now', 'localtime')"""
                ).fetchone()["count"]
                if int(generic_used) + int(english_world_used) >= safe_limit:
                    conn.commit()
                    return None
            cursor = conn.execute(
                """UPDATE english_world_douyin_publications
                   SET state = 'SUBMITTING', attempt_count = attempt_count + 1,
                       claimed_at = CURRENT_TIMESTAMP, evidence_dir = ?,
                       last_error_message = NULL, recovery_authorized_at = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE review_id = ? AND state = 'QUEUED'
                     AND (attempt_count = 0 OR recovery_authorized_at IS NOT NULL)""",
                ((evidence_dir or "").strip() or None, clean_review_id),
            )
            if cursor.rowcount != 1:
                conn.commit()
                return None
            from uuid import uuid4
            attempt_id = uuid4().hex
            row = conn.execute(
                "SELECT artifact_sha256 FROM english_world_douyin_publications WHERE review_id = ?",
                (clean_review_id,),
            ).fetchone()
            conn.execute(
                """INSERT INTO english_world_douyin_attempts (
                       attempt_id, review_id, artifact_sha256, evidence_dir
                   ) VALUES (?, ?, ?, ?)""",
                (attempt_id, clean_review_id, row["artifact_sha256"], (evidence_dir or "").strip() or None),
            )
            ticket_source = conn.execute(
                """SELECT publication.artifact_sha256, review.mp4_path
                   FROM english_world_douyin_publications publication
                   JOIN english_world_review_items review ON review.id = publication.review_id
                   WHERE publication.review_id = ? AND publication.state = 'SUBMITTING'""",
                (clean_review_id,),
            ).fetchone()
            if not ticket_source:
                conn.rollback()
                return None
            ticket = self._insert_douyin_browser_launch_ticket(
                conn,
                source_type="ENGLISH_WORLD",
                source_ref=attempt_id,
                video_path=str(ticket_source["mp4_path"]),
                asset_sha256=str(ticket_source["artifact_sha256"]),
            )
            conn.commit()
            claimed = self.get_english_world_douyin_publication(clean_review_id)
            return {**(claimed or {}), "_attempt_id": attempt_id, **ticket}

    def complete_english_world_douyin_publication(
        self,
        review_id: str,
        *,
        attempt_id: str,
        state: str,
        uploader_exit_code: int,
        evidence_dir: str,
        message: str,
    ) -> Dict[str, Any]:
        """将一次英语世界抖音投稿保守收口；已受理不等同公开。"""
        target_state = (state or "").strip().upper()
        if target_state not in {
            "UNDER_REVIEW", "LOGIN_REQUIRED", "UNCERTAIN", "CANCELED", "FAILED",
        }:
            raise ValueError("Invalid English World Douyin submission state")
        clean_review_id = (review_id or "").strip()
        clean_attempt_id = (attempt_id or "").strip()
        clean_message = " ".join((message or "").split())[:1000] or None
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE english_world_douyin_publications
                   SET state = ?, evidence_dir = ?, last_error_message = ?,
                       submitted_at = CASE WHEN ? = 'UNDER_REVIEW' THEN CURRENT_TIMESTAMP ELSE submitted_at END,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE review_id = ? AND state = 'SUBMITTING'""",
                (
                    target_state, (evidence_dir or "").strip() or None, clean_message,
                    target_state, clean_review_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("English World Douyin publication cannot be completed")
            attempt_cursor = conn.execute(
                """UPDATE english_world_douyin_attempts
                   SET state = ?, uploader_exit_code = ?, evidence_dir = ?, error_message = ?,
                       finished_at = CURRENT_TIMESTAMP
                   WHERE attempt_id = ? AND review_id = ? AND state = 'SUBMITTING'""",
                (
                    target_state, int(uploader_exit_code), (evidence_dir or "").strip() or None,
                    clean_message, clean_attempt_id, clean_review_id,
                ),
            )
            if attempt_cursor.rowcount != 1:
                raise ValueError("English World Douyin attempt cannot be completed")
            conn.commit()
            return self.get_english_world_douyin_publication(clean_review_id) or {}

    def _cancel_english_world_douyin_pre_launch_failure_in_transaction(
        self,
        conn,
        *,
        review_id: str,
        attempt_id: str,
        ticket_id: str,
        evidence_dir: str,
        message: str,
        uploader_exit_code: Optional[int],
        stale_after_seconds: Optional[int] = None,
    ) -> bool:
        """只在当前英语世界票据从未启动时原子收口，调用方必须已持有写事务。"""
        stale_clause = ""
        ticket_params: list[Any] = [ticket_id, attempt_id, review_id, review_id]
        if stale_after_seconds is not None:
            stale_clause = " AND datetime(ticket.issued_at) <= datetime('now', ?)"
            ticket_params.append(f"-{stale_after_seconds} seconds")
        ticket = conn.execute(
            f'''SELECT ticket.ticket_id
                FROM douyin_browser_launch_tickets ticket
                JOIN english_world_douyin_attempts attempt
                  ON attempt.attempt_id = ticket.source_ref
                JOIN english_world_douyin_publications publication
                  ON publication.review_id = attempt.review_id
                WHERE ticket.ticket_id = ?
                  AND ticket.source_type = 'ENGLISH_WORLD'
                  AND ticket.action_scope = 'publish'
                  AND ticket.source_ref = ?
                  AND ticket.launch_started_at IS NULL
                  AND ticket.prelaunch_canceled_at IS NULL
                  AND attempt.review_id = ? AND attempt.state = 'SUBMITTING'
                  AND publication.review_id = ? AND publication.state = 'SUBMITTING'
                  {stale_clause}''',
            ticket_params,
        ).fetchone()
        if not ticket:
            return False
        if not self._cancel_unstarted_douyin_browser_ticket(conn, ticket_id, message):
            return False
        publication_cursor = conn.execute(
            '''UPDATE english_world_douyin_publications
               SET state = 'CANCELED', evidence_dir = ?, last_error_message = ?,
                   updated_at = CURRENT_TIMESTAMP
               WHERE review_id = ? AND state = 'SUBMITTING' ''',
            (evidence_dir or None, message, review_id),
        )
        if publication_cursor.rowcount != 1:
            return False
        attempt_cursor = conn.execute(
            '''UPDATE english_world_douyin_attempts
               SET state = 'CANCELED', uploader_exit_code = ?, evidence_dir = ?,
                   error_message = ?, finished_at = CURRENT_TIMESTAMP
               WHERE attempt_id = ? AND review_id = ? AND state = 'SUBMITTING' ''',
            (uploader_exit_code, evidence_dir or None, message, attempt_id, review_id),
        )
        return attempt_cursor.rowcount == 1

    def cancel_english_world_douyin_pre_launch_failure(
        self,
        review_id: str,
        *,
        attempt_id: str,
        ticket_id: str,
        evidence_dir: str,
        message: str,
    ) -> Optional[Dict[str, Any]]:
        """收口本进程已确认未启动浏览器的英语世界投稿失败。

        票据、尝试和发布账本必须仍是同一个 ``SUBMITTING`` 领取，且 ticket 未写入
        ``launch_started_at``；否则返回 ``None``，调用方不得把可能已执行的投稿降级为
        可恢复取消。
        """
        clean_review_id = (review_id or "").strip()
        clean_attempt_id = (attempt_id or "").strip()
        clean_ticket_id = (ticket_id or "").strip()
        detail = " ".join((message or "").split())[:850]
        if not clean_review_id or not clean_attempt_id or not clean_ticket_id:
            return None
        audit_message = (
            "发布前浏览器未启动；"
            f"{detail or '投稿包准备或子进程启动失败'}。未确认提交，禁止自动重投。"
        )[:1000]
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            canceled = self._cancel_english_world_douyin_pre_launch_failure_in_transaction(
                conn,
                review_id=clean_review_id,
                attempt_id=clean_attempt_id,
                ticket_id=clean_ticket_id,
                evidence_dir=(evidence_dir or "").strip(),
                message=audit_message,
                uploader_exit_code=1,
            )
            if not canceled:
                conn.rollback()
                return None
            conn.commit()
        return self.get_english_world_douyin_publication(clean_review_id)

    def cancel_stale_english_world_douyin_pre_launch_failure(
        self,
        review_id: str,
        *,
        stale_after_seconds: int,
        evidence_dir: str,
    ) -> Optional[Dict[str, Any]]:
        """回收进程中断遗留的未启动英语世界票据；只收口为 CANCELED。

        该入口不创建新尝试也不转回 ``QUEUED``。超过 TTL 仅说明原 worker 已失去
        启动机会；后续仍必须经既有具名恢复入口重新授权。
        """
        clean_review_id = (review_id or "").strip()
        safe_ttl = max(1, min(24 * 60 * 60, int(stale_after_seconds)))
        if not clean_review_id:
            return None
        audit_message = (
            f"发布前浏览器未启动超过 {safe_ttl} 秒；投稿进程可能在启动上传器前中断。"
            "未确认提交，禁止自动重投。"
        )
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            candidate = conn.execute(
                '''SELECT attempt.attempt_id, ticket.ticket_id
                   FROM english_world_douyin_publications publication
                   JOIN english_world_douyin_attempts attempt
                     ON attempt.review_id = publication.review_id
                   JOIN douyin_browser_launch_tickets ticket
                     ON ticket.source_type = 'ENGLISH_WORLD'
                    AND ticket.source_ref = attempt.attempt_id
                   WHERE publication.review_id = ?
                     AND publication.state = 'SUBMITTING'
                     AND attempt.state = 'SUBMITTING'
                     AND ticket.action_scope = 'publish'
                     AND ticket.launch_started_at IS NULL
                     AND ticket.prelaunch_canceled_at IS NULL
                     AND datetime(ticket.issued_at) <= datetime('now', ?)
                   ORDER BY ticket.issued_at ASC, ticket.ticket_id ASC
                   LIMIT 1''',
                (clean_review_id, f"-{safe_ttl} seconds"),
            ).fetchone()
            if not candidate:
                conn.rollback()
                return None
            canceled = self._cancel_english_world_douyin_pre_launch_failure_in_transaction(
                conn,
                review_id=clean_review_id,
                attempt_id=str(candidate["attempt_id"]),
                ticket_id=str(candidate["ticket_id"]),
                evidence_dir=(evidence_dir or "").strip(),
                message=audit_message,
                uploader_exit_code=None,
                stale_after_seconds=safe_ttl,
            )
            if not canceled:
                conn.rollback()
                return None
            conn.commit()
        return self.get_english_world_douyin_publication(clean_review_id)

    def record_english_world_douyin_reconciliation(
        self,
        review_id: str,
        *,
        platform_state: str,
        evidence_dir: str,
        message: str,
    ) -> Dict[str, Any]:
        """写入按完整标题/文案得到的抖音管理页状态；只有 PUBLISHED 才落公开终态。"""
        observed = (platform_state or "").strip().upper()
        if observed not in {"PUBLISHED", "UNDER_REVIEW", "UNCERTAIN"}:
            raise ValueError("Invalid English World Douyin reconciliation state")
        next_state = "PUBLISHED" if observed == "PUBLISHED" else "UNDER_REVIEW"
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE english_world_douyin_publications
                   SET state = ?, platform_state = ?, evidence_dir = ?, last_error_message = ?,
                       reconciliation_failures = CASE WHEN ? = 'UNCERTAIN'
                           THEN reconciliation_failures + 1 ELSE 0 END,
                       last_reconciled_at = CURRENT_TIMESTAMP,
                       published_at = CASE WHEN ? = 'PUBLISHED'
                           THEN COALESCE(published_at, CURRENT_TIMESTAMP) ELSE published_at END,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE review_id = ? AND state = 'UNDER_REVIEW'""",
                (
                    next_state, observed, (evidence_dir or "").strip() or None,
                    " ".join((message or "").split())[:1000] or None,
                    observed, observed, (review_id or "").strip(),
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("English World Douyin publication cannot be reconciled")
            if observed == "PUBLISHED":
                conn.execute(
                    """UPDATE english_world_douyin_attempts
                       SET state = 'PUBLISHED'
                       WHERE review_id = ? AND state = 'UNDER_REVIEW'""",
                    ((review_id or "").strip(),),
                )
            conn.commit()
            return self.get_english_world_douyin_publication(review_id) or {}

    def record_english_world_douyin_canceled_published_reconciliation(
        self,
        review_id: str,
        *,
        evidence_dir: str,
        message: str,
    ) -> Dict[str, Any]:
        """凭作品管理页已发布证据修正取消账本，绝不覆盖原始投稿尝试。

        此入口只处理“提交前闸门曾判定 CANCELED，但之后由外部操作或平台异步完成
        投稿”的稀有分叉。它必须由人工/管理页精确匹配调用，且必须携带证据目录；
        调度器的常规审核回查不调用本方法。原先 ``CANCELED`` 的 attempts 保持原样，
        防止将未确认提交历史伪造成成功回执。
        """
        clean_review_id = (review_id or "").strip()
        clean_evidence_dir = (evidence_dir or "").strip()
        clean_message = " ".join((message or "").split())[:1000]
        if not clean_review_id:
            raise ValueError("English World Douyin review_id is required")
        if not clean_evidence_dir:
            raise ValueError("English World canceled reconciliation requires evidence_dir")
        if not clean_message:
            raise ValueError("English World canceled reconciliation requires message")
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE english_world_douyin_publications
                   SET state = 'PUBLISHED', platform_state = 'PUBLISHED', evidence_dir = ?,
                       last_error_message = ?, reconciliation_failures = 0,
                       last_reconciled_at = CURRENT_TIMESTAMP,
                       published_at = COALESCE(published_at, CURRENT_TIMESTAMP),
                       updated_at = CURRENT_TIMESTAMP
                   WHERE review_id = ? AND state = 'CANCELED' AND attempt_count > 0""",
                (clean_evidence_dir, clean_message, clean_review_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Only an attempted CANCELED English World Douyin publication can be reconciled")
            conn.commit()
            return self.get_english_world_douyin_publication(clean_review_id) or {}

    def claim_next_english_world_douyin_reconciliation(
        self, *, min_interval_minutes: int = 30, failure_limit: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """节流领取一条英语世界抖音审核中记录做只读管理页回查。"""
        safe_interval = max(5, min(24 * 60, int(min_interval_minutes)))
        safe_failure_limit = max(1, min(10, int(failure_limit)))
        interval = f"-{safe_interval} minutes"
        with self.get_connection() as conn:
            candidate = conn.execute(
                """SELECT review_id FROM english_world_douyin_publications
                   WHERE state = 'UNDER_REVIEW' AND reconciliation_failures < ?
                     AND (last_reconciled_at IS NULL OR last_reconciled_at <= datetime('now', ?))
                   ORDER BY COALESCE(last_reconciled_at, submitted_at) ASC, id ASC LIMIT 1""",
                (safe_failure_limit, interval),
            ).fetchone()
            if not candidate:
                return None
            cursor = conn.execute(
                """UPDATE english_world_douyin_publications
                   SET last_reconciled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                   WHERE review_id = ? AND state = 'UNDER_REVIEW'
                     AND reconciliation_failures < ?
                     AND (last_reconciled_at IS NULL OR last_reconciled_at <= datetime('now', ?))""",
                (candidate["review_id"], safe_failure_limit, interval),
            )
            if cursor.rowcount != 1:
                return None
            conn.commit()
            return self.get_english_world_douyin_publication(str(candidate["review_id"]))

    def list_english_world_douyin_attempts(
        self, review_id: str, *, limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """按时间倒序返回英语世界抖音不可变投稿尝试。"""
        with self.get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM english_world_douyin_attempts
                   WHERE review_id = ? ORDER BY started_at DESC, attempt_id DESC LIMIT ?""",
                ((review_id or "").strip(), max(1, min(100, int(limit)))),
            ).fetchall()
            return [dict(row) for row in rows]

    def hold_english_world_review_item(self, review_id: str) -> Dict[str, Any]:
        """将待审核学习卡显式搁置；搁置后任何按钮都不能自动提交。"""
        clean_id = (review_id or "").strip()
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE english_world_review_items
                   SET state = 'HELD', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'READY_FOR_REVIEW'""",
                (clean_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("English World review item cannot be held from its current state")
            conn.commit()
            row = conn.execute("SELECT * FROM english_world_review_items WHERE id = ?", (clean_id,)).fetchone()
            return dict(row) if row else {}

    def list_english_world_review_items(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        """读取最近审核/投稿回执；只读，不触发 worker 或任何平台动作。"""
        safe_limit = max(1, min(100, int(limit)))
        with self.get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM english_world_review_items
                   ORDER BY updated_at DESC, id DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def record_telegram_notification_receipt(
        self,
        *,
        event_type: str,
        priority: str,
        content_sha256: str,
        delivery_state: str,
        telegram_message_id: Optional[str] = None,
        error_kind: Optional[str] = None,
    ) -> Dict[str, Any]:
        """记录 Telegram API 投递结果；不把 API 接受等同于用户设备已读。"""
        allowed_priorities = {"P0", "P1", "P2"}
        allowed_states = {"ACCEPTED", "UNKNOWN", "FAILED", "SUPPRESSED"}
        if priority not in allowed_priorities:
            raise ValueError(f"Invalid Telegram notification priority: {priority}")
        if delivery_state not in allowed_states:
            raise ValueError(f"Invalid Telegram notification delivery state: {delivery_state}")
        with self.get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO telegram_notification_receipts
                   (event_type, priority, content_sha256, delivery_state, telegram_message_id, error_kind)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    (event_type or "unknown")[:120],
                    priority,
                    (content_sha256 or "")[:128],
                    delivery_state,
                    (telegram_message_id or "")[:80] or None,
                    (error_kind or "")[:120] or None,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM telegram_notification_receipts WHERE id = ?", (cursor.lastrowid,),
            ).fetchone()
            return dict(row) if row else {}

    def has_recent_telegram_notification(
        self, *, event_type: str, content_sha256: str, since_utc: str,
    ) -> bool:
        """查询近期已获 API 回执的同一通知；UNKNOWN 不得当作送达。"""
        with self.get_connection() as conn:
            row = conn.execute(
                """SELECT 1 FROM telegram_notification_receipts
                   WHERE event_type = ? AND content_sha256 = ? AND created_at >= ?
                     AND delivery_state = 'ACCEPTED'
                   LIMIT 1""",
                ((event_type or "unknown")[:120], (content_sha256 or "")[:128], since_utc),
            ).fetchone()
            return row is not None

    # --- Dubbing studio DAL (manual-only, isolated from PipelineManager) ---
    _DUBBING_STATES = {
        "DRAFT", "ANALYZING", "SCRIPT_READY", "SYNTHESIZING", "ALIGNING", "RENDERING",
        "QA_REQUIRED", "READY_TO_PUBLISH", "PUBLISHING", "UNDER_REVIEW", "PUBLISHED",
        "NEEDS_REWRITE", "FAILED", "CANCELED",
    }
    _DUBBING_PUBLICATION_STATES = {
        "QUEUED", "UPLOADING", "DRAFT", "UNDER_REVIEW", "PUBLISHED",
        "RETRYABLE_FAILED", "UNCERTAIN", "BANNED", "CANCELED",
    }
    _DUBBING_PLATFORMS = {"wechat", "douyin", "kuaishou"}

    def create_dubbing_job(
        self,
        youtube_id: str,
        *,
        slice_index: int = 0,
        provider: str = "minimax",
        model: str,
        voice_id: str,
        requested_platforms: Sequence[str] = (),
        config: Optional[Dict[str, Any]] = None,
        force_new_version: bool = False,
    ) -> Dict[str, Any]:
        """人工为已发布源片创建配音再制任务；绝不修改源片记录。"""
        platforms = sorted({str(platform).lower() for platform in requested_platforms})
        if any(platform not in self._DUBBING_PLATFORMS for platform in platforms):
            raise ValueError("requested_platforms contains unsupported platform")
        if provider not in {"minimax", "volc_speech"}:
            raise ValueError("provider is unsupported")
        if not model.strip() or not voice_id.strip():
            raise ValueError("model and voice_id are required")
        with self.get_connection() as conn:
            source = conn.execute(
                "SELECT id, status FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            if not source:
                raise ValueError("Source video or slice does not exist")
            if source["status"] != "PUBLISHED":
                raise ValueError("Only platform-published source videos can enter dubbing")
            latest = conn.execute(
                "SELECT * FROM dubbing_jobs WHERE source_video_id = ? ORDER BY version DESC LIMIT 1",
                (source["id"],),
            ).fetchone()
            if latest and not force_new_version:
                return dict(latest)
            version = (int(latest["version"]) + 1) if latest else 1
            conn.execute(
                """INSERT INTO dubbing_jobs
                   (source_video_id, version, provider, model, voice_id, requested_platforms, config_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (source["id"], version, provider, model, voice_id, json.dumps(platforms, ensure_ascii=False),
                 json.dumps(config or {}, ensure_ascii=False, sort_keys=True)),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM dubbing_jobs WHERE source_video_id = ? AND version = ?", (source["id"], version)).fetchone()
            if not row:
                raise RuntimeError("Failed to create dubbing job")
            return dict(row)

    def get_dubbing_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        """返回再制任务及只读源片标识。"""
        with self.get_connection() as conn:
            row = conn.execute(
                """SELECT dj.*, pv.youtube_id, pv.slice_index, pv.title AS source_title,
                          pv.zh_title AS source_zh_title,
                          pv.upload_date AS source_upload_date,
                          pv.status AS source_status
                   FROM dubbing_jobs dj JOIN processed_videos pv ON pv.id = dj.source_video_id
                   WHERE dj.id = ?""",
                (job_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_dubbing_job_by_source(self, youtube_id: str, *, slice_index: int = 0) -> Optional[Dict[str, Any]]:
        """按源片取最新再制版本，便于人工 status/publish 命令恢复任务。"""
        with self.get_connection() as conn:
            row = conn.execute(
                """SELECT dj.*, pv.youtube_id, pv.slice_index, pv.title AS source_title,
                          pv.zh_title AS source_zh_title,
                          pv.upload_date AS source_upload_date,
                          pv.status AS source_status
                   FROM dubbing_jobs dj JOIN processed_videos pv ON pv.id = dj.source_video_id
                   WHERE pv.youtube_id = ? AND pv.slice_index = ?
                   ORDER BY dj.version DESC LIMIT 1""",
                (youtube_id, slice_index),
            ).fetchone()
            return dict(row) if row else None

    def update_dubbing_job(self, job_id: int, state: str, **fields: Any) -> None:
        """更新独立再制任务状态和产物指针，禁止写入未知列。"""
        normalized = (state or "").upper()
        if normalized not in self._DUBBING_STATES:
            raise ValueError(f"Unsupported dubbing state: {state}")
        allowed = {
            "workspace_path", "narration_path", "subtitle_path", "output_video_path",
            "qa_report_path", "asset_sha256", "error_message",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unsupported dubbing fields: {sorted(unknown)}")
        assignments = ["state = ?", "updated_at = CURRENT_TIMESTAMP"]
        values: List[Any] = [normalized]
        for key, value in fields.items():
            assignments.append(f"{key} = ?")
            values.append(value)
        values.append(job_id)
        with self.get_connection() as conn:
            cursor = conn.execute(f"UPDATE dubbing_jobs SET {', '.join(assignments)} WHERE id = ?", values)
            if cursor.rowcount != 1:
                raise ValueError("Dubbing job does not exist")
            conn.commit()

    def replace_dubbing_utterances(self, job_id: int, utterances: Sequence[Dict[str, Any]]) -> None:
        """原子替换一个任务的配音片段时间线；调用方不得执行原始 SQL。"""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM dubbing_utterances WHERE job_id = ?", (job_id,))
            for ordinal, item in enumerate(utterances):
                conn.execute(
                    """INSERT INTO dubbing_utterances
                    (job_id, ordinal, speaker_key, source_start_ms, source_end_ms, source_text, zh_text,
                     actual_start_ms, actual_end_ms, actual_duration_ms, speed, alignment_strategy,
                     synthesis_attempts, cache_key)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        job_id, ordinal, item.get("speaker_key", "NARRATOR"), int(item["source_start_ms"]),
                        int(item["source_end_ms"]), item.get("source_text", ""), item["zh_text"],
                        item.get("actual_start_ms"), item.get("actual_end_ms"), item.get("actual_duration_ms"),
                        item.get("speed"), item.get("alignment_strategy"), int(item.get("synthesis_attempts", 0)),
                        item.get("cache_key"),
                    ),
                )
            conn.commit()

    def upsert_dubbing_speaker(
        self, job_id: int, speaker_key: str, *, voice_id: str, mapping_source: str = "DEFAULT",
        confidence: Optional[float] = None,
    ) -> None:
        """记录当前视频内的说话人音色映射；P1 单人任务固定为 NARRATOR。"""
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO dubbing_speakers (job_id, speaker_key, voice_id, mapping_source, confidence)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(job_id, speaker_key) DO UPDATE SET
                     voice_id=excluded.voice_id, mapping_source=excluded.mapping_source,
                     confidence=excluded.confidence, updated_at=CURRENT_TIMESTAMP""",
                (job_id, speaker_key, voice_id, mapping_source, confidence),
            )
            conn.commit()

    def get_dubbing_speakers(self, job_id: int) -> List[Dict[str, Any]]:
        """返回任务内说话人映射，跨视频不共享身份。"""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM dubbing_speakers WHERE job_id = ? ORDER BY speaker_key ASC", (job_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_dubbing_utterances(self, job_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM dubbing_utterances WHERE job_id = ? ORDER BY ordinal ASC", (job_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def upsert_dubbing_artifact(
        self, job_id: int, artifact_kind: str, path: str, *, sha256: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录可追溯产物；路径与哈希仅属于再制版本。"""
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO dubbing_artifacts (job_id, artifact_kind, path, sha256, metadata_json)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(job_id, artifact_kind) DO UPDATE SET
                     path=excluded.path, sha256=excluded.sha256, metadata_json=excluded.metadata_json,
                     created_at=CURRENT_TIMESTAMP""",
                (job_id, artifact_kind, path, sha256, json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)),
            )
            conn.commit()

    def get_dubbing_artifacts(self, job_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM dubbing_artifacts WHERE job_id = ? ORDER BY id ASC", (job_id,)).fetchall()
            return [dict(row) for row in rows]

    def update_dubbing_publication(
        self, job_id: int, platform: str, state: str, *, error_message: Optional[str] = None,
        external_url: Optional[str] = None, external_post_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """登记一次显式投递的状态；任何平台终态均不回写源视频。"""
        platform = (platform or "").lower()
        state = (state or "").upper()
        if platform not in self._DUBBING_PLATFORMS or state not in self._DUBBING_PUBLICATION_STATES:
            raise ValueError("Unsupported dubbing publication platform or state")
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO dubbing_publications
                   (job_id, platform, state, attempt_count, last_error_message, external_url, external_post_id)
                   VALUES (?, ?, ?, 1, ?, ?, ?)
                   ON CONFLICT(job_id, platform) DO UPDATE SET
                     state=excluded.state, attempt_count=dubbing_publications.attempt_count + 1,
                     last_error_message=excluded.last_error_message, external_url=excluded.external_url,
                     external_post_id=excluded.external_post_id, updated_at=CURRENT_TIMESTAMP""",
                (job_id, platform, state, error_message, external_url, external_post_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM dubbing_publications WHERE job_id = ? AND platform = ?", (job_id, platform)
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to update dubbing publication")
            return dict(row)

    def claim_dubbing_douyin_publication_launch(
        self,
        job_id: int,
        *,
        payload_sha256: str,
    ) -> Optional[Dict[str, Any]]:
        """原子领取一条配音抖音上传并签发一次性浏览器启动凭据。"""
        normalized_payload = str(payload_sha256 or "").strip().lower()
        if not self._is_sha256_digest(normalized_payload):
            return None
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            job = conn.execute(
                """SELECT id, state, output_video_path, asset_sha256
                   FROM dubbing_jobs WHERE id = ?""",
                (job_id,),
            ).fetchone()
            if not job:
                conn.commit()
                return None
            job_data = dict(job)
            canonical_path = self._canonical_douyin_launch_path(
                str(job_data.get("output_video_path") or "")
            )
            asset_sha256 = str(job_data.get("asset_sha256") or "").strip().lower()
            if (
                job_data.get("state") != "PUBLISHING"
                or not canonical_path
                or not self._is_sha256_digest(asset_sha256)
            ):
                conn.commit()
                return None
            existing = conn.execute(
                "SELECT * FROM dubbing_publications WHERE job_id = ? AND platform = 'douyin'",
                (job_id,),
            ).fetchone()
            if existing:
                existing_data = dict(existing)
                if existing_data.get("state") not in {"QUEUED", "RETRYABLE_FAILED", "CANCELED"}:
                    conn.commit()
                    return None
                cursor = conn.execute(
                    '''UPDATE dubbing_publications
                       SET state = 'UPLOADING', attempt_count = attempt_count + 1,
                           last_error_message = NULL, external_url = NULL,
                           external_post_id = NULL, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND state IN ('QUEUED', 'RETRYABLE_FAILED', 'CANCELED')''',
                    (existing_data["id"],),
                )
                if cursor.rowcount != 1:
                    conn.commit()
                    return None
                publication_id = int(existing_data["id"])
            else:
                cursor = conn.execute(
                    '''INSERT INTO dubbing_publications (
                           job_id, platform, state, attempt_count
                       ) VALUES (?, 'douyin', 'UPLOADING', 1)''',
                    (job_id,),
                )
                publication_id = int(cursor.lastrowid)
            publication = conn.execute(
                "SELECT * FROM dubbing_publications WHERE id = ?", (publication_id,)
            ).fetchone()
            if not publication:
                conn.rollback()
                return None
            publication_data = dict(publication)
            ticket = self._insert_douyin_browser_launch_ticket(
                conn,
                source_type="DUBBING",
                source_ref=self._douyin_launch_source_ref(
                    publication_data["id"], publication_data["attempt_count"],
                ),
                video_path=canonical_path,
                asset_sha256=asset_sha256,
                payload_sha256=normalized_payload,
            )
            conn.commit()
            return {**publication_data, **ticket}

    def complete_dubbing_douyin_publication_launch(
        self,
        publication_id: int,
        state: str,
        *,
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """收口一次已领取的配音抖音尝试，不再次增加 attempt_count。"""
        target_state = str(state or "").strip().upper()
        allowed_states = {
            "UNDER_REVIEW", "PUBLISHED", "RETRYABLE_FAILED", "UNCERTAIN", "BANNED", "CANCELED",
        }
        if target_state not in allowed_states:
            raise ValueError("Unsupported dubbing Douyin launch completion state")
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            publication = conn.execute(
                "SELECT * FROM dubbing_publications WHERE id = ? AND platform = 'douyin'",
                (publication_id,),
            ).fetchone()
            if not publication:
                conn.commit()
                raise ValueError("Dubbing Douyin publication does not exist")
            publication_data = dict(publication)
            if publication_data.get("state") != "UPLOADING":
                conn.commit()
                raise ValueError("Dubbing Douyin publication is not an active launch")
            source_ref = self._douyin_launch_source_ref(
                publication_data["id"], publication_data["attempt_count"],
            )
            ticket = conn.execute(
                '''SELECT launch_started_at FROM douyin_browser_launch_tickets
                   WHERE source_type = 'DUBBING' AND source_ref = ?''',
                (source_ref,),
            ).fetchone()
            # ticket 未启动时只允许收口为 CANCELED：这表示 guard 在浏览器前拒绝，
            # 绝不能伪装成已提交/未确认。
            if not ticket or (ticket["launch_started_at"] is None and target_state != "CANCELED"):
                conn.commit()
                raise ValueError("Dubbing Douyin browser launch was not started")
            cursor = conn.execute(
                '''UPDATE dubbing_publications
                   SET state = ?, last_error_message = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND platform = 'douyin' AND state = 'UPLOADING' ''',
                (target_state, error_message, publication_id),
            )
            if cursor.rowcount != 1:
                conn.commit()
                raise ValueError("Dubbing Douyin publication cannot be completed")
            conn.commit()
            row = conn.execute(
                "SELECT * FROM dubbing_publications WHERE id = ?", (publication_id,)
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to read completed Dubbing Douyin publication")
            return dict(row)

    def get_dubbing_publications(self, job_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM dubbing_publications WHERE job_id = ? ORDER BY platform ASC", (job_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def correct_dubbing_publication_state(
        self, job_id: int, platform: str, state: str, *, error_message: Optional[str] = None,
        external_url: Optional[str] = None, external_post_id: Optional[str] = None,
        attempt_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """人工校正已存在投递记录；不增加 attempt_count，不代表重新上传。"""
        platform = (platform or "").lower()
        state = (state or "").upper()
        if platform not in self._DUBBING_PLATFORMS or state not in self._DUBBING_PUBLICATION_STATES:
            raise ValueError("Unsupported dubbing publication platform or state")
        if attempt_count is not None and attempt_count < 0:
            raise ValueError("attempt_count must be non-negative")
        with self.get_connection() as conn:
            conn.execute(
                """UPDATE dubbing_publications
                   SET state = ?, attempt_count = COALESCE(?, attempt_count), last_error_message = ?,
                       external_url = COALESCE(?, external_url),
                       external_post_id = COALESCE(?, external_post_id), updated_at = CURRENT_TIMESTAMP
                   WHERE job_id = ? AND platform = ?""",
                (state, attempt_count, error_message, external_url, external_post_id, job_id, platform),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM dubbing_publications WHERE job_id = ? AND platform = ?", (job_id, platform)
            ).fetchone()
            if not row:
                raise ValueError("Dubbing publication does not exist")
            return dict(row)

    # --- Kuaishou browser publication DAL ---
    _KUAISHOU_STATES = {
        "QUEUED", "UPLOADING", "DRAFT", "UNDER_REVIEW", "PUBLISHED",
        "RETRYABLE_FAILED", "UNCERTAIN", "BANNED", "CANCELED",
    }
    _KUAISHOU_SOURCES = {"HISTORY", "NEW"}
    _DOUYIN_STATES = _KUAISHOU_STATES
    _DOUYIN_SOURCES = _KUAISHOU_SOURCES
    _BACKFILL_SPEECH_TERMS = (
        "访谈", "采访", "专访", "演讲", "讲座", "对谈", "圆桌", "炉边谈话",
        "interview", "full interview", "speech", "full speech", "lecture",
        "keynote", "panel discussion", "conversation", "fireside chat",
        "remarks", "address",
    )

    def create_kuaishou_publication(
        self,
        youtube_id: str,
        asset_sha256: str,
        video_path: str,
        *,
        source_kind: str,
        slice_index: int = 0,
    ) -> Dict[str, Any]:
        """登记一次快手投递尝试；已在途、审核或确认发布的同源/同成片均不得重投。"""
        source = (source_kind or "").upper()
        if source not in self._KUAISHOU_SOURCES:
            raise ValueError(f"Unsupported Kuaishou source kind: {source_kind}")
        if len(asset_sha256) != 64:
            raise ValueError("asset_sha256 must be a SHA-256 hex digest")
        with self.get_connection() as conn:
            video = conn.execute(
                "SELECT id FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            if not video:
                raise ValueError("Video or slice does not exist")
            protected = conn.execute(
                '''
                SELECT * FROM kuaishou_publications
                WHERE state IN ('QUEUED', 'UPLOADING', 'UNDER_REVIEW', 'UNCERTAIN', 'PUBLISHED')
                  AND (video_id = ? OR asset_sha256 = ?)
                ORDER BY CASE WHEN video_id = ? THEN 0 ELSE 1 END, id DESC
                LIMIT 1
                ''',
                (video["id"], asset_sha256, video["id"]),
            ).fetchone()
            if protected:
                return dict(protected)
            next_attempt = conn.execute(
                "SELECT COALESCE(MAX(attempt_number), 0) + 1 AS number FROM kuaishou_publications WHERE video_id = ?",
                (video["id"],),
            ).fetchone()["number"]
            conn.execute(
                '''
                INSERT INTO kuaishou_publications (
                    video_id, asset_sha256, source_kind, video_path, attempt_number
                ) VALUES (?, ?, ?, ?, ?)
                ''',
                (video["id"], asset_sha256, source, video_path, next_attempt),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM kuaishou_publications WHERE video_id = ? AND attempt_number = ?",
                (video["id"], next_attempt),
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to create Kuaishou publication")
            return dict(row)

    def get_kuaishou_publication(self, youtube_id: str, slice_index: int = 0) -> Optional[Dict[str, Any]]:
        """按原视频/切片查询快手发布记录。"""
        with self.get_connection() as conn:
            row = conn.execute(
                '''
                SELECT kp.*, pv.youtube_id, pv.slice_index
                FROM kuaishou_publications kp
                JOIN processed_videos pv ON pv.id = kp.video_id
                WHERE pv.youtube_id = ? AND pv.slice_index = ?
                ORDER BY kp.attempt_number DESC, kp.id DESC LIMIT 1
                ''',
                (youtube_id, slice_index),
            ).fetchone()
            return dict(row) if row else None

    def get_kuaishou_publications_by_states(self, states: Collection[str]) -> List[Dict[str, Any]]:
        """按状态返回快手发布账本，包含原视频标识，供审核回查任务使用。"""
        normalized_states = [str(state or "").upper() for state in states]
        if not normalized_states or any(state not in self._KUAISHOU_STATES for state in normalized_states):
            raise ValueError("states must contain supported Kuaishou states")
        placeholders = ", ".join("?" for _ in normalized_states)
        with self.get_connection() as conn:
            rows = conn.execute(
                f'''\
                SELECT kp.*, pv.youtube_id, pv.slice_index
                FROM kuaishou_publications kp
                JOIN processed_videos pv ON pv.id = kp.video_id
                WHERE kp.state IN ({placeholders})
                ORDER BY kp.updated_at ASC, kp.id ASC
                ''',
                normalized_states,
            ).fetchall()
            return [dict(row) for row in rows]

    def get_unqueued_kuaishou_history_videos(self, limit: int = 20) -> List[Dict[str, Any]]:
        """返回微信已发布、尚未登记快手账本且未被拉黑的历史视频。

        文件是否仍在本地由上层检查；此方法只负责从数据库给出合规候选，避免业务层直接写 SQL。
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        with self.get_connection() as conn:
            rows = conn.execute(
                '''
                SELECT pv.*
                FROM processed_videos pv
                WHERE pv.status = 'PUBLISHED'
                  AND pv.youtube_id NOT IN (SELECT youtube_id FROM blacklisted_videos)
                  AND NOT EXISTS (
                      SELECT 1 FROM kuaishou_publications kp WHERE kp.video_id = pv.id
                  )
                ORDER BY pv.updated_at ASC, pv.id ASC
                LIMIT ?
                ''',
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def claim_next_kuaishou_publication(
        self,
        source_kind: str,
        *,
        daily_limit: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """原子领取同一来源的一条可重试快手任务。

        HISTORY 必须提供 daily_limit；NEW 不受历史迁移配额限制，保证新片可同步投递。
        """
        source = (source_kind or "").upper()
        if source not in self._KUAISHOU_SOURCES:
            raise ValueError(f"Unsupported Kuaishou source kind: {source_kind}")
        if source == "HISTORY" and (daily_limit is None or daily_limit < 1):
            raise ValueError("daily_limit must be at least 1 for HISTORY")
        with self.get_connection() as conn:
            if source == "HISTORY":
                used = conn.execute(
                    '''
                    SELECT COUNT(*) AS count FROM kuaishou_publications
                    WHERE source_kind = 'HISTORY'
                      AND state IN ('UPLOADING', 'UNDER_REVIEW', 'PUBLISHED', 'UNCERTAIN')
                      AND claimed_at IS NOT NULL
                      AND date(claimed_at, 'localtime') = date('now', 'localtime')
                    '''
                ).fetchone()["count"]
                if used >= daily_limit:
                    return None
            candidate = conn.execute(
                '''
                SELECT kp.*, pv.youtube_id, pv.slice_index
                FROM kuaishou_publications kp
                JOIN processed_videos pv ON pv.id = kp.video_id
                WHERE kp.source_kind = ? AND kp.state IN ('QUEUED', 'RETRYABLE_FAILED')
                  AND (kp.claimed_at IS NULL OR date(kp.claimed_at, 'localtime') < date('now', 'localtime'))
                ORDER BY kp.created_at ASC, kp.id ASC LIMIT 1
                ''',
                (source,),
            ).fetchone()
            if not candidate:
                return None
            cursor = conn.execute(
                '''
                UPDATE kuaishou_publications
                SET state = 'UPLOADING', attempt_count = attempt_count + 1,
                    claimed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND state IN ('QUEUED', 'RETRYABLE_FAILED')
                ''',
                (candidate["id"],),
            )
            if cursor.rowcount != 1:
                conn.commit()
                return None
            conn.commit()
            row = conn.execute(
                '''
                SELECT kp.*, pv.youtube_id, pv.slice_index
                FROM kuaishou_publications kp
                JOIN processed_videos pv ON pv.id = kp.video_id
                WHERE kp.id = ?
                ''',
                (candidate["id"],),
            ).fetchone()
            if not row:
                conn.rollback()
                return None
            conn.commit()
            return dict(row)

    def claim_kuaishou_publication(self, publication_id: int) -> Optional[Dict[str, Any]]:
        """原子领取指定快手任务，供新片在视频号成功后立即同步投递。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                '''
                UPDATE kuaishou_publications
                SET state = 'UPLOADING', attempt_count = attempt_count + 1,
                    claimed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND state IN ('QUEUED', 'RETRYABLE_FAILED')
                ''',
                (publication_id,),
            )
            if cursor.rowcount != 1:
                conn.commit()
                return None
            row = conn.execute(
                '''
                SELECT kp.*, pv.youtube_id, pv.slice_index
                FROM kuaishou_publications kp
                JOIN processed_videos pv ON pv.id = kp.video_id
                WHERE kp.id = ?
                ''',
                (publication_id,),
            ).fetchone()
            if not row:
                conn.rollback()
                return None
            conn.commit()
            return dict(row)

    def claim_next_kuaishou_history_publication(self, daily_limit: int) -> Optional[Dict[str, Any]]:
        """兼容入口：原子领取一条历史迁移任务并遵守当天上限。"""
        return self.claim_next_kuaishou_publication("HISTORY", daily_limit=daily_limit)

    def update_kuaishou_publication_state(
        self,
        publication_id: int,
        state: str,
        *,
        external_post_id: Optional[str] = None,
        external_url: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """更新快手投递状态；只有 PUBLISHED 才会在后续尝试中触发成片去重。"""
        normalized_state = (state or "").upper()
        if normalized_state not in self._KUAISHOU_STATES:
            raise ValueError(f"Unsupported Kuaishou state: {state}")
        if normalized_state == "PUBLISHED" and error_message is None:
            error_message = "快手作品管理已确认本次作品为已发布。"
        requested_state = normalized_state
        normalized_state = self._derive_platform_display_state(normalized_state, error_message)
        assignments = ["state = ?", "updated_at = CURRENT_TIMESTAMP"]
        values: List[Any] = [normalized_state]
        if external_post_id is not None:
            assignments.append("external_post_id = ?")
            values.append(external_post_id)
        if external_url is not None:
            assignments.append("external_url = ?")
            values.append(external_url)
        if error_message is not None:
            assignments.append("last_error_message = ?")
            values.append(error_message)
        if normalized_state == "PUBLISHED":
            assignments.append("published_at = COALESCE(published_at, CURRENT_TIMESTAMP)")
        elif requested_state == "PUBLISHED" or normalized_state in {"UNDER_REVIEW", "UNCERTAIN", "BANNED"}:
            assignments.append("published_at = NULL")
        values.append(publication_id)
        with self.get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE kuaishou_publications SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
            conn.commit()
            return cursor.rowcount == 1

    def mark_kuaishou_publication_attempted(self, publication_id: int) -> bool:
        """回填一次已实际提交的尝试，用于人工恢复流程也遵守 HISTORY 当日配额。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                '''
                UPDATE kuaishou_publications
                SET claimed_at = COALESCE(claimed_at, CURRENT_TIMESTAMP),
                    attempt_count = CASE WHEN attempt_count = 0 THEN 1 ELSE attempt_count END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                ''',
                (publication_id,),
            )
            conn.commit()
            return cursor.rowcount == 1

    # --- Douyin browser publication DAL ---
    def create_douyin_publication(
        self,
        youtube_id: str,
        asset_sha256: str,
        video_path: str,
        *,
        source_kind: str,
        slice_index: int = 0,
    ) -> Dict[str, Any]:
        """登记一次抖音投递尝试；仅已发布的相同成片摘要会阻止再次投递。"""
        source = (source_kind or "").upper()
        if source not in self._DOUYIN_SOURCES:
            raise ValueError(f"Unsupported Douyin source kind: {source_kind}")
        if len(asset_sha256) != 64:
            raise ValueError("asset_sha256 must be a SHA-256 hex digest")
        with self.get_connection() as conn:
            published = conn.execute(
                "SELECT * FROM douyin_publications WHERE asset_sha256 = ? AND state = 'PUBLISHED'",
                (asset_sha256,),
            ).fetchone()
            if published and self._derive_platform_display_state(
                published["state"], published["last_error_message"]
            ) == "PUBLISHED":
                return dict(published)
            video = conn.execute(
                "SELECT id FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            if not video:
                raise ValueError("Video or slice does not exist")
            next_attempt = conn.execute(
                "SELECT COALESCE(MAX(attempt_number), 0) + 1 AS number FROM douyin_publications WHERE video_id = ?",
                (video["id"],),
            ).fetchone()["number"]
            conn.execute(
                '''
                INSERT INTO douyin_publications (
                    video_id, asset_sha256, source_kind, video_path, attempt_number
                ) VALUES (?, ?, ?, ?, ?)
                ''',
                (video["id"], asset_sha256, source, video_path, next_attempt),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM douyin_publications WHERE video_id = ? AND attempt_number = ?",
                (video["id"], next_attempt),
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to create Douyin publication")
            return dict(row)

    def get_douyin_publication(self, youtube_id: str, slice_index: int = 0) -> Optional[Dict[str, Any]]:
        """按原视频/切片查询抖音发布记录。"""
        with self.get_connection() as conn:
            row = conn.execute(
                '''
                SELECT dp.*, pv.youtube_id, pv.slice_index
                FROM douyin_publications dp
                JOIN processed_videos pv ON pv.id = dp.video_id
                WHERE pv.youtube_id = ? AND pv.slice_index = ?
                ORDER BY dp.attempt_number DESC, dp.id DESC LIMIT 1
                ''',
                (youtube_id, slice_index),
            ).fetchone()
            return dict(row) if row else None

    def get_douyin_publication_by_id(self, publication_id: int) -> Optional[Dict[str, Any]]:
        """按账本 ID 读取抖音投递记录，包含源视频标识，供人工恢复前核验。"""
        with self.get_connection() as conn:
            row = conn.execute(
                '''
                SELECT dp.*, pv.youtube_id, pv.slice_index
                FROM douyin_publications dp
                JOIN processed_videos pv ON pv.id = dp.video_id
                WHERE dp.id = ?
                ''',
                (publication_id,),
            ).fetchone()
            return dict(row) if row else None

    # --- Douyin one-time browser launch ticket DAL ---
    @staticmethod
    def _canonical_douyin_launch_path(value: str) -> str:
        """规范化本地路径；空值不可用于浏览器启动凭据。"""
        clean_value = str(value or "").strip()
        return str(Path(clean_value).expanduser().resolve()) if clean_value else ""

    @staticmethod
    def _is_sha256_digest(value: str) -> bool:
        """仅接受小写或大写 64 位十六进制摘要，避免把任意 CLI 文本写入凭据。"""
        clean_value = str(value or "").strip()
        if len(clean_value) != 64:
            return False
        return all(character in "0123456789abcdefABCDEF" for character in clean_value)

    @staticmethod
    def _douyin_launch_source_ref(identifier: Any, attempt: Any) -> str:
        """将可重领记录和其当前尝试绑定为不可复用的凭据来源。"""
        return f"{int(identifier)}:{int(attempt)}"

    def _insert_douyin_browser_launch_ticket(
        self,
        conn,
        *,
        source_type: str,
        source_ref: str,
        video_path: str,
        asset_sha256: str,
        payload_sha256: str = "",
    ) -> Dict[str, str]:
        """在既有领取事务内签发一次性凭据；明文 token 只返回给当前父进程。"""
        canonical_path = self._canonical_douyin_launch_path(video_path)
        normalized_asset = str(asset_sha256 or "").strip().lower()
        normalized_payload = str(payload_sha256 or "").strip().lower()
        if (
            source_type not in {"GENERIC", "ENGLISH_WORLD", "DUBBING"}
            or not source_ref
            or not canonical_path
            or not self._is_sha256_digest(normalized_asset)
            or (normalized_payload and not self._is_sha256_digest(normalized_payload))
        ):
            raise ValueError("Invalid Douyin browser launch ticket source")
        ticket_id = secrets.token_urlsafe(24)
        token = secrets.token_urlsafe(32)
        token_sha256 = hashlib.sha256(token.encode("utf-8")).hexdigest()
        conn.execute(
            '''INSERT INTO douyin_browser_launch_tickets (
                   ticket_id, source_type, source_ref, video_path, asset_sha256,
                   payload_sha256, action_scope, token_sha256
               ) VALUES (?, ?, ?, ?, ?, ?, 'publish', ?)''',
            (
                ticket_id,
                source_type,
                source_ref,
                canonical_path,
                normalized_asset,
                normalized_payload,
                token_sha256,
            ),
        )
        return {
            "_douyin_launch_ticket_id": ticket_id,
            "_douyin_launch_token": token,
        }

    @staticmethod
    def _parse_douyin_launch_source_ref(source_ref: str) -> Optional[tuple[int, int]]:
        """解析 ``record_id:attempt_count``；任一异常都不得推断为当前领取。"""
        try:
            identifier, attempt = str(source_ref or "").split(":", 1)
            parsed_identifier = int(identifier)
            parsed_attempt = int(attempt)
        except (TypeError, ValueError):
            return None
        if parsed_identifier < 1 or parsed_attempt < 1:
            return None
        return parsed_identifier, parsed_attempt

    def _ticket_source_matches_current_launch(
        self,
        conn,
        ticket: Dict[str, Any],
        *,
        canonical_path: str,
        asset_sha256: str,
        require_new_source: bool,
    ) -> bool:
        """在同一事务复核 ticket 对应的真实状态、尝试号、路径与成片哈希。"""
        source_type = str(ticket.get("source_type") or "")
        source_ref = str(ticket.get("source_ref") or "")
        if source_type == "GENERIC":
            parsed_ref = self._parse_douyin_launch_source_ref(source_ref)
            if not parsed_ref:
                return False
            publication_id, attempt_count = parsed_ref
            row = conn.execute(
                "SELECT * FROM douyin_publications WHERE id = ?", (publication_id,)
            ).fetchone()
            if not row:
                return False
            row_data = dict(row)
            return (
                row_data.get("state") == "UPLOADING"
                and int(row_data.get("attempt_count") or 0) == attempt_count
                and (not require_new_source or row_data.get("source_kind") == "NEW")
                and self._canonical_douyin_launch_path(str(row_data.get("video_path") or "")) == canonical_path
                and str(row_data.get("asset_sha256") or "").lower() == asset_sha256
            )
        if source_type == "ENGLISH_WORLD":
            row = conn.execute(
                '''SELECT publication.state AS publication_state,
                          publication.artifact_sha256 AS publication_sha256,
                          attempt.state AS attempt_state,
                          attempt.artifact_sha256 AS attempt_sha256,
                          review.mp4_path AS video_path
                   FROM english_world_douyin_attempts attempt
                   JOIN english_world_douyin_publications publication
                     ON publication.review_id = attempt.review_id
                   JOIN english_world_review_items review ON review.id = attempt.review_id
                   WHERE attempt.attempt_id = ?''',
                (source_ref,),
            ).fetchone()
            if not row:
                return False
            row_data = dict(row)
            return (
                row_data.get("publication_state") == "SUBMITTING"
                and row_data.get("attempt_state") == "SUBMITTING"
                and str(row_data.get("publication_sha256") or "").lower() == asset_sha256
                and str(row_data.get("attempt_sha256") or "").lower() == asset_sha256
                and self._canonical_douyin_launch_path(str(row_data.get("video_path") or "")) == canonical_path
            )
        if source_type == "DUBBING":
            parsed_ref = self._parse_douyin_launch_source_ref(source_ref)
            if not parsed_ref:
                return False
            publication_id, attempt_count = parsed_ref
            row = conn.execute(
                '''SELECT publication.state AS publication_state, publication.platform,
                          publication.attempt_count, job.state AS job_state,
                          job.output_video_path, job.asset_sha256
                   FROM dubbing_publications publication
                   JOIN dubbing_jobs job ON job.id = publication.job_id
                   WHERE publication.id = ?''',
                (publication_id,),
            ).fetchone()
            if not row:
                return False
            row_data = dict(row)
            return (
                row_data.get("platform") == "douyin"
                and row_data.get("publication_state") == "UPLOADING"
                and int(row_data.get("attempt_count") or 0) == attempt_count
                and row_data.get("job_state") == "PUBLISHING"
                and self._canonical_douyin_launch_path(str(row_data.get("output_video_path") or "")) == canonical_path
                and str(row_data.get("asset_sha256") or "").lower() == asset_sha256
            )
        return False

    def bind_douyin_browser_launch_ticket_payload(
        self,
        ticket_id: str,
        token: str,
        *,
        payload_sha256: str,
    ) -> bool:
        """在启动前把完整投稿包绑定到已领取的 ticket；不得覆盖或重放已绑定内容。"""
        clean_ticket_id = str(ticket_id or "").strip()
        clean_token = str(token or "").strip()
        clean_payload = str(payload_sha256 or "").strip().lower()
        if not clean_ticket_id or not clean_token or not self._is_sha256_digest(clean_payload):
            return False
        token_sha256 = hashlib.sha256(clean_token.encode("utf-8")).hexdigest()
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM douyin_browser_launch_tickets WHERE ticket_id = ?", (clean_ticket_id,)
            ).fetchone()
            if not row:
                conn.commit()
                return False
            ticket = dict(row)
            stored_token = str(ticket.get("token_sha256") or "")
            if (
                not stored_token
                or not hmac.compare_digest(stored_token, token_sha256)
                or ticket.get("launch_started_at") is not None
                or ticket.get("prelaunch_canceled_at") is not None
                or str(ticket.get("action_scope") or "") != "publish"
            ):
                conn.commit()
                return False
            canonical_path = self._canonical_douyin_launch_path(str(ticket.get("video_path") or ""))
            asset_sha256 = str(ticket.get("asset_sha256") or "").lower()
            if not self._ticket_source_matches_current_launch(
                conn,
                ticket,
                canonical_path=canonical_path,
                asset_sha256=asset_sha256,
                require_new_source=False,
            ):
                conn.commit()
                return False
            existing_payload = str(ticket.get("payload_sha256") or "").lower()
            if existing_payload and existing_payload != clean_payload:
                conn.commit()
                return False
            cursor = conn.execute(
                '''UPDATE douyin_browser_launch_tickets
                   SET payload_sha256 = ?
                   WHERE ticket_id = ? AND launch_started_at IS NULL
                     AND prelaunch_canceled_at IS NULL
                     AND (payload_sha256 IS NULL OR payload_sha256 = '' OR payload_sha256 = ?)''',
                (clean_payload, clean_ticket_id, clean_payload),
            )
            conn.commit()
            return cursor.rowcount == 1

    def begin_douyin_browser_launch(
        self,
        ticket_id: str,
        token: str,
        *,
        video_path: str,
        asset_sha256: str,
        payload_sha256: str,
        require_new_source: bool,
    ) -> bool:
        """原子消费一次 ticket；成功才允许低层上传器启动 Playwright。"""
        clean_ticket_id = str(ticket_id or "").strip()
        clean_token = str(token or "").strip()
        canonical_path = self._canonical_douyin_launch_path(video_path)
        normalized_asset = str(asset_sha256 or "").strip().lower()
        normalized_payload = str(payload_sha256 or "").strip().lower()
        if (
            not clean_ticket_id
            or not clean_token
            or not canonical_path
            or not self._is_sha256_digest(normalized_asset)
            or not self._is_sha256_digest(normalized_payload)
        ):
            return False
        token_sha256 = hashlib.sha256(clean_token.encode("utf-8")).hexdigest()
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM douyin_browser_launch_tickets WHERE ticket_id = ?", (clean_ticket_id,)
            ).fetchone()
            if not row:
                conn.commit()
                return False
            ticket = dict(row)
            stored_token = str(ticket.get("token_sha256") or "")
            if (
                not stored_token
                or not hmac.compare_digest(stored_token, token_sha256)
                or ticket.get("launch_started_at") is not None
                or ticket.get("prelaunch_canceled_at") is not None
                or str(ticket.get("action_scope") or "") != "publish"
                or self._canonical_douyin_launch_path(str(ticket.get("video_path") or "")) != canonical_path
                or str(ticket.get("asset_sha256") or "").lower() != normalized_asset
                or str(ticket.get("payload_sha256") or "").lower() != normalized_payload
                or not self._ticket_source_matches_current_launch(
                    conn,
                    ticket,
                    canonical_path=canonical_path,
                    asset_sha256=normalized_asset,
                    require_new_source=bool(require_new_source),
                )
            ):
                conn.commit()
                return False
            cursor = conn.execute(
                '''UPDATE douyin_browser_launch_tickets
                   SET launch_started_at = CURRENT_TIMESTAMP
                   WHERE ticket_id = ? AND launch_started_at IS NULL
                     AND prelaunch_canceled_at IS NULL''',
                (clean_ticket_id,),
            )
            conn.commit()
            return cursor.rowcount == 1

    @staticmethod
    def _douyin_prelaunch_cancel_message(reason: str) -> str:
        """规范化“浏览器尚未启动”审计原因，避免把可恢复事实写成投稿不确定。"""
        clean_reason = " ".join(str(reason or "").split())[:800]
        if not clean_reason:
            clean_reason = "领取后的父进程未能在恢复等待期内启动浏览器。"
        return (
            "抖音发布前浏览器未启动；"
            f"{clean_reason} 已安全取消本次尝试，需人工新建尝试。"
        )

    @staticmethod
    def _cancel_unstarted_douyin_browser_ticket(conn, ticket_id: str, message: str) -> bool:
        """撤销尚未启动的 ticket；与源账本同事务调用，避免持票旧进程晚到启动。"""
        cursor = conn.execute(
            '''UPDATE douyin_browser_launch_tickets
               SET prelaunch_canceled_at = CURRENT_TIMESTAMP,
                   prelaunch_cancel_reason = ?
               WHERE ticket_id = ? AND launch_started_at IS NULL
                 AND prelaunch_canceled_at IS NULL''',
            (message, ticket_id),
        )
        return cursor.rowcount == 1

    def cancel_stale_generic_douyin_prelaunch_attempts(
        self,
        *,
        min_age_seconds: int,
        reason: str,
    ) -> int:
        """取消超时仍未打开浏览器的通用抖音领取；绝不触碰已启动或未知提交。"""
        minimum_age = int(min_age_seconds)
        if minimum_age < 0:
            raise ValueError("min_age_seconds must be non-negative")
        message = self._douyin_prelaunch_cancel_message(reason)
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            tickets = conn.execute(
                '''SELECT ticket_id, source_ref
                   FROM douyin_browser_launch_tickets
                   WHERE source_type = 'GENERIC' AND launch_started_at IS NULL
                     AND prelaunch_canceled_at IS NULL
                     AND datetime(issued_at) <= datetime('now', ?)''',
                (f"-{minimum_age} seconds",),
            ).fetchall()
            canceled = 0
            for ticket in tickets:
                ticket_data = dict(ticket)
                parsed_ref = self._parse_douyin_launch_source_ref(ticket_data["source_ref"])
                if not parsed_ref:
                    self._cancel_unstarted_douyin_browser_ticket(
                        conn, ticket_data["ticket_id"], message,
                    )
                    continue
                publication_id, attempt_count = parsed_ref
                cursor = conn.execute(
                    '''UPDATE douyin_publications
                       SET state = 'CANCELED', last_error_message = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND state = 'UPLOADING' AND attempt_count = ?''',
                    (message, publication_id, attempt_count),
                )
                if self._cancel_unstarted_douyin_browser_ticket(
                    conn, ticket_data["ticket_id"], message,
                ) and cursor.rowcount == 1:
                    canceled += 1
            conn.commit()
            return canceled

    def cancel_douyin_publication_pre_launch_failure(
        self,
        publication_id: int,
        *,
        ticket_id: str,
        reason: str,
    ) -> bool:
        """按当前父进程已知 ticket 立即收口通用发布前失败，拒绝碰任何已启动尝试。"""
        clean_ticket_id = str(ticket_id or "").strip()
        if not clean_ticket_id:
            return False
        message = self._douyin_prelaunch_cancel_message(reason)
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            publication = conn.execute(
                "SELECT id, state, attempt_count FROM douyin_publications WHERE id = ?",
                (publication_id,),
            ).fetchone()
            if not publication or publication["state"] != "UPLOADING":
                conn.rollback()
                return False
            source_ref = self._douyin_launch_source_ref(
                publication["id"], publication["attempt_count"],
            )
            ticket = conn.execute(
                '''SELECT ticket_id FROM douyin_browser_launch_tickets
                   WHERE ticket_id = ? AND source_type = 'GENERIC' AND source_ref = ?
                     AND launch_started_at IS NULL AND prelaunch_canceled_at IS NULL''',
                (clean_ticket_id, source_ref),
            ).fetchone()
            if not ticket:
                conn.rollback()
                return False
            cursor = conn.execute(
                '''UPDATE douyin_publications
                   SET state = 'CANCELED', last_error_message = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND state = 'UPLOADING' AND attempt_count = ?''',
                (message, publication["id"], publication["attempt_count"]),
            )
            if cursor.rowcount != 1 or not self._cancel_unstarted_douyin_browser_ticket(
                conn, clean_ticket_id, message,
            ):
                conn.rollback()
                return False
            conn.commit()
            return True

    def cancel_stale_dubbing_douyin_prelaunch_attempts(
        self,
        *,
        min_age_seconds: int,
        reason: str,
        job_id: Optional[int] = None,
    ) -> int:
        """取消超时仍未启动的配音抖音领取；已启动记录永远留给人工核验。"""
        minimum_age = int(min_age_seconds)
        if minimum_age < 0:
            raise ValueError("min_age_seconds must be non-negative")
        message = self._douyin_prelaunch_cancel_message(reason)
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            tickets = conn.execute(
                '''SELECT ticket_id, source_ref
                   FROM douyin_browser_launch_tickets
                   WHERE source_type = 'DUBBING' AND launch_started_at IS NULL
                     AND prelaunch_canceled_at IS NULL
                     AND datetime(issued_at) <= datetime('now', ?)''',
                (f"-{minimum_age} seconds",),
            ).fetchall()
            canceled = 0
            for ticket in tickets:
                ticket_data = dict(ticket)
                parsed_ref = self._parse_douyin_launch_source_ref(ticket_data["source_ref"])
                if not parsed_ref:
                    self._cancel_unstarted_douyin_browser_ticket(
                        conn, ticket_data["ticket_id"], message,
                    )
                    continue
                publication_id, attempt_count = parsed_ref
                if job_id is not None:
                    publication = conn.execute(
                        "SELECT job_id FROM dubbing_publications WHERE id = ? AND platform = 'douyin'",
                        (publication_id,),
                    ).fetchone()
                    if not publication or int(publication["job_id"]) != int(job_id):
                        continue
                cursor = conn.execute(
                    '''UPDATE dubbing_publications
                       SET state = 'CANCELED', last_error_message = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND platform = 'douyin' AND state = 'UPLOADING'
                         AND attempt_count = ?''',
                    (message, publication_id, attempt_count),
                )
                if self._cancel_unstarted_douyin_browser_ticket(
                    conn, ticket_data["ticket_id"], message,
                ) and cursor.rowcount == 1:
                    canceled += 1
            conn.commit()
            return canceled

    def requeue_canceled_douyin_publication(self, publication_id: int) -> Dict[str, Any]:
        """人工确认修复后从 CANCELED 新建一次 QUEUED 尝试，不覆盖历史账本。"""
        with self.get_connection() as conn:
            current = conn.execute(
                "SELECT * FROM douyin_publications WHERE id = ?", (publication_id,)
            ).fetchone()
            if not current:
                raise ValueError("Douyin publication does not exist")
            if current["state"] != "CANCELED":
                raise ValueError("Only CANCELED Douyin publications can be requeued")
            next_attempt = conn.execute(
                "SELECT COALESCE(MAX(attempt_number), 0) + 1 AS number FROM douyin_publications WHERE video_id = ?",
                (current["video_id"],),
            ).fetchone()["number"]
            conn.execute(
                '''
                INSERT INTO douyin_publications (
                    video_id, asset_sha256, source_kind, video_path, attempt_number
                ) VALUES (?, ?, ?, ?, ?)
                ''',
                (
                    current["video_id"], current["asset_sha256"], current["source_kind"],
                    current["video_path"], next_attempt,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM douyin_publications WHERE video_id = ? AND attempt_number = ?",
                (current["video_id"], next_attempt),
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to requeue canceled Douyin publication")
            return dict(row)

    def get_douyin_publications_by_states(self, states: Collection[str]) -> List[Dict[str, Any]]:
        """按状态返回抖音发布账本，包含原视频标识，供审核回查任务使用。"""
        normalized_states = [str(state or "").upper() for state in states]
        if not normalized_states or any(state not in self._DOUYIN_STATES for state in normalized_states):
            raise ValueError("states must contain supported Douyin states")
        placeholders = ", ".join("?" for _ in normalized_states)
        with self.get_connection() as conn:
            rows = conn.execute(
                f'''\
                SELECT dp.*, pv.youtube_id, pv.slice_index
                FROM douyin_publications dp
                JOIN processed_videos pv ON pv.id = dp.video_id
                WHERE dp.state IN ({placeholders})
                ORDER BY dp.updated_at ASC, dp.id ASC
                ''',
                normalized_states,
            ).fetchall()
            return [dict(row) for row in rows]

    def get_douyin_upstream_shadow_snapshot(
        self,
        limit: int = 5,
        *,
        lookback_hours: int = 24,
    ) -> Dict[str, Any]:
        """只读量化被视频号确认门禁挡住的抖音候选，不创建或恢复任何账本。"""
        safe_limit = max(1, min(int(limit), 50))
        safe_lookback_hours = max(1, int(lookback_hours))
        with self.get_connection() as conn:
            rows = conn.execute(
                '''
                WITH latest_douyin AS (
                    SELECT dp.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY dp.video_id
                               ORDER BY dp.attempt_number DESC, dp.id DESC
                           ) AS rn
                    FROM douyin_publications dp
                ), blocked AS (
                    SELECT pv.youtube_id, pv.slice_index, pv.title, pv.zh_title,
                           pv.status AS local_state, pv.updated_at,
                           (
                               SELECT wp.state FROM wechat_publications wp
                               WHERE wp.video_id = pv.id
                               ORDER BY wp.updated_at DESC, wp.id DESC LIMIT 1
                           ) AS wechat_state,
                           ld.state AS douyin_state,
                           ld.last_error_message AS douyin_error
                    FROM processed_videos pv
                    LEFT JOIN latest_douyin ld ON ld.video_id = pv.id AND ld.rn = 1
                    WHERE pv.status IN ('UNDER_REVIEW', 'SUBMITTED_UNBOUND', 'SUBMITTED_BOUND', 'UNCERTAIN')
                      AND COALESCE(pv.publication_review_required, 0) = 0
                      AND EXISTS (
                          SELECT 1 FROM wechat_publications wp
                          WHERE wp.video_id = pv.id
                            AND wp.state IN ('UNDER_REVIEW', 'SUBMITTED_UNBOUND', 'SUBMITTED_BOUND', 'UNCERTAIN')
                      )
                      AND (
                          ld.id IS NULL
                          OR (
                              ld.state = 'CANCELED'
                              AND (
                                  COALESCE(ld.last_error_message, '') LIKE '视频号仅确认提交%'
                                  OR COALESCE(ld.last_error_message, '') LIKE '视频号提交结果不可确认%'
                              )
                          )
                      )
                )
                SELECT blocked.*,
                       COUNT(*) OVER () AS total_count,
                       SUM(CASE WHEN douyin_state IS NULL THEN 1 ELSE 0 END) OVER () AS without_ledger_count,
                       SUM(CASE
                           WHEN douyin_state IS NULL AND updated_at >= datetime('now', ?) THEN 1
                           ELSE 0
                       END) OVER () AS independent_eligible_count
                FROM blocked
                ORDER BY updated_at DESC, youtube_id ASC, slice_index ASC
                LIMIT ?
                ''',
                (f"-{safe_lookback_hours} hours", safe_limit),
            ).fetchall()
        items = [dict(row) for row in rows]
        total = int(items[0].get("total_count") or 0) if items else 0
        without_ledger = int(items[0].get("without_ledger_count") or 0) if items else 0
        independent_eligible = int(items[0].get("independent_eligible_count") or 0) if items else 0
        for item in items:
            item.pop("total_count", None)
            item.pop("without_ledger_count", None)
            item.pop("independent_eligible_count", None)
        return {
            "count": total,
            "without_ledger_count": without_ledger,
            "independent_eligible_count": independent_eligible,
            "lookback_hours": safe_lookback_hours,
            "items": items,
        }

    def get_unqueued_douyin_history_videos(self, limit: int = 20) -> List[Dict[str, Any]]:
        """返回微信已发布、尚未登记抖音账本且未被拉黑的历史视频。"""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        with self.get_connection() as conn:
            rows = conn.execute(
                '''
                SELECT pv.*
                FROM processed_videos pv
                WHERE pv.status = 'PUBLISHED'
                  AND pv.youtube_id NOT IN (SELECT youtube_id FROM blacklisted_videos)
                  AND NOT EXISTS (
                      SELECT 1 FROM douyin_publications dp WHERE dp.video_id = pv.id
                  )
                ORDER BY pv.updated_at ASC, pv.id ASC
                LIMIT ?
                ''',
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_unqueued_douyin_new_videos(
        self,
        *,
        lookback_hours: int = 24,
        limit: int = 10,
        require_wechat_public_confirmation: bool = True,
    ) -> List[Dict[str, Any]]:
        """返回最近可独立投递且从未登记抖音账本的新片。

        默认只接受视频号已确认公开的 ``PUBLISHED``。显式关闭上游依赖时，可接受已经完成
        成片但视频号延后、审核中或结果不确定的状态；``NOT EXISTS`` 针对全部抖音历史账本，
        因此不会复活 CANCELED / UNCERTAIN / UNDER_REVIEW 等既有尝试。候选发现必须提供
        正数的时间和批次边界；不能以 ``None`` 旁路 NEW 与 HISTORY 的隔离。
        """
        if isinstance(lookback_hours, bool) or not isinstance(lookback_hours, int) or lookback_hours < 1:
            raise ValueError("lookback_hours must be a positive integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        allowed_statuses = (
            ("PUBLISHED",)
            if require_wechat_public_confirmation
            else (
                "PUBLISHED",
                "WECHAT_DEFERRED",
                "UNDER_REVIEW",
                "SUBMITTED_UNBOUND",
                "SUBMITTED_BOUND",
                "UNCERTAIN",
            )
        )
        status_placeholders = ", ".join("?" for _ in allowed_statuses)
        params: List[Any] = [*allowed_statuses, f"-{lookback_hours} hours", limit]
        with self.get_connection() as conn:
            rows = conn.execute(
                f'''
                SELECT pv.*
                FROM processed_videos pv
                WHERE pv.status IN ({status_placeholders})
                  AND pv.updated_at >= datetime('now', ?)
                  AND COALESCE(pv.publication_review_required, 0) = 0
                  AND pv.youtube_id NOT IN (SELECT youtube_id FROM blacklisted_videos)
                  AND pv.channel_id NOT IN (SELECT channel_id FROM recommended_channels WHERE status = 'BLACKLISTED')
                  AND NOT EXISTS (
                      SELECT 1 FROM douyin_publications dp WHERE dp.video_id = pv.id
                )
                ORDER BY pv.updated_at ASC, pv.id ASC
                LIMIT ?
                ''',
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def claim_next_douyin_publication(
        self,
        source_kind: str,
        *,
        daily_limit: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """原子领取同一来源的一条可重试抖音任务。"""
        source = (source_kind or "").upper()
        if source not in self._DOUYIN_SOURCES:
            raise ValueError(f"Unsupported Douyin source kind: {source_kind}")
        with self.get_connection() as conn:
            if daily_limit is not None:
                if daily_limit < 1:
                    return None
                used = conn.execute(
                    '''
                    SELECT (
                        SELECT COUNT(*) FROM douyin_publications
                        WHERE source_kind = ?
                          AND state IN ('UPLOADING', 'UNDER_REVIEW', 'PUBLISHED', 'UNCERTAIN')
                          AND claimed_at IS NOT NULL
                          AND date(claimed_at, 'localtime') = date('now', 'localtime')
                    ) + CASE WHEN ? = 'NEW' THEN (
                        SELECT COUNT(*) FROM english_world_douyin_publications
                        WHERE state IN ('SUBMITTING', 'UNDER_REVIEW', 'PUBLISHED', 'UNCERTAIN')
                          AND claimed_at IS NOT NULL
                          AND date(claimed_at, 'localtime') = date('now', 'localtime')
                    ) ELSE 0 END AS count
                    ''',
                    (source, source),
                ).fetchone()["count"]
                if used >= daily_limit:
                    return None
            candidate = conn.execute(
                '''
                SELECT dp.*, pv.youtube_id, pv.slice_index
                FROM douyin_publications dp
                JOIN processed_videos pv ON pv.id = dp.video_id
                WHERE dp.source_kind = ? AND dp.state IN ('QUEUED', 'RETRYABLE_FAILED')
                  AND (dp.claimed_at IS NULL OR date(dp.claimed_at, 'localtime') < date('now', 'localtime'))
                  AND NOT (
                      dp.state = 'RETRYABLE_FAILED'
                      AND COALESCE(dp.last_error_message, '') LIKE '%提交后未能在作品管理确认可见%'
                  )
                ORDER BY dp.created_at ASC, dp.id ASC LIMIT 1
                ''',
                (source,),
            ).fetchone()
            if not candidate:
                return None
            cursor = conn.execute(
                '''
                UPDATE douyin_publications
                SET state = 'UPLOADING', attempt_count = attempt_count + 1,
                    claimed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND state IN ('QUEUED', 'RETRYABLE_FAILED')
                ''',
                (candidate["id"],),
            )
            if cursor.rowcount != 1:
                conn.commit()
                return None
            row = conn.execute(
                '''
                SELECT dp.*, pv.youtube_id, pv.slice_index
                FROM douyin_publications dp
                JOIN processed_videos pv ON pv.id = dp.video_id
                WHERE dp.id = ?
                ''',
                (candidate["id"],),
            ).fetchone()
            if not row:
                conn.rollback()
                return None
            row_data = dict(row)
            ticket = self._insert_douyin_browser_launch_ticket(
                conn,
                source_type="GENERIC",
                source_ref=self._douyin_launch_source_ref(
                    row_data["id"], row_data["attempt_count"],
                ),
                video_path=str(row_data["video_path"]),
                asset_sha256=str(row_data["asset_sha256"]),
            )
            conn.commit()
            return {**row_data, **ticket}

    def claim_douyin_publication(
        self,
        publication_id: int,
        *,
        daily_limit: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """原子领取指定抖音任务；指定额度时同样受当日领取总数约束。"""
        with self.get_connection() as conn:
            current = conn.execute(
                "SELECT source_kind FROM douyin_publications WHERE id = ?", (publication_id,)
            ).fetchone()
            if not current:
                return None
            if daily_limit is not None:
                if daily_limit < 1:
                    return None
                used = conn.execute(
                    '''
                    SELECT (
                        SELECT COUNT(*) FROM douyin_publications
                        WHERE source_kind = ?
                          AND state IN ('UPLOADING', 'UNDER_REVIEW', 'PUBLISHED', 'UNCERTAIN')
                          AND claimed_at IS NOT NULL
                          AND date(claimed_at, 'localtime') = date('now', 'localtime')
                    ) + CASE WHEN ? = 'NEW' THEN (
                        SELECT COUNT(*) FROM english_world_douyin_publications
                        WHERE state IN ('SUBMITTING', 'UNDER_REVIEW', 'PUBLISHED', 'UNCERTAIN')
                          AND claimed_at IS NOT NULL
                          AND date(claimed_at, 'localtime') = date('now', 'localtime')
                    ) ELSE 0 END AS count
                    ''',
                    (current["source_kind"], current["source_kind"]),
                ).fetchone()["count"]
                if used >= daily_limit:
                    return None
            cursor = conn.execute(
                '''
                UPDATE douyin_publications
                SET state = 'UPLOADING', attempt_count = attempt_count + 1,
                    claimed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND state IN ('QUEUED', 'RETRYABLE_FAILED')
                ''',
                (publication_id,),
            )
            if cursor.rowcount != 1:
                conn.commit()
                return None
            row = conn.execute(
                '''
                SELECT dp.*, pv.youtube_id, pv.slice_index
                FROM douyin_publications dp
                JOIN processed_videos pv ON pv.id = dp.video_id
                WHERE dp.id = ?
                ''',
                (publication_id,),
            ).fetchone()
            if not row:
                conn.rollback()
                return None
            row_data = dict(row)
            ticket = self._insert_douyin_browser_launch_ticket(
                conn,
                source_type="GENERIC",
                source_ref=self._douyin_launch_source_ref(
                    row_data["id"], row_data["attempt_count"],
                ),
                video_path=str(row_data["video_path"]),
                asset_sha256=str(row_data["asset_sha256"]),
            )
            conn.commit()
            return {**row_data, **ticket}

    def reserve_douyin_browser_action_slot(
        self,
        minimum_interval_seconds: int,
        reason: str,
        *,
        now_epoch: Optional[float] = None,
    ) -> float:
        """原子预留下一次抖音浏览器动作；返回仍需等待的秒数。"""
        interval = max(0, int(minimum_interval_seconds or 0))
        if interval == 0:
            return 0.0
        current_epoch = float(time.time() if now_epoch is None else now_epoch)
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT last_action_at_epoch FROM platform_browser_action_slots WHERE platform = 'douyin'"
            ).fetchone()
            if row:
                elapsed = max(0.0, current_epoch - float(row["last_action_at_epoch"]))
                remaining = float(interval) - elapsed
                if remaining > 0:
                    conn.commit()
                    return remaining
            conn.execute(
                '''
                INSERT INTO platform_browser_action_slots (
                    platform, last_action_at_epoch, last_reason, updated_at
                ) VALUES ('douyin', ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(platform) DO UPDATE SET
                    last_action_at_epoch = excluded.last_action_at_epoch,
                    last_reason = excluded.last_reason,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (current_epoch, reason),
            )
            conn.commit()
        return 0.0

    def record_platform_ui_failure(
        self,
        platform: str,
        stage: str,
        reason: str,
        *,
        evidence_path: Optional[str] = None,
        recording_threshold: int = 2,
    ) -> Dict[str, Any]:
        """原子累计同平台同阶段 UI 失败，并在达到阈值时记录录屏请求时间。"""
        platform_key = str(platform or "").strip().lower()
        stage_key = str(stage or "").strip()
        reason_text = str(reason or "").strip()
        if not platform_key or not stage_key or not reason_text:
            raise ValueError("platform、stage 和 reason 均不能为空")
        threshold = max(1, int(recording_threshold or 1))
        evidence = str(evidence_path).strip() if evidence_path else None
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                '''
                SELECT consecutive_failures, active
                FROM platform_ui_failure_streaks
                WHERE platform = ? AND stage = ?
                ''',
                (platform_key, stage_key),
            ).fetchone()
            if current and int(current["active"] or 0) == 1:
                next_count = int(current["consecutive_failures"] or 0) + 1
                conn.execute(
                    '''
                    UPDATE platform_ui_failure_streaks
                    SET consecutive_failures = ?,
                        last_failed_at = CURRENT_TIMESTAMP,
                        last_reason = ?,
                        evidence_path = COALESCE(?, evidence_path),
                        recording_requested_at = CASE
                            WHEN ? >= ? THEN COALESCE(recording_requested_at, CURRENT_TIMESTAMP)
                            ELSE recording_requested_at
                        END,
                        cleared_at = NULL
                    WHERE platform = ? AND stage = ?
                    ''',
                    (
                        next_count,
                        reason_text,
                        evidence,
                        next_count,
                        threshold,
                        platform_key,
                        stage_key,
                    ),
                )
            elif current:
                conn.execute(
                    '''
                    UPDATE platform_ui_failure_streaks
                    SET consecutive_failures = 1,
                        active = 1,
                        first_failed_at = CURRENT_TIMESTAMP,
                        last_failed_at = CURRENT_TIMESTAMP,
                        last_reason = ?,
                        evidence_path = ?,
                        recording_requested_at = CASE WHEN 1 >= ? THEN CURRENT_TIMESTAMP ELSE NULL END,
                        cleared_at = NULL
                    WHERE platform = ? AND stage = ?
                    ''',
                    (reason_text, evidence, threshold, platform_key, stage_key),
                )
            else:
                conn.execute(
                    '''
                    INSERT INTO platform_ui_failure_streaks (
                        platform, stage, consecutive_failures, active, last_reason,
                        evidence_path, recording_requested_at
                    ) VALUES (?, ?, 1, 1, ?, ?, CASE WHEN 1 >= ? THEN CURRENT_TIMESTAMP ELSE NULL END)
                    ''',
                    (platform_key, stage_key, reason_text, evidence, threshold),
                )
            row = conn.execute(
                '''
                SELECT * FROM platform_ui_failure_streaks
                WHERE platform = ? AND stage = ?
                ''',
                (platform_key, stage_key),
            ).fetchone()
            conn.commit()
            return dict(row)

    def get_platform_ui_failure_streaks(self, platform: str) -> List[Dict[str, Any]]:
        """返回一个平台全部 UI 失败阶段，供调度前熔断与运维状态查询。"""
        platform_key = str(platform or "").strip().lower()
        if not platform_key:
            raise ValueError("platform 不能为空")
        with self.get_connection() as conn:
            rows = conn.execute(
                '''
                SELECT * FROM platform_ui_failure_streaks
                WHERE platform = ?
                ORDER BY active DESC, consecutive_failures DESC, last_failed_at DESC, stage ASC
                ''',
                (platform_key,),
            ).fetchall()
            return [dict(row) for row in rows]

    def clear_platform_ui_failure_streak(
        self,
        platform: str,
        stage: str,
        evidence_reference: str,
    ) -> bool:
        """用明确成功或校准证据清除一个阶段；保留旧失败和清除审计，不删除记录。"""
        platform_key = str(platform or "").strip().lower()
        stage_key = str(stage or "").strip()
        evidence = str(evidence_reference or "").strip()
        if not platform_key or not stage_key or not evidence:
            raise ValueError("platform、stage 和 evidence_reference 均不能为空")
        with self.get_connection() as conn:
            cursor = conn.execute(
                '''
                UPDATE platform_ui_failure_streaks
                SET consecutive_failures = 0,
                    active = 0,
                    cleared_at = CURRENT_TIMESTAMP,
                    clear_evidence_path = ?
                WHERE platform = ? AND stage = ?
                ''',
                (evidence, platform_key, stage_key),
            )
            conn.commit()
            return cursor.rowcount > 0

    def claim_next_douyin_history_publication(self, daily_limit: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """兼容入口：原子领取一条抖音历史迁移任务；可不设当日上限。"""
        return self.claim_next_douyin_publication("HISTORY", daily_limit=daily_limit)

    def get_douyin_history_progress_snapshot(self, daily_limit: int) -> Dict[str, int]:
        """返回抖音历史补发的今日进度和可领取队列数。"""
        if daily_limit < 1:
            raise ValueError("daily_limit must be at least 1")
        with self.get_connection() as conn:
            claimed_today = conn.execute(
                '''
                SELECT COUNT(*) AS count FROM douyin_publications
                WHERE source_kind = 'HISTORY'
                  AND state IN ('UPLOADING', 'UNDER_REVIEW', 'PUBLISHED', 'UNCERTAIN')
                  AND claimed_at IS NOT NULL
                  AND date(claimed_at, 'localtime') = date('now', 'localtime')
                '''
            ).fetchone()["count"]
            queue_ready = conn.execute(
                '''
                SELECT COUNT(*) AS count FROM douyin_publications dp
                WHERE dp.source_kind = 'HISTORY'
                  AND dp.state IN ('QUEUED', 'RETRYABLE_FAILED')
                  AND (dp.claimed_at IS NULL OR date(dp.claimed_at, 'localtime') < date('now', 'localtime'))
                  AND NOT (
                      dp.state = 'RETRYABLE_FAILED'
                      AND COALESCE(dp.last_error_message, '') LIKE '%提交后未能在作品管理确认可见%'
                  )
                '''
            ).fetchone()["count"]
            return {
                "daily_limit": daily_limit,
                "claimed_today": claimed_today,
                "remaining_today": max(0, daily_limit - claimed_today),
                "queue_ready": queue_ready,
            }

    def update_douyin_publication_state(
        self,
        publication_id: int,
        state: str,
        *,
        external_post_id: Optional[str] = None,
        external_url: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """更新抖音投递状态；只有 PUBLISHED 才会在后续尝试中触发成片去重。"""
        normalized_state = (state or "").upper()
        if normalized_state not in self._DOUYIN_STATES:
            raise ValueError(f"Unsupported Douyin state: {state}")
        if normalized_state == "PUBLISHED" and error_message is None:
            error_message = "抖音作品管理已确认本次作品为已发布。"
        requested_state = normalized_state
        normalized_state = self._derive_platform_display_state(normalized_state, error_message)
        assignments = ["state = ?", "updated_at = CURRENT_TIMESTAMP"]
        values: List[Any] = [normalized_state]
        if external_post_id is not None:
            assignments.append("external_post_id = ?")
            values.append(external_post_id)
        if external_url is not None:
            assignments.append("external_url = ?")
            values.append(external_url)
        if error_message is not None:
            assignments.append("last_error_message = ?")
            values.append(error_message)
        if normalized_state == "PUBLISHED":
            assignments.append("published_at = COALESCE(published_at, CURRENT_TIMESTAMP)")
        elif requested_state == "PUBLISHED" or normalized_state in {"UNDER_REVIEW", "UNCERTAIN", "BANNED"}:
            assignments.append("published_at = NULL")
        values.append(publication_id)
        with self.get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE douyin_publications SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
            conn.commit()
            return cursor.rowcount == 1

    def cancel_queued_downstream_publications_for_unconfirmed_wechat(
        self,
        youtube_id: str,
        *,
        reason: str,
        slice_index: int = 0,
        cancel_douyin: bool = True,
    ) -> Dict[str, int]:
        """按显式策略取消尚未提交的下游投递；永不触碰已开始或待核验任务。"""
        clean_reason = (reason or "视频号尚未确认公开发布，停止下游自动投递。").strip()
        with self.get_connection() as conn:
            video = conn.execute(
                "SELECT id FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            if not video:
                raise ValueError(f"Video not found: {youtube_id}#{slice_index}")
            counts: Dict[str, int] = {"kuaishou": 0, "douyin": 0}
            targets = [("kuaishou", "kuaishou_publications")]
            if cancel_douyin:
                targets.append(("douyin", "douyin_publications"))
            for platform, table in targets:
                cursor = conn.execute(
                    f"UPDATE {table} SET state = 'CANCELED', last_error_message = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE video_id = ? AND state = 'QUEUED'",
                    (clean_reason, video["id"]),
                )
                counts[platform] = cursor.rowcount
            conn.commit()
            return counts

    def cancel_douyin_pre_submit_gate_failures(self) -> int:
        """将明确未提交的抖音旧失败停在 CANCELED，绝不触碰审核中或不确定记录。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                '''
                UPDATE douyin_publications
                SET state = 'CANCELED',
                    last_error_message = COALESCE(last_error_message, '')
                        || ' 已停止自动重试，修复后请人工重新入队。',
                    updated_at = CURRENT_TIMESTAMP
                WHERE state = 'RETRYABLE_FAILED'
                  AND (
                      COALESCE(last_error_message, '') LIKE '%发布前元信息、封面或自主声明闸门未能确认%'
                      OR COALESCE(last_error_message, '') LIKE '%上传器尚未完成页面校准%'
                      OR COALESCE(last_error_message, '') LIKE '%抖音投递产物缺失%'
                  )
                '''
            )
            conn.commit()
            return cursor.rowcount

    def mark_douyin_publication_attempted(self, publication_id: int) -> bool:
        """回填一次已实际提交的尝试，用于人工恢复流程也遵守 HISTORY 当日配额。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                '''
                UPDATE douyin_publications
                SET claimed_at = COALESCE(claimed_at, CURRENT_TIMESTAMP),
                    attempt_count = CASE WHEN attempt_count = 0 THEN 1 ELSE attempt_count END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                ''',
                (publication_id,),
            )
            conn.commit()
            return cursor.rowcount == 1

    def get_platform_backfill_preview_candidates(
        self,
        platform: str,
        *,
        wall_street_since_upload_date: str,
        limit: Optional[int] = 500,
    ) -> List[Dict[str, Any]]:
        """只读返回平台补录预览候选；不创建发布账本，也不改变视频状态。

        规则：
        1. 已产出/发布的视频里，标题、中文标题、分类或频道名命中访谈/演讲线索；
        2. Wall Street Truthbombs 在指定源发布日期之后的视频。

        微信补录只看 WECHAT_DEFERRED；抖音补录看已完成成片（PUBLISHED/WECHAT_DEFERRED），
        并排除抖音已有排队、上传、审核、已发布、待人工核实或封禁记录的视频；
        未尝试候选稳定排在可重试失败项之前，避免失败重试挤占新候选批次。
        """
        normalized = (platform or "").lower()
        if normalized not in {"wechat", "douyin"}:
            raise ValueError("platform must be one of: wechat, douyin")
        if not wall_street_since_upload_date or len(wall_street_since_upload_date) != 8:
            raise ValueError("wall_street_since_upload_date must be YYYYMMDD")
        if limit is not None and int(limit) < 1:
            raise ValueError("limit must be at least 1 when specified")
        safe_limit = min(int(limit), 5000) if limit is not None else None

        text_expr = (
            "lower(COALESCE(pv.title, '') || ' ' || COALESCE(pv.zh_title, '') || ' ' || "
            "COALESCE(pv.category, '') || ' ' || COALESCE(rc.channel_name, pv.channel_id, ''))"
        )
        speech_clause = " OR ".join(f"{text_expr} LIKE ?" for _ in self._BACKFILL_SPEECH_TERMS)
        speech_params = [f"%{term.lower()}%" for term in self._BACKFILL_SPEECH_TERMS]

        source_status_clause = "pv.status = 'WECHAT_DEFERRED'"
        platform_state_expr = "NULL"
        platform_filter = ""
        if normalized == "douyin":
            source_status_clause = "pv.status IN ('PUBLISHED', 'WECHAT_DEFERRED')"
            platform_state_expr = """
                (
                    SELECT dp.state
                    FROM douyin_publications dp
                    WHERE dp.video_id = pv.id
                    ORDER BY dp.attempt_number DESC, dp.id DESC
                    LIMIT 1
                )
            """
            platform_filter = """
                AND NOT EXISTS (
                    SELECT 1 FROM douyin_publications dp_block
                    WHERE dp_block.video_id = pv.id
                      AND dp_block.state IN ('QUEUED', 'UPLOADING', 'DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'UNCERTAIN', 'BANNED', 'CANCELED')
                )
            """

        query = f"""
            SELECT
                pv.youtube_id,
                pv.slice_index,
                pv.title,
                pv.zh_title,
                pv.channel_id,
                COALESCE(rc.channel_name, pv.channel_id) AS channel_name,
                pv.category,
                pv.upload_date,
                pv.status AS wechat_status,
                pv.score,
                CASE WHEN {speech_clause} THEN 1 ELSE 0 END AS is_speech_or_interview,
                CASE
                    WHEN lower(COALESCE(rc.channel_name, pv.channel_id, '')) = 'wall street truthbombs'
                     AND pv.upload_date >= ?
                    THEN 1 ELSE 0
                END AS is_recent_wall_street,
                {platform_state_expr} AS platform_state
            FROM processed_videos pv
            LEFT JOIN recommended_channels rc ON rc.channel_id = pv.channel_id
            WHERE {source_status_clause}
              AND pv.youtube_id NOT IN (SELECT youtube_id FROM blacklisted_videos)
              AND pv.channel_id NOT IN (SELECT channel_id FROM recommended_channels WHERE status = 'BLACKLISTED')
              AND (
                    ({speech_clause})
                 OR (
                    lower(COALESCE(rc.channel_name, pv.channel_id, '')) = 'wall street truthbombs'
                    AND pv.upload_date >= ?
                 )
              )
              {platform_filter}
            ORDER BY
                is_recent_wall_street DESC,
                CASE WHEN platform_state IS NULL THEN 0 ELSE 1 END ASC,
                pv.upload_date DESC,
                pv.updated_at DESC,
                pv.id ASC
            {"LIMIT ?" if safe_limit is not None else ""}
        """
        params: List[Any] = [
            *speech_params,
            wall_street_since_upload_date,
            *speech_params,
            wall_street_since_upload_date,
        ]
        if safe_limit is not None:
            params.append(safe_limit)
        with self.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def delete_video_record(self, youtube_id: str, slice_index: Optional[int] = None) -> bool:
        """物理删除视频记录。如果 slice_index 传入 None，删除父及所有关联子视频；否则只删除单切片。"""
        # [Gemini_3.5_Flash_planning] 支持分级删除。级联删除靠 FOREIGN KEY ... REFERENCES ... ON DELETE CASCADE 实现
        with self.get_connection() as conn:
            try:
                if slice_index is None:
                    conn.execute(
                        "DELETE FROM processed_videos WHERE youtube_id = ?",
                        (youtube_id,)
                    )
                else:
                    conn.execute(
                        "DELETE FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                        (youtube_id, slice_index)
                    )
                conn.commit()
                return True
            except Exception as e:
                self._logger.error(f"delete_video_record failed for {youtube_id} (slice {slice_index}): {e}")
                return False

    def delete_slices_by_parent_id(self, parent_id: int) -> bool:
        """[Unknown_Model_planning] 物理删除指定父任务关联的所有子切片任务。"""
        with self.get_connection() as conn:
            try:
                conn.execute(
                    "DELETE FROM processed_videos WHERE parent_id = ?",
                    (parent_id,)
                )
                conn.commit()
                return True
            except Exception as e:
                self._logger.error(f"delete_slices_by_parent_id failed for parent {parent_id}: {e}")
                return False

    def batch_delete_video_records(self, youtube_ids: List[str], tombstone: bool = True) -> tuple[int, List[str]]:
        if not youtube_ids:
            return 0, []

        deleted = 0
        failed: List[str] = []
        with self.get_connection() as conn:
            try:
                if tombstone:
                    for yid in youtube_ids:
                        conn.execute(
                            "INSERT OR IGNORE INTO blacklisted_videos (youtube_id, reason) VALUES (?, ?)",
                            (yid, "user_deleted")
                        )
                placeholders = ",".join(["?"] * len(youtube_ids))
                cursor = conn.execute(
                    f"DELETE FROM processed_videos WHERE youtube_id IN ({placeholders})",
                    youtube_ids
                )
                deleted = cursor.rowcount
                conn.commit()
            except Exception as e:
                self._logger.error(f"batch_delete_video_records failed: {e}")
                failed = list(youtube_ids)
        return deleted, failed

    def add_to_blacklist(self, youtube_id: str, reason: str = 'user_deleted') -> bool:
        with self.get_connection() as conn:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO blacklisted_videos (youtube_id, reason) VALUES (?, ?)",
                    (youtube_id, reason)
                )
                conn.commit()
                self._logger.info(f"[Blacklist] Added: {youtube_id} ({reason})")
                return True
            except Exception as e:
                self._logger.error(f"add_to_blacklist failed for {youtube_id}: {e}")
                return False

    def is_blacklisted(self, youtube_id: str) -> bool:
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM blacklisted_videos WHERE youtube_id = ?",
                (youtube_id,)
            )
            return cursor.fetchone() is not None

    def remove_from_blacklist(self, youtube_id: str) -> bool:
        with self.get_connection() as conn:
            try:
                conn.execute(
                    "DELETE FROM blacklisted_videos WHERE youtube_id = ?",
                    (youtube_id,)
                )
                conn.commit()
                self._logger.info(f"[Blacklist] Removed from blacklist: {youtube_id}")
                return True
            except Exception as e:
                self._logger.error(f"remove_from_blacklist failed for {youtube_id}: {e}")
                return False

    def update_process_pid(self, youtube_id: str, pid: Optional[int], slice_index: int = 0) -> None:
        """记录或清除特定切片视频关联的处理进程组 ID。"""
        # [Gemini_3.5_Flash_planning] 定位增加 slice_index = ?
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET process_pid = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ?",
                (pid, youtube_id, slice_index)
            )
            conn.commit()

    def update_video_censor_status(self, youtube_id: str, tag: Optional[str], score: Optional[int], slice_index: int = 0) -> None:
        """更新特定切片的违禁词过滤状态。"""
        # [Gemini_3.5_Flash_planning] 定位增加 slice_index = ?
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET censor_tag = ?, censor_score = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE youtube_id = ? AND slice_index = ?",
                (tag, score, youtube_id, slice_index)
            )
            conn.commit()

    def set_manually_scored(self, youtube_id: str, locked: bool = True, slice_index: int = 0) -> None:
        """设置或解除特定视频/切片的人工评分锁。"""
        # [Gemini_3.5_Flash_planning] 定位增加 slice_index = ?
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET is_manually_scored = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE youtube_id = ? AND slice_index = ?",
                (1 if locked else 0, youtube_id, slice_index)
            )
            conn.commit()
