# 视频号商品池与 L1 内容匹配

作者：Codex。2026-11-02。批准规格：[2026-11-02 规格](../specs/wechat-product-pool-content-match-2026-11-02.md)。

新 AUTO 任务使用 `wechat-product-content-match-v1`。目录必须完整、受控采集凭证与原始目录 SHA-256 一致、稳定发布账号一致、7 天内且明确可售。库存为零、下架、未知可售、人工停用和身份冲突均排除。凭证单独保存在 `config/wechat_product_catalog.live.json`；普通人工 v2 导入本身不提升 live 状态。

`config/wechat_product_matching.json` 保存精确 ID、全名和双语主题短语。标题 4 分、对白字幕 2 分、主题/标签 2 分、分类支持 1 分；每字段最多计两个不同特定短语，同一短语重复不加分。最低 4 分且须有特定主题命中。同分按 ID/全名稳定排序，最多 3 个候选。英语世界的精确快捷英语身份可优先，但同样受商品池约束；无相关候选写 `MATCH_EMPTY`。本期无 LLM 或付费调用。

普通流水线读取对应 `youtube_id_sN` 的标题和 ASS 对白；词汇卡及绘图不计入。英语世界读取审核包哈希绑定的标题、清单、展示计划和本分片时间线，证据不足时不借用父片字幕。冻结记录保存内容/策略/匹配配置/目录/凭证摘要及打分理由。旧任务原样重放，执行前最新负面证据只能否决，不能扩充或替换原候选。

商品操作继续共享 30 秒内的选品和清理预算，实际绑定仍须 ID 与完整标题一致。无候选或挂载失败可以在确认清空和表单就绪后无商品继续；显式 `require_bound` 仍要求实际绑定。选品 BOUND 仅表示表单绑定，不能当成平台受理、发布成功或播放页商品展示。

## 同步与调度

```sh
# 仅本地检查，不访问平台
.venv/bin/python scripts/sync_wechat_product_catalog.py --status
# 一次正常受控只读同步；不自动重试，不写回 Cookie，不恢复登录
.venv/bin/python scripts/sync_wechat_product_catalog.py
```

每日本机时间 07:35 的受管 cron 由 `scripts/manage_wechat_catalog_schedule.py` 在本任务维护窗排空后安装；原 cron/launchd 和运行意图保存在工作区外，CAS 与完整回读通过才记录正常运行意图。同步用途 `catalog_sync` 独立限制为滚动 24 小时 2 次、至少间隔 6 小时，原六类操作额度不变；共享账号退避、登录失效、物理会话锁和发布优先级继续有效。单次启动及采集共用最多 60 秒，预留关闭和回执时间，最多 20 页。

目录过期的新任务冻结前可尝试刷新一次，须先于发布会话锁；已冻结任务不重刷。在途发布会话内跳过同步。失败或被阻挡时保留 `output/wechat_catalog_sync/<attempt>/receipt.json`，不覆盖旧目录、不更新旧目录日期。缺稳定公开账号标识、完整遍历或可售证据时只能报告 partial；禁止用昵称、本地 profile 哈希或旧 HTML 自证成功。当前公开 DOM 选择器仍需实机验证，不能因合成浏览器测试通过而声称平台采集成功。

完整采集才走原 `import_catalog` 的策略/目录锁、CAS、冲突检查及旧快照归档。目录和凭证之间若并发变化，摘要不一致即闭锁。原 `wechat_product_catalog_history`、`wechat_product_catalog_live_history` 和尝试回执长期保留。

## 验收与观察

隔离测试入口如下。不要在生产直接运行 pytest。

```sh
.venv/bin/python scripts/run_isolated_tests.py -- -q tests/unit/test_wechat_product_*.py tests/unit/test_wechat_catalog_import.py tests/unit/test_wechat_catalog_schedule.py tests/unit/test_product_final_receipts.py tests/unit/test_english_preferred_product.py tests/unit/test_wechat_operations_policy.py
.venv/bin/python scripts/run_isolated_tests.py --browser -- -q tests/browser/test_wechat_product_picker_browser.py tests/browser/test_wechat_product_catalog_browser.py
.venv/bin/python scripts/replay_wechat_product_matches.py --input /absolute/replay-inputs.json --output /absolute/report.json --historical-hypothesis
```

离线报告以 `strict_current_pool` 为验收口径。`historical_hypothesis` 明确忽略 TTL 与当天可售证据，只帮助解释规则，不能称为当前命中或绑定能力。原冻结决定不变，回放不触发发布。

恢复后观察自然发生的至少 10 次新合同发布流程，分别统计 BOUND/总流程、BOUND/实际尝试、安全无商品和原因。样本不足标待观察；不为补样本发布，不重试已受理、已发表或 UNCERTAIN 历史任务。平台受理、作品管理回读、播放页商品展示需分别有证据。

## 回滚

进入自己的维护窗并自然排空后，将匹配配置 `enabled` 改为 false，可让后续新任务恢复旧准入版本；已冻结任务保持原样。移除受管 cron 也须沿用快照、CAS 和运行意图回读，不能直接留下调度漂移。不要删除目录、凭证、失败记录、历史快照、数据库或任何 output 数据。

## 2026-11-02 发布页滚动列表适配

每日 07:35 继续使用原生同步入口，成功原子更新，失败保留旧缓存和原 captured_at；7 天 TTL、2 次/24h、6 小时间隔、60 秒以及 20 步上限不变，不增加自动重试。线上商品可售与本地缓存过期是两个不同事实。

公开总数存在时仍核对分页和计数。公开总数缺失时，只支持同一 ant-table-wrapper 内分离表头、非虚拟 ant-table-body 的未筛选列表：两次从顶到最终底部，等待加载器消失及底部稳定，商品 ID、标题、库存和可售状态全量一致才接受遍历。任何分页候选、虚拟列表标记、非空筛选、身份冲突或预算耗尽均拒绝晋升。total_items 表示本次遍历的去重数量，不宣称是平台显式总数；凭证明确 explicit_total=false 并保存遍历摘要、步数和终点几何。该判据是对已知公开 DOM 的有界观察，未知结构不能套用。

账号使用首页公开“视频号ID”节点 `.finder-uniq-id-wrap .finder-uniq-id[data-clipboard-text]`，可见文本必须与复制属性相同。同一独立浏览器上下文中，采集前后通过公开“首页”菜单回读一致才入库；关闭商品弹窗只点“取消”，不选商品、不添加、不保存或发布，不读写 Cookie/storage_state、不登录。昵称与本地profile均不作身份。

历史来源分别见 tests/fixtures/wechat_catalog_public_dialog_20261010.json 和 wechat_catalog_home_identity_20260523.json。旧HTML只证明选择器来源；离线通过和部署完成均不代表已取得新鲜 live 商品池。下一次预算允许的正常同步仍需回执证明 COMPLETE 和 live_verified。
