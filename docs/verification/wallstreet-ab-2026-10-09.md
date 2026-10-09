# 华尔街二创与配对机制验收记录

作者：Codex；日期：2026-10-09。宿主模型身份未另行核验。本记录区分代码采用、成片验收和平台后台发布证据。

## 固化范围

采用已获用户批准的 `insight-editorial-mobile-2`：完整保留原片；中英字幕保留重点词与释义，取消独立生词列表；字幕根据真实语音对齐显示指读下划线；二创正文采用手写圈画，禁止指读效果。头部、正文、底部明确分区，必要信息避开手机状态栏和平台简介区；口号上移至右侧；源视频上沿保留 1 像素进度条；结尾邀请自然评论。

豆包缓存验收绑定实际音色、语速和音效参数；新增分析只接受 V2 引证脚本，不回退旧版或裁掉原片。事实疑点留证供审核，不作为普通 A 的发布阻断条件；现行平台内容闸门继续执行。视觉规格见 `docs/specs/masterpiece-visual-quality.md`，配对规格见 `docs/specs/wallstreet-paired-ab.md`。

## 程序化机制与运行边界

目标频道使用稳定频道 ID `UCTK_cv-y88CScoudcXnS1Ew`。A 素材准备完成后，持久队列登记独立 B；B 失败或等待不影响 A。各版本分别保留资产、投稿记录、平台原生作品 ID。正常配对 B 在同平台 A 确认公开后至少等待 6 小时提交。提交结果不明时只读回查，不盲目重传。

复用现有每分钟调度和发布执行者，按需启动二创执行者；不依赖打开 Codex。需要主机、既有调度、登录会话、策划/配音和渲染依赖可用。试验已激活，激活时刻 `1791479000.786148`；20 组完整 PAIRED 为复盘节点。本次具名授权单条 B_ONLY，不计入完整配对数；截至本记录，完整配对数为 0。

自动审批曾拒绝将真实字幕发送给现有 AGY 服务，理由是尚无该外部发送的明确授权。未重试该请求、未切换供应商绕过。本条改用本地审核的 V2 脚本完成，AGY 独立语义复核未调用。

新增 `WALLSTREET_AB_REMOTE_PLANNING_AUTHORIZED=false` 默认保护：新 B 正常入队；缺脚本时记录 `REMOTE_PLANNING_APPROVAL_PENDING`，等待明确授权，A 继续运行；已有本地审核脚本可加工。配置启用必须等用户回复此前授权问题。该边界意味着当前尚不能宣称未来全部 B 已自动策划。

## 最新二创成片

- 源视频：`h7rY4nSB2tM`，THE 84-MONTH TRAP: Why Car Loans Are Becoming the New Subprime Crisis!
- 原片 604.736 秒，成片 629.867 秒，1080×1920、30 fps、H.264/AAC；片头 15.5 秒，片尾约 9.6 秒。
- 六个分析点绑定原字幕引文；本地 ASR 1331 词、末词约 598.46 秒，字幕全局对齐 191 页。
- 全片实际解码通过；实际编码成片的片头、两处分析正文、片尾四个抽帧已查看；双比例专门封面已查看。
- 成片 SHA-256：`3006bed0a4cbe176ae469462971242dd8d4cc1a0106521ccb6422e75a880de07`。
- 成片：`/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/wallstreet_ab/1/insight-editorial-mobile-2/editorial.mp4`。

## 平台后台发布证据

视频号：原生 ID `export/UzFfBgAAxP2lfBtHSEmik8zT4DCa-YZH7VIqhX5rHv0kq-M6BQ`，状态 PUBLISHED。证据：`output/wallstreet_ab/1/insight-editorial-mobile-2/recovery/1791482413/management_readback.json`。通过精确作品 ID 绑定，真实组件同时证明 posted、process_success、可见 posted-info 和公开权限，且非处理中、非定时。未猜测 API 数字状态含义。

抖音：原生 ID `7694353709907725587`，状态 PUBLISHED。证据：`output/wallstreet_ab/1/insight-editorial-mobile-2/recovery/1791482605/douyin_management_readback.json`。完整标题和文案精确绑定 API 的字符串作品 ID，再核验同一文案的管理卡片已发布状态；保留平台真实换行序列兼容，不采用浮点截断作品 ID 或共享标题模糊匹配。

两项公开时间均为首次后台观察时刻（视频号 `1791482442.636426`，抖音 `1791482613.6860611`），不能当作平台原生发布时间。独立手机播放和公开页面可见性尚未另行核验。

## 测试与数据边界

- 发布绑定、回读与执行者：150 项通过，证据 `/private/tmp/video-pytest-9uzous1f/pytest.log`。
- 抖音真实序列化文案状态匹配：94 项通过，证据 `/private/tmp/video-pytest-g8964r6n/pytest.log`。
- 待授权策划保护和配对 DAL：17 项通过，证据 `/private/tmp/video-pytest-w1f_lfup/pytest.log`。

以上均由项目隔离测试入口运行，数量存在范围重叠，不累加为总覆盖数。平台回读是独立运行证据。

指标目前支持绑定真实原生 ID 的后台快照导入，未实现自动抓取。分别记录每版公开后 24/72/168 小时的播放、点赞、评论、转发、收藏；缺失值保持 null，同一时点累计值更新而不相加。只有原生平台时间和接近目标年龄的数据才标为可比较；固定先 A 后 B 仍存在时效和受众重叠偏差。当前没有配对互动数据，不能宣称哪版效果更好。

生产 `main` 与 `origin/main` 已采用并推送运行代码提交 `c77dbeda7e2ff23eab07babf9ee04f305f86e192`；新发布执行者 PID 33886 的 `output/ready_publications_status.json.git_revision` 精确回读该提交，阶段 IDLE，心跳约 2 秒。运行设置确认 `remote_planning_authorized=false`。后续文档修订不代表执行代码再次变化；运行代码版本以 `git_revision` 为准。上线命令及人工单条提示词分别见 `docs/guides/wallstreet-ab-operations.md`、`docs/guides/masterpiece-publish-prompt.md`。


## 2026-10-09 授权恢复、真实策划与上线修复

用户在明确说明现有 AGY 将接收目标频道公开视频标题、字幕和二创脚本的询问后回复“继续”；已记录具名范围并将生产非敏感开关启用为 true。自动审批已接受本次调用，前述待授权状态是历史记录。授权证据为 `output/wallstreet_ab/authorization-2026-10-09/authorization.json`；既有调度已启动读取 true 的二创短进程，无须 Codex 会话。

同一完整字幕首次使用普通 45 秒预算超时；遵守缓存冷却后，现有 AGY 的真实诊断调用在 80.984 秒返回 V2 结构化策划，独立复核在 39.416 秒返回结构化疑点。维护代码增加二创专用 `WALLSTREET_AB_PLANNING_TIMEOUT_SECONDS=180`（45–300 秒有界），普通 A 仍用原 45 秒预算。没有切换供应商或清除冷却。诊断为 `output/wallstreet_ab/authorization-2026-10-09/provider_diagnostic.json`。

原双语 ASS 的翻译在相邻英文事件中交错，导致跨事件英语引文误判。现按引文语言提取字幕，排除注释和独立 GlossaryCard，同时保留词序、数字及否定；复核缓存版本改为 `insight-advisory-1.1`。真实候选六条引文均匹配，但独立语义复核仍指出五个范围、数值或动机疑点，状态 NEEDS_REVIEW，publication_blocked=false。该诊断候选保存在授权目录，不替换或重发此前本地审核并发布的成片；引文对应不等于事实正确。

在当前生产 main 源码上通过项目隔离测试入口：64 passed in 27.58s，日志 `/private/tmp/video-pytest-6j5v6y88/pytest.log`，覆盖 B 独立预算、普通 A 预算、双语引用、否定与数值变更及现行 V2 加工回归。保留同期其他任务已提交的 TED 与手写视频修改，以及无关未提交文件。

最新只读视频号回查为 PUBLISHED，精确作品 ID 与前述一致：`output/wallstreet_ab/1/completion-audit/1791527799/wechat/management_readback.json`。抖音常规回查 exit 4 是管理页熔断，不是登录失效；其失败历史属于其他普通作品的回读。按维护的非最终恢复校准入口，只读同一已绑定原生作品，回查 exit 0、PUBLISHED、API_EXACT_DESCRIPTION，原生 ID `7694353709907725587`：`output/douyin_calibration/wallstreet-completion-1791531118/douyin_management_readback.json`。凭同次真实管理控件证据由维护脚本解除 management_verify；保留失败历史，不上传、不点击发布、不重置作品账本。

截至此次收尾，只有一条 B_ONLY，完整 PAIRED 为 0；目标频道最新已准备素材仍为 h7rY4nSB2tM，其他近期合格 A 在试验启用前已有投稿。不能把这些历史 A 自动补发、把 B_ONLY 改成配对，或缩短已确认 6 小时间隔。代码和最新单条交付已具备证据；首组正常 A/B 的真实平台配对回读及后续 24/72/168 小时真实读数仍需合格新视频入组，实验验收尚未完全完成。
