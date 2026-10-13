# 视频号 Browser Use 访问诊断与恢复交接

核查：Codex，2026-10-13。仅只读检查配置和客户端错误映射；未修改安全策略或尝试绕过。

## 已确认

- 桌面应用 `/Applications/ChatGPT.app` 版本 26.1007.30912，build 20156。
- 本地 `~/.codex/config.toml` 的 `[browser_use.origins."https://channels.weixin.qq.com"]` 已为 `access = "allow"`。
- 已安装官方 Browser 插件 `browser-service.mjs` 和 `browser-client.mjs` 的错误映射将原始报错对应到 `site_status_blocked`，`decisionSource: site_status`，`retryable: false`。
- `persisted_user_denied`（用户保存的拒绝）和 `navigation_url_policy_blocked`（浏览器 URL 策略）是不同错误类型。本次报错不是这两者。
- 原始调用在绑定现有视频号登录页标签时失败，尚未读取网页内容；未触发用户许可或 Auto-review。

## 尚不能确认

站点为什么被此安全检查判为 blocked、是否误判、是否客户端或服务策略缺陷，以及何时解除。现有信息不足以宣称腾讯封禁、登录过期或组织管理员拒绝。没有找到官方提供的本地强制解除此错误的设置。

## 支持的恢复路径

1. 在应用输入 `/feedback`，提交下方最小诊断；请求支持确认 channels.weixin.qq.com 的 site_status 判定、是否误判、解除条件及工单编号。当前未自动提交任何反馈或日志。
2. 若支持指向组织管理策略，由组织管理员按官方 Browser Use 管理要求处理；不要自行删除管理配置。
3. 若支持指向已修复的客户端问题，按官方发布渠道更新并重启应用；更新和重启本身不是解除证明。不要清除微信登录态、开启全局 CDP 或修改插件代码来绕过。
4. 支持确认恢复或有关配置正式修复后，在本线程用原 Browser Use 通道执行一次只读验证。能读取真实页面才算访问恢复；之后继续当前账号身份、评论定位、分页完整性验证，无需重新规划或重复只读授权。

## 可复制反馈

在 ChatGPT desktop 26.1007.30912 (build 20156) 中，Browser Use 能列出 Chrome 标签，但绑定已有 https://channels.weixin.qq.com/login.html 标签被拒绝。用户已明确授权只读检查，配置中的该 origin 已设 access="allow"。

错误：Browser Use rejected this action due to browser security policy. Reason: The site-safety policy blocks this action; no user permission prompt or Auto-review was attempted.

安装包对应错误类型：site_status_blocked；decisionSource=site_status；retryable=false。

任务聊天 ID：01a12e99-2fe0-7a00-b669-cff624c44f87。

请确认该站点的安全分类是否误判，提供受支持的恢复方式及解除条件。目标仅为视频号评论区的真实只读验收，不发送评论、不上传、不导出认证数据。请勿仅建议增加 origin allow，该配置已存在。未经核对不附完整日志、Cookie、Token 或浏览器存储。

## 官方参考

- https://learn.chatgpt.com/docs/config-file/config-reference （allow 不覆盖正常审批和安全检查）
- https://learn.chatgpt.com/docs/browser （站点权限和管理控制）
- https://learn.chatgpt.com/docs/chrome-extension （/feedback 及附聊天 ID 的支持入口）
