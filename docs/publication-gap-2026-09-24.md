# 2026-09-24 自动发布稀少：调查与修复证据

## 目标作品

- YouTube `IdzwLrRQN5o` 于 2026-09-23 21:00 北京时间以 `source=AUTO` 入库。评分日志显示原始 55，可信频道保底后为 80。
- 重型加工受 MarketGuard 在 20:30–04:15 北京时间保护；就绪 worker 于 2026-09-24 04:54 开始提交，04:56 获得视频号受理回执。数据库保持 `SUBMITTED_BOUND`，这只证明已受理且有绑定回执，不证明公开。
- 只读作品列表在 05:30 显示短标题“原油跌破百元柴油创历史新高”的卡片，`objectId=export/UzFfBgAAxNGkGDg7bljRk8zT4DCa89RMPCmtpbp__gysY3wXZw`，`createTime=2026-09-24 04:58:34`，状态数值 1，已有播放与评论；原受理回执却绑定 `export/UzFfBgAAxKqmKF0rNVvRk8zT4DCaqBmZJY2bOdt6wDM-VnAMvQ`。按回执 ID 的只读回查返回不确定，不能据短标题改写账本，也不能据播放量认定该回执对应的公开视频。
- 平台 `post_list` 当前将 `desc` 返回为含 `shortTitle` / `description` 的对象。旧解析把整个对象转为字符串，而绑定逻辑对 API 记录允许“唯一新增 ID”绕过标题核对。这是原生 ID 误绑风险。修复后必须同时满足同次会话唯一新增 ID 与精确短标题；证据不足保留 `SUBMITTED_UNBOUND`，禁止自动重传。

## 9 月 22–23 日北京日期漏斗

以下读取 2026-09-24 05:37 左右的 SQLite 快照；分数、人工锁定和状态是**读取时当前值**，不代表入库时历史快照。

| 入库日 | AUTO 入库 | 当前分数达频道门槛且未人工锁定 | 其中当前失败 | 当日平台 ID 已绑定受理尝试 |
| --- | ---: | ---: | ---: | ---: |
| 09-22 | 48 | 6 | 1 | 5（均为 AUTO 入库，实际触发者未知） |
| 09-23 | 71 | 8 | 3 | 5（其中 1 条已人工评分锁定，其余触发者未知） |

`source=AUTO` 仅表示发现入口，不能证明处理、提交由调度器触发。新 `publication_trigger_events` 从修复生效后记录 cron、dashboard 定时器、就绪 worker、后台准备和人工入口；日报按投稿尝试发生日将受理分为“已证实自动”“人工参与”“旧记录未知”。历史数据不回填为自动。

## 频道产出（09-22 至 09-23 入库，当前评分）

| 已批准频道 | AUTO 入库 | 达当前门槛且未人工锁定 | 备注 |
| --- | ---: | ---: | --- |
| Bloomberg Television | 35 | 0 | 另有已受理项，但当前有人工评分锁定，不能算自动产出 |
| TEDx Talks | 25 | 1 | 门槛 40，仍仅 1 条合格 |
| BNN Bloomberg | 24 | 0 | 门槛 75，零合格 |
| C-SPAN | 20 | 7 | 其中 2 条当前失败，策略闸门不能绕过 |
| Hoover Institution | 3 | 2 | 其中 1 条当前失败 |
| Wall Street Truthbombs | 2 | 2 | 样本太小，不据此扩量 |

建议先将 BNN Bloomberg 和 TEDx Talks 的自动发现改为影子监测，保留历史账本；对数据库中尚为 `PENDING` 的 Bloomberg Originals、Financial Times、The Wall Street Journal 做同门槛影子采集和受众/版权检查，再决定是否替换。此处未修改频道白名单，也未降低内容或审核门槛。

## 运行约束与验收

- 保留 OptionSense MarketGuard 重型加工时段，不为追求发布量提前抢占资源。
- 保留 `WECHAT_REVIEW_MAX_PER_RUN=0`，因为原回执 ID 与当前列表 ID 不一致，且平台数值状态尚无可审计语义映射。先修正未来受理绑定并做只读影子校准，再考虑单轮小批量回查。
- 单元隔离测试覆盖 AUTO/人工/未知三类归因、原生 ID 精确绑定与旧记录不回填；平台公开视频状态另以精确 ID 回读验证。
