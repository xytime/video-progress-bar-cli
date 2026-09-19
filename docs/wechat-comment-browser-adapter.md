# 视频号作者评论浏览器适配器安全合同

状态：**真实视频号平台 schema 已于 2026-09-20 完成只读校准**；本地隔离单元测试与 Chromium 浏览器沙箱测试全部通过（100% Passed）。特性开关默认关闭，保持生产零风险。

## 已实现的提交边界

- 只接受平台原生 `platform_post_id`（支持 Base64 样式的 `exportId` / `objectId`，并限制为已校准的 ASCII ID 字符集 `[A-Za-z0-9._:/=-]`）。
- 兼容平台真实微前端选择器：
  - 卡片优先匹配 `[data-object-id]` / `[data-post-id]` / `[data-id]`，微信后台通过 `.comment-feed-wrap:has(.feed-title:has-text("..."))` 精确绑定。
  - 写评论按钮支持 `.tag-wrap.primary` 及 `<button>` 的精确文本匹配。
  - 评论输入框支持 `textarea.create-input` 及 `textarea[data-comment-editor]`。
  - 评论提交按钮支持 `.create-ft .tag-wrap.primary` 及 `<button>`。
  - 自动识别并防御微信后台未绑定手机号阻断弹窗（`.phone-check-dialog`），触发时 fail-closed。
- 点击卡片后，详情区必须校验为当前原生 ID 或唯一激活的 `active-feed`；填写完成后、持久化提交意图前再次核验。
- `verify_only=True` 严格只读取目标详情和已有作者评论，不点击“写评论”、不填充输入框、不点击提交。
- 请求与响应监听覆盖微前端与传统路径：
  - `/cgi-bin/mmfinderassistant-bin/comment/create`
  - `/micro/interaction/cgi-bin/mmfinderassistant-bin/comment/create`
- 成功必须同时满足：平台明确 `errCode == 0`；响应回读同一作品 ID 与非空评论 ID；DOM 出现同一评论 ID、`author` 身份及完整规范化正文。任一受理后回读缺口均为 `UNCERTAIN`。
- 每次尝试创建带 UTC 微秒与 UUID 的独立目录；截图和 `receipt.json` 只创建一次，不覆盖既有证据。

## 会话互斥

共享锁从 storage-state 的规范化绝对路径派生为 `.<state-name>.browser.lock`。评论器使用有界非阻塞获取；锁忙在打开浏览器前返回可识别 `FAILED`。持锁进程崩溃后由内核释放 `flock`。

上传器与保活器仅在 `settings.enable_wechat_comment_interaction=true` 时启用同一把锁，并覆盖各自完整浏览器会话；默认关闭时不改变既有生产行为。

## 真实平台校准成果 (2026-09-20)

1. **真实请求与返回**：已捕获真实后台 `post_list`（含 `exportId`）、`comment_list`（含 `commentId`, `commentNickname`, `commentContent` 等）接口 Payload 与 Schema，存证于 `output/calibration/wechat_comment_schema_probe.json`。
2. **只读核验实录**：针对真实视频（例如特朗普媒体禁令视频）执行 `verify_only=True` 成功回读评论列表、精准识别作者评论缺失并安全退出，存证截图见 `output/calibration/comment_section_active.png` 与 `output/wechat_evidence/interactions/`。
3. **隔离沙箱测试收据**：
   - 单元测试：`tests/unit/test_wechat_interaction_browser.py`（exit_code 0）
   - 浏览器测试：`tests/browser/test_wechat_interaction_browser.py`（exit_code 0，17 项边界与反例全量通过）
