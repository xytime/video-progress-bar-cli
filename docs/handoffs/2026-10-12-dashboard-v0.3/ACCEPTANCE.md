# 管理后台 v0.3 开发与上线验收

责任记录：Codex；2026-10-12。用户已确认 v0.3 并授权上线 A；真实搜索 B 继续禁止。此记录随实际回读更新，未完成项不当作上线成功。

## 本次改变

五区共享导航与只读工作总览；关键词入口同时位于选题中心与首页。保留商品、专题草稿，原列表操作和筛选 URL；运维、频道和手动入队回归各自工作区。生产未提交的词汇及商品等工作通过临时三方整合保留。

## 隔离证据

- 整合副本真实 Chromium：93 passed。覆盖总览与列表数字、首屏、深链/刷新/前进后退、失效入口、旧数据与恢复、三主题文本对比度、较大字号、390/1024/1366/1920视口及200%等效 CSS 视口重排、44px 导航目标、Escape/focus、商品/专题保存与草稿、手动入队和旧列表操作。
- 完整单元回归：3,327 passed、30 subtests passed。切换检查发现旧 SIGTERM 覆盖服务器退出的缺陷；新版本保留 Uvicorn 信号处理，补充真实自进程 SIGTERM 与维护生命周期测试，36 passed。完整回归基于修复前整合副本；修复后仅重验受影响的维护、退出与候选故障边界。
- 静态 strict 审查报告两处既有动态绑定误报：manual-products-retry 在 manual_products.js 中绑定 load；btn-confirm-delete 在打开确认框时绑定，并校验确认码。两个真实行为均有浏览器回归。没有为清除扫描提示改写业务操作。
- 未执行物理手机/屏幕阅读器测试；200%为等效 CSS 视口重排，不宣称全部浏览器真实缩放矩阵。项目没有 DESIGN.md 官方 lint 工具；保留现有 Markdown 设计文档及单一运行主题，没有引入生成 token 工程。

证据在 evidence/，每个测试回执绑定沙盒副本、运行参数和源文件摘要。隔离沙盒验证外部读写、网络和信号拒绝。

## 生产采用

2026-10-12 14:10（北京时间）已采用到生产 main，运行代码提交 `1b987ea`（包含 `3c65563` 首页实现）。真实地址为 http://localhost:9100/ ，关键词入口为 http://localhost:9100/topic-candidates 。维护验收后正常服务 PID 32397，cwd 为生产目录，源码摘要绑定 `c434f13c86c9e61afe10c854afcb70c70775d7651091f121a74e15eded9afd7a`（包括原有生产未提交 Python 工作）。

- 七项原有已跟踪未提交改动保留；涉及相同文件的三项通过预先测试的三方整合保留，未提交业务资产不纳入本次提交。SQLite 一致性备份完整性通过，恢复后 quick_check=ok，processed_videos=5693、blacklisted_videos=73，与切换前一致。
- 维护期间冻结本项目九条 cron 和六个非 UI launchd 来源；正常关闭旧进程后采用代码。发现遗留空闲 ready worker，独立核对心跳、账本、业务锁后 SIGTERM 退出，没有删除业务记录或强制杀死工作任务。
- 新 UI 在维护模式下保存“AI产业与算力”专题，编辑查询为 `AI infrastructure investment`，暂停；刷新和重启后持久化成功。该专题作为验收样例保留为已暂停，未创建候选或视频。
- 新版维护 stop-ui 通过完整来源/锁/PID 检查，正常 SIGTERM 停止 PID 25720；重新启动 PID 32397，角色归属与源码摘要一致。最后 fresh inspection safe=true，resume 将维护版本 1 切到版本 2 RUNNING。
- 原 crontab 逐字节恢复，六个非 UI launchd 来源重新载入，原 plist 文件保持不变。AI cover 与历史 forced-recovery 的本次载入抑制 RunAtLoad，保留原周期/日历，避免集中补跑和历史单次任务重放；未手动补跑错过的 14:00 任务。UI、ready worker、Bot 分别恢复；ready worker PID 33005，Bot PID 33284。既有生产队列已按原策略接纳一项工作，无新增人工验收视频。
- localhost、127.0.0.1：首页、关键词页面均 200；维护期搜索/模式变更返回 MAINTENANCE，恢复 RUNNING 后两者返回 SEARCH_CLOSED。mode=OFF、搜索任务=0、搜索计数=0、详情计数=0。真实 LAN 对端请求关键词页面及 API 均 403。
- 配置仍为 topic_search_enabled=false、topic_quota_verified=false、topic_quota_project 为空；其余业务保护快照未改变。**生产凭据项目/共享调用者的配额证据未闭环，真实搜索 B 继续禁止。**
- 最终真实浏览器从总览导航到关键词页并返回，无 console error；截图见 evidence/production-home.jpg、production-keywords.jpg。首页数字为实际快照，不代表历史异常已修复或本地受理已公开发布。

脱敏回执见 evidence/production-*.json。数据库、原 crontab、完整进程检查、脏文件和部署备份位于本机私有目录 `~/Library/Application Support/VideoProcessing/deployments/dashboard-v03-20261012`，不提交数据库或凭据。

操作兼容性备注：本机 launchctl 输出使用 enabled/disabled 文本，本次采用协议允许的文件回执绑定逐项真实 launchd 回读，不使用仅识别布尔 true 的 launchd-disabled 快捷证据类型。首次冷启动超过 vpanel 的十秒等待，已独立回读监听与健康状态；后续受控重启命令正常成功。

## 交付验收

1. 打开首页，确认五区导航、需关注、当前任务和常用入口的层级。
2. 点“关键词追踪”，确认能找到已暂停的验收专题，搜索显示尚未开放。
3. 进入生产队列、发布记录、商品挂载，确认原业务操作仍可找到。

本次交付为已上线的后台与管理入口；用户验收意见待回收。真实搜索另行批准。
