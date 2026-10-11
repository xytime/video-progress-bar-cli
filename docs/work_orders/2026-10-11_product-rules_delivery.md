# 商品挂载规则开发交付与上线检查

2026-10-11，开发责任：Codex。规格见 `2026-10-11_youtube-like-rate-product-gate.md`。
本文是代码与隔离测试交付记录；生产部署、平台受理、作品管理回读、播放页挂载各自需要新证据。

## 已实现的行为

- 自动英语世界首条按 Asia/Shanghai 正式制作登记。候选、来源预检、影子运行和手动 NONE/PRODUCT 不计数。首条失败或跨日重试不转让原名额。
- 其他自动 YouTube 任务用源 view_count/like_count 原值判断 >=10%；未知或非法跳过。非有限 float 保留明确字符串和类型标记，完整冻结、写出与子进程读回不会变成 0 或导致发布失败。
- 新手动入口默认显式 NONE；选择商品写入精确 ID/全名，子片继承，不使用自动备选或默认书替换。
- DAL 加法迁移保留历史任务 AUTO；正式制作记录并发事务只产生一条首条。商品决策独立冻结，配置保存不改已冻结任务。
- 通用发布、独立英语世界、华尔街独立微信 B 都给上传器传 `--product-task-decision`。旧全局开关或 `--require-product` 不覆盖明确 NONE。跳过仍核实表单无残留；要求商品必须核实真实 ID/全名及最终绑定。
- 商品等待由实际发布入口消费；SQL 在 LIMIT 前排除整个仍退避、已阻断或检查达限的等待集合，两条队列后续正常任务可以继续。
- 预览显示原指标、意图、业务日与首条身份；冻结实际决定与当前配置模拟分别显示。保存影响分别展示候选链变化和实际新选品影响。

共享依赖：`scripts/web/pipeline_manager -> utils.wechat_product_task/execution/context -> core.wechat_product_attachment/policy + db.PipelineDB`。纯规则不依赖外层脚本；SQL只在 DAL。

## 商品来源与实际限制

历史目录中可靠的精确 ID/全名可显式选择，界面标为“待当前会话核验”。没有发布账号的历史目录不宣称实时全量、所属账号 VERIFIED 或已挂载；商家 AppID 不能代替发布账号 ID。明确跨账号资料冲突、停用及无法取得精确身份的条目仍拒绝新入队。

当前同一受控发布会话必须用平台公开“请输入商品名称/编码搜索”控件筛选，回读商品行完整 ID/全名、单选可用性，并完成绑定卡片实际身份回读。`radio.value` 和 `data-row-key` 与实际商品 ID 不一致，不能拿它们作身份。

已有公开历史绑定卡片只提供书名时，仍无法证明实际商品 ID；选择器保持阻断。浏览器测试提供的 data-product-id 或商品链接是合成 DOM 的协议用例，不证明视频号当前真的提供该字段。上线后需捕获当前公开 DOM 并确认可靠绑定字段，再以原生作品 ID 回读作品和播放页；本交付未执行真实上传/发表。

每日范围采用实际 `wechat_state.json` 路径的哈希作为内部受控 profile scope，不读取登录态、不声称平台账号已识别。换发布账号应另用受控 profile 路径；复用旧路径换账号需要运营重新确认范围，不能自动猜账号身份。

## 旧英语世界包兼容

首次数据库迁移记录当时已存在审核项的 review_id + manifest_sha256 白名单，随后写一次性 `legacy-review-cutover-v2` 哨兵。重启不扩大白名单，修改同 review_id 的包摘要不继承兼容。

仅白名单中完全未带 product_context 的旧包，经原授权、内容审核、产物校验和去重门禁后明确不补挂，也不占新首条；状态不因迁移改变。新制作包必须正式登记，缺少、损坏或伪造上下文阻断。三条新自动规则适用于上线后开始正式制作的新任务；既有已受理、审核中、不明结果禁止因新规则重传。

## 等待与运营处理

只有明确尚未点击发表的商品失败可回原 PENDING / SUBMISSION_APPROVED，授权、原商品、成片和尝试历史保留。已有原生提交 ID、submission_receipt 或结果不明保留停止重传状态。

库存、商品额度及可用性暂未证实进入 WAITING，按已保存 wait_policy 退避，最多检查次数；到期重新核验同一冻结决定。可靠目录/配置观察代次更新可以开启一轮有界检查。登录错误沿用原登录恢复；代码不推测平台额度或恢复时间。

人工商品入队后停用、归属冲突或身份失去可靠证据，冻结原 ID/全名并写 BLOCKED，不换书、不上传。库存旧快照为0保留原身份，实际平台核验后等待。绑定在最终提交前改变，同样明确 BLOCKED。

查看入口：后台商品设置“等待与恢复”，或只读 `GET /api/product-settings/waits`。BLOCKED 当前没有安全的“强制恢复/重置”API或按钮；重新启用配置不会自动解除已经冻结的阻断。

工程师接手 BLOCKED 必须先核实：原任务未受理/无不明结果、原视频/文案/封面摘要未变、原 ID/全名和当前会话归属已可靠恢复、原授权仍有效。需要增加受控同任务恢复入口，保留冻结业务决定和历史、重新验证原商品后才交回既有门禁。本版没有该入口，不提供删账本、删除冻结决定或改已受理终态的操作。无法满足这些条件应继续保留 BLOCKED。

## 上线与只读运行采用核验

1. 独立审查最终提交；在纯工作树叠加原运营商品配置及无关生产改动做联合回归，保护原配置和现有目录。
2. 仅任务空闲且取得既有加工、发布、浏览器、启动互斥时切换；备份数据库及 owned UI 改动。迁移只加字段/表并记录旧包白名单，不重新登记老成片或改已有受理状态。
3. 重启 9100 后台和长期 `scripts/run_ready_publications.py` 进程；只重启后台不能证明发布执行者已加载新代码。
4. 只读 `GET /api/product-settings/runtime`：核对 loaded_revision、publisher_capability、attachment_version、当前 config_digest/version 与内部 scope。该接口不创建任务、不计首条、不写采用。
5. 读取 output/ready_publications_status.json：核对 git_revision、product_publisher_capability、product_attachment_version、product_config_digest/version、profile scope 和新心跳。能力字段是加载证据，不是挂载成功。
6. `GET /api/product-settings` 的 runtime_adoption_verified 仅对当前能力、当前摘要且终态 BOUND/严格 SKIPPED 的采用证据为真；STARTED、BLOCKED、旧版本或旧能力均为假。actual_binding_verified 单独表达真实绑定回读。

回滚先暂停并停发布执行者，保留新增表、冻结决定、等待记录和实际提交证据。旧代码不理解显式 NONE，不能直接让旧执行者消费新任务。不要还原数据库到提交前快照而抹掉上线期间的新受理记录；修复兼容后再恢复调度。

## 华尔街独立 B 补充与入口范围

华尔街 B 使用内部发布实体主键 `wallstreet:wechat:B:<publication_id>`，读取原 YouTube 视频/分片的源指标、类型及人工意图。B 的状态来自独立发布账本，不把已发布 A 的状态当成 B 已受理。内容/封面门禁完成后先冻结、检查商品退避，再进入原 A 已公开加6小时、窗口、暂停、去重和一次性抖音票据门禁。等待项继续扫描，不阻塞下一条 B。

每次领取使用独立 evidence 目录，保存 attempt_claim.json；商品契约输入不写进上传证据目录。退出14只有同一尝试、任务/配置摘要一致、真实产物与投稿包摘要未变、明确 NOT_SUBMITTED 且无提交或管理回读回执时，才由 DAL 恢复 WAITING。次数和每次证据保留。已有 native ID、缺失等待证据或接受回执商品身份不符转 UNCERTAIN，停止重传。只读 B 回查兼容旧目录和新尝试目录的提交 nonce 回执。

华尔街执行者由 ensure_wallstreet_worker 启动一次性进程；部署也须等已有华尔街执行进程退出或受控停止，下一次进程才加载新代码。本补充没有新增数据库表、改变现有 A 状态或抖音投稿行为。

其余 direct uploader 调用的只读审计：run_publication_window、PipelineManager 的 reconciliation 及 run_wallstreet_ab 的 reconcile/bind 均为 verify-only；web/app 和 bot 的登录入口为 login-only。这些不进行商品选择。bot/pipeline_agent.upload_to_wechat、pipeline_handwritten_pager、HighlightPublisher.submit、DubbingService.publish 是独立具名人工上传/审批入口，仍沿用既有上传器商品配置，不是本次自动候选调度链；本交付没有宣称它们已消费 v2 或具有后台添加视频的默认 NONE 行为。直接 CLI 也须显式传冻结契约才适用本次任务规则。

## 隔离测试证据

- 华尔街 B 补丁最终28文件联合：652 passed、2条既有 FastAPI 废弃提醒，probe/pytest exit 0，`/private/tmp/video-pytest-myabiiv2/pytest.log`、receipt.json。包含下述25文件及 test_wallstreet_product_contract/test_wallstreet_experiment/test_wallstreet_worker；新增26例验证9.99%/10%/缺指标、手动NONE/精确PRODUCT、已发布A与独立B状态、14严格恢复、16种冲突证据拒绝、退避到期/公平性、停用前置阻断及抖音/只读入口保持。
- 最终核心与治理 25 文件：597 passed、2条既有 FastAPI 废弃提醒，probe/pytest exit 0，`/private/tmp/video-pytest-etnn373e/pytest.log`；完整命令和源摘要在同目录 receipt.json。包含首次旧包迁移4并发初始化与重启不扩大白名单、同一任务8并发冻结、两条队列等待公平性、停用/身份冲突阻断及非有限指标完整写出/子进程读回。
- 最终真实 Chromium UI/选择器联合：89 passed，probe/pytest exit 0，`/private/tmp/video-pytest-7wipfq06/pytest.log`，Chromium 148.0.7778.96。包含搜索跨页、明确空态、重复/冲突 ID、禁用行、完整商品列表搜索、默认 NONE、手动传播、冻结预览、移动端和错误恢复。此轮后仅补强数据库首次迁移事务与对应测试，前端和选择器源码未再变化。
- 补充原声明与队列治理 2 文件：15 passed、2条既有 FastAPI 废弃提醒，probe/pytest exit 0，`/private/tmp/video-pytest-bbo_e9qs/pytest.log`；也包含在上述最终25文件联合中。
- 英语世界链独立回归：214 passed，probe/pytest exit 0，`/private/tmp/video-pytest-u29ee50f/pytest.log`；已包含在最终核心联合的相关入口回归中。

所有 pytest 使用 `.venv/bin/python scripts/run_isolated_tests.py`，浏览器使用 `--browser`。各证据目录 receipt.json 保存完整参数、源摘要、探针和 pytest 退出码。操作系统边界探针先通过，未读写生产数据库/登录态、未上传或发表。
