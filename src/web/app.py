"""Web 控制中心后端 — FastAPI 仪表盘服务

| video-review-origin-v1 | 2026-10-25 | Codex | 修复受保护 HTTPS 控制台单条复核的 Origin 拒绝，并为 CP/P1/P2 批准留审计。 |
| english-public-origin-v1 | 2026-10-25 | Codex | 仅允许配置的受保护 HTTPS Origin 访问英语世界路由；其它配置页边界不变。 |
| english-workbench-v1 | 2026-10-25 | Codex | 注入英语世界桌面研究、制作、审核投稿与具名待审核续做执行器。 |
| proxy-peer-v1 | 2026-10-25 | Codex | 禁用 Uvicorn 转发头改写，保留英语世界本机边界使用的真实连接对端。 |
| demand-keepalive-v1 | 2026-10-25 | Codex | 按真实认证证据排期、跨重启退避与准确的准入等待原因。 |
| publishing-recovery-v1 | 2026-10-23 | Codex | 接入持久恢复批次，旧批量重试入口改为固定范围确认。 |
| manual-login-v1 | 2026-10-22 | Codex | 人工单次扫码恢复保留账户互斥与限流即停，不恢复发布队列。 |

| 3.57.0 | 2026-10-18 | Antigravity | 修复看门狗空字典恒真判锁 Bug；新增重登失败指数退避与回退探测防饿死机制；整轮异常保护与调度心跳记录。 |
| 3.56.0 | 2026-10-17 | Antigravity | 自动重登遵循 settings.wechat_headless；重登未确认时清理冷却 flag；看门狗联动跨进程会话锁并在繁忙/预热重登后 5 分钟快速复检。 |
| evidence-v1 | 2026-10-17 | Codex | 复核 GET 展示经输入及规则指纹核对的原审计命中证据。 |
| cover-source-v1 | 2026-10-15 | Codex | 列表返回统一封面来源，缩略图读取投稿冻结文件。 |
| maintenance-v1 | 2026-10-12 | Codex | 共用持久化准入、调度角色互斥、单项线程归属和资源等待；维护启动保留本地候选管理。 |
| topic-candidates-v1 | 2026-10-11 | Codex | 挂载本机候选独立路由，生产搜索默认关闭；不接入主流水线。 |
| ted-cleanup-v1 | 2026-10-10 | Codex | 统计 API 回读当前进程的原片清理开关及配方，用于运行采用核验。 |
| 3.55.0 | 2026-10-08 | Antigravity | /api/trending-keywords 与 /refresh 增加异常防崩与静态兜底降级包装 |
| 3.54.0 | 2026-09-28 | Antigravity | /api/wechat/status 基于结构化验证事实判断登录有效性；自动重登与登录恢复绑定本次成功授权时间戳 |
| 3.53.0 | 2026-09-28 | Antigravity | 持久化记录实际随机选定的计划保活时刻，消除计划保活时间估算的平均伪造。 |
| 3.52.0 | 2026-09-28 | Antigravity | 会话重登检测优先读取结构化授权状态，保活循环识别锁冲突 (code 11) 不再报错。 |
| 3.51.0 | 2026-09-26 | Antigravity | 修复移动端静态资源强缓存导致新卡片样式未生效问题；HTML 注入静态文件 mtime 版本号，直出无缓存响应头。 |
| 3.50.0 | 2026-09-26 | Antigravity | 全局漏斗与频道漏斗端点默认时间窗口统一改为 today_bj (北京时间今日)。 |
| 3.49.0 | 2026-09-26 | Antigravity | 新增 /apple-touch-icon.png 与 /favicon.ico 根路由直出支持，保障 iOS 桌面与 PWA 📺 视觉呈现。 |
| 3.47.0 | 2026-09-24 | Codex | 区分自动与人工管线触发来源，提供逐日视频号投稿归因漏斗。 |
| 3.48.0 | 2026-09-25 | Codex | 登录标记缺失时恢复自动重登，并在保活确认为过期后立即启动既有登录流程。 |
| 3.46.0 | 2026-09-23 | Antigravity | [Code Review Fix] 1. _safe_kill_pid_or_pgid 增加自杀保护 (pid == os.getpid())；2. _process_group_alive 增加命令白名单特征过滤，防御 PID 复用；3. _queue_runner_loop 补偿排水审核通知；4. _trigger_video_async 等待超时扩展至 120s 对齐附件发送 |
| 3.45.0 | 2026-09-23 | Antigravity | [看门狗与进程组加固] 1. _process_group_alive 区分并同时校验 PID 与 PGID，防止批量入口 worker 被误回收；2. _run_pipeline_manager 与 run_full_pipeline 启用 start_new_session=True；3. 预提交孤儿回收联动 read_lease_owner 内核文件锁双重防误杀；4. 进程终止操作支持 PGID 与 PID 阶梯强杀；5. 巡检循环回收超期审核通知 |
| 3.44.0 | 2026-09-23 | Worker M2 (Topic Clues) | 重构 /api/trending-keywords 与 /refresh 接入 TopicCluesHub，消除 sys.path.insert(0, scripts) 与同步阻塞 |
| 3.43.0 | 2026-09-23 | Codex | 守护独立发布进程；显示待发布归属、占用原因与就绪时间。 |
| 3.42.0 | 2026-09-20 | Antigravity | 新增 waitlist/queue 治理接口 (cleanup-expired, discard-stale, calibrate, ignore)；promote 与 ignore 增加平台生命周期防重保护；GET /api/videos 支持 include_expired 归档回溯 |
| 3.41.0 | 2026-09-20 | Gemini | GET /api/videos 新增 funnel_stage 参数，支持大盘漏斗各阶段穿透查询与数据严格联动。 |
| 3.40.0 | 2026-09-20 | Gemini | 全局漏斗与频道漏斗端点新增 24h 与 today_bj 窗口支持；视频分页查询透传 created_window 时间过滤。 |
| 3.39.0 | 2026-09-20 | Gemini | 新增 GET /api/funnel 全站流转漏斗数据 API，支持 7d/30d/all 三维时间切片。 |
| 3.38.0 | 2026-09-20 | Gemini | 挂载 /static 静态资源目录 (StaticFiles)；_check_dashboard_origin 中间件放行 /static 路径，杜绝静态资源跨源加载 403。 |
| 3.37.0 | 2026-09-20 | Gemini | 新增白名单频道暂停/恢复 (/pause, /resume) 与多时间切片漏斗数据 (/funnel) API；list_channels 支持全量受管状态聚合。 |
| 3.36.2 | 2026-09-20 | Gemini | 修复添加频道时 yt-dlp --flat-playlist 导致 channel_id 为 NA 的 Bug；优先提取播放列表级/多候选元数据 |
| 3.35.1 | 2026-09-08 | Codex | 仪表盘允许局域网 IPv4 绑定；浏览器 Origin 必须与当前请求地址同源，保留轻量 CSRF 边界。 |
| 3.36.0 | 2026-09-09 | Codex | 新增已确认公开发布账本只读接口，供 Telegram /last 查询；拒绝本地工作流状态回退。 |
| 3.36.1 | 2026-09-09 | Codex | /last API 拒绝 SQLite 不可表示的位置参数，避免将异常暴露给 Telegram。 |
| Version | Date | Author | Description |
| console-receipts-v1 | 2026-10-25 | Codex | 授权回执读回、封面认证时效和人工投稿确认提示闭环。 |
| --- | --- | --- | --- |
| operations-v1 | 2026-10-24 | Codex | 分用途滚动预算与安全有界重试接入，保留既有提交事实与内容保护。 |
| retry-resume-v1 | 2026-10-23 | Codex | 历史审核标签不再提供当前复核入口，展示真实字幕阶段与复用结果。 |
| 3.23.0 | 2026-08-21 | Codex | 控制台对视频号生命周期 fail-closed：中止/孤儿发布先落未绑定账本，禁用无删除证明的重发，并阻断通用重试、改规格、删除和硬重置 |
| 3.24.0 | 2026-08-21 | Codex | 回收无存活进程的预提交孤儿任务；提交后状态继续 fail-closed，且待绑定提交进入待核验而非加工队列 |
| 3.25.0 | 2026-08-21 | Codex | 新增英语世界短视频候选研究与二次制作确认 API；不接入通用队列或发布入口 |
| 3.26.0 | 2026-08-23 | Codex | 新增英语世界 Telegram 审核项的显式投稿批准入口与独立 worker，不复用通用队列 |
| 3.27.0 | 2026-08-28 | Codex | 微信重登后仅续投一条登录前明确失败的自动英语世界项；已受理、未确认和历史项继续禁止自动重传。 |
| 3.28.0 | 2026-08-29 | Codex | 新增 Telegram 单任务微信发布 lease 候选、签发与立即启动 API；两小时一次性授权不扩散到自动队列。 |
| 3.29.0 | 2026-08-29 | Codex | Lease API 增加独立内部令牌和浏览器来源拒绝，并提供未消费授权撤销；响应区分领取与平台提交。 |
| 3.30.0 | 2026-08-29 | Codex | Dashboard 控制面仅绑定回环地址并拒绝非本机 Origin，消除局域网直连与浏览器 CSRF 写入面。 |
| 3.31.0 | 2026-08-29 | Codex | 英语世界人工批准、未确认重传和登录恢复在领取前绑定并核验完整投稿包指纹。 |
| 3.32.0 | 2026-08-29 | Codex | Telegram 二次确认制作启动受锁协调器；只制作已选候选并强制返回人工审核。 |
| 3.33.0 | 2026-09-02 | Codex | 抖音 HISTORY 补录与 CANCELED 重入队在写账本前读取阶段化 UI 熔断，读取异常或格式异常 fail-closed。 |
| 3.34.0 | 2026-09-07 | Codex | P0 审查红线在复核接口写库前 fail-closed 拒绝；复核证据优先读取触发预检的源 VTT，消除界面假放行与空字幕误导。 |
| 3.35.0 | 2026-09-07 | Codex | 恢复 P0 人工复核放行，要求双重确认并写入审计台账；管线只认可该审计记录对应的 P0 放行。 |
| 3.34.1 | 2026-09-07 | Codex | 列表筛选排序改为服务端分页前执行，并新增独立近期高互动浏览标记 API。 |
| 3.34.2 | 2026-09-07 | Codex | 默认按来源发布日期倒序；分数筛选支持跨任务 Tab 的 80 分以上候选。 |
| 3.22.0 | 2026-08-20 | Codex | 新增 Highlight 候选人工选定 API，并创建独立发布主体但不触发渲染或发布 |
| 3.21.0 | 2026-08-20 | Codex | 新增手动 Highlight Job 候选分析 API；独立于既有视频状态机和任何发布入口 |
| 3.20.0 | 2026-08-20 | Codex | 禁止视频号标题回查接口启动浏览器；仅允许发布链写入平台原生 ID 后进入精确确认流程 |
| 3.19.0 | 2026-08-20 | Codex | 视频号待确认增加作品管理页受控回查入口；通用重试拒绝绕过在途/成功视频号账本 |
| 1.0.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 初始创建 Dashboard API 服务 |
| 1.1.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 新增频道管理 API：add/delete，yt-dlp 验证后入库 |
| 1.2.0 | 2026-05-22 | Gemini_3.5_Flash_fast | 修复手工添加视频（含 TG Bot 提交）卡在 PENDING 不自动触发的问题 |
| 2.0.0 | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning | [v7.0 Phase 3+4] SIGTERM 强杀+黑名单墓碑、人工调分锁、频道手动隔离(MANUAL_ONLY) |
| 2.0.1 | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning | [v7.0 Review Fix] BUG-1: SIGTERM 注册移至主线程 startup_event；清理函数内重复 import |
| 2.1.0 | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning | [v7.0 Phase 6] SEC-1: urlparse 严格 netloc 校验替换 in-string 旁路；SEC-2: add_channel 覆盖 MANUAL_ONLY 防隐式提升 |
| 2.1.1 | 2026-05-26 | Gemini_3.5_Flash_planning           | [v7.0 macOS Fix] 解决 killpg(pid, 0) 对未收割僵尸进程返回 EPERM 导致误报的 macOS 特有行为 |
| 2.2.0 | 2026-05-27 | Gemini_3.5_Flash                    | 新增 trim_start/trim_end 请求参数接收与安全校验 |
| 2.3.0 | 2026-05-27 | Gemini_2.0_Flash_fast               | 适配微信扫码登录 QR 服务与状态查询 API |
| 2.3.1 | 2026-05-27 | Gemini_3.5_Flash_planning           | 修复由于缺少 re 模块导致的视频添加接口 500 报错 |
| 2.4.0 | 2026-05-27 | Gemini_3.5_Flash_High_planning      | 升级 delete_video 接口支持单个 slice 物理删除；新增获取所有 slices 与重试单个 slice 的 API |
| 2.5.0 | 2026-05-27 | Unknown_Model_planning              | 新增 process_slice_now 接口以支持立即强制执行切片子任务 |
| 2.6.0 | 2026-05-28 | Gemini_3.5_Flash_planning           | 新增 stop_video 接口以支持真实停止进程并状态置为 FAILED |
| 2.7.0 | 2026-05-28 | Gemini_3.5_Flash_planning           | 新增后台队列自动轮询器 _queue_runner_loop 自动执行切片/高分任务 |
| 2.8.0 | 2026-05-28 | Gemini_3.5_Flash_planning           | 使用 python -u 启动子进程以实现 pipeline.log 实时无缓冲日志输出 |
| 2.9.0 | 2026-06-01 | Claude_Sonnet_4.6_Thinking_planning | 新增 respec_video 端点：停止当前处理、覆盖规格并重新入队；add_video_manual 重复检测补充 video_id/title 返回 |
| 3.0.0 | 2026-06-07 | Claude_Sonnet_4.6_Thinking_planning | 新增 /api/trending-keywords 端点，整合 HN 热词注入功能到后台 Web UI 热词监控 Tab |
| 3.1.0 | 2026-06-07 | Claude_Sonnet_4.6_Thinking_planning | [BugFix+防卡] _run_pipeline_manager 使用 settings.get_active_proxies() 动态代理注入；_queue_runner_loop 新增 purge_stale_tasks() 自动清理卡死 DOWNLOADING 任务 |
| 3.2.0 | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 新增 _wechat_keepalive_loop：定期局动 wechat_keepalive.py 子进程刷新 Session，防止闲置掉线 |
| 3.3.0 | 2026-06-09 | Gemini_2.5_Pro_planning             | 修复 DISCOVERY 源视频被 process_video_now / update_video_priority 误触发自动处理的 Bug；API 层防火墙 |
| 3.4.0 | 2026-06-11 | Gemini_3.5_Flash_planning           | [高赞+防泄露] 新增 _is_pipeline_manager_running；全量管线去重，防止并发阻塞导致进程泄露 |
| 3.4.1 | 2026-06-11 | Claude_Opus_4.6_Thinking_planning   | [P0修复] _run()闭包缺少global声明导致刷新按钮一次性失效；fcntl提升为top-level import |
| 3.5.0 | 2026-06-13 | Claude_Opus_4.8                     | 新增 promote_video 端点 (/api/videos/{id}/promote)：高赞发现视频一键转 MANUAL(100) 并立即触发管线，替代删除+重粘的绕路 |
| 3.6.0 | 2026-06-13 | Claude_Opus_4.8                     | 新增 censor_keywords + bypass_censor 端点：审查失败视频「🔓 复核放行」——返回命中词/标题+字幕关键词标签云，确认后置 bypass 标志并重新触发管线 |
| 3.7.0 | 2026-06-13 | Claude_Opus_4.8                     | 新增 download_progress 端点：轮询 output/{yid}.f* 临时文件大小 + info.json.filesize_approx 估算下载进度/速度/ETA（下载器无关，零侵入下载流程） |
| 3.8.0 | 2026-06-13 | Claude_Opus_4.8                     | 新增 republish_video 端点 (/api/videos/{id}/republish)：已完成视频「🔁 再次发布」——重置 PENDING 重新触发，复用 GC 保留的成片/封面/文案 checkpoint 秒级重发 |
| 3.9.0 | 2026-06-15 | Claude_Opus_4.8                     | [BUG-1 配套] bypass_censor / censor_keywords / _read_subtitle_text 增加 slice_index 粒度，与管线侧透传对齐，使审查类失败的切片可按 (id,slice) 单独放行 |
| 3.10.0 | 2026-06-15 | Claude_Opus_4.8                    | [BUG-5] clear_waitlist 改走 DAL get_waitlist_clearable_ids（排除 DISCOVERY），消除业务层裸 SQL，修复一键清空击穿发现防火墙 |
| 3.11.0 | 2026-06-18 | Claude_Opus_4.8                    | [盘中重负载保护] 新增 _in_us_market_window()；_auto_pipeline_loop 与 _queue_runner_loop 在美股盘中(ET 09:15–16:15,工作日,自动夏/冬令时)暂停重型管线，避免抢占共享主机实盘行情管线 CPU；开关 settings.enable_market_hours_guard；仪表盘端口默认 8765→9100 |
| 3.12.0 | 2026-06-28 | Claude_Opus_4.8                    | 新增 POST /api/videos/retry-recent?hours=N：批量重置最近 N 小时 FAILED 为 PENDING（不逐条触发，交调度器按节奏重发），供 Telegram /retry <小时数> |
| 3.13.0 | 2026-07-04 | Gemini_3.5_Flash_planning           | [anduchencang] 新增 /demo 交互式英文精读体验页路由 |
| 3.14.0 | 2026-07-05 | Codex                               | 修复微信扫码状态假阳性：状态接口改信真实登录成功标记，并阻止 Web 端重复启动并发登录进程 |
| 3.14.1 | 2026-07-05 | Codex                               | /api/videos/retry-recent 批量重试纳入 LOGIN_REQUIRED，覆盖微信登录过期恢复场景 |
| 3.14.2 | 2026-07-05 | Codex                               | 新增 /api/videos/retry-recent/preview 只读预览，供 Telegram /status 展示批量重试会影响几条 |
| 3.14.3 | 2026-07-07 | Codex                               | 微信扫码登录启动前先失效旧登录标记，并在状态接口中显式返回登录流程是否仍在进行，避免后台误把旧态判成成功 |
| 3.14.4 | 2026-07-08 | Codex                               | 调度器新增孤儿 PUBLISHING 回收：发现发布进程已死但状态长时间未回收时，保守降级为 FAILED 并提示先核对视频号后台，避免队列被无限卡住 |
| 3.15.0 | 2026-07-10 | Codex                               | 会话临期自动预热重登：保留旧 state，提前经 Telegram 推送二维码，扫码成功后才替换会话 |
| 3.16.0 | 2026-07-13 | Codex                               | 新增 AI 处理审计 API，后台可读取 provider 尝试、降级和质量结果 |
| 3.17.0 | 2026-07-23 | Codex                               | 新增三平台补录预览与抖音补录确认入队 API |
| 3.18.0 | 2026-07-24 | Codex                               | [新任务启动保护] _in_us_market_window 跟随 settings 的 ET 08:15–16:15 窗口，仅阻止调度器启动新管线 |
| 3.18.1 | 2026-07-27 | Codex                               | 微信扫码登录成功后自动恢复 LOGIN_REQUIRED 为 PENDING，交由既有队列调度器按分数线重发 |
| 3.18.2 | 2026-07-30 | Codex                               | 音轨规格改变时失效竖版成片与封面缓存，避免配音版继续复用原声封面       |
| 3.18.3 | 2026-07-31 | Codex                               | 同步删除封面来源清单，防止音轨规格切换后遗留哈希失配的封面证明         |
| 3.18.4 | 2026-08-04 | Codex                               | 仪表盘列表优先展示真实投递短标题，避免本地 zh_title 与微信后台标题错位 |
| 3.18.5 | 2026-08-05 | Codex                               | 后台标题翻译拒绝 Error 500 响应并改走 zh_title DAL，防止列表源译名污染 |
| 3.18.6 | 2026-08-07 | Codex                               | 新增抖音 CANCELED 账本的显式人工重新入队 API，保留原失败记录供审计 |
| 3.18.7 | 2026-08-09 | Codex                               | 手动入队显式接收内容生产类型，支持英语世界短视频的持久化标识 |
| 3.18.8 | 2026-08-11 | Codex                               | 视频号平台已受理但未公开的任务展示为 UNDER_REVIEW，禁止将其作为可重试或已完成状态 |
| 3.18.9 | 2026-08-14 | Codex                               | 将平台待确认状态从实际加工计数中分离，避免仪表盘把已提交待回查误报为处理中 |
| 3.18.10 | 2026-08-26 | Codex                              | 所有微信登录入口统一使用带平台提交证据保护的任务恢复逻辑 |
| 3.19.0  | 2026-09-23 | Antigravity                         | [进程生命周期与看门狗加固] 1. _trigger_video_async 改用 Popen 并在独立会话启动后立即记录 process_pid，结束自动置空，子进程退出前调用 wait_for_review_notifications 保护异步推送；2. _recover_orphaned_pre_submission_tasks 增加保护：若进程组存活，或 pid 为空但 pipeline.lock 正在被管线持有，则绝不误判孤儿 |
"""
import hashlib
import logging
import asyncio
import os
import re  # [Gemini_3.5_Flash_planning] 统一导入正则模块
import secrets
import fcntl  # [Claude_Opus_4.6_Thinking_planning] 用于 _is_pipeline_manager_running() 非阻塞锁探测
import sys
import signal
import time
import json
import shutil
import subprocess
import threading
from collections.abc import Mapping
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

# 确保能导入 src 下的模块
_src = str(Path(__file__).parent.parent)
if _src not in sys.path:
    sys.path.insert(0, _src)

from fastapi import FastAPI, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from video_processing.db.database import MAX_SQLITE_INTEGER, PipelineDB
from video_processing.content_types import CONTENT_TYPE_GENERAL, normalize_content_type
from video_processing.core.douyin_ui_guard_policy import (
    active_douyin_ui_failure_stages,
    douyin_management_verify_is_blocked,
    douyin_publish_is_blocked,
)
from config.settings import settings  # [Claude_Sonnet_4.6_Thinking_planning] v7.0: 模块顶层导入，避免函数体内重复 import
from web.local_runtime_access import configured_english_world_public_origin, configured_video_review_public_origin
from video_processing.utils.translation_helper import translate_text as _translate_text  # [Claude_Sonnet_4.6_planning] 统一翻译入口
from video_processing.utils.generated_content_validation import is_upstream_error_response
from video_processing.highlight import HighlightJobService
from video_processing.english_world import EnglishWorldResearchService
from video_processing.english_world.package_integrity import calculate_package_hashes
from web.listening_transcriber import router as listening_transcriber_router
from video_processing.core.maintenance_child import run_admitted
from video_processing.core.maintenance import gate, guarded, entry, running, spawn_admitted, MaintenanceDenied
from video_processing.core.maintenance_child import child_continuation
from video_processing.core.maintenance_runtime import registered, role_lease, inspection
from video_processing.core.engagement_presentation import STAGES as ENGAGEMENT_STAGES, present_engagement
from video_processing.core.task_lease import TaskLease, TaskLeaseBusy

app = FastAPI(title="Video Pipeline Control Center", version="1.1.0")
app.include_router(listening_transcriber_router)

_static_dir = Path(__file__).parent / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.middleware("http")
async def reject_untrusted_browser_origins(request, call_next):
    """只允许当前 Dashboard 地址的同源浏览器请求，阻止第三方网页跨站写入。"""
    if (
        request.url.path == "/static"
        or request.url.path.startswith("/static/")
        or request.url.path in {"/favicon.ico", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"}
    ):
        response = await call_next(request)
        if request.url.path.endswith(".css") or request.url.path.endswith(".js"):
            if "v=" in str(request.query_params):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response
    origin = request.headers.get("origin")
    if origin:
        port = settings.dashboard_port
        trusted_origins = {
            f"http://localhost:{port}",
            f"http://127.0.0.1:{port}",
            f"http://[::1]:{port}",
            f"{request.url.scheme}://{request.url.netloc}",
        }
        english_world_origin = configured_english_world_public_origin(
            request, settings.dashboard_english_world_public_origin,
        )
        review_origin = configured_video_review_public_origin(
            request, settings.dashboard_review_public_origin,
        )
        if origin not in trusted_origins and origin not in {english_world_origin, review_origin}:
            return JSONResponse(
                status_code=403,
                content={"detail": "untrusted dashboard origin"},
            )
    return await call_next(request)

# 使用全局 DB 实例（每次方法调用内部创建新连接，线程安全）
db = PipelineDB()
from web.vocabulary_outro_settings import create_vocabulary_outro_settings_router
app.include_router(create_vocabulary_outro_settings_router(
    active=settings.vocabulary_outro_policy_path,
    output=Path(__file__).resolve().parents[2] / 'output', videos=db.get_product_preview_videos,
))
from web.product_settings import create_product_settings_router
app.include_router(create_product_settings_router(
    active=settings.wechat_product_policy_path, status=settings.wechat_product_status_path,
    output=Path(__file__).resolve().parents[2] / "output", videos=db.get_product_preview_videos,
    publisher_connected=True, production_lookup=db.get_product_production, decision_lookup=db.get_product_task_decision,
    legacy_lookup=db.is_legacy_product_review,
))

from web.topic_candidates import create_topic_candidates_router


def _create_topic_tracker():
    from video_processing.topic_tracker.service import TopicTracker
    from video_processing.utils.topic_search import ExistingTopicRules, YouTubeTopicSearch
    return TopicTracker(db, settings, YouTubeTopicSearch(settings), ExistingTopicRules())


app.include_router(create_topic_candidates_router(_create_topic_tracker, port=settings.dashboard_port))
from web.secondary_reply_settings import create_secondary_reply_settings_router
app.include_router(
    create_secondary_reply_settings_router(
        active=settings.wechat_reply_policy_path,
        history_lookup=lambda limit: db.list_secondary_reply_history(limit=limit),
        access_db=db,
    )
)
from web.wechat_cooldown_settings import create_wechat_cooldown_settings_router
app.include_router(
    create_wechat_cooldown_settings_router(
        active=settings.wechat_scheduler_policy_path,
    )
)

from web.runtime_configuration import create_runtime_configuration_router
app.include_router(create_runtime_configuration_router(db,port=settings.dashboard_port))
from web.english_world_console import create_english_console_router
app.include_router(create_english_console_router(
    db, port=settings.dashboard_port,
    public_origin=settings.dashboard_english_world_public_origin,
    start_research=lambda job_id: _start_english_world_research(job_id),
    start_production=lambda job_id: _start_english_world_production(job_id),
    start_submission=lambda review_id: _start_english_world_submission(review_id),
    start_resume=lambda request_path: _start_english_world_workbench_resume(request_path),
))


@app.on_event('startup')
async def runtime_configuration_ack_loop():
    """只核验本地版本；不启动或探测平台工作。"""
    async def loop():
        from video_processing.utils.runtime_configuration import acknowledge
        while True:
            try:
                await asyncio.to_thread(acknowledge,'dashboard')
            except Exception:
                logging.getLogger(__name__).warning('配置加载确认不可写，界面将显示待加载')
            await asyncio.sleep(5)
    app.state.runtime_configuration_task=asyncio.create_task(loop())


@app.on_event('shutdown')
async def runtime_configuration_ack_stop():
    task=getattr(app.state,'runtime_configuration_task',None)
    if task:
        task.cancel()
        try:await task
        except asyncio.CancelledError:pass


@app.get("/api/wechat-operations-policy")
def wechat_operations_policy_status():
    """紧急参数上线的只读实际生效视图；不是完整 G1 配置后台。"""
    from video_processing.utils.wechat_operations_policy import load_policy, revision
    from video_processing.core.wechat_request_guard import WeChatRequestGuard, WeChatRequestDeferred
    try:
        policy = load_policy()
        if policy is None:
            return {"enabled": False}
        guard = WeChatRequestGuard(settings.default_output_dir / "wechat_state.json")
        purpose_names = {"publish":"发布", "first_comment":"首评", "reply":"回复", "comment_scan":"评论扫描", "post_match":"作品匹配", "keepalive":"保活"}
        views = {}
        for key, purpose in purpose_names.items():
            info = guard.evaluate(purpose=purpose, account_only=True)
            views[key] = {name: info.get(name) for name in ("allowed", "blockers", "until", "sessions_24h_count", "sessions_1h_count", "daily_limit", "hourly_limit", "interval_seconds", "policy_revision")}
        return {"enabled": True, "loaded_revision": revision(policy), "config": policy, "admission": views,
                "meaning": "until 是账号已知时间门禁下界，不保证任务已经具备其他资格；旧共享额度界面字段不再用于正常分用途准入"}
    except WeChatRequestDeferred as exc:
        raise HTTPException(503, str(exc)) from exc


from web.publishing_recovery import create_publishing_recovery_router
from video_processing.utils.publishing_recovery_worker import ensure_publishing_recovery_worker
app.include_router(create_publishing_recovery_router(
    db, settings.project_root,
    wake=lambda: ensure_publishing_recovery_worker(db, settings.project_root),
))


@app.middleware("http")
async def maintenance_admission(request, call_next):
    """旧业务写请求共用准入；候选本地操作仍走自己的来源/会话检查。"""
    if request.method in {"GET", "HEAD", "OPTIONS"} or request.url.path.startswith("/api/topic-candidates/"):
        return await call_next(request)
    try:
        matched = re.fullmatch(r"/api/videos/([^/]+)(?:/slices/(\d+))?/[^/]+", request.url.path)
        key = f"{matched[1]}:{matched[2] or 0}" if matched else request.url.path
        if request.url.path == "/api/publication-leases":
            try:
                body = await request.json()
                key = f"{body['youtube_id']}:{body.get('slice_index', 0)}"
            except (ValueError, KeyError, TypeError):
                pass
        with gate().admit("web-write", key) as ticket:
            ticket.start()
            if matched and request.url.path.rsplit("/", 1)[-1] in {"process", "promote", "retry", "bypass-censor", "review-censor"}:
                # 同一视频的人工恢复请求跨线程/进程互斥，先核实版本再执行完整动作。
                lock_key = hashlib.sha256(matched[1].encode()).hexdigest()
                try:
                    with TaskLease(_OUT_DIR / "engagement_action_locks" / f"{lock_key}.lock",
                                   stage="dashboard-action", video=matched[1]):
                        return await call_next(request)
                except TaskLeaseBusy:
                    return JSONResponse(status_code=409, content={"detail": "该视频已有操作正在提交，请刷新后查看"})
            return await call_next(request)
    except MaintenanceDenied as exc:
        return JSONResponse(status_code=503, content={"detail": {"code": exc.code, "message": str(exc)}})


@app.get("/api/maintenance/status")
def maintenance_status(request: Request):
    import ipaddress
    try:
        local = request.client and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    if not local:
        raise HTTPException(403, "维护状态仅允许本机读取")
    return inspection(gate())
_wechat_login_thread: Optional[threading.Thread] = None
_WECHAT_AUTO_RELOGIN_FLAG = "wechat_auto_relogin_started.flag"

_VIDEO_TABS = {"waitlist", "queue", "ready", "active", "wechat_deferred", "review", "completed", "error", "high_likes"}
_VIDEO_SORTS = {"updated_at_desc","default", "score_desc", "views_desc", "like_rate_desc", "source_published_at_desc", "upload_date_desc"}
_SCORE_BANDS = {"all", "unscored", "below_50", "50_74", "80_plus"}
_ERROR_TYPES = {"all", "channel_policy", "login", "youtube_403", "copy_quality", "censorship_p0", "other"}
_ENGAGEMENT_WINDOWS = {1, 3, 7, 30}
_CREATED_WINDOWS = {"all", "24h", "today_bj", "7d", "30d"}
_FUNNEL_STAGES = {"", "ingested", "qualified", "processed", "published", "failed", "blocked"}
_VIDEO_STATUSES = {
    "PENDING", "METADATA_PENDING", "PROCESSING", "PUBLISH_PRECHECK", "DOWNLOADING", "TRANSCRIBING", "COPYWRITING", "AI_COVER_PENDING",
    "PUBLISHING", "PUBLISHED", "COMPLETED", "IGNORED", "FAILED", "LOGIN_REQUIRED", "SEGMENTED",
    "WECHAT_DEFERRED", "UNDER_REVIEW", "SUBMITTED_UNBOUND", "SUBMITTED_BOUND", "UNCERTAIN",
}


def _require_pipeline_internal_token(
    x_pipeline_internal_token: Optional[str] = Header(default=None),
    origin: Optional[str] = Header(default=None),
) -> None:
    """高权限 lease 控制面仅接受持有独立令牌的非浏览器本机服务调用。"""
    expected = settings.pipeline_internal_api_token
    if not expected or len(expected) < 32:
        raise HTTPException(status_code=503, detail="lease control token is not configured")
    if origin:
        raise HTTPException(status_code=403, detail="browser-origin lease requests are forbidden")
    if not x_pipeline_internal_token or not secrets.compare_digest(
        x_pipeline_internal_token, expected,
    ):
        raise HTTPException(status_code=403, detail="invalid lease control token")


class DeliveryRecoveryAction(BaseModel):
    action: str
    actor: str


@app.get("/api/delivery-recoveries", dependencies=[Depends(_require_pipeline_internal_token)])
def list_delivery_recoveries():
    from video_processing.delivery_recovery import DeliveryRecoveryService
    service = DeliveryRecoveryService(db, settings.project_root)
    return {"items": [service.view(row['id']) for row in db.list_delivery_recoveries()]}


@app.post("/api/delivery-recoveries/{recovery_id}", dependencies=[Depends(_require_pipeline_internal_token)])
def delivery_recovery_action(recovery_id: str, request: DeliveryRecoveryAction):
    from video_processing.delivery_recovery import DeliveryRecoveryService
    try:
        view = DeliveryRecoveryService(db, settings.project_root).act(
            recovery_id, action=request.action, actor=request.actor)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if request.action == 'retry':
        from video_processing.utils.delivery_recovery_worker import ensure_delivery_recovery_worker
        ensure_delivery_recovery_worker(db, settings.project_root)
    return view


def _start_highlight_analysis(job_id: str) -> None:
    """独立启动轻量候选分析；不调用 PipelineManager，也不启动下载/渲染/发布。"""
    def _run() -> None:
        service = HighlightJobService(db, Path(__file__).parent.parent.parent)
        service.analyze(job_id)

    spawn_admitted(_run, role="highlight-analysis", object_key="highlight:" + job_id, name=f"highlight-analysis-{job_id[:8]}", continuation=True)


def _start_english_world_research(job_id: str) -> None:
    """异步进行只读元数据研究；不会下载媒体、渲染学习卡或提交任何平台。"""
    def _run() -> None:
        EnglishWorldResearchService(db).research(job_id)

    spawn_admitted(_run, role="english-research", object_key="english-job:" + job_id, name=f"english-research-{job_id[:8]}", continuation=True)


def _start_english_world_production(job_id: str) -> None:
    """启动已二次确认的单候选生产；协调器内部原子领取并强制人工审核。"""
    project_root = Path(__file__).parent.parent.parent
    python_bin = project_root / ".venv" / "bin" / "python"
    runner = project_root / "scripts" / "run_english_world_daily.py"

    def _run() -> None:
        try:
            result = run_admitted(
                [
                    str(python_bin), str(runner), "--job-id", job_id,
                    "--wait-for-lock-seconds", "7200",
                ],
                cwd=str(project_root), timeout=4 * 60 * 60, text=True, capture_output=True,
            )
            if result.returncode:
                logging.getLogger(__name__).error(
                    "[EnglishWorld] production coordinator returned %s for %s: %s",
                    result.returncode, job_id[:8], result.stderr[-500:],
                )
        except subprocess.TimeoutExpired:
            logging.getLogger(__name__).error(
                "[EnglishWorld] production coordinator parent timed out for %s; inspect durable run state",
                job_id[:8],
            )
        except OSError as exc:
            logging.getLogger(__name__).exception(
                "[EnglishWorld] failed to launch production coordinator for %s: %s", job_id[:8], exc,
            )

    spawn_admitted(_run, role="english-production", object_key="english-job:" + job_id, name=f"english-production-{job_id[:8]}", waiting=True)


def _start_english_world_workbench_resume(request_path: str) -> None:
    """只把具名旧交付包续入审核待办；runner 必须强制 manual-review-only。"""
    project_root = Path(__file__).parent.parent.parent
    python_bin = project_root / ".venv" / "bin" / "python"
    runner = project_root / "scripts" / "run_english_world_daily.py"

    def _run() -> None:
        result = run_admitted([str(python_bin), str(runner), "--resume-delivery-request", request_path,
                               "--workbench-resume"], cwd=str(project_root), timeout=4*60*60,
                              text=True, capture_output=True)
        if result.returncode:
            logging.getLogger(__name__).error("[EnglishWorld] workbench delivery resume failed: %s", result.stderr[-500:])

    spawn_admitted(_run, role="english-workbench-resume", object_key="english-resume:"+Path(request_path).name,
                   name="english-workbench-resume", continuation=True)


def _start_english_world_submission(review_id: str) -> None:
    """仅启动某一已批准审核项的专用投稿器；领取动作在子进程内原子完成。"""
    project_root = Path(__file__).parent.parent.parent
    python_bin = project_root / ".venv" / "bin" / "python"
    runner = project_root / "scripts" / "submit_english_world_review.py"

    def _run() -> None:
        try:
            result = run_admitted(
                [str(python_bin), str(runner), "--review-id", review_id],
                cwd=str(project_root), timeout=30 * 60, text=True, capture_output=True,
            )
            if result.returncode:
                logging.getLogger(__name__).error(
                    "[EnglishWorld] submission worker returned %s for %s: %s",
                    result.returncode, review_id[:8], result.stderr[-500:],
                )
        except subprocess.TimeoutExpired:
            logging.getLogger(__name__).error(
                "[EnglishWorld] submission worker timed out for %s; inspect its independent review ledger",
                review_id[:8],
            )
        except OSError as exc:
            logging.getLogger(__name__).exception(
                "[EnglishWorld] failed to launch submission worker for %s: %s", review_id[:8], exc,
            )

    spawn_admitted(_run, role="english-submit", object_key="review:" + review_id, name=f"english-submit-{review_id[:8]}", waiting=True)


def _wechat_login_env() -> dict:
    """构建登录子进程环境，确保 Telegram 凭据随设置注入而不是依赖父进程环境。"""
    proxy_keys = frozenset({
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    })
    env = {k: v for k, v in os.environ.items() if k not in proxy_keys}
    env["PYTHONPATH"] = str(Path(__file__).parent.parent)
    if settings.telegram_bot_token:
        env["TELEGRAM_BOT_TOKEN"] = settings.telegram_bot_token
    if settings.active_telegram_chat_id:
        env["TELEGRAM_CHAT_ID"] = settings.active_telegram_chat_id
    if settings.telegram_admin_ids:
        env["TELEGRAM_ADMIN_IDS"] = settings.telegram_admin_ids
    return env


@guarded("login-recovery")
def _restore_login_required_after_wechat_login() -> int:
    """微信重登成功后恢复因登录态失效暂停的任务，让既有调度器按分数线重发。"""
    import logging

    restore = getattr(db, "restore_login_required_videos", None)
    if restore is not None:
        count = restore()
        if count:
            logging.getLogger(__name__).info(
                "[WeChatLogin] Restored %s LOGIN_REQUIRED task(s) to PENDING after login success.",
                count,
            )
        return count

    # 兼容精简测试替身/旧外部调用者；生产 PipelineDB 始终走上面的原子 DAL 方法。
    rows = db.get_videos_by_status("LOGIN_REQUIRED")
    count = 0
    for row in rows:
        db.update_video_status(
            row["youtube_id"],
            "PENDING",
            error_msg=None,
            slice_index=int(row.get("slice_index") or 0),
        )
        count += 1
    if count:
        logging.getLogger(__name__).info(
            "[WeChatLogin] Restored %s LOGIN_REQUIRED task(s) to PENDING after login success.",
            count,
        )
    return count


@guarded("english-login-recovery")
def _resume_eligible_english_world_after_wechat_login() -> Optional[dict]:
    """登录成功后续投一条可证明未触达平台的英语世界自动任务。

    领取规则在 DAL 内原子执行：仅 ``AUTO_POLICY``、``exit=2``、近期且此前
    未恢复过一次的记录可通过。此处不扫描历史项，也不触碰 ``UNCERTAIN`` 或
    已受理记录。
    """
    if not settings.enable_english_world_auto_publish or settings.wechat_publishing_paused:
        return None
    claim = getattr(db, "claim_english_world_login_recovery", None)
    if claim is None:
        return None
    candidate = getattr(db, "get_english_world_login_recovery_candidate", lambda **_kwargs: None)(
        max_age_hours=12,
    )
    if candidate:
        try:
            hashes = calculate_package_hashes(candidate)
            db.bind_english_world_review_package_hashes(str(candidate["id"]), hashes=hashes)
        except (ValueError, OSError) as exc:
            logging.getLogger(__name__).error(
                "[EnglishWorld] Refusing login recovery because package verification failed for %s: %s",
                str(candidate["id"])[:8], exc,
            )
            return None
    item = claim(max_age_hours=12)
    if item:
        _start_english_world_submission(str(item["id"]))
        logging.getLogger(__name__).info(
            "[EnglishWorld] Resuming one pre-login failure after WeChat login: %s",
            str(item["id"])[:8],
        )
    return item


@guarded("wechat-login")
def _start_wechat_login_flow(*, headless: bool | None = None, preserve_marker: bool = False, reason: str = "manual") -> dict:
    """启动单实例微信登录；自动预热时保留旧登录标记和 state，避免提前把现行会话判死。"""
    # 固定时钟重登与账户统一调度互斥；在删标记/建线程之前退出。
    if settings.wechat_account_scheduler_enabled and reason != "manual":
        return {"success": False, "deferred": True, "message": "账户统一调度已停用自动保活及预热重登"}
    from video_processing.core.wechat_request_guard import WeChatRequestGuard, WeChatRequestDeferred
    if headless is None:
        headless = bool(settings.wechat_headless)
    prj_root = Path(__file__).parent.parent.parent
    python = str(prj_root / ".venv" / "bin" / "python")
    script = str(prj_root / "scripts" / "wechat_uploader.py")
    state = prj_root / "output" / "wechat_state.json"
    qr_path = prj_root / "output" / "login_qr.png"
    login_at_path = prj_root / "output" / "wechat_login_at.txt"
    auto_flag = prj_root / "output" / _WECHAT_AUTO_RELOGIN_FLAG

    if _is_wechat_login_running():
        return {"success": True, "already_running": True, "message": "微信登录程序已在运行"}

    if auto_flag.exists():
        try:
            # 未扫码的登录流程最多保留 15 分钟，避免一次失败永久阻塞后续预热。
            if time.time() - auto_flag.stat().st_mtime < 15 * 60:
                return {"success": True, "already_running": True, "message": "自动重登二维码仍在有效等待期"}
            auto_flag.unlink()
        except Exception:
            pass

    manual_login_token = ""
    try:
        guard = WeChatRequestGuard(state)
        if reason == "manual":
            manual_login_token = guard.issue_manual_login()
        else:
            guard.check()
    except WeChatRequestDeferred as exc:
        return {"success": False, "deferred": True, "message": str(exc)}

    if not preserve_marker and not manual_login_token:
        try:
            login_at_path.unlink()
        except FileNotFoundError:
            pass
    try:
        qr_path.unlink()
    except FileNotFoundError:
        pass

    args = [python, script, "--login-only", "--relogin", "--state", str(state)]
    if manual_login_token:
        args.extend(["--manual-login-token", manual_login_token])
    if not headless:
        args.append("--no-headless")
    if preserve_marker:
        try:
            auto_flag.write_text(str(int(time.time())), encoding="utf-8")
        except Exception:
            pass

    start_ts = time.time()
    from video_processing.core.wechat_auth_state import (
        read_wechat_auth_state,
        record_wechat_auth_attempt,
    )
    pre_auth = read_wechat_auth_state(state) if state.exists() else {}
    pre_auth_at = float(pre_auth.get("authorized_at") or 0.0)
    pre_gen = pre_auth.get("credential_generation")

    def _run():
        try:
            result = run_admitted(args, cwd=str(prj_root), env=_wechat_login_env())
            post_auth = read_wechat_auth_state(state) if state.exists() else {}
            post_auth_at = float(post_auth.get("authorized_at") or 0.0)
            auth_succeeded_this_run = (
                result.returncode == 0
                and post_auth_at > pre_auth_at
                and post_auth_at >= (start_ts - 2.0)
            )
            if auth_succeeded_this_run and not manual_login_token:
                _restore_login_required_after_wechat_login()
                _resume_eligible_english_world_after_wechat_login()
            elif not auth_succeeded_this_run:
                if preserve_marker:
                    try:
                        auto_flag.unlink(missing_ok=True)
                    except Exception:
                        pass
                # 若非会话锁占用 (returncode != 11) 且子进程未写入本次失败尝试，补记失败退避以防死循环饿死保活
                if result.returncode != 11 and state.exists():
                    post_att_at = float(post_auth.get("last_auth_attempt_at") or 0.0)
                    post_att_status = post_auth.get("last_auth_attempt_status")
                    if post_att_status != "FAILED" or post_att_at < (start_ts - 2.0):
                        try:
                            record_wechat_auth_attempt(
                                state,
                                method="auto",
                                success=False,
                                reason="PAGE_UNREADY" if result.returncode == 1 else "LOGIN_REQUIRED",
                                expected_generation=pre_gen,
                            )
                        except Exception:
                            pass
                import logging
                logging.getLogger(__name__).warning(
                    f"WeChat login subprocess finished (code={result.returncode}) but fresh authorization was not confirmed (pre={pre_auth_at}, post={post_auth_at}, start={start_ts})."
                )
        except Exception as exc:
            if preserve_marker:
                try:
                    auto_flag.unlink(missing_ok=True)
                except Exception:
                    pass
            import logging
            logging.getLogger(__name__).error(f"WeChat login subprocess failed ({reason}): {exc}")

    global _wechat_login_thread
    _wechat_login_thread = spawn_admitted(_run, role="wechat-login", object_key="wechat-login", name="wechat-login", continuation=True)
    return {"success": True, "message": "微信登录流程已启动"}


def _wechat_session_needs_auto_relogin() -> bool:
    """判断是否已接近服务端绝对会话上限，且当前没有进行中的自动重登或重登失败退避。"""
    if (settings.wechat_account_scheduler_enabled or not settings.wechat_auto_relogin_enabled
            or not settings.wechat_keepalive_enabled):
        return False
    prj_root = Path(__file__).parent.parent.parent
    login_at = prj_root / "output" / "wechat_login_at.txt"
    state_file = prj_root / "output" / "wechat_state.json"
    auto_flag = prj_root / "output" / _WECHAT_AUTO_RELOGIN_FLAG
    try:
        now_ts = time.time()
        if auto_flag.exists() and now_ts - auto_flag.stat().st_mtime < 15 * 60:
            return False
        from video_processing.core.wechat_auth_state import read_wechat_auth_state
        auth_state = read_wechat_auth_state(state_file)
        # 防饿死保护：若上次重登失败且处于指数退避窗口，或重登失败后尚未对旧凭证执行过普通保活探测，
        # 优先让出给普通 keepalive 探测刷新旧凭证，严禁每 5 分钟连续触发重登而饿死保活。
        next_relogin_at = auth_state.get("next_relogin_allowed_at")
        if next_relogin_at is not None and now_ts < next_relogin_at:
            return False
        last_att_status = auth_state.get("last_auth_attempt_status")
        last_att_at = auth_state.get("last_auth_attempt_at")
        last_ka_at = auth_state.get("last_keepalive_at")
        if (
            last_att_status == "FAILED"
            and last_att_at is not None
            and (last_ka_at is None or last_ka_at < last_att_at)
        ):
            return False
        stamp = auth_state.get("authorized_at")
        if stamp is None:
            stamp = int(login_at.read_text(encoding="utf-8").strip())
        return (now_ts - stamp) / 3600.0 >= settings.wechat_session_warn_hours
    except (OSError, ValueError):
        # 旧看门狗会删标记；只有保存过会话时才尝试恢复，避免首次安装时误启动。
        return state_file.is_file()

@guarded("title-translation", lambda youtube_id, *a: str(youtube_id) + ":0")
def _translate_title_task(youtube_id: str, english_title: str):
    """后台任务：调用翻译接口（阿里云 MT 优先）翻译标题并更新数据库。

    [Claude_Sonnet_4.6_planning] 改用 translation_helper.translate_text，
    使标题翻译与字幕翻译共享相同的阿里云 MT 优先策略。
    """
    try:
        zh_title = _translate_text(english_title, src_lang="auto", target_lang="zh-CN")
        if zh_title and zh_title != english_title and not is_upstream_error_response(zh_title):
            db.update_video_zh_title(youtube_id, zh_title)
            print(f"[Translator] {youtube_id} translated: {zh_title}")
        elif is_upstream_error_response(zh_title):
            existing = db.get_video_by_youtube_id(youtube_id)
            if existing and is_upstream_error_response(existing.get("zh_title") or ""):
                db.update_video_zh_title(youtube_id, english_title)
            print(f"[Translator] {youtube_id} returned upstream error page; keeping source title")
    except Exception as e:
        print(f"[Translator] Failed to translate {youtube_id}: {e}")
    finally:
        # [Gemini_3.1_Pro_High] 手工加急视频翻译完成后立即触发异步处理管线，通过 claim_video_for_processing 防止竞态
        try:
            if db.claim_video_for_processing(youtube_id):
                video = db.get_video_by_youtube_id(youtube_id)
                if video:
                    print(f"[Scheduler] Auto-triggering pipeline for manual video: {youtube_id}")
                    _trigger_video_async(video, trigger_source="dashboard_scheduler")
        except Exception as trigger_err:
            import logging
            logging.getLogger(__name__).error(f"[Scheduler] Failed to auto-trigger video {youtube_id}: {trigger_err}")

def _in_us_market_window() -> bool:
    """[Claude_Opus_4.8] 美股盘中重负载保护窗口判定，委托 settings 单一真相源
    （ET 08:15–16:15 工作日，自动夏/冬令时；与 pipeline_manager 共用同一实现）。"""
    return settings.is_us_market_guard_window()


@registered("auto-pipeline")
def _auto_pipeline_loop(stop=None):
    """后台循环任务：启动后延迟10秒执行首次管线，之后每4小时执行一次"""
    stop = stop if stop is not None else _scheduler_stop
    import time
    stop.wait(10)
    while not stop.is_set():
        try:
            # [Claude_Opus_4.8] 美股盘中保护：盘中跳过重型全量管线，避免抢占实盘行情管线 CPU
            if not running():
                pass
            elif _in_us_market_window():
                print("[Scheduler] 美股盘中，跳过全量管线（重负载保护）。")
            else:
                # 复用已有的全量管线触发逻辑
                _start_full_pipeline("scheduler")
                print("[Scheduler] Auto-triggered full pipeline run.")
        except Exception as e:
            print(f"[Scheduler] Auto pipeline error: {e}")
        stop.wait(14400)  # 4 小时 = 14400 秒


@guarded("queue-dispatch")
def _run_pipeline_manager():
    """[Gemini_3.5_Flash_planning] 后台运行 pipeline_manager 进程处理高分视频"""
    prj_root = Path(__file__).parent.parent.parent
    python = str(prj_root / ".venv" / "bin" / "python")
    src_dir = str(prj_root / "src")
    log_path = prj_root / "output" / "pipeline.log"
    log_path.parent.mkdir(exist_ok=True)
    # [Claude_Sonnet_4.6_Thinking_planning] v3.1.0: 动态代理注入策略
    # 1. 先清除老代理变量，防止某些历史变量影响子进程
    # 2. 再检测当前代理可用性，就绣将代理注入，不就绣则不注入
    _proxy_keys = frozenset({'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'})
    env_clean = {k: v for k, v in os.environ.items() if k not in _proxy_keys}
    env_clean.update(settings.get_active_proxies())  # 就绣注入，不就绣空 update（无副作用）

    import subprocess as sp
    try:
        with open(log_path, "a") as f:
            f.write("\n=== Auto-triggered queue pipeline run ===\n")
            # [Gemini_3.5_Flash_planning] 使用 -u 启用无缓冲输出
            run_admitted([python, "-u", "-m", "video_processing.pipeline_manager",
                    "--trigger-source", "dashboard_scheduler"],
                   cwd=src_dir, stdout=f, stderr=f, env=env_clean, start_new_session=True)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"_run_pipeline_manager failed: {e}")


@registered("ready-supervisor")
def _ready_publication_supervisor(stop=None):
    """独立发布进程守护；不查询加工锁或市场避让，进程锁防重复启动。"""
    stop = stop if stop is not None else _scheduler_stop
    import time
    from video_processing.core.task_lease import read_lease_owner

    root = Path(__file__).resolve().parents[2]
    out = root / "output"
    child = None
    while not stop.is_set():
        try:
            if running() and (child is None or child.poll() is not None) and not read_lease_owner(out / "ready_publications.lock"):
                with gate().admit("worker-launch", "ready-worker-launch") as ticket:
                    ticket.start()
                    with (out / "ready_publications.log").open("a") as log:
                        child = subprocess.Popen(
                        [str(root / ".venv/bin/python"), str(root / "scripts/run_ready_publications.py")],
                        cwd=str(root), stdout=log, stderr=log, start_new_session=True,
                    )
        except Exception:
            logging.getLogger(__name__).exception("[ReadyPublication] 独立执行者启动失败")
        stop.wait(15)


@registered("queue-runner")
def _queue_runner_loop(stop=None):
    """[Gemini_3.5_Flash_planning] 每15秒巡检一次：如果有 >=75 分且状态为 PENDING 的任务，且当前没有管线任务在运行，则自动启动管线处理"""
    stop = stop if stop is not None else _scheduler_stop
    import time
    # [Gemini_3.5_Flash_planning] 自动执行队列轮询逻辑，解决切片子任务需要手动点击的痛点
    stop.wait(5)
    while not stop.is_set():
        try:
            if not running():
                stop.wait(15)
                continue
            # 复用单实例 queue-runner 角色、来源指纹及维护接纳；不新增 cron。
            if settings.topic_scheduler_enabled:
                try:
                    app.state.topic_runtime.service().tick()
                except Exception:
                    logging.getLogger(__name__).warning("关键词调度暂不可用，等待下一轮核实")
            recovered = _recover_orphaned_publishing_tasks(stale_minutes=30)
            if recovered > 0:
                logging.getLogger(__name__).warning(
                    f"[Scheduler] Recovered {recovered} orphaned PUBLISHING task(s) to SUBMITTED_UNBOUND"
                )

            recovered_pre_submission = _recover_orphaned_pre_submission_tasks(stale_minutes=20)
            if recovered_pre_submission > 0:
                logging.getLogger(__name__).warning(
                    "[Scheduler] Recovered %s orphaned pre-submission task(s)",
                    recovered_pre_submission,
                )

            # 回收超期卡在 PROCESSING 的视频号审核通知任务并补偿排水投递
            try:
                from video_processing.pipeline_manager import PipelineManager
                PipelineManager().drain_pending_review_notifications(limit=3)
            except Exception as e:
                logging.getLogger(__name__).debug(f"[Scheduler] Drain review notifications: {e}")

            # [Claude_Sonnet_4.6_Thinking_planning] v3.1.0: 每轮先清理卡在非终态的任务
            # 将卡在 DOWNLOADING/PROCESSING 超过 2 小时的死锁任务重置回 PENDING
            # 这解决了历史任务卡死后永久占用队列、幹操新任务调度的问题
            purged = db.purge_stale_tasks(stale_hours=2)
            if purged > 0:
                logging.getLogger(__name__).info(
                    f"[Scheduler] Purged {purged} stale task(s) back to PENDING"
                )

            # [Claude_Opus_4.8] 美股盘中保护：盘中不启动重型队列管线（下载/Whisper/渲染），
            # 避免抢占与实盘交易行情管线共用的整机 CPU。盘后（北京 04:15 起）自动恢复。
            if _in_us_market_window():
                stop.wait(15)
                continue

            # 队列执行者只负责窗口内提交；非窗口由受管 cron 的后台预加工入口
            # 拉取字幕并完成重活，避免仪表盘每 15 秒反复启动完整管线进程。
            if not settings.is_public_publish_window():
                stop.wait(15)
                continue

            # 1. 普通频道75，TED/TEDx50，其它演讲频道复用各自配置线
            pending_videos = db.get_high_score_pending_videos(
                min_score=75,
                limit=1,
                ready_only=False,
                channel_min_scores=settings.auto_publish_channel_min_scores,
            )
            if pending_videos:
                # 同时检查本进程线程和跨进程 pipeline.lock；cron 的受管巡航不在
                # 仪表盘线程枚举中，遗漏锁检查会额外拉起一个等待锁的重复管线。
                if _queue_pipeline_launch_allowed():
                    print(f"[Scheduler] Found pending high-score video {pending_videos[0]['youtube_id']}, auto-triggering queue pipeline...")
                    spawn_admitted(_run_pipeline_manager, role="queue-dispatch", object_key="queue-dispatch", name="queue-pipeline")
        except Exception as e:
            logging.getLogger(__name__).error(f"[Scheduler] Queue runner loop error: {e}")
        stop.wait(15)


def _queue_pipeline_launch_allowed() -> bool:
    """仅在本进程及其它进程均没有流水线持锁时允许队列启动新任务。"""
    active_threads = threading.enumerate()
    has_local_pipeline = any(
        thread.name in ("full-pipeline", "queue-pipeline") or thread.name.startswith("pipeline-")
        for thread in active_threads
    )
    return not has_local_pipeline and not _is_pipeline_manager_running()


_PIPELINE_PROCESS_MARKERS = frozenset({
    "python", "ffmpeg", "ffprobe", "yt-dlp", "curl", "playwright",
    "node", "chromium", "chrome", "video_processing", "video-processing",
    "video-precessing", "app.py", "pipeline_manager",
})


def _process_group_alive(pid: Optional[int]) -> bool:
    """保守判断进程或进程组是否仍活着。

    区分任务执行者 PID 与子进程 PGID：
    同时检查 PID 与 PGID 是否存在且非僵尸状态，结合进程命令行特征过滤，
    避免在 PID != PGID（如批量入口继承父进程组）或 PID 被操作系统无关进程复用时误判。
    """
    if not pid:
        return False
    target = int(pid)
    try:
        result = run_admitted(
            ["ps", "-axo", "pid=,pgid=,stat=,command="],
            cwd=str(Path(__file__).parent.parent.parent),
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        # 当 ps 命令受沙箱或容器权限限制不可达时，回退到基于内核系统调用的信号探测
        return _is_pid_or_pgid_alive(target)

    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 3:
            continue
        try:
            p_pid = int(parts[0])
            p_pgid = int(parts[1])
        except ValueError:
            continue
        stat = parts[2]
        if "Z" in stat:
            continue
        if p_pid == target or p_pgid == target:
            if len(parts) >= 4:
                cmd_lower = parts[3].lower()
                if any(m in cmd_lower for m in _PIPELINE_PROCESS_MARKERS):
                    return True
            else:
                return True
    return False


def _safe_kill_pid_or_pgid(pid: Optional[int], sig: int) -> None:
    """终止进程或进程组：优先以进程组终止，失败时回退至单进程。严格防御自杀。"""
    if not pid or pid == os.getpid():
        return
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def _is_pid_or_pgid_alive(pid: Optional[int]) -> bool:
    """检查进程或进程组是否仍在运行且非僵尸进程。严格防御自判。"""
    if not pid:
        return False
    if pid == os.getpid():
        return True
    try:
        os.killpg(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False


def _recover_orphaned_publishing_tasks(stale_minutes: int = 30) -> int:
    """将已死发布进程转为未绑定提交，保留平台结果未知的 fail-closed 边界。"""
    from video_processing.core.task_lease import read_lease_owner

    recovered = 0
    candidates = db.get_stale_publishing_videos(stale_minutes=stale_minutes)
    prj_root = Path(__file__).resolve().parents[2]
    for video in candidates:
        pid = video.get("process_pid")
        if _process_group_alive(pid):
            continue

        yid = video.get("youtube_id")
        slice_index = int(video.get("slice_index") or 0)
        prefix = f"{yid}_s{slice_index}" if slice_index else yid
        task_lock = prj_root / "output" / "task_locks" / f"{prefix}.lock"
        if read_lease_owner(task_lock):
            continue

        reason = (
            "发布进程已结束，但数据库仍停留在 PUBLISHING；平台可能已受理。"
            "已停止自动重传，等待视频号后台按平台记录核验。"
        )
        try:
            db.record_wechat_publication_confirmation(
                yid, evidence_path=None, state="SUBMITTED_UNBOUND",
                error_message=reason, slice_index=slice_index,
            )
            db.record_wechat_submission_attempt(
                yid, evidence_path=None, final_title=video.get("title"), slice_index=slice_index,
            )
            db.cancel_queued_downstream_publications_for_unconfirmed_wechat(
                yid, reason=reason, slice_index=slice_index,
            )
        except Exception:
            logger.exception("[Scheduler] 无法为孤儿发布任务写入未确认账本：%s", yid)
            # 不写 FAILED/PENDING；下一轮仍会尝试补写账本，期间不会放行重传。
            db.update_process_pid(yid, None, slice_index=slice_index)
            continue
        db.update_video_status(yid, "SUBMITTED_UNBOUND", error_msg=reason, slice_index=slice_index)
        db.update_process_pid(yid, None, slice_index=slice_index)
        recovered += 1
    return recovered


def _recover_orphaned_pre_submission_tasks(stale_minutes: int = 20) -> int:
    """回收无存活进程的预提交孤儿任务；视频号发布阶段绝不走此路径。"""
    from video_processing.core.task_lease import read_lease_owner

    recovered = 0
    pipeline_running = _is_pipeline_manager_running()
    prj_root = Path(__file__).resolve().parents[2]
    for video in db.get_stale_pre_submission_processing_videos(stale_minutes=stale_minutes):
        pid = video.get("process_pid")
        if _process_group_alive(pid):
            continue
        if pid is None and pipeline_running:
            continue

        yid = str(video.get("youtube_id") or "")
        slice_index = int(video.get("slice_index") or 0)
        prefix = f"{yid}_s{slice_index}" if slice_index else yid
        task_lock = prj_root / "output" / "task_locks" / f"{prefix}.lock"
        if read_lease_owner(task_lock):
            continue

        stage = str(video.get("status") or "预提交加工")
        next_status = db.recover_orphaned_pre_submission_task(
            yid,
            expected_process_pid=pid,
            error_msg=f"{stage} 子进程已不存在；自动有界回收，尚未触发视频号提交。",
            slice_index=slice_index,
        )
        if not next_status:
            continue
        recovered += 1
        logging.getLogger(__name__).warning(
            "[Scheduler] %s#%s orphaned %s -> %s", yid, slice_index, stage, next_status,
        )
    return recovered


@registered("keepalive-watchdog")
def _wechat_keepalive_loop(stop=None):
    """按成功认证证据保活；每分钟仅本地巡检，排期和失败退避跨重启保留。"""
    stop = stop if stop is not None else _scheduler_stop
    import logging
    log = logging.getLogger(__name__)

    prj_root = Path(__file__).parent.parent.parent
    python = str(prj_root / ".venv" / "bin" / "python")
    state_file = str(prj_root / "output" / "wechat_state.json")
    keepalive_script = str(prj_root / "scripts" / "wechat_keepalive.py")

    import subprocess as _sp
    import threading as _threading

    from video_processing.core.wechat_auth_state import (
        read_wechat_auth_state, record_wechat_keepalive_schedule,
        record_wechat_keepalive_defer, record_wechat_keepalive_attempt,
    )
    from video_processing.core.wechat_keepalive_schedule import demand_plan
    from video_processing.core.wechat_request_guard import WeChatRequestGuard

    first_iteration = True
    while not stop.is_set():
        waited_this_round = False
        try:
            interval = max(5, settings.wechat_keepalive_initial_delay_seconds) if first_iteration else 60
            first_iteration = False
            stop.wait(interval)
            waited_this_round = True
            if stop.is_set():
                break

            # 开关与维护状态检查（sleep 后判断，支持运行时热更新配置）
            if not running():
                log.debug("[Keepalive] System in maintenance, skipping keepalive.")
                continue
            if (settings.wechat_account_scheduler_enabled and not settings.wechat_operations_enabled) or not settings.wechat_keepalive_enabled:
                try:
                    from video_processing.core.wechat_auth_state import record_wechat_keepalive_defer
                    record_wechat_keepalive_defer(state_file, defer_reason="DISABLED")
                except Exception:
                    pass
                log.debug("[Keepalive] Keepalive disabled by settings, skipping.")
                continue

            now = time.time()
            auth = read_wechat_auth_state(state_file)
            plan = demand_plan(auth, now, settings.wechat_keepalive_idle_seconds)
            if plan["due"]:
                admission = WeChatRequestGuard(state_file).evaluate("保活", account_only=True)
                plan = demand_plan(auth, now, settings.wechat_keepalive_idle_seconds, admission)
            record_wechat_keepalive_schedule(state_file, scheduled_at=plan["at"], heartbeat_at=now)
            record_wechat_keepalive_defer(state_file, defer_reason=plan["reason"], timestamp=now)
            if not plan["due"]:
                continue

            # 互斥检测：若有微信上传相关线程或跨进程浏览器锁正在运行，下一轮本地巡检再判定
            # 使用 inspect_wechat_session_lock(state_file).locked 显式布尔判锁，杜绝空字典 {} is not None 恒真陷阱
            active_threads = _threading.enumerate()
            upload_running = any(
                "wechat-uploader" in t.name or "upload" in t.name.lower()
                for t in active_threads
            )
            from video_processing.core.wechat_session_lock import inspect_wechat_session_lock
            lock_status = inspect_wechat_session_lock(state_file)
            if upload_running or lock_status.locked:
                try:
                    from video_processing.core.wechat_auth_state import record_wechat_keepalive_defer
                    record_wechat_keepalive_defer(state_file, defer_reason="LOCK_BUSY")
                except Exception:
                    pass
                log.info("[Keepalive] Upload or browser session lock busy, rechecking locally on the next tick.")
                continue

            # 微信服务端会话存在约 24 小时绝对寿命；在达到阈值窗口（默认 10 小时）提前自动重登，
            # 保留旧 state 直到授权成功，避免发布时才被动发现 LOGIN_REQUIRED。
            # 若重登刚失败处于指数退避窗口或需先探测旧凭证，_wechat_session_needs_auto_relogin() 返回 False，
            # 自动回退到下方普通 keepalive 探测，严禁饿死保活。
            if _wechat_session_needs_auto_relogin():
                started = _start_wechat_login_flow(
                    headless=bool(settings.wechat_headless),
                    preserve_marker=True,
                    reason="automatic pre-expiry relogin",
                )
                try:
                    from video_processing.core.wechat_auth_state import record_wechat_keepalive_defer
                    record_wechat_keepalive_defer(state_file, defer_reason="RELOGIN_IN_PROGRESS")
                except Exception:
                    pass
                log.warning(f"[Keepalive] Automatic pre-expiry relogin triggered: {started}")
                continue

            try:
                from video_processing.core.wechat_auth_state import record_wechat_keepalive_defer
                record_wechat_keepalive_defer(state_file, defer_reason=None)
            except Exception:
                pass
            log.info("[Keepalive] Triggering WeChat session keepalive...")

            # 构建子进程环境：不注入代理（与 wechat_uploader 一致），注入 Telegram 凭据
            _proxy_keys = frozenset({
                'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
                'http_proxy', 'https_proxy', 'all_proxy'
            })
            env = {k: v for k, v in os.environ.items() if k not in _proxy_keys}
            if settings.telegram_bot_token:
                env["TELEGRAM_BOT_TOKEN"] = settings.telegram_bot_token
            if settings.active_telegram_chat_id:
                env["TELEGRAM_CHAT_ID"] = settings.active_telegram_chat_id
            if settings.telegram_admin_ids:
                env["TELEGRAM_ADMIN_IDS"] = settings.telegram_admin_ids

            try:
                result = run_admitted(
                    [
                        python, keepalive_script,
                        "--state", state_file,
                        "--dwell", str(settings.wechat_keepalive_dwell),
                    ],
                    env=env,
                    timeout=120,  # 子进程最大 120 秒超时保护
                )
                if result.returncode == 0:
                    log.info("[Keepalive] WeChat session refreshed successfully.")
                elif result.returncode == 2:
                    log.warning("[Keepalive] WeChat session expired (LOGIN_REQUIRED). Telegram alert sent.")
                    if settings.wechat_auto_relogin_enabled:
                        started = _start_wechat_login_flow(
                            headless=bool(settings.wechat_headless),
                            preserve_marker=True,
                            reason="expired keepalive session",
                        )
                        log.warning("[Keepalive] Expired-session relogin triggered: %s", started)
                elif result.returncode in {15, 17}:
                    admission = WeChatRequestGuard(state_file).evaluate("保活", account_only=True)
                    plan = demand_plan(read_wechat_auth_state(state_file), time.time(),
                                       settings.wechat_keepalive_idle_seconds, admission)
                    record_wechat_keepalive_schedule(state_file, scheduled_at=max(time.time() + 60, plan["at"]))
                    record_wechat_keepalive_defer(state_file, defer_reason=plan["reason"] or "ACCOUNT_WAIT")
                    log.info("[Keepalive] Account admission deferred: %s", plan["reason"])
                elif result.returncode == 11:
                    try:
                        from video_processing.core.wechat_auth_state import record_wechat_keepalive_defer
                        record_wechat_keepalive_defer(state_file, defer_reason="LOCK_BUSY")
                    except Exception:
                        pass
                    log.info("[Keepalive] WeChat session lock busy (upload or other operation running), rechecking locally on the next tick.")
                else:
                    if (read_wechat_auth_state(state_file).get("last_keepalive_attempt_at") or 0) < now:
                        record_wechat_keepalive_attempt(state_file)
                    log.warning(f"[Keepalive] Keepalive subprocess returned code: {result.returncode}.")
            except _sp.TimeoutExpired:
                if (read_wechat_auth_state(state_file).get("last_keepalive_attempt_at") or 0) < now:
                    record_wechat_keepalive_attempt(state_file)
                log.error("[Keepalive] Keepalive subprocess timed out after 120s.")
            except FileNotFoundError:
                record_wechat_keepalive_attempt(state_file)
                log.error(f"[Keepalive] Keepalive script not found: {keepalive_script}")
            except Exception as e:
                if (read_wechat_auth_state(state_file).get("last_keepalive_attempt_at") or 0) < now:
                    record_wechat_keepalive_attempt(state_file)
                log.error(f"[Keepalive] Unexpected error: {e}")
        except Exception as loop_exc:
            log.exception("[Keepalive] Unhandled exception in watchdog loop iteration: %s", loop_exc)
            try:
                from video_processing.core.wechat_auth_state import record_wechat_keepalive_defer
                record_wechat_keepalive_defer(state_file, defer_reason="LOOP_EXCEPTION")
            except Exception:
                pass
            if not waited_this_round and not stop.is_set():
                stop.wait(60)


@app.on_event("startup")
def startup_event():
    """FastAPI 启动时自动运行后台调度器，并在主线程注册信号处理器。

    [Claude_Sonnet_4.6_Thinking_planning] BUG-1 修复：signal.signal() 只能在主线程调用。
    _process_single_video经由 daemon 线程执行，无法在内部注册信号。
    将 SIGTERM handler 注册移至此处（FastAPI startup 在主线程运行）。
    """
    global _maintenance_ui_lease, _scheduler_stop, _scheduler_threads
    if _maintenance_ui_lease is not None:
        return
    lease = role_lease("ui")
    lease.__enter__()
    _maintenance_ui_lease = lease
    _scheduler_stop = threading.Event()
    # Web 生命周期信号归 Uvicorn；流水线标志处理器不负责退出服务器。
    # 维护工具已在发 SIGTERM 前核实在途为空，不能覆盖服务器正常退出处理。

    _scheduler_threads = [threading.Thread(target=target, args=(_scheduler_stop,), daemon=True, name=name)
                          for target, name in (
                              (_auto_pipeline_loop, "auto-pipeline-scheduler"),
                              (_ready_publication_supervisor, "ready-publication-supervisor"),
                              (_queue_runner_loop, "queue-runner-scheduler"),
                              (_wechat_keepalive_loop, "wechat-keepalive-watchdog"),
                          )]
    for thread in _scheduler_threads:
        thread.start()
    print("[Scheduler] Background pipeline scheduler started.")

    print("[Scheduler] Queue runner scheduler started.")

    # [Claude_Sonnet_4.6_Thinking_planning] v3.2.0: WeChat Session 看门狗
    print("[Scheduler] WeChat session keepalive watchdog started.")


_maintenance_ui_lease = None
_scheduler_stop = threading.Event()
_scheduler_threads = []


@app.on_event("shutdown")
def release_maintenance_ui_role():
    global _maintenance_ui_lease
    _scheduler_stop.set()
    deadline = time.monotonic() + 2
    for thread in _scheduler_threads:
        thread.join(max(0, deadline - time.monotonic()))
    if any(thread.is_alive() for thread in _scheduler_threads):
        # 不把未排空的同进程热重载冒充已退出，角色锁仍保留至进程结束。
        raise RuntimeError("维护调度器尚未退出")
    if _maintenance_ui_lease is not None:
        _maintenance_ui_lease.__exit__(None, None, None)
        _maintenance_ui_lease = None

# 下载器与生产加工共用项目虚拟环境。
_YT_DLP = settings.ytdlp_path  # 下载器必须加载项目 FFmpeg 单名额启动钩子。

# [Claude_Sonnet_4.6_Thinking_planning] SEC-1 修复：严格 YouTube 域名白名单。
# 旧方案 `any(d in url ...)` 可被路径、子域名、data URI 等 5 种向量绕过。
# urlparse().netloc 精准提取 host，不受路径/查询串/协议影响。
_ALLOWED_YOUTUBE_HOSTS: frozenset = frozenset({
    "www.youtube.com",
    "youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
})


def _is_youtube_url(url: str) -> bool:
    """严格校验 URL 是否属于 YouTube 官方域名（netloc 级别匹配）。

    防御向量：
    - https://evil.com/youtube.com       → netloc=evil.com → BLOCKED
    - https://youtube.com.evil.com/      → netloc=youtube.com.evil.com → BLOCKED
    - data:text/html,youtube.com         → netloc='' → BLOCKED
    - https://www.youtube.com/watch?v=x  → netloc=www.youtube.com → ALLOWED
    """
    try:
        host = urlparse(url).netloc.lower().split(":")[0]  # 去端口号
        return host in _ALLOWED_YOUTUBE_HOSTS
    except Exception:
        return False


# 实际占用管线执行资源的状态；平台已受理待确认不属于加工中。
PROCESSING_STATUSES = {"PROCESSING", "PUBLISH_PRECHECK", "DOWNLOADING", "TRANSCRIBING", "COPYWRITING", "PUBLISHING"}

# 保留既有安全保护：UNDER_REVIEW 不可被删除/停止接口当作普通终态处理，
# 以免为修正展示语义而误删已提交的平台作品证据。
ACTIVE_STATUSES = PROCESSING_STATUSES | {"UNDER_REVIEW"}

# 视频号平台状态是不可逆外部事实：任何本地平台生命周期状态或账本均不能被
# 通用重试/重置接口回写为 PENDING。只有专用、人工确认的发布流程可另行处理。
_WECHAT_SUBMISSION_GUARD_STATUSES = frozenset({
    "PUBLISHING", "UNDER_REVIEW", "SUBMITTED_UNBOUND", "SUBMITTED_BOUND", "UNCERTAIN",
    "PUBLISHED", "REJECTED", "NOT_FOUND", "HISTORICAL_UNRESOLVED", "HISTORICAL_ARCHIVED",
})


def _wechat_submission_guard_reason(video: dict) -> Optional[str]:
    """返回阻止通用重试的原因；账本读取失败也按 fail-closed 处理。"""
    status = str(video.get("status") or "").upper()
    if status in _WECHAT_SUBMISSION_GUARD_STATUSES:
        return f"视频号当前为 {status}，提交结果未获公开发布证明，禁止通用重试或重置。"
    try:
        publication = db.get_wechat_publication(
            str(video["youtube_id"]), slice_index=int(video.get("slice_index") or 0),
        )
    except Exception as exc:
        logger.error("读取视频号确认账本失败，拒绝重置 %s: %s", video.get("youtube_id"), exc)
        return "无法读取视频号确认账本；为防止重复提交，拒绝重试或重置。"
    if publication:
        return f"视频号存在 {publication.get('state') or 'UNKNOWN'} 平台账本，禁止通用重试或重置。"
    return None

# FSM 状态的显示顺序
STATUS_ORDER = [
    "PENDING", "PROCESSING", "PUBLISH_PRECHECK", "DOWNLOADING", "TRANSCRIBING", "COPYWRITING", "PUBLISHING",
    "SUBMITTED_UNBOUND", "SUBMITTED_BOUND", "UNDER_REVIEW", "UNCERTAIN",
    "PUBLISHED", "FAILED", "LOGIN_REQUIRED",
]


# ── Pydantic 请求体 ──────────────────────────────────────────────────────
class AddChannelRequest(BaseModel):
    url: str
    promote: Optional[bool] = False


class BatchDeleteRequest(BaseModel):  # [Gemini_2.5_Pro_planning]
    youtube_ids: list[str]
    delete_files: bool = False


class CensorshipBypassRequest(BaseModel):
    """P0 须双确认；平台题材复核须绑定当前展示的审计及输入、规则版本。"""
    confirm_p0_review: bool = False
    confirm_pipeline_resume: bool = False
    incident_id: Optional[int] = None
    input_hash: Optional[str] = None
    rule_version: Optional[str] = None


class PlatformBackfillQueueRequest(BaseModel):
    platform: str
    since_upload_date: Optional[str] = None
    wall_street_days: int = 10
    daily_limit: int = 5
    youtube_ids: Optional[list[str]] = None


class DouyinPublicationRequeueRequest(BaseModel):
    publication_id: int


_OUT_DIR = Path(__file__).parent.parent.parent / "output"


def _invalidate_audio_variant_artifacts(youtube_id: str) -> list[str]:
    """删除音轨规格切换后必然失真的派生产物，保留下载源和文案检查点。"""
    deleted: list[str] = []
    for suffix in ("_vertical.mp4", ".ass", "_cover.jpg", "_cover_brief.json", "_cover_provenance.json"):
        path = _OUT_DIR / f"{youtube_id}{suffix}"
        if not path.is_file():
            continue
        try:
            path.unlink()
            deleted.append(path.name)
        except OSError as exc:
            logging.getLogger(__name__).warning("音轨规格变更时无法清理 %s: %s", path.name, exc)
    return deleted


def _default_backfill_since_upload_date(days: int = 10) -> str:
    return (datetime.now().date() - timedelta(days=max(0, int(days)))).strftime("%Y%m%d")


def _normalize_backfill_since(since_upload_date: Optional[str], wall_street_days: int) -> str:
    since = (since_upload_date or "").strip() or _default_backfill_since_upload_date(wall_street_days)
    if not re.match(r"^\d{8}$", since):
        raise HTTPException(status_code=400, detail="since_upload_date must be YYYYMMDD")
    return since


def _active_douyin_ui_failure_stages_for_dashboard() -> tuple[Optional[set[str]], Optional[str]]:
    """读取并严格校验抖音 UI 熔断账本；任何不可判定状态均拒绝控制面写入。"""
    try:
        streaks = db.get_platform_ui_failure_streaks("douyin")
    except Exception as exc:
        logging.getLogger(__name__).exception("读取抖音 UI 熔断账本失败，拒绝仪表盘写入: %s", exc)
        return None, "无法读取抖音 UI 熔断账本；为防止绕过熔断，拒绝写入投递队列。"

    if not isinstance(streaks, list):
        logging.getLogger(__name__).error(
            "抖音 UI 熔断账本格式异常（期待列表，实际 %s），拒绝仪表盘写入",
            type(streaks).__name__,
        )
        return None, "抖音 UI 熔断账本格式异常；为防止绕过熔断，拒绝写入投递队列。"

    try:
        for row in streaks:
            if not isinstance(row, Mapping):
                raise ValueError(f"记录不是映射：{type(row).__name__}")
            stage = row.get("stage")
            active = row.get("active")
            consecutive_failures = row.get("consecutive_failures")
            if not isinstance(stage, str) or not stage.strip():
                raise ValueError("stage 为空或不是字符串")
            if isinstance(active, bool) or not isinstance(active, int) or active not in {0, 1}:
                raise ValueError("active 不是 0 或 1")
            if (
                isinstance(consecutive_failures, bool)
                or not isinstance(consecutive_failures, int)
                or consecutive_failures < 0
            ):
                raise ValueError("consecutive_failures 不是非负整数")
        return active_douyin_ui_failure_stages(
            streaks,
            recording_threshold=settings.douyin_ui_failure_recording_threshold,
        ), None
    except (TypeError, ValueError) as exc:
        logging.getLogger(__name__).error("抖音 UI 熔断账本格式异常，拒绝仪表盘写入: %s", exc)
        return None, "抖音 UI 熔断账本格式异常；为防止绕过熔断，拒绝写入投递队列。"


def _backfill_asset_paths(youtube_id: str, slice_index: int) -> dict[str, Path]:
    prefix = f"{youtube_id}_s{slice_index}" if slice_index > 0 else youtube_id
    return {
        "video": _OUT_DIR / f"{prefix}_vertical.mp4",
        "copy": _OUT_DIR / f"{prefix}_copy.txt",
        "title": _OUT_DIR / f"{prefix}_title.txt",
    }


def _read_publish_text(path: Path, *, max_chars: int = 800) -> Optional[str]:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except Exception as exc:
        logging.getLogger(__name__).warning("[Dashboard] Failed to read publish artifact %s: %s", path, exc)
        return None
    if not text:
        return None
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "..."
    return text


def _attach_publish_display_fields(rows: list[dict]) -> list[dict]:
    """为仪表盘行补齐真实投递标题，保证后台列表与平台发布标题一致。"""
    for row in rows:
        from video_processing.core.censorship_state import review_state
        row['censorship_state'] = review_state(row, bool(
            row.get('bypass_censorship') and db.has_manual_p0_approval(
                row.get('youtube_id'), slice_index=int(row.get('slice_index') or 0))))
        row['processing_detail'] = _caption_processing_detail(row)
        em = row.get('error_msg') or ''
        row['failure_summary'] = '原字幕定位失败' if row.get('status') == 'FAILED' and '原字幕位置或文字不确定' in em else ''
        yid = row.get("youtube_id")
        if not yid:
            continue
        slice_index = int(row.get("slice_index") or 0)
        wechat = (row.get('platforms') or {}).get('wechat')
        if wechat and wechat.get('state') == 'UNCERTAIN':
            from video_processing.core.operation_receipts import submission_feedback
            feedback = submission_feedback(_OUT_DIR, yid, slice_index)
            wechat['confirmation'] = feedback
            if feedback['kind'] == 'MANUAL_CONFIRMATION_REQUIRED':
                wechat['display_state'] = 'MANUAL_CONFIRMATION_REQUIRED'
                wechat['error'] = feedback['message']
        paths = _backfill_asset_paths(yid, slice_index)
        published_title = _read_publish_text(paths["title"], max_chars=120)
        published_copy_preview = _read_publish_text(paths["copy"], max_chars=280)
        source_zh_title = (row.get("zh_title") or "").strip()

        row["published_title"] = published_title
        row["published_copy_preview"] = published_copy_preview
        row["display_title"] = (
            published_title
            or source_zh_title
            or (row.get("title") or "").strip()
            or yid
        )
        row["title_mismatch"] = bool(
            published_title
            and source_zh_title
            and published_title != source_zh_title
        )
    return rows


def _caption_processing_detail(row: dict) -> str:
    """只展示当前活跃字幕任务的近期心跳，终态不沿用旧阶段。"""
    if row.get('status') != 'TRANSCRIBING':
        return ''
    yid, index = row.get('youtube_id'), int(row.get('slice_index') or 0)
    prefix = f'{yid}_s{index}' if index else yid
    labels = dict(STARTING='字幕准备中', AUDIO_EXTRACTING='提取音频中', MODEL_LOADING='加载识别模型中',
                  TRANSCRIBING='转录中', TRANSLATING='翻译中', ASR_REUSED='复用转录',
                  TRANSLATION_REUSED='复用翻译', SOURCE_CAPTION_LOCATING='继续原字幕定位',
                  ASS_GENERATING='生成字幕排版', VIDEO_RENDERING='继续视频渲染', COMPLETE='字幕处理完成')
    try:
        path = _OUT_DIR / f'{prefix}_caption_progress.json'
        if path.stat().st_size > 16384:
            return ''
        payload = json.loads(path.read_text(encoding='utf-8'))
        age = time.time() - float(payload['updated_at'])
        if not 0 <= age <= 90:
            return ''
        reused = [label for key, label in (('copy', '复用已有文案'), ('asr', '复用转录'),
                                           ('translation', '复用翻译')) if key in payload.get('reused_steps', [])]
        return ' · '.join(reused + [labels.get(payload.get('stage'), '字幕处理中')])
    except (OSError, ValueError, KeyError, TypeError):
        return ''


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backfill_row_payload(row: dict) -> dict:
    yid = row.get("youtube_id")
    slice_index = int(row.get("slice_index") or 0)
    paths = _backfill_asset_paths(yid, slice_index)
    return {
        **row,
        "slice_index": slice_index,
        "rules": [
            label for flag, label in (
                (row.get("is_speech_or_interview"), "访谈/演讲"),
                (row.get("is_recent_wall_street"), "Wall Street Truthbombs 最近窗口"),
            )
            if int(flag or 0)
        ],
        "assets": {name: path.is_file() for name, path in paths.items()},
    }


def _build_backfill_preview_payload(
    *,
    since_upload_date: str,
    wechat_daily_limit: int,
    wechat_max_daily_limit: int,
    douyin_daily_limit: int,
    limit: int,
) -> dict:
    platform_limits = {
        "wechat": {"label": "微信", "daily_limit": max(1, min(int(wechat_daily_limit), 50))},
        "douyin": {"label": "抖音", "daily_limit": max(1, min(int(douyin_daily_limit), 50))},
    }
    payload = {
        "success": True,
        "since_upload_date": since_upload_date,
        "wechat_max_daily_limit": max(1, min(int(wechat_max_daily_limit), 50)),
        "platforms": {},
    }
    for platform, meta in platform_limits.items():
        rows = [
            _backfill_row_payload(row)
            for row in db.get_platform_backfill_preview_candidates(
                platform,
                wall_street_since_upload_date=since_upload_date,
                limit=max(1, min(int(limit), 5000)),
            )
        ]
        daily_limit = meta["daily_limit"]
        batches = [rows[index:index + daily_limit] for index in range(0, len(rows), daily_limit)]
        payload["platforms"][platform] = {
            "label": meta["label"],
            "daily_limit": daily_limit,
            "candidate_count": len(rows),
            "queueable_count": sum(1 for row in rows if row["assets"]["video"]),
            "estimated_days": len(batches),
            "batches": [
                {"day": index + 1, "items": batch}
                for index, batch in enumerate(batches[:3])
            ],
        }
    return payload


# ── 页面路由 ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def dashboard():
    """返回仪表盘 HTML 页面，自动注入静态资源 mtime 版本号并禁用页面强缓存，击穿移动端/PWA 缓存。"""
    template_path = Path(__file__).parent / "templates" / "index.html"
    content = template_path.read_text(encoding="utf-8")

    css_path = _static_dir / "css" / "dashboard.css"
    js_path = _static_dir / "js" / "channel_manager.js"
    css_v = int(css_path.stat().st_mtime) if css_path.exists() else int(time.time())
    js_v = int(js_path.stat().st_mtime) if js_path.exists() else int(time.time())

    content = re.sub(r'/static/css/dashboard\.css(?:\?v=[^"\'\s>]+)?', f'/static/css/dashboard.css?v={css_v}', content)
    content = re.sub(r'/static/js/channel_manager\.js(?:\?v=[^"\'\s>]+)?', f'/static/js/channel_manager.js?v={js_v}', content)

    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/api/console/capabilities")
def console_capabilities(request: Request):
    """只读入口与配置摘要；不建立候选会话、不启动搜索或触发服务恢复。"""
    import ipaddress
    try:
        local = bool(request.client and ipaddress.ip_address(request.client.host).is_loopback)
    except ValueError:
        local = False
    return {"topic_available": local, "search_enabled": bool(settings.topic_search_enabled)}


@app.api_route("/apple-touch-icon.png", methods=["GET", "HEAD"])
@app.api_route("/apple-touch-icon-precomposed.png", methods=["GET", "HEAD"])
def apple_touch_icon():
    """为 iOS Safari 添加到主屏幕直出高清 📺 原生 PNG 图标"""
    return FileResponse(_static_dir / "apple-touch-icon.png", media_type="image/png")


@app.api_route("/favicon.ico", methods=["GET", "HEAD"])
def favicon_ico():
    """直出 📺 favicon.ico"""
    return FileResponse(_static_dir / "favicon.ico", media_type="image/x-icon")


@app.get("/api/ai-audit/summary")
def get_ai_audit_summary(hours: int = 168):
    """AI 字幕调用概览：近期开销、失败与降级统计。"""
    return db.get_ai_audit_summary(hours=hours)


@app.get("/api/ai-audit/videos/{youtube_id}")
def get_ai_audit_video(youtube_id: str, slice_index: int = 0, limit: int = 20):
    """指定视频的 AI 处理运行与 provider 尝试时间线。"""
    if not re.match(r'^[A-Za-z0-9_\-]+$', youtube_id):
        raise HTTPException(status_code=400, detail="Invalid youtube_id")
    return {
        "youtube_id": youtube_id,
        "slice_index": slice_index,
        "runs": db.get_ai_audit_for_video(youtube_id, slice_index=slice_index, limit=limit),
    }


# ── 封面图片 API ─────────────────────────────────────────────────────────
@app.get("/api/covers/{youtube_id}")
def get_cover(youtube_id: str, slice_index: int = 0):
    """[Gemini_2.5_Pro_planning] 返回指定视频 ID 的封面图片（JPEG）。
    若封面文件不存在则返回 404，前端可据此显示占位符。
    """
    # 安全校验：youtube_id 只允许字母/数字/连字符/下划线
    if not re.match(r'^[A-Za-z0-9_\-]+$', youtube_id):
        raise HTTPException(status_code=400, detail="Invalid youtube_id")
    if slice_index < 0:
        raise HTTPException(status_code=400, detail="Invalid slice_index")
    prefix = youtube_id if slice_index == 0 else f"{youtube_id}_s{slice_index}"
    context = db.get_cover_context(youtube_id, slice_index)
    if context.get("binding") == "submission" and context.get("version_id"):
        cover_path = Path(context["evidence_path"]) / "submitted_cover.jpg"
        import hashlib
        if not cover_path.is_file() or hashlib.sha256(cover_path.read_bytes()).hexdigest() != context.get("cover_sha256"):
            raise HTTPException(status_code=404, detail="Bound cover unavailable")
    else:
        cover_path = _OUT_DIR / f"{prefix}_cover.jpg"
    if not cover_path.exists():
        raise HTTPException(status_code=404, detail="Cover not found")
    return FileResponse(
        str(cover_path),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache"},
    )


# ── 统计 API ─────────────────────────────────────────────────────────────
@app.get("/api/stats")
def get_stats():
    """返回各状态视频数量，用于顶部统计卡片"""
    from video_processing.core.ffmpeg_slot import config_status
    from video_processing.processors.ted_source_cleanup import RECIPE as cleanup_recipe
    counts = db.get_status_counts()
    total = sum(counts.values())
    active = sum(v for k, v in counts.items() if k in PROCESSING_STATUSES)
    detailed = db.get_detailed_stats()
    return {
        "total": total,
        "pending": counts.get("PENDING", 0),
        "active": active,
        "published": counts.get("PUBLISHED", 0),
        "failed": counts.get("FAILED", 0) + counts.get("LOGIN_REQUIRED", 0),
        "breakdown": {s: counts.get(s, 0) for s in STATUS_ORDER},
        "detailed": detailed,
        "server_time": datetime.now().strftime("%H:%M:%S"),
        "source_preparation": {
            "ted_source_cleanup_enabled": settings.enable_ted_source_cleanup,
            "ted_opening_trim_enabled": settings.enable_ted_opening_trim,
            "recipe": cleanup_recipe,
        },
        "resource_control": {
            **config_status(),
            "ffmpeg_guard_enabled": subprocess.Popen.__module__ == "video_processing.core.ffmpeg_slot",
            "pid": os.getpid(),
        },
    }


@app.get("/api/platform-backfill/preview")
def platform_backfill_preview(
    since_upload_date: Optional[str] = None,
    wall_street_days: int = 10,
    wechat_daily_limit: int = 5,
    wechat_max_daily_limit: int = 8,
    douyin_daily_limit: int = 20,
    limit: int = 500,
):
    """只读预览微信/抖音补录候选和日批次，不创建任何发布任务。"""
    since = _normalize_backfill_since(since_upload_date, wall_street_days)
    return _build_backfill_preview_payload(
        since_upload_date=since,
        wechat_daily_limit=wechat_daily_limit,
        wechat_max_daily_limit=wechat_max_daily_limit,
        douyin_daily_limit=douyin_daily_limit,
        limit=limit,
    )


@app.post("/api/platform-backfill/queue")
def queue_platform_backfill(req: PlatformBackfillQueueRequest):
    """确认补录入队。

    微信：WECHAT_DEFERRED 本身就是恢复队列，确认接口只返回首批清单。
    抖音：把首批候选写入 douyin_publications(HISTORY)，等待每日迁移任务按限额发布。
    """
    platform = (req.platform or "").lower()
    if platform not in {"wechat", "douyin"}:
        return {"success": False, "error": "platform 仅支持 wechat / douyin"}
    if platform == "douyin":
        active_stages, guard_error = _active_douyin_ui_failure_stages_for_dashboard()
        if guard_error:
            return {"success": False, "error": guard_error}
        if douyin_management_verify_is_blocked(active_stages or set()):
            stages = ", ".join(sorted(active_stages or set()))
            return {
                "success": False,
                "error": f"抖音 UI 熔断活动（{stages}），已拒绝 HISTORY 补录入队。",
            }
    since = _normalize_backfill_since(req.since_upload_date, req.wall_street_days)
    daily_limit = max(1, min(int(req.daily_limit), 50))
    requested_ids = set(req.youtube_ids or [])
    rows = db.get_platform_backfill_preview_candidates(
        platform,
        wall_street_since_upload_date=since,
        limit=5000,
    )
    if requested_ids:
        rows = [row for row in rows if row.get("youtube_id") in requested_ids]
    rows = rows[:daily_limit]

    queued = []
    skipped = []
    if platform == "wechat":
        for row in rows:
            payload = _backfill_row_payload(row)
            queued.append({
                "youtube_id": payload["youtube_id"],
                "slice_index": payload["slice_index"],
                "state": payload["wechat_status"],
                "message": "已在微信恢复队列，等待每日任务按限额补发",
            })
        return {
            "success": True,
            "platform": platform,
            "since_upload_date": since,
            "queued_count": len(queued),
            "skipped_count": 0,
            "queued": queued,
            "skipped": skipped,
        }

    for row in rows:
        yid = row.get("youtube_id")
        slice_index = int(row.get("slice_index") or 0)
        paths = _backfill_asset_paths(yid, slice_index)
        missing = [name for name, path in paths.items() if not path.is_file()]
        if missing:
            skipped.append({
                "youtube_id": yid,
                "slice_index": slice_index,
                "reason": "缺少抖音投递产物：" + ",".join(missing),
            })
            continue
        publication = db.create_douyin_publication(
            yid,
            _sha256_file(paths["video"]),
            str(paths["video"]),
            source_kind="HISTORY",
            slice_index=slice_index,
        )
        queued.append({
            "youtube_id": yid,
            "slice_index": slice_index,
            "publication_id": publication.get("id"),
            "state": publication.get("state"),
            "attempt_number": publication.get("attempt_number"),
        })
    return {
        "success": True,
        "platform": platform,
        "since_upload_date": since,
        "queued_count": len(queued),
        "skipped_count": len(skipped),
        "queued": queued,
        "skipped": skipped,
    }


@app.post("/api/douyin/publications/requeue")
def requeue_canceled_douyin_publication(req: DouyinPublicationRequeueRequest):
    """人工确认抖音页面与投递产物已修复后，创建一条新的可审计队列记录。"""
    active_stages, guard_error = _active_douyin_ui_failure_stages_for_dashboard()
    if guard_error:
        return {"success": False, "error": guard_error}
    publication = db.get_douyin_publication_by_id(req.publication_id)
    if not publication:
        return {"success": False, "error": "抖音投递记录不存在"}
    if publication.get("state") != "CANCELED":
        return {"success": False, "error": "仅 CANCELED 的抖音记录允许人工重新入队"}
    source_kind = str(publication.get("source_kind") or "").upper()
    if source_kind == "HISTORY":
        blocked = douyin_management_verify_is_blocked(active_stages or set())
    elif source_kind == "NEW":
        blocked = douyin_publish_is_blocked(active_stages or set())
    else:
        return {"success": False, "error": "抖音投递来源异常；为防止绕过熔断，拒绝重新入队。"}
    if blocked:
        stages = ", ".join(sorted(active_stages or set()))
        return {
            "success": False,
            "error": f"抖音 UI 熔断活动（{stages}），已拒绝 {source_kind} CANCELED 重新入队。",
        }
    video_path = Path(str(publication.get("video_path") or ""))
    if not video_path.is_file():
        return {"success": False, "error": "成片不存在，不能重新入队"}
    try:
        requeued = db.requeue_canceled_douyin_publication(req.publication_id)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    return {
        "success": True,
        "publication_id": requeued["id"],
        "attempt_number": requeued["attempt_number"],
        "state": requeued["state"],
    }


class EngagementReviewedRequest(BaseModel):
    """仅记录控制面浏览状态；与生产和平台投递状态完全隔离。"""

    reviewed: bool


def _validate_video_list_query(
    tab: str,
    size: int,
    search: str,
    sort: str,
    score_band: str,
    error_type: str,
    status: str,
    engagement_window_days: int,
    created_window: str = "all",
    funnel_stage: Optional[str] = None,
) -> None:
    """在进入 DAL 前拒绝未知控制面参数，避免静默退化为错误列表。"""
    if tab not in _VIDEO_TABS:
        raise HTTPException(status_code=422, detail="unknown tab")
    if not 1 <= size <= 100:
        raise HTTPException(status_code=422, detail="size must be between 1 and 100")
    if len(search) > 200:
        raise HTTPException(status_code=422, detail="search is too long")
    if sort not in _VIDEO_SORTS:
        raise HTTPException(status_code=422, detail="unknown sort")
    if score_band not in _SCORE_BANDS:
        raise HTTPException(status_code=422, detail="unknown score band")
    if error_type not in _ERROR_TYPES:
        raise HTTPException(status_code=422, detail="unknown error type")
    if status != "all" and status not in _VIDEO_STATUSES and status not in ENGAGEMENT_STAGES:
        raise HTTPException(status_code=422, detail="unknown status")
    if engagement_window_days not in _ENGAGEMENT_WINDOWS:
        raise HTTPException(status_code=422, detail="unsupported engagement window")
    if created_window not in _CREATED_WINDOWS:
        raise HTTPException(status_code=422, detail="unknown created window")
    if funnel_stage and funnel_stage not in _FUNNEL_STAGES:
        raise HTTPException(status_code=422, detail="unknown funnel stage")
    if not funnel_stage and tab != "error" and error_type != "all":
        raise HTTPException(status_code=422, detail="error type only applies to error tab")
    if tab != "high_likes" and status != "all":
        raise HTTPException(status_code=422, detail="status filter only applies to recent engagement")


def _attach_ready_publication_fields(videos: list[dict]) -> None:
    """只读真实资格与当前运行门禁；过期的文字原因不作为当前事实。"""
    import json
    import time
    from video_processing.core.task_lease import read_lease_owner
    from video_processing.core.wechat_session_lock import canonical_wechat_session_lock_path
    from video_processing.core.wechat_request_guard import WeChatRequestDeferred
    from video_processing.utils.wechat_product_execution import blocked_product_task_keys

    ready = [v for v in videos if v.get('status') == 'PUBLISH_PRECHECK'
             or (v.get('status') == 'PENDING' and v.get('preparation_ready'))]
    if not ready:
        return
    out = _OUT_DIR
    excluded = blocked_product_task_keys(out, settings.wechat_product_policy_path)
    facts = db.get_publication_eligibility([v['id'] for v in ready],
        source_subtitle_retry_hours=settings.source_subtitle_retry_hours, excluded_product_tasks=excluded)
    owner = read_lease_owner(canonical_wechat_session_lock_path(out / 'wechat_state.json'))
    details = db.get_publication_queue_details([v['id'] for v in ready])
    try:
        runtime = json.loads((out / 'ready_publications_status.json').read_text())
        healthy = time.time() - float(runtime.get('heartbeat_at', 0)) < 30 and bool(read_lease_owner(out / 'ready_publications.lock'))
    except (OSError, ValueError, TypeError):
        runtime, healthy = {}, False
    soft = {'STATE','RECOVERY_OPERATION','COPYWRITER_BACKOFF','UPLOAD_BACKOFF','PREDECESSOR','PRODUCT_WAIT'}
    for video in ready:
        assessment = facts[video['id']]
        blockers = list(assessment['blockers'])
        prefix = video['youtube_id'] + (f"_s{video['slice_index']}" if video.get('slice_index') else '')
        try:
            cooldown = _wechat_cooldown_guard().admission_view(prefix)
        except WeChatRequestDeferred:
            cooldown = {'active':True, 'reason':'账号记录无法核实，等待恢复', 'blockers':[]}
        if settings.wechat_publishing_paused:
            blockers.append({'code':'PUBLISHING_PAUSED','reason':'视频号发布已被人工暂停'})
        if not running():
            blockers.append({'code':'MAINTENANCE','reason':'系统处于维护或停止状态'})
        if cooldown['active']:
            blockers.extend(cooldown.get('blockers') or [{'code':'ACCOUNT_WAIT','reason':cooldown['reason']}])
        if owner:
            blockers.append({'code':'BROWSER_BUSY','reason':f"同账号浏览器占用：{owner.get('video','其他操作')}（{owner.get('stage','浏览器操作')}）"})
        if not healthy:
            blockers.append({'code':'WORKER_UNAVAILABLE','reason':'发布执行者心跳缺失，等待恢复；成片已保留'})
        hard = [b for b in assessment['blockers'] if b['code'] not in soft]
        display = 'RESULT_UNCERTAIN' if any(b['code']=='SUBMISSION_PROTECTED' for b in blockers) else 'QUALIFICATION_BLOCKED' if hard else 'READY_WAITING' if blockers else 'READY_TO_PUBLISH'
        reason = '；'.join(b['reason'] for b in blockers) if blockers else '通过当前准入检查，等待串行领取；提交前仍复验内容与素材'
        video.update(display_status=display, publication_wait_reason=reason,
            publication_eligibility=dict(assessment, eligible=not blockers, blockers=blockers),
            publication_next_attempt_at=details.get(video['id'],{}).get('next_attempt_at'),
            publication_owner=owner, publication_target='视频号', wechat_cooldown=cooldown)
        # 同一行的平台徽标和详情也须显示当前事实，不能继续引用持久化的旧冷却原因。
        wechat = (video.get('platforms') or {}).get('wechat')
        if wechat is not None:
            wechat.update(display_state=display, error=reason)


@app.get("/api/videos")
def get_videos(
    tab: str = "waitlist",
    page: int = 1,
    size: int = 20,
    search: str = "",
    channel: str = "",
    sort: str = "source_published_at_desc",
    score_band: str = "all",
    error_type: str = "all",
    status: str = "all",
    engagement_window_days: int = 3,
    include_processed: bool = False,
    include_expired: bool = False,
    created_window: str = "all",
    funnel_stage: Optional[str] = None,
    attention_kind: Optional[str] = None,
    like_rate_min: Optional[float] = None,
    like_rate_max: Optional[float] = None,
):
    """在服务端筛选和稳定排序后分页返回列表及准确总数。"""
    _validate_video_list_query(tab, size, search, sort, score_band, error_type, status, engagement_window_days, created_window, funnel_stage)
    if attention_kind and (attention_kind not in {"delivery","blocked","execution","review","policy"} or funnel_stage):
        raise HTTPException(422, "unknown or conflicting attention kind")
    for bound in (like_rate_min, like_rate_max):
        if bound is not None and not 0 <= bound <= 100:
            raise HTTPException(422, "点赞率必须在 0–100% 之间")
    if like_rate_min is not None and like_rate_max is not None and like_rate_min > like_rate_max:
        raise HTTPException(422, "点赞率下限不能超过上限")
    page = max(1, page)
    filters = dict(
        search=search.strip(), channel=channel.strip(),
        score_band=score_band, error_type=error_type, status=status,
        engagement_window_days=engagement_window_days, include_processed=include_processed,
        include_expired=include_expired,
        created_window=created_window,
        funnel_stage=funnel_stage, attention_kind=attention_kind,
        like_rate_min=like_rate_min, like_rate_max=like_rate_max,
    )
    videos, total_count = db.get_paginated_videos(tab, page, size, sort=sort, **filters)
    for video in videos:
        video['publish_score_line'] = settings.auto_publish_channel_min_scores.get(video.get('channel_id'), 75)
        video['cover_provenance'] = db.get_cover_context(video['youtube_id'], video.get('slice_index') or 0)
        video['product_decision'] = db.get_product_task_decision(f"pipeline:{video['youtube_id']}:{video.get('slice_index') or 0}")
    _attach_publish_display_fields(videos)
    _attach_ready_publication_fields(videos)
    if tab == "high_likes":
        for video in videos:
            video["engagement"] = present_engagement(video)
            path = _prepared_video_path(video["youtube_id"], video.get("slice_index") or 0)
            video["prepared_video_url"] = (
                f"/api/videos/{video['youtube_id']}/prepared-video?slice_index={video.get('slice_index') or 0}"
                if path and video.get("preparation_ready") else None
            )
    tab_counts = db.get_filtered_tab_counts(tab, **filters)
    tab_counts[tab] = total_count
    return {
        "videos": videos,
        "total_count": total_count,
        "page": page,
        "size": size,
        "total_pages": (total_count + size - 1) // size,
        "tab_counts": tab_counts,
        "filter_options": {"channels": db.get_video_filter_channels(tab, engagement_window_days)},
        "publish_policy": {"ted_min_score": settings.ted_publish_score_line,
            "speech_min_score": settings.speech_publish_score_line,
            "ted_min_like_rate_pct": settings.ted_min_like_rate_pct,
            "ready_metric_refresh_enabled": settings.enable_ready_metric_refresh},
    }


def _prepared_video_path(youtube_id: str, slice_index: int) -> Optional[Path]:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", youtube_id) or slice_index < 0:
        return None
    path = _backfill_asset_paths(youtube_id, slice_index)["video"]
    return path if path.is_file() and path.resolve().is_relative_to(_OUT_DIR.resolve()) else None


@app.get("/api/videos/{youtube_id}/prepared-video")
def prepared_video(youtube_id: str, slice_index: int = 0):
    """只读取该任务的成片，不接受任意文件路径，不触发加工或发布。"""
    if not db.get_video_by_youtube_id(youtube_id, slice_index=slice_index):
        raise HTTPException(404, "视频不存在")
    path = _prepared_video_path(youtube_id, slice_index)
    if path is None:
        raise HTTPException(404, "成片当前不可用")
    return FileResponse(path, media_type="video/mp4")


@app.get("/api/published-videos")
def get_confirmed_published_videos(start: int = 1, end: int = 10):
    """返回指定名次范围内、至少一个平台已明确确认发布的视频。"""
    if start < 1 or end < start or end > MAX_SQLITE_INTEGER or end - start + 1 > 100:
        raise HTTPException(status_code=422, detail="invalid published-video range")
    videos = db.get_recent_confirmed_published_videos(offset=start - 1, limit=end - start + 1)
    for video in videos:
        video["cover_provenance"] = db.get_cover_context(video["youtube_id"], video.get("slice_index") or 0)
    return {
        "videos": videos,
        "start": start,
        "end": end,
    }


@app.post("/api/videos/{youtube_id}/engagement-reviewed")
def set_engagement_reviewed(youtube_id: str, req: EngagementReviewedRequest, slice_index: int = 0):
    """持久化近期高互动的只读浏览标记，不改变任务或任何平台账本。"""
    if not re.match(r'^[A-Za-z0-9_-]+$', youtube_id):
        raise HTTPException(status_code=400, detail="invalid youtube_id")
    if not db.set_engagement_reviewed(youtube_id, req.reviewed, slice_index):
        raise HTTPException(status_code=404, detail="video not found")
    return {"success": True, "youtube_id": youtube_id, "reviewed": req.reviewed}


@app.get("/api/videos/{youtube_id}/slices")
def get_slices(youtube_id: str):
    """[Gemini_3.5_Flash_High_planning] 获取指定 YouTube ID 的所有切片子任务"""
    slices = db.get_slices_by_parent_yid(youtube_id)
    for video in slices:
        video["cover_provenance"] = db.get_cover_context(video["youtube_id"], video.get("slice_index") or 0)
    _attach_publish_display_fields(slices)
    _attach_ready_publication_fields(slices)
    return {"slices": slices}


# ── Highlight Job（显式候选与人工选定；不接既有管线或发布）────────────────────
class CreateHighlightJobRequest(BaseModel):
    source_youtube_id: str
    max_clips: int = 3
    min_duration_sec: float = 35
    max_duration_sec: float = 90
    requested_by: str = "manual"


def _highlight_job_payload(job: dict) -> dict:
    """对外仅暴露 Highlight 自身状态与只读源标识，避免伪装成原视频任务。"""
    payload = dict(job)
    payload["clips"] = db.get_highlight_clips(str(job["id"]))
    return payload


@app.get("/api/highlights/sources")
def list_highlight_sources(limit: int = 10, offset: int = 0):
    """列出最近源视频及本地字幕可用性；接口本身绝不创建任务。"""
    service = HighlightJobService(db, Path(__file__).parent.parent.parent)
    return {"sources": service.list_sources(limit=limit, offset=offset)}


@app.post("/api/highlights/jobs")
def create_highlight_job(req: CreateHighlightJobRequest):
    """显式创建一个独立 Highlight Job，并只启动本地候选分析。"""
    source_youtube_id = (req.source_youtube_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", source_youtube_id):
        return {"success": False, "error": "source_youtube_id 格式不合法"}
    service = HighlightJobService(db, Path(__file__).parent.parent.parent)
    if not service.has_source_subtitle(source_youtube_id):
        return {
            "success": False,
            "error": "该视频没有可用的带时间轴源字幕，暂不能生成 Highlight 候选",
        }
    try:
        job, created = db.create_highlight_job(
            source_youtube_id,
            max_clips=req.max_clips,
            min_duration_sec=req.min_duration_sec,
            max_duration_sec=req.max_duration_sec,
            requested_by=req.requested_by,
        )
    except (TypeError, ValueError) as exc:
        return {"success": False, "error": str(exc)}
    _start_highlight_analysis(str(job["id"]))
    return {
        "success": True,
        "created": created,
        "message": "已开始生成金句候选；不会下载、渲染或发布任何视频。" if created
                   else "该源视频已有进行中的 Highlight Job；已返回现有任务。",
        "job": _highlight_job_payload(job),
    }


@app.post("/api/highlights/clips/{clip_id}/select")
def select_highlight_clip(clip_id: str):
    """显式选定一个 Highlight 候选并创建独立发布主体；不渲染、不上传、不发布。"""
    if not re.fullmatch(r"[a-f0-9]{32}", clip_id or ""):
        return {"success": False, "error": "Highlight Clip ID 格式不合法"}
    try:
        clip = db.select_highlight_clip_for_publication(clip_id)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    return {
        "success": True,
        "message": "已选定候选并创建独立发布主体；尚未渲染、上传或发布。",
        "clip": clip,
    }


@app.get("/api/highlights/jobs")
def list_highlight_jobs(limit: int = 20):
    """读取 Highlight Job 列表；不触发任何分析、渲染或发布。"""
    return {"jobs": [_highlight_job_payload(job) for job in db.list_highlight_jobs(limit=limit)]}


@app.get("/api/highlights/jobs/{job_id}")
def get_highlight_job(job_id: str):
    """读取一个独立 Highlight Job 及其候选，不修改其状态。"""
    if not re.fullmatch(r"[a-f0-9]{32}", job_id or ""):
        raise HTTPException(status_code=404, detail="Highlight Job 不存在")
    job = db.get_highlight_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Highlight Job 不存在")
    return _highlight_job_payload(job)


# ── English World research（独立选题/制作请求；不接通用队列或发布）────────────
class CreateEnglishWorldResearchRequest(BaseModel):
    requested_by: str = "manual"
    notification_target: Optional[str] = None
    source_url: Optional[str] = None


def _english_world_job_payload(job: dict) -> dict:
    """只暴露英语世界自己的候选和状态，避免被误读为普通视频或平台发布任务。"""
    payload = dict(job)
    payload["candidates"] = db.get_english_world_candidates(str(job["id"]))
    return payload


@app.post("/api/english-world/research")
def create_english_world_research(req: CreateEnglishWorldResearchRequest):
    """创建只读候选研究任务并异步启动；不会下载、制作、入队或发布。"""
    source_url = (req.source_url or "").strip() or None
    if source_url and not _is_youtube_url(source_url):
        return {"success": False, "error": "指定来源必须是 youtube.com 或 youtu.be 视频 URL"}
    try:
        job = db.create_english_world_research_job(
            requested_by=req.requested_by,
            notification_target=req.notification_target,
            source_url=source_url,
        )
    except (TypeError, ValueError) as exc:
        return {"success": False, "error": str(exc)}
    _start_english_world_research(str(job["id"]))
    return {
        "success": True,
        "message": "已开始英语世界候选研究；不会下载、制作或发布。",
        "job": _english_world_job_payload(job),
    }


@app.get("/api/english-world/jobs")
def list_english_world_jobs(limit: int = 20):
    """读取英语世界独立任务账本；不触发网络研究、制作或平台提交。"""
    return {"jobs": [_english_world_job_payload(job) for job in db.list_english_world_jobs(limit=limit)]}


@app.get("/api/english-world/jobs/{job_id}")
def get_english_world_job(job_id: str):
    """读取单个英语世界任务及候选；只读。"""
    if not re.fullmatch(r"[a-f0-9]{32}", job_id or ""):
        raise HTTPException(status_code=404, detail="英语世界任务不存在")
    job = db.get_english_world_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="英语世界任务不存在")
    return _english_world_job_payload(job)


@app.post("/api/english-world/candidates/{candidate_id}/select")
def select_english_world_candidate(candidate_id: str):
    """选定研究候选；只进入二次制作确认，不下载、渲染或发布。"""
    if not re.fullmatch(r"[a-f0-9]{32}", candidate_id or ""):
        return {"success": False, "error": "英语世界候选 ID 格式不合法"}
    try:
        candidate = db.select_english_world_candidate(candidate_id)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    job = db.get_english_world_job(str(candidate["job_id"]))
    return {
        "success": True,
        "message": "候选已选定；需要再次确认后才会登记生产请求。",
        "candidate": candidate,
        "job": _english_world_job_payload(job) if job else None,
    }


@app.post("/api/english-world/jobs/{job_id}/request-production")
def request_english_world_production(job_id: str):
    """登记第二次制作确认并启动单候选协调器；不触发平台发布。"""
    if not re.fullmatch(r"[a-f0-9]{32}", job_id or ""):
        return {"success": False, "error": "英语世界任务 ID 格式不合法"}
    try:
        job = db.request_english_world_production(job_id)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    _start_english_world_production(job_id)
    return {
        "success": True,
        "message": "已登记并启动单候选生产；完成后只进入 Telegram 人工审核，尚未发布。",
        "job": _english_world_job_payload(job),
    }


@app.post("/api/english-world/review-items/{review_id}/approve-submission")
def approve_english_world_submission(review_id: str):
    """接收 Telegram 对一条审核成片的唯一投稿授权，并启动独立投稿 worker。"""
    if not re.fullmatch(r"[a-f0-9]{32}", review_id or ""):
        return {"success": False, "error": "英语世界审核编号格式不合法"}
    if settings.wechat_publishing_paused:
        return {"success": False, "error": "视频号投稿当前已暂停；未记录批准，也未启动上传。"}
    item = db.get_english_world_review_item(review_id)
    if not item:
        return {"success": False, "error": "英语世界审核项不存在"}
    state = str(item.get("state") or "")
    try:
        if state == "READY_FOR_REVIEW":
            hashes = calculate_package_hashes(item)
            db.bind_english_world_review_package_hashes(review_id, hashes=hashes)
            item = db.approve_english_world_submission(review_id)
            _start_english_world_submission(review_id)
        elif state == "SUBMISSION_APPROVED":
            # API 进程可能刚好在首次批准后重启；再次点击只允许唤起同一审核项，领取仍原子防重。
            _start_english_world_submission(review_id)
            item = db.get_english_world_review_item(review_id) or item
        elif state in {"SUBMITTING", "UNDER_REVIEW", "UNCERTAIN", "LOGIN_REQUIRED", "FAILED", "HELD"}:
            return {
                "success": True,
                "message": f"该审核项当前为 {state}；未创建新的投稿尝试。",
                "item": item,
            }
        else:
            return {"success": False, "error": f"审核项状态异常：{state}"}
    except (ValueError, OSError) as exc:
        return {"success": False, "error": str(exc)}
    return {
        "success": True,
        "message": "已记录本条审核项的投稿批准，正在发起视频号提交；后续以平台回执为准。",
        "item": item,
    }


@app.get("/api/english-world/review-items")
def list_english_world_review_items(limit: int = 20):
    """只读返回英语世界学习卡的审核/投稿状态，不启动任何操作。"""
    return {"items": db.list_english_world_review_items(limit=limit)}


@app.post("/api/english-world/recover-login-required")
def recover_english_world_login_required_submission():
    """在已确认登录恢复后，领取唯一合格的登录前失败英语世界自动任务。"""
    if not _wechat_login_marker_active(Path(__file__).parent.parent.parent / "output" / "wechat_login_at.txt"):
        return {"success": False, "error": "视频号登录尚未确认恢复；未创建投稿尝试"}
    item = _resume_eligible_english_world_after_wechat_login()
    if item is None:
        return {"success": True, "message": "没有可安全自动续投的英语世界登录失败项。"}
    return {
        "success": True,
        "message": "已领取一条登录前失败项并启动一次自动续投；后续以平台回执为准。",
        "item": item,
    }


@app.post("/api/english-world/review-items/{review_id}/confirm-not-published-retry")
def reopen_uncertain_english_world_submission(review_id: str):
    """仅在 Telegram 二次确认后重开同一英语世界审核项，绝不走通用视频重试。"""
    if not re.fullmatch(r"[a-f0-9]{32}", review_id or ""):
        return {"success": False, "error": "英语世界审核编号格式不合法"}
    try:
        item = db.get_english_world_review_item(review_id)
        if not item:
            return {"success": False, "error": "英语世界审核项不存在"}
        hashes = calculate_package_hashes(item)
        db.bind_english_world_review_package_hashes(review_id, hashes=hashes)
        item = db.reopen_uncertain_english_world_submission(review_id)
        _start_english_world_submission(review_id)
    except (ValueError, OSError) as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "message": "已重开同一审核项的一次人工确认重传。", "item": item}


@app.post("/api/english-world/review-items/{review_id}/hold")
def hold_english_world_review_item(review_id: str):
    """显式搁置某条待审核学习卡；不触发制作或投稿。"""
    if not re.fullmatch(r"[a-f0-9]{32}", review_id or ""):
        return {"success": False, "error": "英语世界审核编号格式不合法"}
    try:
        item = db.hold_english_world_review_item(review_id)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "message": "已搁置本条审核项，未提交视频号。", "item": item}


# ── 频道管理 API ──────────────────────────────────────────────────────────
@app.get("/api/channels")
def get_channels():
    """返回频道白名单（含 APPROVED 与 PAUSED 状态）"""
    managed = db.get_managed_channels()
    approved = [c for c in managed if c.get("status") == "APPROVED"]
    paused = [c for c in managed if c.get("status") == "PAUSED"]
    pending = db.get_pending_channels()
    return {
        "channels": managed,
        "approved": approved,
        "paused": paused,
        "pending": pending,
        "total_approved": len(approved),
        "total_paused": len(paused),
        "total_managed": len(managed),
    }


@app.post("/api/channels/add")
def add_channel(req: AddChannelRequest):
    """
    通过 yt-dlp 严格验证 YouTube 频道 URL，验证通过后写入白名单。

    验证链：
      1. URL 格式必须是 YouTube 域名
      2. yt-dlp --flat-playlist 获取频道元数据（不触发视频格式检查）
      3. Channel ID 必须符合 YouTube 规范（UC 开头，24字符）
      4. 重复检测：已存在的 APPROVED 频道直接提示，不重复写入
    """
    url = req.url.strip()
    if not url:
        return {"success": False, "error": "URL 不能为空"}

    # ── 1. 前置 URL 格式校验（拒绝非 YouTube 输入）──────────────────────
    # [Claude_Sonnet_4.6_Thinking_planning] SEC-1: 使用 _is_youtube_url() 严格 netloc 匹配
    if not _is_youtube_url(url):
        return {
            "success": False,
            "error": "请输入有效的 YouTube 频道 URL（必须来自 youtube.com 或 youtu.be）"
        }

    # ── 2. 调用 yt-dlp 获取频道元数据 ─────────────────────────────────
    # 关键：使用 --flat-playlist 只获取列表元数据，不触发视频格式解析，
    # 避免 "Requested format is not available" 导致的误报失败。
    # 注意：yt-dlp 在 --flat-playlist 模式下条目对象的 channel_id 为 None（格式化为 NA），
    # 真实的频道 ID 与名称位于播放列表层级（playlist_channel_id / playlist_channel），
    # 因此需通过多候选字段与 playlist: 前缀提取，确保频道首页、分栏与普通条目均能稳定解析。
    try:
        result = run_admitted(
            [
                _YT_DLP,
                "--flat-playlist",          # 不解析视频格式，只取列表元数据
                "--playlist-items", "1",    # 只取第一条，快速返回
                "--print", "playlist:%(channel_id,id)s|%(channel,title)s",
                "--print", "%(playlist_channel_id,channel_id,uploader_id)s|%(playlist_channel,channel,uploader,playlist_title)s",
                "--no-warnings",
                *settings.get_yt_cookie_args(),
                url,
            ],
            capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "yt-dlp 请求超时（30s），请检查网络"}
    except FileNotFoundError:
        return {"success": False, "error": f"找不到 yt-dlp 可执行文件：{_YT_DLP}"}

    # ── 3. 解析输出（stdout 有内容 = 频道存在，与 returncode 无关）───────
    raw_lines = [
        line.strip() for line in result.stdout.strip().splitlines()
        if line.strip() and "|" in line
    ]
    if not raw_lines:
        # 真正的频道不存在：stdout 为空
        first_err = result.stderr.strip().split("\n")[0] if result.stderr.strip() else ""
        # 过滤掉格式错误（这类错误不代表频道不存在）
        if "format" in first_err.lower():
            first_err = "频道不存在或无法通过当前 Cookie 访问"
        return {"success": False, "error": first_err or "无法解析频道信息，请检查 URL"}

    # 优先选取符合 YouTube 频道规范（UC 开头，24 字符）的行
    selected_line = next(
        (l for l in raw_lines if l.split("|", 1)[0].strip().startswith("UC") and len(l.split("|", 1)[0].strip()) == 24),
        raw_lines[0]
    )
    channel_id, channel_name = selected_line.split("|", 1)
    channel_id   = channel_id.strip()
    channel_name = channel_name.strip()

    # ── 4. Channel ID 格式校验 ─────────────────────────────────────────
    # YouTube 频道 ID 固定以 "UC" 开头，长度 24 个字符
    if not channel_id.startswith("UC") or len(channel_id) != 24:
        return {
            "success": False,
            "error": f"解析到的频道 ID 格式异常（{channel_id}），请确认这是一个频道页面而非单个视频链接"
        }

    # ── 5. 重复检测 ───────────────────────────────────────────────────
    # [Claude_Sonnet_4.6_Thinking_planning] SEC-2 修复：覆盖所有已存在状态，防止 MANUAL_ONLY → APPROVED 隐式提升。
    # 旧逻辑只检测 APPROVED，MANUAL_ONLY 频道被放行后 INSERT OR REPLACE 会静默覆盖为 APPROVED，
    # 导致用户手动下载某视频后其频道被意外加入爬虫白名单，直接破坏频道隔离设计。
    existing = db.get_channel_by_id(channel_id)
    if existing:
        status = existing.get("status")
        if status == "APPROVED":
            return {
                "success": False,
                "error": f"该频道已在白名单中：{existing['channel_name']}（{channel_id}）",
                "already_exists": True,
            }
        elif status == "MANUAL_ONLY":
            if not req.promote:
                # 该频道曾通过手动视频下载注册，需用户明确确认才能提升为自动爬取白名单
                return {
                    "success": False,
                    "error": (
                        f"频道《{existing['channel_name']}》（{channel_id}）已通过手动视频下载注册（MANUAL_ONLY），"
                        "不会被自动爬取。是否确认将其状态提升为 APPROVED（加入自动监控白名单）？"
                    ),
                    "requires_promotion": True,
                    "channel_id": channel_id,
                    "channel_name": existing['channel_name'],
                }
            # 用户确认了 promote，允许通过
        # 其他状态（PENDING/REJECTED 等）：允许覆盖写入 APPROVED

    # ── 6. 全部通过，写入 ──────────────────────────────────────────────
    db.add_channel(channel_id, channel_name, status="APPROVED", reason="Added via Web UI")
    return {"success": True, "channel_id": channel_id, "channel_name": channel_name}



@app.delete("/api/channels/{channel_id}")
def remove_channel(channel_id: str):
    """从白名单中删除一个频道"""
    ok = db.delete_channel(channel_id)
    return {"success": ok}


@app.post("/api/channels/{channel_id}/pause")
def pause_channel(channel_id: str):
    """暂停白名单频道的自动轮询抓取（状态置为 PAUSED）"""
    ok = db.set_channel_paused(channel_id, paused=True)
    if not ok:
        return {"success": False, "error": "频道不存在或不允许暂停"}
    return {"success": True, "channel_id": channel_id, "status": "PAUSED"}


@app.post("/api/channels/{channel_id}/resume")
def resume_channel(channel_id: str):
    """恢复白名单频道的自动轮询抓取（状态置为 APPROVED）"""
    ok = db.set_channel_paused(channel_id, paused=False)
    if not ok:
        return {"success": False, "error": "频道不存在或不允许恢复"}
    return {"success": True, "channel_id": channel_id, "status": "APPROVED"}


@app.get("/api/console/attention")
def get_console_attention():
    """只读关注事项；摘要与落地页复用 DAL 分类。"""
    return db.get_attention_summary()


@app.get("/api/funnel")
def get_global_funnel(window: str = "today_bj"):
    """获取全站视频生产流转全局漏斗指标（支持 24h, today_bj, 7d, 30d, all）"""
    valid_windows = {"24h", "today_bj", "7d", "30d", "all"}
    win = window if window in valid_windows else "today_bj"
    metrics = db.get_global_funnel_metrics(window=win)
    return {
        "success": True,
        "window": win,
        "metrics": metrics,
    }


@app.get("/api/publication-funnel")
def get_publication_funnel(day_bj: date):
    """按北京日期返回自动入库、平台 ID 已绑定受理与人工参与量。"""
    return {
        "success": True,
        "metrics": db.get_daily_publication_funnel(
            str(day_bj), channel_min_scores=settings.auto_publish_channel_min_scores,
        ),
    }


@app.get("/api/channels/{channel_id}/funnel")
def get_channel_funnel(channel_id: str, window: str = "today_bj"):
    """获取频道的生产转化漏斗（支持 24h, today_bj, 7d, 30d, all）"""
    valid_windows = {"24h", "today_bj", "7d", "30d", "all"}
    win = window if window in valid_windows else "today_bj"
    metrics = db.get_channel_funnel_metrics(channel_id, window=win)
    channel = db.get_channel_by_id(channel_id)
    channel_name = channel.get("channel_name", "") if channel else ""
    return {
        "success": True,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "window": win,
        "metrics": metrics,
    }


# ── 手动添加视频 API ──────────────────────────────────────────────────────
class AddVideoRequest(BaseModel):
    url: str
    trim_start: Optional[str] = None
    trim_end: Optional[str] = None
    disable_slicing: Optional[bool] = True  # [Gemini_3.5_Flash_planning] 默认不分片 (整片模式)
    tts_provider: Optional[str] = None      # [Claude_Sonnet_4.6_Thinking_planning] TTS 配音引擎，nullable
    content_type: str = CONTENT_TYPE_GENERAL
    product_intent: str = 'NONE'
    product_alias: Optional[str] = None


@app.post("/api/videos/add")
def add_video_manual(req: AddVideoRequest, bg_tasks: BackgroundTasks):
    """
    手动将一条 YouTube 视频链接加入处理队列（状态：PENDING）。

    验证链：
      1. URL 必须是 YouTube 域名
      2. 校验裁剪时间参数格式
      3. yt-dlp 获取 video_id / title / channel_id / channel_name / duration / views / likes / upload_date
      4. 重复检测：已存在则返回当前状态，不重复写入
      5. 通过 DAL 写入 processed_videos，评分 100（手工加急），触发异步翻译
    """
    url = req.url.strip()
    if not url:
        return {"success": False, "error": "URL 不能为空"}

    # ── 1. 裁剪时间参数校验与格式清洗 ──────────────────────────────────
    trim_start = req.trim_start.strip() if req.trim_start else None
    trim_end = req.trim_end.strip() if req.trim_end else None
    try:
        content_type = normalize_content_type(req.content_type)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    # 正则防注入校验 (只允许数字、冒号、点)
    time_pattern = re.compile(r"^[0-9:.]*$")
    if trim_start and not time_pattern.match(trim_start):
        return {"success": False, "error": "开始时间格式不合法，仅支持数字、冒号和点"}
    if trim_end and not time_pattern.match(trim_end):
        return {"success": False, "error": "结束时间格式不合法，仅支持数字、冒号和点"}

    # ── 2. 前置 URL 格式校验 ─────────────────────────────────────────
    # [Claude_Sonnet_4.6_Thinking_planning] SEC-1: 使用 _is_youtube_url() 严格 netloc 匹配
    if not _is_youtube_url(url):
        return {"success": False, "error": "请输入有效的 YouTube 视频 URL（必须来自 youtube.com 或 youtu.be）"}

    # 手动商品意图在任何抓取前核验，不相信客户端商品标题/账号标记。
    product = None
    if req.product_intent not in {'NONE', 'PRODUCT'}:
        return {"success": False, "error": "手动任务必须明确不绑定或指定商品"}
    if req.product_intent == 'NONE' and req.product_alias:
        return {"success": False, "error": "不绑定商品不能同时指定商品"}
    if req.product_intent == 'PRODUCT':
        try:
            from video_processing.utils.wechat_product_task import validate_manual_product
            product = validate_manual_product(settings.wechat_product_policy_path, req.product_alias)
        except (ValueError, OSError) as exc:
            return {"success": False, "error": str(exc)}

    # ── 3. yt-dlp 获取视频元数据 ─────────────────────────────────────
    try:
        result = run_admitted(
            [
                _YT_DLP,
                "--print", "%(id)s|||%(title)s|||%(channel_id)s|||%(channel)s|||%(duration)s|||%(view_count)s|||%(like_count)s|||%(upload_date)s",
                "--no-playlist",
                "--no-warnings",
                *settings.get_yt_cookie_args(),
                url,
            ],
            capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "yt-dlp 请求超时（30s），请检查网络"}
    except FileNotFoundError:
        return {"success": False, "error": f"找不到 yt-dlp：{_YT_DLP}"}

    raw = result.stdout.strip().split("\n")[0] if result.stdout.strip() else ""
    if not raw or raw.count("|||") < 3:
        err = result.stderr.strip().split("\n")[0] if result.stderr.strip() else "无法解析视频信息"
        return {"success": False, "error": f"视频不存在或无法访问：{err}"}

    parts = raw.split("|||", 7)
    video_id    = parts[0].strip()
    title       = parts[1].strip()
    channel_id  = parts[2].strip()
    channel_name = parts[3].strip()
    # 容错处理：字段可能是 "NA" 或空
    def _int_or_none(v): 
        try: return int(v)
        except: return None
    duration_sec  = _int_or_none(parts[4]) if len(parts) > 4 else None
    view_count    = _int_or_none(parts[5]) if len(parts) > 5 else None
    like_count    = _int_or_none(parts[6]) if len(parts) > 6 else None
    upload_date   = parts[7].strip() if len(parts) > 7 and parts[7].strip() not in ("NA", "") else None

    if not video_id or len(video_id) != 11:
        return {"success": False, "error": f"解析到的视频 ID 格式异常（{video_id}），请检查链接"}

    # ── 4. 重复检测 ───────────────────────────────────────────────────
    existing = db.get_video_by_youtube_id(video_id)
    if existing:
        return {
            "success": False,
            "error": f"视频已在队列中（当前状态：{existing['status']}）：{existing['title']}",
            "already_exists": True,
            "current_status": existing["status"],
            "video_id": video_id,        # [Claude_Sonnet_4.6_Thinking_planning] 供 Bot 侧 respec 直接使用
            "title": existing["title"],  # [Claude_Sonnet_4.6_Thinking_planning] 供 Bot 侧特显提示展示
        }

    # ── 5. 写入队列（手工添加） ───────────────────────────────────────
    # [Claude_Sonnet_4.6_Thinking_planning] v7.0 Phase 4: 手动添加视频时，频道写入 MANUAL_ONLY
    # 而非 APPROVED，避免单视频下载导致频道被自动爬虫拉取
    if not db.get_channel_by_id(channel_id):
        db.add_channel(channel_id, channel_name,
                       status="MANUAL_ONLY", reason="Auto-registered via manual video add — NOT whitelisted")

    # 手工添加给100分加急
    disable_slicing_val = 1 if req.disable_slicing else 0
    inserted = db.add_video(
        video_id, title, channel_id, score=100, source="MANUAL",
        duration_sec=duration_sec, view_count=view_count,
        like_count=like_count, upload_date=upload_date,
        trim_start=trim_start, trim_end=trim_end,
        disable_slicing=disable_slicing_val,
        tts_provider=req.tts_provider or None,  # [Claude_Sonnet_4.6_Thinking_planning] 传递 TTS 配音引擎设置
        content_type=content_type,
        product_intent=req.product_intent, product_id=product['product_id'] if product else None,
        product_title=product['title'] if product else None,
    )
    if not inserted:
        existing = db.get_video_by_youtube_id(video_id)
        return {"success": False, "already_exists": bool(existing), "error": "任务未新增；已有任务不会覆盖商品意图"}
    bg_tasks.add_task(_translate_title_task, video_id, title)
    
    return {
        "success": True,
        "video_id": video_id,
        "title": title,
        "channel_name": channel_name,
        "trim_start": trim_start,
        "trim_end": trim_end,
        "disable_slicing": req.disable_slicing,
        "tts_provider": req.tts_provider,  # [Claude_Sonnet_4.6_Thinking_planning]
        "content_type": content_type,
        "product_intent": req.product_intent, "product_id": product['product_id'] if product else None,
        "product_title": product['title'] if product else None,
    }



# ── 优先级调整 API ────────────────────────────────────────────────────────
class PriorityRequest(BaseModel):
    action: str          # "increase" | "decrease" | "set"
    value: Optional[int] = None   # 仅 action="set" 时使用


class CreateManualPublishLeaseRequest(BaseModel):
    youtube_id: str
    slice_index: int = 0
    issued_by: str
    ttl_minutes: int = 120


class RevokeManualPublishLeaseRequest(BaseModel):
    revoked_by: str


def _trigger_video_async(video: dict, *, trigger_source: str = "dashboard_manual_item") -> None:
    """
    在独立子进程中处理单个视频，避免相对导入和 CWD 问题。
    输出写入 output/pipeline.log 与 vp job logs 共享。
    """
    yid = str(video.get("youtube_id") or "")
    slice_index = int(video.get("slice_index") or 0)

    def _run():
        prj_root = Path(__file__).parent.parent.parent
        python   = str(prj_root / ".venv" / "bin" / "python")
        src_dir  = str(prj_root / "src")
        log_path = prj_root / "output" / "pipeline.log"
        log_path.parent.mkdir(exist_ok=True)

        # 内联脚本：改用 JSON 通过 stdin 传递数据，避免 repr() 带来的代码注入风险
        import json
        video_json = json.dumps(dict(video))
        cmd = [python, "-u", str(prj_root / "scripts/run_video_task.py"),
               "--trigger-source", trigger_source, f"--object-key={yid}:{slice_index}"]
        try:
            with open(log_path, "a") as f:
                import subprocess as sp
                # [Gemini_3.5_Flash_planning] 使用 -u 启用无缓冲输出
                # [Antigravity] v3.19.0: 使用 Popen 启动独立进程组并立即记录 PID，保护预提交加工免受看门狗误判
                with child_continuation(cmd, dict(stdin=sp.PIPE, stdout=f, stderr=f, text=True,
                        cwd=str(prj_root), start_new_session=True)) as kwargs:
                    proc = sp.Popen(cmd, **kwargs)
                    if yid:
                        db.update_process_pid(yid, proc.pid, slice_index=slice_index)
                    proc.communicate(input=video_json)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"_trigger_video_async failed: {e}")
        finally:
            if yid:
                db.update_process_pid(yid, None, slice_index=slice_index)

    spawn_admitted(_run, role="video", object_key=f"{yid}:{slice_index}",
                   name=f"pipeline-{yid[:8]}", waiting=True)


@app.get(
    "/api/publication-leases/candidates",
    dependencies=[Depends(_require_pipeline_internal_token)],
)
def list_manual_publish_lease_candidates(limit: int = 8):
    """只读返回手机端可选择的单任务候选和当前未消费 lease。"""
    candidates = db.list_manual_publish_lease_candidates(limit=limit)
    market_guard_active = settings.is_us_market_guard_window()
    if market_guard_active:
        candidates = [item for item in candidates if item.get("preparation_ready")]
    return {
        "candidates": candidates,
        "active_leases": db.list_active_manual_publish_leases(limit=limit),
        "ttl_minutes": 120,
        "market_guard_active": market_guard_active,
    }


@app.post(
    "/api/publication-leases",
    dependencies=[Depends(_require_pipeline_internal_token)],
)
def create_manual_publish_lease(req: CreateManualPublishLeaseRequest):
    """签发两小时单任务微信 lease，并原子领取后启动既有安全管线。"""
    youtube_id = (req.youtube_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", youtube_id):
        return {"success": False, "error": "youtube_id 格式不合法"}
    if req.slice_index < 0:
        return {"success": False, "error": "slice_index 不能为负数"}
    if not re.fullmatch(r"telegram:[1-9][0-9]{0,19}", req.issued_by or ""):
        return {"success": False, "error": "issued_by 必须绑定 Telegram 管理员 ID"}
    video = db.get_video_by_youtube_id(youtube_id, slice_index=req.slice_index)
    if not video:
        return {"success": False, "error": "任务不存在"}
    if settings.is_us_market_guard_window() and not video.get("preparation_ready"):
        return {
            "success": False,
            "error": "美股盘中仅允许已完成预加工的成片签发发布 lease",
        }
    try:
        lease = db.issue_manual_publish_lease(
            youtube_id,
            slice_index=req.slice_index,
            issued_by=req.issued_by,
            issued_via="telegram",
            ttl_minutes=req.ttl_minutes,
            claim_video=True,
        )
    except (TypeError, ValueError) as exc:
        return {"success": False, "error": str(exc)}

    fresh = db.get_video_by_youtube_id(youtube_id, slice_index=req.slice_index)
    if not fresh:
        return {"success": False, "error": "任务领取后读取失败；lease 未消费", "lease": lease}
    _trigger_video_async(fresh)
    return {
        "success": True,
        "message": "两小时单任务 lease 已签发，任务已领取，本地 worker 调度请求已提交",
        "dispatch_state": "LOCAL_WORKER_REQUESTED",
        "lease": lease,
        "video": fresh,
    }


@app.post(
    "/api/publication-leases/{lease_id}/revoke",
    dependencies=[Depends(_require_pipeline_internal_token)],
)
def revoke_manual_publish_lease(
    lease_id: str, req: RevokeManualPublishLeaseRequest,
):
    """撤销尚未消费且未过期的单任务 lease；不伪装成任务停止确认。"""
    if not re.fullmatch(r"[a-f0-9]{32}", lease_id):
        return {"success": False, "error": "lease_id 格式不合法"}
    if not re.fullmatch(r"telegram:[1-9][0-9]{0,19}", req.revoked_by or ""):
        return {"success": False, "error": "revoked_by 必须绑定 Telegram 管理员 ID"}
    try:
        lease = db.revoke_manual_publish_lease(lease_id, revoked_by=req.revoked_by)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    if not lease:
        return {
            "success": False,
            "error": "lease 不存在、已过期、已撤销或已被上传器消费",
        }
    return {
        "success": True,
        "message": "lease 已撤销；这不等同于已停止正在进行的预提交加工",
        "lease": lease,
    }

@app.patch("/api/videos/{youtube_id}/priority")
def update_video_priority(youtube_id: str, req: PriorityRequest):
    """
    调整视频优先级（即 score 字段）。
    若调整后 score >= 75 且视频仍是 PENDING，立即在后台启动处理管线。
    """
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}

    wechat_publication = db.get_wechat_publication(youtube_id)
    if wechat_publication and wechat_publication.get("state") in {"PUBLISHED", "UNDER_REVIEW", "UNCERTAIN", "REJECTED"}:
        return {
            "success": False,
            "error": f"视频号账本当前为 {wechat_publication['state']}；请先运行作品管理页回查，禁止绕过账本直接重传。",
        }

    # [Gemini_2.5_Pro_planning] v3.3.0: DISCOVERY 源视频禁止通过评分按钮触发管线
    # 用户可以在 high_likes tab 浏览，但不能通过调分间接发起下载/发布
    is_discovery = video.get("source") == "DISCOVERY"

    current = video.get("score", 0)
    if req.action == "increase":
        new_score = min(100, current + 10)
    elif req.action == "decrease":
        new_score = max(0, current - 10)
    elif req.action == "set" and req.value is not None:
        new_score = max(0, min(100, req.value))
    else:
        return {"success": False, "error": f"未知操作：{req.action}"}

    # [Claude_Sonnet_4.6_Thinking_planning] v7.0 Phase 3+4:
    # 人工调分使用 force=True 打上手动锁，防止自动算分覆盖
    db.update_video_score(youtube_id, new_score, force=True)

    # 若打分为 0，将视频加入黑名单（Flag 保护）
    # [Gemini_2.5_Pro_planning] DISCOVERY 视频打 0 分只删除记录，不加黑名单（发现列表和业务黑名单隔离）
    if new_score == 0 and settings.enable_blacklist_tombstone and not is_discovery:
        db.add_to_blacklist(youtube_id, reason="manually_scored_zero")  # LINT-3: 去除多余 f-string
        db.delete_video_record(youtube_id)
        return {"success": True, "youtube_id": youtube_id, "score": 0,
                "triggered": False, "blacklisted": True,
                "message": "已打 0 分并移入黑名单，该视频不会被自动爬虫再次拉取"}
    elif new_score == 0 and is_discovery:
        db.delete_video_record(youtube_id)
        return {"success": True, "youtube_id": youtube_id, "score": 0,
                "triggered": False, "blacklisted": False,
                "message": "已从高赞发现列表中删除该条目"}

    # 自动触发：score 越过调度线，且抢占成功（原状态为 PENDING）
    # [Gemini_2.5_Pro_planning] DISCOVERY 视频不允许通过调分触发管线，防火墙保护
    triggered = False
    publish_line = settings.auto_publish_channel_min_scores.get(video.get("channel_id"), 75)
    if not is_discovery and new_score >= publish_line and db.claim_video_for_processing(youtube_id):
        fresh = db.get_video_by_youtube_id(youtube_id)
        if fresh:
            _trigger_video_async(fresh)
            triggered = True

    return {"success": True, "youtube_id": youtube_id, "score": new_score, "triggered": triggered}


def _check_engagement_action(youtube_id: str, action: str, version: Optional[str], slice_index: int = 0) -> None:
    """高互动入口按服务端最新事实重新核实，不信任页面按钮或旧快照。"""
    if version is None:
        return  # 保持其他控制台入口的既有契约及各自保护。
    video = db.get_engagement_video(youtube_id, slice_index)
    if video is None:
        raise HTTPException(404, "视频不存在")
    current = present_engagement(video)
    if current["version"] != version or current["action"] != action:
        raise HTTPException(409, "任务状态或操作资格已变化，请刷新列表后重新检查")


def _wechat_cooldown_guard():
    from video_processing.core.wechat_request_guard import WeChatRequestGuard
    return WeChatRequestGuard(_OUT_DIR / "wechat_state.json")


def _manual_cooldown_check(video: dict, action: str, version: str):
    """确认前不认领、不改任务；只签发绑定当前作品的单次许可。"""
    from video_processing.core.wechat_request_guard import WeChatRequestDeferred
    if action not in ("", "wait", "force"):
        return {"success": False, "error": "未知冷却操作"}, None
    guard = _wechat_cooldown_guard()
    try:
        prefix = video["youtube_id"] + (f"_s{video['slice_index']}" if video.get("slice_index") else "")
        info = guard.admission_view(prefix)
        hard = {"SUBMISSION_PROTECTED", "RESERVED_PRIORITY", "RECOVERY_RESERVED", "READBACK_DISABLED", "KEEPALIVE_DISABLED"}
        if any(b["code"] in hard for b in info["blockers"]):
            return {"success": False, "code": "WECHAT_ACCOUNT_BLOCKED", "error": info["reason"],
                    "recovery_url": "/wechat-cooldown-settings"}, None
        if action == "wait":
            return {"success": True, "waiting": True, "cooldown": info,
                    "message": "保留任务，等待冷却结束后自动重试"}, None
        if action == "force":
            prefix = video["youtube_id"]
            if video.get("slice_index"):
                prefix += f"_s{video['slice_index']}"
            if version != info["version"]:
                return {"success": False, "code": "WECHAT_COOLDOWN", "cooldown": info,
                        "prepared": bool(video.get("preparation_ready")),
                        "error": "冷却状态已变化，请重新确认"}, None
            return None, guard.issue_override(prefix, version, full_state=True)
        if info["active"]:
            return {"success": False, "code": "WECHAT_COOLDOWN", "cooldown": info,
                    "prepared": bool(video.get("preparation_ready")),
                    "error": "账号准入受阻，请查看全部原因，选择等待或确认单次尝试"}, None
        return None, None
    except WeChatRequestDeferred as exc:
        return {"success": False, "error": str(exc)}, None


@app.post("/api/videos/{youtube_id}/process")
def process_video_now(youtube_id: str, engagement_version: Optional[str] = None,
                      cooldown_action: str = "", cooldown_version: str = ""):
    """立即处理指定视频，忽略分数阈值。"""
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}
    _check_engagement_action(youtube_id, "process", engagement_version)
    guard_reason = _wechat_submission_guard_reason(video)
    if guard_reason:
        return {"success": False, "error": guard_reason}
    # [Gemini_2.5_Pro_planning] v3.3.0: DISCOVERY 源视频仅供浏览，禁止通过 API 直接触发自动处理管线
    if video.get("source") == "DISCOVERY":
        return {"success": False, "error": "DISCOVERY 来源视频不允许自动处理，请手动添加后再执行"}
    if video.get("status") != "PENDING":
        return {"success": False, "error": "任务状态已变化，请刷新列表"}
    reply, override = _manual_cooldown_check(video, cooldown_action, cooldown_version)
    if reply is not None:
        return reply
    if not db.claim_video_for_processing(youtube_id):
        if override:
            _wechat_cooldown_guard().revoke_override(override)
        return {"success": False, "error": f"视频当前状态不是 PENDING，或者已被其他进程抢占处理"}

    fresh = db.get_video_by_youtube_id(youtube_id)
    if fresh:
        if override:
            fresh["_wechat_cooldown_override"] = override
        _trigger_video_async(fresh)

    return {"success": True, "message": ("已确认跳过本地冷却，仅尝试一次：" if override else "已在后台启动处理：") + video['title']}


@app.post("/api/videos/{youtube_id}/promote")
def promote_video(youtube_id: str, engagement_version: Optional[str] = None):
    """将高赞发现(DISCOVERY)或待筛选(waitlist)低分视频一键「提权/加入队列」并立即处理。

    - DISCOVERY 来源：原子转换 source 为 MANUAL、score=100 并加评分锁，脱离发现防火墙；
    - 待筛选/普通来源：原子转换 source 为 MANUAL、score=100 并加评分锁，重置为 PENDING 入队。
    提权成功后立即抢占触发完整处理管线（若抢占成功则后台异步处理，否则等待调度器消费）。
    受平台发布账本守护，已在微信发布的视频拒绝提权。
    """
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}
    _check_engagement_action(youtube_id, "promote", engagement_version)

    guard_reason = _wechat_submission_guard_reason(video)
    if guard_reason:
        return {"success": False, "error": f"无法提权：{guard_reason}"}

    if video.get("source") == "DISCOVERY":
        # 原子转换：DISCOVERY → MANUAL，score=100，并打手动评分锁
        if not db.promote_to_manual(youtube_id, score=100):
            return {"success": False, "error": "转换失败：该视频可能已被处理、已在发布账本中或来源已变更"}
    else:
        # 待筛选/普通素材提权入队
        if not db.promote_waitlist_to_queue(youtube_id, score=100):
            return {"success": False, "error": "提权失败：该视频当前状态不符合提权条件或已被处理"}

    # 立即触发管线：抢占 PENDING → DOWNLOADING 后异步执行
    triggered = False
    if db.claim_video_for_processing(youtube_id):
        fresh = db.get_video_by_youtube_id(youtube_id)
        if fresh:
            _trigger_video_async(fresh)
            triggered = True

    return {
        "success": True,
        "youtube_id": youtube_id,
        "triggered": triggered,
        "message": "已提权入队并立即开始处理" if triggered
                   else "已提权入队（score=100），等待调度器触发",
    }


@app.post("/api/videos/{youtube_id}/ignore")
def ignore_video(youtube_id: str, slice_index: Optional[int] = None):
    """将指定视频标记为已忽略(IGNORED)，从待处理/待筛选队列中移除。"""
    video = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index or 0)
    if not video:
        return {"success": False, "error": "视频不存在"}

    guard_reason = _wechat_submission_guard_reason(video)
    if guard_reason:
        return {"success": False, "error": f"已在平台发布或归档，禁止忽略：{guard_reason}"}

    if video.get("status") in {"PROCESSING", "PUBLISH_PRECHECK", "DOWNLOADING", "TRANSCRIBING", "COPYWRITING", "PUBLISHING"}:
        return {"success": False, "error": f"视频处于 {video.get('status')} 处理中，无法直接忽略"}

    success = db.ignore_video(youtube_id, slice_index=slice_index, reason="控制台人工放弃/忽略")
    if not success:
        return {"success": False, "error": "忽略操作未生效"}

    return {"success": True, "message": "视频已标记为已忽略"}


@app.post("/api/platforms/wechat/reconcile")
def reconcile_wechat_publications():
    """拒绝历史标题回查，避免把不同视频号作品错误关联。"""
    return {
        "success": False,
        "message": "自动回查已停用：必须先绑定视频号平台原生 post_id，禁止按标题或时间匹配。",
    }


# ── 审查复核：关键词标签云 + 一键放行 ───────────────────────────────────────
# [Claude_Opus_4.8] 供「🔓 复核放行」按钮：把命中词与字幕关键词摊给人看，知情后绕过审查。
_EN_STOPWORDS = {
    "the","a","an","and","or","but","of","to","in","on","for","with","at","by","from",
    "is","are","was","were","be","been","being","this","that","these","those","it","its",
    "as","if","so","than","then","there","here","not","no","you","your","yours","we","our",
    "they","he","she","his","her","him","i","me","my","us","them","what","which","who","how",
    "when","where","why","will","would","can","could","should","may","might","must","do","does",
    "did","done","have","has","had","about","into","over","under","after","before","up","down",
    "out","off","just","like","get","got","now","all","one","two","more","most","some","any",
    "very","also","only","even","because","while","such","each","other","many","much","they're",
}


def _read_subtitle_text(youtube_id: str, slice_index: int = 0, max_chars: int = 40000) -> str:
    """读取该视频（或指定切片）所有 .ass 双语字幕的纯文本（去 ASS 标签）并拼接。失败时返回空串。

    [Claude_Opus_4.8] 实现已下沉至 utils.file_utils.read_subtitle_text（单一真相源，
    与管线字幕审查共用）；此处保留薄封装以兼容 Web 复核 UI 既有调用点。
    """
    from video_processing.utils.file_utils import read_subtitle_text
    return read_subtitle_text(_OUT_DIR, youtube_id, slice_index=slice_index, max_chars=max_chars)


def _read_censorship_review_subtitle(
    youtube_id: str, slice_index: int = 0, max_chars: int = 40000,
) -> tuple[str, str]:
    """读取人工复核所对应的字幕证据，优先源字幕预检实际使用的 VTT。

    源字幕预检发生在渲染 ASS 之前；若复核页只读取 ASS，会把真实触发审查的
    内容误报为“无字幕”。源 VTT 不存在时才回退已渲染的双语 ASS。
    """
    from video_processing.utils.file_utils import read_webvtt_text

    prefix = f"{youtube_id}_source_subtitle"
    source_files = sorted(
        path for path in _OUT_DIR.glob(f"{prefix}*.vtt")
        if path.name == f"{prefix}.vtt" or path.name.startswith(f"{prefix}.")
    )
    source_text = read_webvtt_text(source_files, max_chars=max_chars)
    if source_text:
        return source_text, "源 VTT 字幕预检"

    rendered_text = _read_subtitle_text(
        youtube_id, slice_index=slice_index, max_chars=max_chars,
    )
    if rendered_text:
        return rendered_text, "渲染 ASS 字幕"
    return "", "无可用字幕"


def _censor_layer_from_error(error_msg: str):
    """从 error_msg 反推审查层级与告警严重度。返回 (layer, label, severity)。"""
    from video_processing.core.censorship_state import censor_layer_from_error
    return censor_layer_from_error(error_msg)


def _build_keyword_cloud(text_zh: str, text_en: str, matched_terms: list, top_k: int = 40) -> list:
    """jieba(中文 TF-IDF) + 英文词频 → [{word, weight, flagged}]，命中词置顶并高亮。"""
    cloud: dict = {}
    # 中文关键词（TF-IDF）
    try:
        import jieba.analyse
        for word, weight in jieba.analyse.extract_tags(text_zh, topK=top_k, withWeight=True):
            w = (word or "").strip()
            if len(w) >= 2:
                cloud[w] = max(cloud.get(w, 0.0), float(weight))
    except Exception:
        pass
    # 英文词频（归一化到与 TF-IDF 量级接近的区间）
    try:
        from collections import Counter
        words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z'\-]{2,}", text_en.lower())
                 if w not in _EN_STOPWORDS]
        if words:
            cnt = Counter(words)
            mx = max(cnt.values())
            for w, c in cnt.most_common(top_k):
                cloud[w] = max(cloud.get(w, 0.0), 0.15 + 0.5 * (c / mx))
    except Exception:
        pass

    matched_lower = [str(m.get("term", "")).lower() for m in matched_terms if m.get("term")]
    # 命中词强制注入，权重置顶，确保即使未被 TF-IDF 选中也出现在云里
    for m in matched_terms:
        t = str(m.get("term", "")).strip()
        if t:
            cloud[t] = max(cloud.get(t, 0.0), 1.0)

    def _is_flagged(word: str) -> bool:
        wl = word.lower()
        return any(mt and (mt in wl or wl in mt) for mt in matched_lower)

    items = [{"word": w, "weight": round(wt, 4), "flagged": _is_flagged(w)} for w, wt in cloud.items()]
    items.sort(key=lambda x: (not x["flagged"], -x["weight"]))  # 命中词置顶，其余按权重降序
    return items[:top_k]


@app.get("/api/videos/{youtube_id}/censor-keywords")
def censor_keywords(youtube_id: str, slice_index: int = 0):
    """[Claude_Opus_4.8] 「复核放行」弹窗数据：审查层级、全部命中词、标题+字幕关键词标签云。"""
    if not re.match(r'^[A-Za-z0-9_\-]+$', youtube_id):
        raise HTTPException(status_code=400, detail="Invalid youtube_id")
    video = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
    if not video:
        return {"success": False, "error": "视频不存在"}

    title = video.get("title") or ""
    zh_title = video.get("zh_title") or ""
    subtitle, subtitle_source = _read_censorship_review_subtitle(
        youtube_id, slice_index=slice_index,
    )

    has_zh = bool(re.search(r"[一-龥]", title))
    text_zh = "\n".join(filter(None, [zh_title or (title if has_zh else ""), subtitle]))
    text_en = "\n".join(filter(None, [title, subtitle]))

    from video_processing.censor_engine import scan_all_matches
    matched = scan_all_matches(zh_text=text_zh, en_text=text_en)
    layer, layer_label, severity = _censor_layer_from_error(video.get("error_msg"))
    keywords = _build_keyword_cloud(text_zh, text_en, matched)
    from video_processing.censorship_evidence import review_evidence
    source_files = sorted(path for path in _OUT_DIR.glob(f"{youtube_id}_source_subtitle*.vtt")
                          if path.name == f"{youtube_id}_source_subtitle.vtt"
                          or path.name.startswith(f"{youtube_id}_source_subtitle."))
    evidence = review_evidence(video, db.get_censorship_incidents(
        youtube_id, slice_index=slice_index, limit=1), subtitle, source_files)
    if layer == "RISK":
        from video_processing.social_unrest_review import replay
        incident = next((row for row in db.get_censorship_incidents(
            youtube_id, slice_index=slice_index, limit=100) if row.get("stage") == "social_unrest"), {})
        evidence = replay(video, incident, _OUT_DIR)
        if evidence["status"] == "VERIFIED_REPLAY":
            matched += [{"term": term["actual"], "layer": "RISK", "channel": "context",
                         "tag": "平台题材风险：社会动荡"} for term in evidence["terms"]]
            keywords = _build_keyword_cloud(text_zh, text_en, matched)

    return {
        "success": True,
        "youtube_id": youtube_id,
        "title": title,
        "zh_title": zh_title,
        "error_msg": video.get("error_msg") or "",
        "censor_tag": video.get("censor_tag") or "",
        "layer": layer,
        "layer_label": layer_label,
        "severity": severity,
        "matched": matched,
        "keywords": keywords,
        "has_subtitle": bool(subtitle),
        "subtitle_chars": len(subtitle),
        "subtitle_source": subtitle_source,
        "evidence": evidence,
    }


@app.post("/api/videos/{youtube_id}/review-censor")
def review_censor(youtube_id: str, request: CensorshipBypassRequest, slice_index: int = 0,
                  engagement_version: Optional[str] = None):
    """对当前完整素材追加独立审计；不批准、不恢复、不发通知或投稿。"""
    from video_processing import social_unrest_review as review
    video = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
    if not video or video.get("status") != "FAILED" or _censor_layer_from_error(video.get("error_msg") or "")[0] != "RISK":
        return {"success": False, "error": "仅平台题材审查失败的视频可重新审查"}
    _check_engagement_action(youtube_id, "bypass-censor", engagement_version, slice_index)
    guard = _wechat_submission_guard_reason(video)
    if guard:
        return {"success": False, "error": guard}
    incident = next((row for row in db.get_censorship_incidents(
        youtube_id, slice_index=slice_index, limit=100) if row.get("stage") == "social_unrest"), {})
    if request.incident_id != incident.get("id") or not incident:
        return {"success": False, "error": "审计已更新，请关闭弹窗后重新打开"}
    try:
        documents = review.current_documents(video, incident, _OUT_DIR, fresh=True)
        evidence = review.current_evidence(documents)
        if (incident.get("review_input_json") and evidence["input_hash"] == incident.get("input_hash")
                and evidence["rule_version"] == incident.get("rule_pack_version")
                and review.replay(video, incident, _OUT_DIR)["status"] == "VERIFIED_REPLAY"):
            return {"success": True, "evidence": review.replay(video, incident, _OUT_DIR)}
        fields = {d["source"]: d["text"] for d in documents}
        incident_id = db.record_censorship_incident(
            youtube_id, slice_index=slice_index, stage="social_unrest", level="RISK",
            action="RECHECK_ONLY", tag=review.TAG, score=None, matched=evidence["matched"], channel="operator",
            decision="SOCIAL_UNREST_MANUAL_REVIEW" if evidence["terms"] else "SOCIAL_UNREST_RECHECK_CLEAR",
            rule_pack_version=evidence["rule_version"], input_hash=evidence["input_hash"],
            rule_id="social_unrest." + evidence.get("family", "clear"), source_field=evidence["source_field"],
            review_stage=incident.get("review_stage") or "pipeline", platform=incident.get("platform"),
            title=fields.get("title"), zh_title=fields.get("zh_title"), description_preview=fields.get("description"),
            text_excerpt=review.ledger_excerpt(evidence), review_input_json=review.snapshot(video, documents, _OUT_DIR))
        current = next(row for row in db.get_censorship_incidents(youtube_id, slice_index=slice_index, limit=100)
                       if row["id"] == incident_id)
        return {"success": True, "evidence": review.replay(video, current, _OUT_DIR)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"success": False, "error": "重新审查失败：" + str(exc)}


@app.get("/api/videos/{youtube_id}/operation-receipts")
def get_operation_receipts(youtube_id: str, slice_index: int = 0):
    from video_processing.core.operation_receipts import review_receipt, submission_feedback
    receipt = review_receipt(db, youtube_id, slice_index)
    if receipt['state'] == 'NOT_FOUND':
        raise HTTPException(404, '视频不存在')
    video = db.get_engagement_video(youtube_id, slice_index=slice_index)
    platform = (video.get('platforms') or {}).get('wechat') or {}
    submission = submission_feedback(_OUT_DIR, youtube_id, slice_index) if platform.get('state') == 'UNCERTAIN' else None
    return JSONResponse({'success': True, 'receipt': receipt, 'submission': submission,
                         'wechat_state': platform.get('state'), 'automatic_retry': False},
                        headers={'Cache-Control': 'no-store'})


@app.get("/api/cover-service/auth")
def get_cover_auth():
    from video_processing.utils.agy_background_auth import auth_snapshot
    response = JSONResponse(auth_snapshot(_OUT_DIR / 'agy_cover_auth.json', now=time.time()))
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.post("/api/cover-service/auth/recheck")
def recheck_cover_auth():
    from video_processing.utils.agy_background_auth import auth_ready, require_auth
    from video_processing.utils.subprocess_env import build_subprocess_env
    from video_processing.utils.cover_agy import run_process
    env = build_subprocess_env(include_gemini=False, include_telegram=False)
    for key in ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'OPENAI_API_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'TELEGRAM_ADMIN_IDS'):
        env.pop(key, None)
    auth_ready(_OUT_DIR / 'agy_cover_auth.json',
               check=lambda: require_auth(settings.agy_command, cwd=_OUT_DIR, env=env, runner=run_process),
               notify=None, now=time.time(), force=True)
    return get_cover_auth()


@app.post("/api/videos/{youtube_id}/bypass-censor")
def bypass_censor(
    youtube_id: str,
    request: Optional[CensorshipBypassRequest] = None,
    slice_index: int = 0,
    engagement_version: Optional[str] = None,
):
    """[Claude_Opus_4.8] 人工复核放行：对审查类失败视频置 bypass 标志，解黑名单、过线、重置并重新触发。

    仅 FAILED 且失败原因为审查（P0/P1/P2 或 Channel Policy）的视频可放行。
    P0 放行必须提交内容复核和恢复管线两项确认，并先写入独立审计台账；
    平台题材风险须提交当前可核实审计的绑定字段；其他层沿用既有流程。

    [Claude_Opus_4.8] BUG-1 配套：bypass 现按 (youtube_id, slice_index) 粒度放行——
    与管线侧 _check_censorship 透传 slice_index 对齐，避免「放行父视频即静默放行全部切片」。
    切片任务（slice_index>0）须由调用方传入对应 slice_index 才能释放该切片本身。
    """
    video = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
    if not video:
        return {"success": False, "error": "视频不存在"}
    _check_engagement_action(youtube_id, "bypass-censor", engagement_version, slice_index)
    guard_reason = _wechat_submission_guard_reason(video)
    if guard_reason:
        return {"success": False, "error": guard_reason}

    em = video.get("error_msg") or ""
    is_censor_fail = _censor_layer_from_error(em)[0] is not None
    if video.get("status") != "FAILED" or not is_censor_fail:
        return {"success": False,
                "error": f"仅审查类失败(FAILED)的视频可复核放行（当前状态：{video.get('status')}）"}

    layer, _label, _sev = _censor_layer_from_error(em)
    is_p0_redline = layer == "P0"
    if is_p0_redline and not (
        request and request.confirm_p0_review and request.confirm_pipeline_resume
    ):
        return {
            "success": False,
            "error": "P0 放行需要完成“已复核内容”与“确认恢复管线”两项确认。",
        }

    if is_p0_redline:
        approval_id = db.record_censorship_incident(
            youtube_id,
            slice_index=slice_index,
            stage="manual_review",
            level="P0",
            action="MANUAL_BYPASS",
            tag=video.get("censor_tag") or "🔴 政治安全违禁",
            score=None,
            matched=em,
            channel="operator",
            decision="MANUAL_P0_APPROVED",
            rule_id="dashboard.p0_double_confirm",
            source_field="dashboard",
            review_stage="manual_p0_double_confirm",
            platform="预加工",
            title=video.get("title") or "",
            zh_title=video.get("zh_title") or "",
            text_excerpt="Operator confirmed content review and pipeline resume in dashboard.",
        )

    if layer == "RISK":
        from video_processing.social_unrest_review import replay, APPROVAL, TAG
        incident = next((row for row in db.get_censorship_incidents(
            youtube_id, slice_index=slice_index, limit=100) if row.get("stage") == "social_unrest"), {})
        evidence = replay(video, incident, _OUT_DIR)
        if evidence["status"] != "VERIFIED_REPLAY":
            return {"success": False, "error": "原输入或规则无法核实，请先重新审查：" + evidence["message"], "evidence_stale": True}
        if not request or (request.incident_id, request.input_hash, request.rule_version) != (
                evidence["incident_id"], evidence["input_hash"], evidence["rule_version"]):
            return {"success": False, "error": "复核证据已过期或未绑定，请刷新证据后确认", "evidence_stale": True}
        approval_id = db.record_censorship_incident(
            youtube_id, slice_index=slice_index, stage="manual_review", level="RISK",
            action="MANUAL_BYPASS", tag=TAG, score=None, matched=incident.get("matched"), channel="operator",
            decision=APPROVAL, rule_pack_version=evidence["rule_version"], input_hash=evidence["input_hash"],
            rule_id="dashboard.social_unrest_input_bound", source_field=incident.get("source_field"),
            review_stage=incident.get("review_stage"), platform=incident.get("platform"),
            title=video.get("title"), zh_title=video.get("zh_title"),
            text_excerpt="Operator approved only the verified input and rule fingerprint.",
        )

    if layer in {"CP", "P1", "P2"}:
        incident = next((row for row in db.get_censorship_incidents(
            youtube_id, slice_index=slice_index, limit=100,
        ) if row.get("level") == layer and row.get("stage") != "manual_review"), {})
        approval_id = db.record_censorship_incident(
            youtube_id, slice_index=slice_index, stage="manual_review", level=layer,
            action="MANUAL_BYPASS", tag=video.get("censor_tag") or layer,
            score=None, matched=incident.get("matched") or em, channel="operator",
            decision=f"MANUAL_{layer}_APPROVED", rule_id=f"dashboard.{layer.lower()}_review",
            input_hash=incident.get("input_hash"), rule_pack_version=incident.get("rule_pack_version"),
            source_field=incident.get("source_field"), review_stage=incident.get("review_stage"),
            platform=incident.get("platform"), title=video.get("title"), zh_title=video.get("zh_title"),
            text_excerpt=f"Operator approved task {video['id']} slice {slice_index}; source incident {incident.get('id')}.",
        )

    # 1) 置放行标志。P0 还须由上方 MANUAL_P0_APPROVED 审计记录配对认可。
    db.set_bypass_censorship(youtube_id, True, slice_index=slice_index)
    # 2) 若 P0 曾写入黑名单墓碑，移除以允许继续处理（黑名单按视频 ID 维度，无切片粒度）
    db.remove_from_blacklist(youtube_id)
    # 3) 确保分数过调度线（P2 曾降权至 0；其余一般已过线）
    if (video.get("score") or 0) < settings.auto_publish_channel_min_scores.get(video.get("channel_id"),75):
        db.update_video_score(youtube_id, 100, force=True, slice_index=slice_index)
    # 4) 重置为 PENDING 并清除错误信息
    db.update_video_status(youtube_id, "PENDING", error_msg=None, slice_index=slice_index)
    # 审计与启用标志均须读回；保存成功与执行启动分别报告。
    from video_processing.core.operation_receipts import review_receipt
    receipt = review_receipt(db, youtube_id, slice_index)
    if receipt['state'] != 'SAVED' or receipt['approval']['id'] != approval_id:
        raise HTTPException(503, '授权回执未能读回，请核实授权结果，勿重复提交')
    # 5) 立即抢占并触发管线
    triggered = False
    if db.claim_video_for_processing(youtube_id, slice_index=slice_index):
        fresh = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
        if fresh:
            try:
                _trigger_video_async(fresh)
                triggered = True
            except Exception:
                logging.getLogger(__name__).exception("授权已保存，但处理启动失败：%s", youtube_id)
                db.update_video_status(youtube_id, "PENDING", error_msg=None, slice_index=slice_index)

    return {
        "success": True,
        "receipt": receipt,
        "youtube_id": youtube_id,
        "slice_index": slice_index,
        "layer": layer,
        "triggered": triggered,
        "message": "授权已保存，已发起后续处理请求" if triggered else "授权已保存，处理尚未启动，请查看调度状态",
    }


# ── 下载进度估算（磁盘轮询，下载器无关）─────────────────────────────────────
# [Claude_Opus_4.8] yt-dlp 用 curl 外部下载器，其进度模板/钩子对外部下载不生效；
# 改为轮询 output/{yid}.f* 临时分片文件大小估算已下字节，info.json.filesize_approx 为总量，
# 两次轮询的字节差 / 时间差即为速度。完全不侵入 pipeline_manager 的下载流程。
_DL_SAMPLES: dict = {}   # {yid: (monotonic_ts, downloaded_bytes)} 用于速度估算


def _dl_downloaded_bytes(yid: str) -> int:
    """累加 output/{yid}.f*（视频流/音频流/分片，含 .part）的大小作为已下字节数。"""
    total = 0
    for p in _OUT_DIR.glob(f"{yid}.f*"):
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def _dl_total_bytes(yid: str):
    """从 output/{yid}.info.json 读取选定格式的总大小（filesize 优先，回退 filesize_approx）。"""
    info = _OUT_DIR / f"{yid}.info.json"
    if not info.exists():
        return None
    try:
        import json
        d = json.loads(info.read_text(encoding="utf-8"))
        return d.get("filesize") or d.get("filesize_approx")
    except Exception:
        return None


@app.get("/api/videos/{youtube_id}/download-progress")
def download_progress(youtube_id: str):
    """[Claude_Opus_4.8] 估算 DOWNLOADING 视频的下载进度/速度/ETA。

    返回 active=False 表示当前不在下载态（前端据此停止显示进度条）。
    percent 为 None 表示拿不到总量（info.json 缺 filesize_*），此时仍返回已下字节与速度。
    """
    if not re.match(r'^[A-Za-z0-9_\-]+$', youtube_id):
        raise HTTPException(status_code=400, detail="Invalid youtube_id")
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}
    if video.get("status") != "DOWNLOADING":
        _DL_SAMPLES.pop(youtube_id, None)
        return {"success": True, "active": False, "phase": "idle"}

    downloaded = _dl_downloaded_bytes(youtube_id)
    total = _dl_total_bytes(youtube_id)

    # 速度：与上次采样比较（dt ≥ 0.5s 才更新采样，避免多标签页高频轮询导致抖动）
    now = time.monotonic()
    speed_bps = None
    prev = _DL_SAMPLES.get(youtube_id)
    if prev:
        dt = now - prev[0]
        delta = downloaded - prev[1]
        if dt >= 0.5:
            if delta >= 0:
                speed_bps = delta / dt
            _DL_SAMPLES[youtube_id] = (now, downloaded)
    else:
        _DL_SAMPLES[youtube_id] = (now, downloaded)

    if downloaded <= 0:
        return {"success": True, "active": True, "phase": "starting",
                "downloaded_bytes": 0, "total_bytes": total,
                "percent": None, "speed_bps": int(speed_bps) if speed_bps else None, "eta_sec": None}

    percent = None
    eta_sec = None
    if total and total > 0:
        percent = max(0.0, min(99.0, downloaded / total * 100.0))
        if speed_bps and speed_bps > 0:
            eta_sec = max(0, int((total - downloaded) / speed_bps))

    return {
        "success": True, "active": True, "phase": "downloading",
        "downloaded_bytes": downloaded, "total_bytes": total,
        "percent": round(percent, 1) if percent is not None else None,
        "speed_bps": int(speed_bps) if speed_bps else None,
        "eta_sec": eta_sec,
    }


@app.post("/api/videos/{youtube_id}/republish")
def republish_video(youtube_id: str):
    """再次发布入口暂时 fail-closed，避免本地状态被误当作平台删除证明。"""
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}
    if video.get("status") not in ("PUBLISHED", "COMPLETED"):
        return {"success": False,
                "error": f"仅已完成/已发布的视频可再次发布（当前状态：{video.get('status')}）"}

    publication = db.get_wechat_publication(youtube_id)
    if not publication or publication.get("state") != "PUBLISHED" or not all(
        publication.get(field) for field in ("confirmed_at", "evidence_path", "platform_post_id")
    ):
        return {
            "success": False,
            "error": "缺少按原生平台 ID 确认的公开视频账本，拒绝再次发布以避免重复提交。",
        }
    return {
        "success": False,
        "error": "平台作品是否已删除尚无按原生 ID 的可审计证明；再次发布入口已暂停，禁止自动重传。",
    }


@app.post("/api/videos/{youtube_id}/retry")
def retry_video(youtube_id: str, engagement_version: Optional[str] = None):
    """
    重试/强制重置视频状态为 PENDING。
    - FAILED / LOGIN_REQUIRED：正常重试，清除错误信息
    - DOWNLOADING/TRANSCRIBING/COPYWRITING：服务器重启后卡死的预提交任务，强制重置
    若当前分数 >= 75，重置后立即自动重新触发。
    """
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}
    _check_engagement_action(youtube_id, "retry", engagement_version)

    submission_guard = _wechat_submission_guard_reason(video)
    if submission_guard:
        return {"success": False, "error": submission_guard}

    subtitle_blocker = db.subtitle_recovery_blocker(video['id'])
    if subtitle_blocker:
        return {"success": False, "error": subtitle_blocker['reason'], "subtitle_recovery": subtitle_blocker}

    retryable = {"FAILED", "LOGIN_REQUIRED", "DOWNLOADING", "TRANSCRIBING", "COPYWRITING"}
    if video.get("status") not in retryable:
        return {
            "success": False,
            "error": f"只有 FAILED / LOGIN_REQUIRED / 各活跃状态可重置（当前：{video['status']}）"
        }

    db.update_video_status(youtube_id, "PENDING", error_msg=None)

    triggered = False
    if video.get("score", 0) >= settings.auto_publish_channel_min_scores.get(video.get("channel_id"),75) and db.claim_video_for_processing(youtube_id):
        fresh = db.get_video_by_youtube_id(youtube_id)
        if fresh:
            _trigger_video_async(fresh)
            triggered = True

    return {
        "success": True,
        "triggered": triggered,
        "message": "已重置并立即重新触发" if triggered else f"已重置为 PENDING，当前频道准入分数线为{settings.auto_publish_channel_min_scores.get(video.get('channel_id'),75)}；其它门禁仍须通过",
    }


@app.post("/api/videos/retry-recent")
def retry_recent(hours: int = 24):
    """旧调用保留参数，进入同一固定预览确认流程，避免扩大范围或误重投。"""
    return {"success": False, "confirmation_required": True, "hours": hours,
            "error": "请在发布恢复后台预览并确认具体任务，旧接口不再直接批量修改状态。",
            "url": "/wechat-cooldown-settings?window=24h"}


@app.get("/api/videos/retry-recent/preview")
def retry_recent_preview(hours: int = 24):
    if hours <= 0 or hours > 720:
        return {"success": False, "error": "hours 需在 1~720 之间"}
    from video_processing.publishing_recovery import PublishingRecoveryService
    from datetime import datetime, timedelta, timezone
    last = datetime.now(timezone.utc)
    result = PublishingRecoveryService(db, settings.project_root).preview(
        window="custom", start=(last-timedelta(hours=hours)).isoformat(), end=last.isoformat())
    return {**result, "success": True, "count": sum(i["eligible"] for i in result["items"]),
            "hours": hours, "url": "/wechat-cooldown-settings?preview="+result["preview_id"]}


@app.post("/api/videos/{youtube_id}/slices/{slice_index}/retry")
def retry_slice(youtube_id: str, slice_index: int):
    """[Gemini_3.5_Flash_High_planning] 针对单个切片子任务执行重置与重试"""
    video = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
    if not video:
        raise HTTPException(status_code=404, detail="切片任务不存在")

    submission_guard = _wechat_submission_guard_reason(video)
    if submission_guard:
        return {"success": False, "error": submission_guard}

    subtitle_blocker = db.subtitle_recovery_blocker(video['id'])
    if subtitle_blocker:
        return {"success": False, "error": subtitle_blocker['reason'], "subtitle_recovery": subtitle_blocker}

    retryable = {"FAILED", "LOGIN_REQUIRED", "DOWNLOADING", "TRANSCRIBING", "COPYWRITING"}
    if video.get("status") not in retryable:
        return {
            "success": False,
            "error": f"只有 FAILED / LOGIN_REQUIRED / 各活跃状态可重置（当前：{video['status']}）"
        }

    db.update_video_status(youtube_id, "PENDING", error_msg=None, slice_index=slice_index)

    triggered = False
    # 手动重试：若分数 >= 75 且父视频存在，并且满足 Sequence Lock（前序子任务均已发布），则立即触发
    if video.get("score", 0) >= settings.auto_publish_channel_min_scores.get(video.get("channel_id"),75):
        from video_processing.pipeline_manager import PipelineManager
        pm = PipelineManager()
        parent_file = pm._find_downloaded_video(youtube_id)
        
        all_slices = db.get_slices_by_parent_yid(youtube_id)
        prev_not_published = [s for s in all_slices if s['slice_index'] < slice_index and s['status'] != 'PUBLISHED']
        
        if parent_file and not prev_not_published:
            if db.claim_video_for_processing(youtube_id, slice_index=slice_index):
                fresh = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
                if fresh:
                    _trigger_video_async(fresh)
                    triggered = True

    return {
        "success": True,
        "triggered": triggered,
        "message": "已重置并立即重新触发" if triggered else "已重置为 PENDING，等待父任务下载或前导分集发布",
    }


@app.post("/api/videos/{youtube_id}/slices/{slice_index}/process")
def process_slice_now(youtube_id: str, slice_index: int,
                      cooldown_action: str = "", cooldown_version: str = ""):
    """[Unknown_Model_planning] 立即处理指定切片子任务，忽略分数。"""
    video = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
    if not video:
        raise HTTPException(status_code=404, detail="切片任务不存在")

    if video.get("status") != "PENDING":
        return {
            "success": False,
            "error": f"只有 PENDING 状态的切片可以启动（当前：{video['status']}）"
        }

    # 检查父视频文件是否下载就绪
    from video_processing.pipeline_manager import PipelineManager
    pm = PipelineManager()
    parent_file = pm._find_downloaded_video(youtube_id)
    if not parent_file:
        return {"success": False, "error": "父视频主文件尚未就绪，请先下载或重试父视频。"}

    # 检查顺序锁（前序子任务是否已发布）
    all_slices = db.get_slices_by_parent_yid(youtube_id)
    prev_not_published = [s for s in all_slices if s['slice_index'] < slice_index and s['status'] not in ('PUBLISHED', 'IGNORED', 'COMPLETED')]
    if prev_not_published:
        prev_indices = [s['slice_index'] for s in prev_not_published]
        return {
            "success": False,
            "error": f"前序切片 {prev_indices} 尚未发布/跳过/手动上传，当前切片已被顺序锁阻断。"
        }

    guard_reason = _wechat_submission_guard_reason(video)
    if guard_reason:
        return {"success": False, "error": guard_reason}
    reply, override = _manual_cooldown_check(video, cooldown_action, cooldown_version)
    if reply is not None:
        return reply
    # 抢占任务
    if not db.claim_video_for_processing(youtube_id, slice_index=slice_index):
        if override:
            _wechat_cooldown_guard().revoke_override(override)
        return {"success": False, "error": "切片已被其他进程抢占。"}

    fresh = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
    if fresh:
        if override:
            fresh["_wechat_cooldown_override"] = override
        _trigger_video_async(fresh)

    return {
        "success": True,
        "message": f"已在后台启动切片子任务 [{youtube_id} s{slice_index}] 处理"
    }


@app.post("/api/videos/{youtube_id}/reset-hard")
def reset_video_hard(youtube_id: str):
    """
    硬重置：删除该视频所有本地产物文件（mp4/vertical/copy/cover/title/category），
    然后重置状态为 PENDING。若分数 >= 75 立即重新触发完整管线（从下载开始）。
    """
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}

    submission_guard = _wechat_submission_guard_reason(video)
    if submission_guard:
        return {"success": False, "error": submission_guard}

    # 调用 PipelineManager 的硬重置方法删除产物文件
    from video_processing.pipeline_manager import PipelineManager
    pm = PipelineManager()
    deleted = pm.reset_video_artifacts(youtube_id)

    db.update_video_status(youtube_id, "PENDING", error_msg=None)

    triggered = False
    if video.get("score", 0) >= settings.auto_publish_channel_min_scores.get(video.get("channel_id"),75) and db.claim_video_for_processing(youtube_id):
        fresh = db.get_video_by_youtube_id(youtube_id)
        if fresh:
            _trigger_video_async(fresh)
            triggered = True

    return {
        "success": True,
        "deleted_files": deleted,
        "triggered": triggered,
        "message": f"已删除 {len(deleted)} 个产物文件，重置为 PENDING" + ("并重新触发" if triggered else ""),
    }


# [Gemini_2.5_Pro_planning] 注意：此路由必须在 /api/videos/{youtube_id} 之前注册，
# 否则 FastAPI 会将 'waitlist' 当成 youtube_id 参数，导致 404。
@app.post("/api/videos/waitlist/cleanup-expired")
def cleanup_expired_waitlist(days: Optional[int] = None):
    """一键清理/归档超过指定天数（默认 30 天）的待筛选低分素材，流转为 EXPIRED。"""
    ttl_days = days if days is not None else settings.waitlist_ttl_days
    count = db.cleanup_expired_waitlist_videos(ttl_days=ttl_days)
    return {
        "success": True,
        "cleaned_count": count,
        "ttl_days": ttl_days,
        "message": f"已成功归档清理 {count} 条超过 {ttl_days} 天的过期待筛选素材",
    }


@app.post("/api/videos/queue/discard-stale")
def discard_stale_queue(days: Optional[int] = None):
    """批量放弃排队超过指定天数（默认 7 天）的高分过时视频，流转为 IGNORED。"""
    stale_days = days if days is not None else settings.queue_stale_days
    count = db.discard_stale_queue_videos(stale_days=stale_days)
    return {
        "success": True,
        "discarded_count": count,
        "stale_days": stale_days,
        "message": f"已成功放弃/忽略 {count} 条超过 {stale_days} 天的超期排队任务",
    }


@app.post("/api/videos/queue/calibrate")
def calibrate_queue():
    """手动触发幽灵排队任务状态自愈校准。"""
    count = db.reconcile_pending_ghost_tasks()
    return {
        "success": True,
        "calibrated_count": count,
        "message": f"已校准 {count} 条幽灵排队任务状态",
    }


@app.delete("/api/videos/waitlist/all")
def clear_waitlist():
    """[Gemini_2.5_Pro_planning] 清空待筛选列表（全部 PENDING 且分数 < 75 的视频）。

    清空后会写入黑名单墓碑，爬虫不会再次拉取这些视频。

    [Claude_Opus_4.8] BUG-5: 改走 DAL get_waitlist_clearable_ids()，显式排除 DISCOVERY，
    避免一键清空误删/拉黑高赞发现条目（击穿发现防火墙）。
    """
    # 获取待筛选列表所有可清空 ID（DAL 集中谓词，排除 DISCOVERY）
    all_ids = db.get_waitlist_clearable_ids()

    if not all_ids:
        return {"success": True, "deleted_count": 0, "message": "待筛选列表已经是空的"}

    tombstone = settings.enable_blacklist_tombstone
    deleted_count, failed_ids = db.batch_delete_video_records(all_ids, tombstone=tombstone)

    msg = f"共清空 {deleted_count} 条待筛选视频"
    if tombstone:
        msg += "（已全部写入黑名单，爬虫不会再次抓取）"
    return {
        "success": not failed_ids,
        "deleted_count": deleted_count,
        "failed_ids": failed_ids,
        "message": msg,
    }


@app.delete("/api/videos")
def batch_delete_videos(req: BatchDeleteRequest):
    """[Gemini_2.5_Pro_planning]    批量删除视频记录（不含物理文件，除非可选）。
    
    # Modification History
| backlog-v1 | 2026-10-26 | Codex | TED 专属50分、真实资格展示与成片积压治理。 |
| reply-recovery-v1 | 2026-10-25 | Codex | 移除迁移入口无条件冲突，策略页改走活动配置与本机权限。 |
| filtered-counts-v1 | 2026-10-25 | Codex | 标签计数与列表筛选一致，验证频道、时间和清除筛选。 |
    | Version | Date | Author | Description |
    | --- | --- | --- | --- |
    | 1.0.0 | 2026-05-24 | Unknown_Model | Initial creation |
    | 1.1.0 | 2026-05-27 | Unknown_Model_planning | 修复未清理活跃切片任务进程和产物文件的 bug |
    
    不支持删除正处于活跃状态的视频（ACTIVE_STATUSES）——需先停止进程再删除。
    """
    if not req.youtube_ids:
        return {"success": False, "error": "请提供要删除的视频 ID 列表"}

    # 安全校验：拒绝删除活跃任务
    invalid = [yid for yid in req.youtube_ids if not re.match(r'^[A-Za-z0-9_\-]+$', yid)]
    if invalid:
        return {"success": False, "error": f"非法 ID: {invalid}"}

    active_ids = []
    protected_ids = []
    for yid in req.youtube_ids:
        parent = db.get_video_by_youtube_id(yid, slice_index=0)
        slices = db.get_slices_by_parent_yid(yid)
        targets = ([parent] if parent else []) + slices
        if any(_wechat_submission_guard_reason(target) for target in targets):
            protected_ids.append(yid)
        if any(t.get("status") in ACTIVE_STATUSES for t in targets):
            active_ids.append(yid)

    if protected_ids:
        return {
            "success": False,
            "error": f"以下视频存在视频号平台账本，禁止删除以保留防重传审计：{protected_ids}",
        }

    if active_ids:
        return {
            "success": False,
            "error": f"以下视频（或其切片）正在处理中，无法批量删除：{active_ids}",
        }

    # 可选删除产物文件
    deleted_files_total: list[str] = []
    if req.delete_files:
        from video_processing.pipeline_manager import PipelineManager
        pm = PipelineManager()
        for yid in req.youtube_ids:
            deleted_files_total.extend(pm.reset_video_artifacts(yid))
            slices = db.get_slices_by_parent_yid(yid)
            for s in slices:
                deleted_files_total.extend(pm.reset_video_artifacts(f"{yid}_s{s['slice_index']}"))

    tombstone = settings.enable_blacklist_tombstone
    deleted_count, failed_ids = db.batch_delete_video_records(req.youtube_ids, tombstone=tombstone)

    msg = f"共删除 {deleted_count} 条视频记录"
    if tombstone:
        msg += "（已写入黑名单，爬虫不会再次抓取）"
    if req.delete_files:
        msg += f"，并清理了 {len(deleted_files_total)} 个产物文件"
    if failed_ids:
        msg += f"。失败: {failed_ids}"

    return {
        "success": not failed_ids,
        "deleted_count": deleted_count,
        "failed_ids": failed_ids,
        "deleted_files": deleted_files_total,
        "message": msg,
    }


@app.delete("/api/videos/{youtube_id}")
def delete_video(youtube_id: str, delete_files: bool = False, slice_index: Optional[int] = None):
    """
    删除任务记录并可选写入黑名单墓碑。
    如果 delete_files=True，同时删除相关的本地产物文件。

    # Modification History
    | Version | Date | Author | Description |
    | --- | --- | --- | --- |
    | 1.0.0 | 2026-05-24 | Unknown_Model | Initial creation |
    | 1.1.0 | 2026-05-27 | Gemini_3.5_Flash_High_planning | 支持定向删除 slice_index，加入 SIGTERM 强杀逻辑 |
    | 1.2.0 | 2026-05-27 | Unknown_Model_planning | [Bugfix] 删除父视频时，连带强杀所有活跃切片子进程并删除产物 |

    [Gemini_3.5_Flash_High_planning] 升级：
    - 支持通过 slice_index 参数定向物理删除子任务。
    - 如果视频处于活跃状态且 settings.enable_sigterm_kill=True，
      会向其进程组发 SIGTERM 优雅终止，超时 2s 后强杀。
    - 删除后（若是父视频）将 youtube_id 写入 blacklisted_videos 墓碑表，
      防止爬虫二次拉取。
    """
    if slice_index is not None:
        targets = [db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)]
    else:
        parent = db.get_video_by_youtube_id(youtube_id, slice_index=0)
        slices = db.get_slices_by_parent_yid(youtube_id)
        targets = ([parent] if parent else []) + slices

    targets = [t for t in targets if t]
    if not targets:
        return {"success": False, "error": "视频不存在"}

    if any(_wechat_submission_guard_reason(target) for target in targets):
        return {
            "success": False,
            "error": "视频号存在平台账本或待确认提交，禁止删除以保留防重传审计。",
        }

    # ── 1. 处理活跃任务：SIGTERM 阶梯强杀 ───────────────────────
    active_targets = [t for t in targets if t.get("status") in ACTIVE_STATUSES]
    
    if active_targets:
        if not settings.enable_sigterm_kill:
            # Flag 未开启：保持原有行为，拒绝删除活跃任务
            active_statuses = {str(t.get("status")) for t in active_targets}
            return {"success": False,
                    "error": f"安全拦截：相关视频/切片正处于执行状态（{', '.join(active_statuses)}）。"
                             "请等待完成或变为 FAILED。"}

        # Flag 开启：SIGTERM 阶梯强杀
        pids_to_kill = [t.get("process_pid") for t in active_targets if t.get("process_pid")]
        if pids_to_kill:
            for pid in pids_to_kill:
                _safe_kill_pid_or_pgid(pid, signal.SIGTERM)
            
            time.sleep(2.0)                  # 等待 2 秒自退（time 已顶层导入）
            
            for pid in pids_to_kill:
                if _is_pid_or_pgid_alive(pid):
                    _safe_kill_pid_or_pgid(pid, signal.SIGKILL)
                    import logging as _logging   # 局部别名，避免覆盖模块级 logger
                    _logging.getLogger(__name__).warning(
                        f"[SIGKILL] Process or group {pid} did not exit after SIGTERM, force killed.")

    # ── 2. 删除产物文件 ─────────────────────────────────────────
    deleted_files = []
    if delete_files:
        from video_processing.pipeline_manager import PipelineManager
        pm = PipelineManager()
        if slice_index is not None:
            prefix = f"{youtube_id}_s{slice_index}" if slice_index > 0 else youtube_id
            deleted_files.extend(pm.reset_video_artifacts(prefix))
        else:
            deleted_files.extend(pm.reset_video_artifacts(youtube_id))
            for t in targets:
                idx = t.get("slice_index")
                if idx and idx > 0:
                    deleted_files.extend(pm.reset_video_artifacts(f"{youtube_id}_s{idx}"))

    # ── 3. 黑名单墓碑 + 删除主表记录 ──────────────────────────
    # [Gemini_3.5_Flash_High_planning] 仅当删除父视频（非 slice 子任务）时，才写入黑名单墓碑
    if settings.enable_blacklist_tombstone and not slice_index:
        db.add_to_blacklist(youtube_id, reason="user_deleted")
        
    db.delete_video_record(youtube_id, slice_index=slice_index)

    msg = "已彻底清除该任务记录"
    if settings.enable_blacklist_tombstone and not slice_index:
        msg += "（已写入黑名单，爬虫不会再次拉取）"
    if delete_files:
        msg += f"，并清理了 {len(deleted_files)} 个关联产物文件"

    return {
        "success": True,
        "deleted_files": deleted_files,
        "message": msg,
    }


class RespecVideoRequest(BaseModel):
    trim_start: Optional[str] = None
    trim_end: Optional[str] = None
    disable_slicing: Optional[bool] = True
    tts_provider: Optional[str] = None


@app.post("/api/videos/{youtube_id}/respec")
def respec_video(youtube_id: str, req: RespecVideoRequest):
    """规格覆盖：停止当前处理（如有），更新规格字段，重新入队并触发。

    适用于：用户发现裁剪参数有误，重发同一 URL + 新参数后的自动修正流程。

    # Modification History
    | Version | Date       | Author                              | Description  |
    | ------- | ---------- | ----------------------------------- | ------------ |
    | 1.0.0   | 2026-06-01 | Claude_Sonnet_4.6_Thinking_planning | 初始创建     |

    状态处理规则：
    - PUBLISHED / SEGMENTED / IGNORED / COMPLETED → 拒绝（终态，不可覆盖）
    - DOWNLOADING / TRANSCRIBING / COPYWRITING → kill 进程后更新
    - PUBLISHING / 视频号待确认账本 → 拒绝，避免中断后自动重传
    - PENDING / FAILED → 直接更新规格，重置 PENDING
    物理文件：通常不删除；但 TTS 音轨规格变化时，会失效竖版成片和封面，
    防止新版本继续复用原声版缓存。
    """
    video = db.get_video_by_youtube_id(youtube_id)
    if not video:
        return {"success": False, "error": "视频不存在"}

    status = video.get("status", "")

    submission_guard = _wechat_submission_guard_reason(video)
    if submission_guard:
        return {"success": False, "error": submission_guard, "current_status": status}

    # ── 1. 终态拒绝 ─────────────────────────────────────────────
    _TERMINAL_STATUSES = {"PUBLISHED", "UNDER_REVIEW", "SEGMENTED", "IGNORED", "COMPLETED"}
    if status in _TERMINAL_STATUSES:
        return {
            "success": False,
            "error": f"视频当前状态为 {status}，无法覆盖规格（终态保护）",
            "current_status": status,
        }

    # ── 2. 活跃状态：杀进程 ────────────────────────────────────
    was_stopped = False
    if status in ACTIVE_STATUSES:
        if not settings.enable_sigterm_kill:
            return {
                "success": False,
                "error": "进程强杀未启用（enable_sigterm_kill=False），无法中止活跃任务",
            }
        pid = video.get("process_pid")
        if pid:
            _safe_kill_pid_or_pgid(pid, signal.SIGTERM)
            time.sleep(2.0)
            if _is_pid_or_pgid_alive(pid):
                _safe_kill_pid_or_pgid(pid, signal.SIGKILL)
                import logging as _log
                _log.getLogger(__name__).warning(
                    f"[SIGKILL] respec forced kill pid={pid} for {youtube_id}"
                )
        was_stopped = True

    # ── 3. 校验裁剪参数 ─────────────────────────────────────
    _time_re = re.compile(r"^[0-9:.]*$")
    trim_start = req.trim_start.strip() if req.trim_start else None
    trim_end   = req.trim_end.strip()   if req.trim_end   else None
    if trim_start and not _time_re.match(trim_start):
        return {"success": False, "error": "开始时间格式不合法，仅支持数字、冒号和点"}
    if trim_end and not _time_re.match(trim_end):
        return {"success": False, "error": "结束时间格式不合法，仅支持数字、冒号和点"}

    disable_slicing_val = 1 if req.disable_slicing else 0
    previous_tts_provider = str(video.get("tts_provider") or "").strip()
    requested_tts_provider = str(req.tts_provider or "").strip()
    invalidated_artifacts: list[str] = []
    if previous_tts_provider != requested_tts_provider:
        invalidated_artifacts = _invalidate_audio_variant_artifacts(youtube_id)

    # ── 4. 更新规格 ─────────────────────────────────────────────
    db.update_video_spec(
        youtube_id,
        trim_start=trim_start,
        trim_end=trim_end,
        disable_slicing=disable_slicing_val,
        tts_provider=req.tts_provider,
    )

    # ── 5. 重置状态并触发 ────────────────────────────────────────
    db.update_video_status(youtube_id, "PENDING", error_msg=None)

    triggered = False
    if db.claim_video_for_processing(youtube_id):
        fresh = db.get_video_by_youtube_id(youtube_id)
        if fresh:
            _trigger_video_async(fresh)
            triggered = True

    return {
        "success": True,
        "youtube_id": youtube_id,
        "title": video.get("title"),
        "trim_start": trim_start,
        "trim_end": trim_end,
        "disable_slicing": req.disable_slicing,
        "tts_provider": req.tts_provider,
        "was_stopped": was_stopped,
        "invalidated_artifacts": invalidated_artifacts,
        "triggered": triggered,
    }


@app.post("/api/videos/{youtube_id}/stop")
def stop_video(youtube_id: str, slice_index: Optional[int] = None):
    """
    停止仍可安全中止的任务；PUBLISHING 一律转入未绑定提交账本，禁止重发。

    # Modification History
    | Version | Date | Author | Description |
    | --- | --- | --- | --- |
    | 1.1.0 | 2026-08-21 | Codex | 发布中手动中止先记 SUBMITTED_UNBOUND；审核中不再误置 FAILED |
    | 1.0.0 | 2026-05-28 | Gemini_3.5_Flash_planning | 初始创建，实现 SIGTERM/SIGKILL 阶梯强杀与状态流转 |

    [Gemini_3.5_Flash_planning]:
    - 支持通过 slice_index 定向停止子切片或停止父视频及其所有切片。
    - 使用 SIGTERM -> wait 2s -> SIGKILL 强杀正在运行的进程组。
    - 预提交任务更新为 FAILED；PUBLISHING 先写未绑定提交账本再停止，绝不自动重传。
    """
    if slice_index is not None:
        targets = [db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)]
    else:
        parent = db.get_video_by_youtube_id(youtube_id, slice_index=0)
        slices = db.get_slices_by_parent_yid(youtube_id)
        targets = ([parent] if parent else []) + slices

    targets = [t for t in targets if t]
    if not targets:
        return {"success": False, "error": "视频不存在"}

    # UNDER_REVIEW 没有可安全终止的本地提交动作；把它改为 FAILED 会使通用重试绕过平台核验。
    protected_targets = [
        t for t in targets
        if str(t.get("status") or "").upper() in {"UNDER_REVIEW", "SUBMITTED_UNBOUND", "SUBMITTED_BOUND", "UNCERTAIN"}
    ]
    if protected_targets:
        return {
            "success": False,
            "error": "相关视频号提交正在等待平台核验，禁止中止或改写为 FAILED。",
        }

    # 过滤出处于可中止处理阶段的任务；PUBLISHING 仍可停止，但会 fail-closed 落账。
    active_targets = [t for t in targets if t.get("status") in ACTIVE_STATUSES]
    if not active_targets:
        return {"success": False, "error": "相关视频/切片当前不处于运行状态"}

    if not settings.enable_sigterm_kill:
        return {"success": False, "error": "未启用进程强杀机制，无法强制停止任务"}

    publishing_targets = [t for t in active_targets if t.get("status") == "PUBLISHING"]
    if publishing_targets:
        reason = "用户在 PUBLISHING 阶段中止本地进程；平台可能已受理，已停止自动重传并等待核验。"
        try:
            for t in publishing_targets:
                db.record_wechat_publication_confirmation(
                    t["youtube_id"], evidence_path=None, state="SUBMITTED_UNBOUND",
                    error_message=reason, slice_index=t.get("slice_index", 0),
                )
                db.record_wechat_submission_attempt(
                    t["youtube_id"], evidence_path=None, final_title=t.get("title"),
                    slice_index=t.get("slice_index", 0),
                )
                db.cancel_queued_downstream_publications_for_unconfirmed_wechat(
                    t["youtube_id"], reason=reason, slice_index=t.get("slice_index", 0),
                )
        except Exception as exc:
            logger.exception("停止发布前无法写入视频号未确认账本")
            return {"success": False, "error": f"无法写入视频号未确认账本，拒绝中止：{exc}"}

    pids_to_kill = [t.get("process_pid") for t in active_targets if t.get("process_pid")]
    if pids_to_kill:
        for pid in pids_to_kill:
            _safe_kill_pid_or_pgid(pid, signal.SIGTERM)
        
        time.sleep(2.0)                  # 等待 2 秒自退 [Gemini_3.5_Flash_planning]
        
        for pid in pids_to_kill:
            if _is_pid_or_pgid_alive(pid):
                _safe_kill_pid_or_pgid(pid, signal.SIGKILL)
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    f"[SIGKILL] Process or group {pid} did not exit after SIGTERM, force killed.")

    # 仅预提交阶段可标记 FAILED；发布中被终止时平台状态未知，必须保持 fail-closed。
    for t in active_targets:
        if t.get("status") == "PUBLISHING":
            db.update_video_status(
                t["youtube_id"], "SUBMITTED_UNBOUND",
                error_msg="用户在 PUBLISHING 阶段中止；平台可能已受理，禁止自动重传。",
                slice_index=t.get("slice_index", 0),
            )
            continue
        db.update_video_status(
            t["youtube_id"],
            "FAILED",
            error_msg="用户手动停止",
            slice_index=t.get("slice_index", 0)
        )

    return {
        "success": True,
        "message": f"成功停止 {len(active_targets)} 个活跃任务；发布中任务已转未确认账本，其余已置为 FAILED"
    }


@app.post("/api/wechat/login")
def wechat_login(headless: bool = True):
    """
    启动微信登录。默认以无头模式运行并生成二维码图片以供前端扫码；
    也可以传递 headless=false 以便在本地有图形界面的机器上弹出浏览器。
    # [Gemini_2.0_Flash_fast]
    """
    started = _start_wechat_login_flow(headless=headless, preserve_marker=False, reason="manual")
    if not started.get("success"):
        return started
    if started.get("already_running"):
        started["message"] = "微信登录程序已在运行，请使用当前二维码扫码"
    return {
        **started,
        "message": (
            "无头登录程序已启动，正在获取二维码，请等待浮层刷新"
            if headless and not started.get("already_running")
            else ("已在本机启动浏览器，请在弹出窗口中扫码" if not headless and not started.get("already_running") else started["message"])
        ),
    }


@app.get("/api/wechat/qr")
def get_wechat_qr():
    """[Gemini_2.0_Flash_fast] 返回微信扫码登录的临时二维码图片"""
    prj_root = Path(__file__).parent.parent.parent
    qr_path = prj_root / "output" / "login_qr.png"
    if not qr_path.exists():
        raise HTTPException(status_code=404, detail="QR code not found")
    return FileResponse(
        str(qr_path),
        media_type="image/png",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/wechat/status")
def get_wechat_status():
    """[Gemini_2.0_Flash_fast] 获取当前微信登录状态与后台登录子进程状态"""
    prj_root = Path(__file__).parent.parent.parent
    state_path = prj_root / "output" / "wechat_state.json"
    login_at_path = prj_root / "output" / "wechat_login_at.txt"
    qr_path = prj_root / "output" / "login_qr.png"
    
    is_running = _is_wechat_login_running()
    login_marker_active = _wechat_login_marker_active(login_at_path)
    login_flow_active = is_running or qr_path.exists()

    from video_processing.core.wechat_auth_state import (
        read_wechat_auth_state,
        evaluate_wechat_session_status,
    )
    auth_state = read_wechat_auth_state(state_path) if state_path.exists() else {}
    eval_status = (
        evaluate_wechat_session_status(auth_state, state_file_exists=state_path.exists())
        if state_path.exists()
        else {"status_label": "❌ 凭证文件缺失"}
    )
    
    return {
        "logged_in": state_path.exists() and login_marker_active,
        "state_exists": state_path.exists(),
        "login_marker_active": login_marker_active,
        "status_label": eval_status.get("status_label", "") + (
            "；" + eval_status["keepalive_wait_label"] if eval_status.get("keepalive_wait_label")
            and auth_state.get("defer_reason") != "RECENT_VERIFIED" else ""),
        "keepalive_wait_reason": auth_state.get("defer_reason"),
        "next_keepalive_scheduled_at": auth_state.get("next_keepalive_scheduled_at"),
        "last_verified_at": auth_state.get("last_verified_at"),
        "authorization_relative_age": eval_status.get("relative_age", "无记录"),
        "authorization_time_bj": eval_status.get("login_time_bj", "无授权记录"),
        "qr_exists": qr_path.exists(),
        "is_running": is_running,
        "login_flow_active": login_flow_active,
    }


def _is_wechat_login_running() -> bool:
    """判断是否已有 Web/TG 触发的微信登录进程在等待扫码，避免二维码互相覆盖。"""
    if _wechat_login_thread and _wechat_login_thread.is_alive():
        return True
    try:
        result = run_admitted(
            ["ps", "-axo", "pid=,command="],
            cwd=str(Path(__file__).parent.parent.parent),
            capture_output=True,
            text=True,
            timeout=2,
        )
        return any(
            ".venv/bin/python" in line and "scripts/wechat_uploader.py" in line and "--login-only" in line
            for line in result.stdout.splitlines()
        )
    except Exception:
        return False


def _wechat_login_marker_active(login_at_path: Path, max_age_hours: int = 23) -> bool:
    """结合结构化状态与验证事实判断微信会话是否真实处于有效登录态。

    不再单凭文本文件时间戳或固定 23h 断言有效，而是优先核验结构化授权状态与最近验证事实。
    """
    prj_root = Path(__file__).parent.parent.parent
    state_file = prj_root / "output" / "wechat_state.json"
    if not state_file.is_file():
        return False

    from video_processing.core.wechat_auth_state import (
        read_wechat_auth_state,
        evaluate_wechat_session_status,
    )
    auth_state = read_wechat_auth_state(state_file)
    eval_res = evaluate_wechat_session_status(auth_state, state_file_exists=True)
    valid_labels = ("✅ 授权且已验证", "🟡 会话已验证（授权时间未知）", "🟡 已达重登阈值", "⚠️ 临近重登阈值")
    return eval_res.get("status_label") in valid_labels


def _is_pipeline_manager_running() -> bool:
    """[Gemini_3.5_Flash_planning] 通过尝试获取文件锁来非阻塞检测当前是否已有 pipeline_manager 正在运行"""
    lock_path = Path(__file__).parent.parent.parent / "output" / "pipeline.lock"
    if not lock_path.exists():
        return False
    try:
        with open(lock_path, "r") as f:
            try:
                # 尝试获取排他锁（非阻塞）
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                # 能够获取到锁，说明当前没有进程持有锁，释放并返回 False
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                return False
            except (BlockingIOError, OSError):
                # 无法获取锁，说明已被其他处理进程占用
                return True
    except Exception:
        return False


@entry
def _start_full_pipeline(trigger_source: str):
    """启动完整管线，并记录实际触发来源。"""
    def _run():
        prj_root = Path(__file__).parent.parent.parent
        python   = str(prj_root / ".venv" / "bin" / "python")
        src_dir  = str(prj_root / "src")
        log_path = prj_root / "output" / "pipeline.log"
        log_path.parent.mkdir(exist_ok=True)
        # BUG-5 修复：清除代理环境变量，防止代理未运行时 monitor_channels 失败
        _proxy = frozenset({'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'})
        env_clean = {k: v for k, v in os.environ.items() if k not in _proxy}

        import subprocess as sp
        with open(log_path, "a") as f:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"\n=== {trigger_source}-triggered pipeline run ({now_str}) ===\n")
            # [Gemini_3.5_Flash_planning] 使用 -u 启用无缓冲输出
            gate().require_running()
            run_admitted([python, "-u", str(prj_root / "scripts" / "monitor_channels.py")],
                   cwd=str(prj_root), stdout=f, stderr=f, env=env_clean, start_new_session=True)
            
            # [Gemini_3.5_Flash_planning] 校验引擎排他锁以防并发阻塞导致进程堆积泄露
            if _is_pipeline_manager_running():
                f.write("[Scheduler] pipeline_manager is already running (pipeline.lock is held). Skipping duplicate run to prevent process leaks.\n")
                f.flush()
            else:
                gate().require_running()
                run_admitted([python, "-u", "-m", "video_processing.pipeline_manager",
                        "--trigger-source", "dashboard_manual_full" if trigger_source == "web" else "dashboard_scheduler"],
                       cwd=src_dir, stdout=f, stderr=f, env=env_clean, start_new_session=True)

    spawn_admitted(_run, role="batch-dispatch", object_key="batch-dispatch", name="full-pipeline")
    return {"success": True, "message": "全量管线已在后台启动，请关注仪表盘进度"}


@app.post("/api/pipeline/run")
def run_full_pipeline():
    """网页手动触发完整管线：monitor_channels + pipeline_manager。"""
    return _start_full_pipeline("web")



# ── 科技选题线索中枢 (Topic Clues Hub) API ─────────────────────────────
@app.get("/api/trending-keywords")
def get_trending_keywords():
    """返回当前科技选题线索列表及元数据 (SWR 毫秒级极速响应，超期后台静默刷新)"""
    try:
        from video_processing.topic_clues.hub import get_topic_clues_hub
        hub = get_topic_clues_hub()
        from video_processing.utils.maintenance_clues import read_clues
        return read_clues(hub)
    except Exception as e:
        logging.getLogger(__name__).warning(f"[TopicClues] 获取热词线索异常降级: {e}")
        from urllib.parse import quote_plus
        DEFAULT_STATIC_KEYWORDS = ["AI interview", "tech keynote 2026", "business podcast", "founder speech"]
        result_kws = [
            {
                "keyword": kw,
                "type": "static",
                "hn_score": None,
                "signal": None,
                "title": None,
                "yt_url": f"https://www.youtube.com/results?search_query={quote_plus(kw)}",
            }
            for kw in DEFAULT_STATIC_KEYWORDS
        ]
        return {
            "enabled": False,
            "source": "error",
            "keywords": result_kws,
            "updated_at": None,
            "error": str(e),
        }


@app.post("/api/trending-keywords/refresh")
def refresh_trending_keywords():
    """强制同步刷新科技选题线索（经 Singleflight 互斥，多并发共享单次底层抓取）"""
    try:
        from video_processing.topic_clues.hub import get_topic_clues_hub
        hub = get_topic_clues_hub()
        return hub.refresh_sync()
    except Exception as e:
        logging.getLogger(__name__).warning(f"[TopicClues] 刷新热词线索异常降级: {e}")
        from urllib.parse import quote_plus
        from video_processing.topic_clues.hub import DEFAULT_STATIC_KEYWORDS
        result_kws = [
            {
                "keyword": kw,
                "type": "static",
                "hn_score": None,
                "signal": None,
                "title": None,
                "yt_url": f"https://www.youtube.com/results?search_query={quote_plus(kw)}",
            }
            for kw in DEFAULT_STATIC_KEYWORDS
        ]
        return {
            "enabled": False,
            "source": "error",
            "keywords": result_kws,
            "updated_at": None,
            "error": str(e),
        }


# ── [Claude_Sonnet_4.6_Thinking_planning] v3.4.0: 高赞内容手动刷新 ──────────────
from web.high_likes_refresh import HighLikesRefresh
_high_likes_refresh = HighLikesRefresh(settings.default_output_dir / 'high_likes_refresh.json')

@app.post("/api/high-likes/refresh")
def refresh_high_likes():
    """异步采集并保留本次结果；不启动加工、发布或改变列表筛选。"""
    gate().require_running()
    def collect(progress):
        scripts_dir = str(settings.project_root / 'scripts')
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from monitor_channels import discover_high_like_videos
        return discover_high_like_videos(db, progress=progress)
    return _high_likes_refresh.start(collect, spawn_admitted)


@app.get("/api/high-likes/status")
def high_likes_refresh_status():
    """查询是否在运行及本次新增、零新增原因与素材去向。"""
    return _high_likes_refresh.status()


@app.get("/demo", response_class=HTMLResponse)
def get_interactive_demo():
    """[Gemini_3.5_Flash_planning] 返回交互式财经英文原声精读体验页 (Anduchencang Demo)"""
    from web.study_demo_html import HTML_CONTENT
    return HTML_CONTENT


# 全局 header 的独立扫描入口；沿用维护写请求准入，不触发完整流水线。
from web.console_header import router as console_header_router
app.include_router(console_header_router)

if __name__ == "__main__":
    import uvicorn
    # 端口选择规则：见 PORTS.md
    # 9100-9199 为本项目专属区间，避开 :8080（其他项目）等。端口为单一真相源 settings.dashboard_port，
    # 可经环境变量 DASHBOARD_PORT 覆盖（见 src/config/settings.py）。
    port = settings.dashboard_port
    host = settings.dashboard_bind_host
    display_host = f"[{host}]" if ":" in host else host
    print(f"\n\U0001f680 Video Pipeline Control Center → http://{display_host}:{port}\n")
    uvicorn.run(app, host=host, port=port, reload=False, proxy_headers=False)
