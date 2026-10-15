# 封面来源统一契约

用户已确认：贯通存储、投稿绑定、接口、管理后台、Telegram 回执；不改变默认封面的自动发布策略，不重发历史视频，不补发旧通知。

实现者：Codex。

- `cover_versions` 保存按规范 JSON 哈希标识的生成版本，包括生成来源、底图生成器、可获知的模型、接力/失败原因、质量回执和成图 SHA256。图片模型未知时留空，不把编排模型当图片模型。
- 队列完成时写入版本表及成图旁的 `_source.json`。上传前校验成图字节和版本身份，缺证据或不一致只记 unknown，不猜测。
- 上传器冻结 `submitted_cover.jpg` 和 `cover_binding.json`，实际上传该冻结文件；同一证据目录禁止替换为另一张图。提交回执包含封面版本和 SHA256。
- 受理事务绑定投稿尝试与封面；平台后续回查更换证据目录也不丢原投稿绑定。新增来源元数据错误不能抹掉已受理事实。
- `/api/videos`、`/api/published-videos` 返回同一 `cover_provenance`；封面接口提供投稿绑定的冻结图片，并核对哈希。未投稿显示当前生成版本，已投稿缺证据显示来源未核验。
- 桌面和手机的缩略图下显示来源；展开非模态详情可核对原因、版本、哈希。Escape 关闭并回到来源标签。
- Telegram 文字及审核视频附带相同来源信息；投递回执 `cover_context_json` 包含来源、投稿尝试、平台 ID、版本、哈希。投递 ACCEPTED/UNKNOWN/FAILED 与视频平台状态保持独立。
- 历史记录不回填、不通知；无需历史重发。隔离测试数据不进入生产业务库。

验收代码：`tests/unit/test_cover_provenance.py`、`tests/browser/test_cover_provenance_browser.py`，以及队列接力、微信受理恢复、Telegram、数据库切片回归。

范围限制：本次普通视频号队列是完整的来源展示入口；独立发布主体写入路径也保留绑定，但没有为独立英语世界/二创工作台新增页面。真实平台发布及真实 Telegram 发送未用于验收。

## 验证与运行采用

- 工作区回归：108 passed。
- 合并生产现有改动后的最终候选：109 passed；含真实 Chromium 1366px/390px 截图、键盘展开/Escape、投稿后换图、平台回查路径变化、切片隔离、默认封面仍可受理、缺失证据和 Telegram 超时回执。
- 最终证据：`/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-a5wsm0mk/receipt.json`、`pytest.xml`；截图在该目录 `sandbox/repo/output/test-evidence/cover-source/`。
- 生产组合源码：`/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/cover-provenance-combined-20261015`，保留线上已有未提交改动，不覆盖它们。
- 运行采用尚未完成：2026-10-15 本机维护检查为 RUNNING / UNKNOWN / safe=false；报告 LEGACY_WORKER 与仍在运行的 run_ready_publications.py。未绕过门禁重启，也未改变维护状态。
- 未进行真实 Telegram 发送、历史补发或任何视频发布操作。真实渠道回执需后续正常新任务产生，不能把隔离传输测试称为真实发送成功。
