# 视频号作者评论浏览器适配器安全合同

状态：本地隔离实现与夹具验收完成；真实视频号平台 schema **尚未只读校准**。在完成校准前，未知 DOM 或 API 结构必须 fail-closed，不能把夹具合同宣称为线上已验证。

## 已实现的提交边界

- 只接受平台原生 `platform_post_id`，并限制为已校准的 ASCII ID 字符集。作品卡片必须通过 `data-object-id`、`data-post-id` 或 `data-id` 精确且唯一匹配；禁止标题、列表顺序、日期或第一项回退。
- 点击卡片后，详情区必须以唯一 `data-current-object-id` 回读同一个原生 ID；填写完成后、持久化提交意图前还要再次核验。使用精确属性 locator，禁止持有会在 DOM 重排后改绑其他作品的 `nth()` locator。
- 评论列表必须明确携带 `data-comments-complete="true"`。结构缺失、目标歧义、作者节点缺少原生评论 ID 均在写入前停止。
- live 模式必须提供 `before_submit()`。回调只有在持久化提交意图后返回 `True`，按钮才可点击；缺失、异常或非 `True` 均停止。
- `verify_only=True` 只读取目标详情和已有作者评论，不点击“写评论”、不填充输入框、不点击提交。
- 请求与响应监听只在提交意图持久化后安装。请求必须是同 origin、精确路径 `/cgi-bin/mmfinderassistant-bin/comment/create`、POST、同一 `objectId` 和完整规范化正文；响应还必须属于该提交窗口内捕获的同一个 Playwright `Request` 对象。预点击请求的延迟响应、列表、读取、跨 origin、无关 POST 和正文不一致响应全部忽略。
- 成功必须同时满足：平台明确 `errCode == 0`；响应回读同一作品 ID 与非空评论 ID；DOM 出现同一评论 ID、`author` 身份及完整规范化正文。任一受理后回读缺口均为 `UNCERTAIN`。
- 只有严格关联响应携带明确数字且非零的 `errCode` 时，才可把平台拒绝返回 `FAILED`。缺字段、非数字或未知 schema 都是 `UNCERTAIN`；一旦可能点击且结果未确认，调用方不得普通重发。
- 每次尝试创建带 UTC 微秒与 UUID 的独立目录；截图和 `receipt.json` 只创建一次，不覆盖既有证据。

## 会话互斥

共享锁从 storage-state 的规范化绝对路径派生为 `.<state-name>.browser.lock`。评论器使用有界非阻塞获取；锁忙在打开浏览器前返回可识别 `FAILED`。持锁进程崩溃后由内核释放 `flock`。

上传器与保活器仅在 `settings.enable_wechat_comment_interaction=true` 时启用同一把锁，并覆盖各自完整浏览器会话；默认关闭时不改变既有生产行为。

## 真实平台启用前必须校准

1. 在明确授权的只读会话中确认作品卡片和当前详情的原生 ID 属性；不得用标题或索引替代。
2. 确认评论分页/加载完成的客观标记，以及作者身份和原生评论 ID 的 DOM 属性。
3. 通过浏览器开发者证据确认真实提交 endpoint、请求字段、受理字段和评论 ID 字段；不能从相似接口名称推断。
4. 将已确认 schema 固化为新夹具和隔离 Chromium 测试后，才可考虑启用特性开关。
5. 校准不得发送评论；真实提交仍需另行明确授权及状态机持久化 callback。
