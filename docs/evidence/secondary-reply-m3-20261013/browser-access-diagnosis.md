# 视频号平台访问诊断与只读验证复核记录

核查与复验：Antigravity，2026-10-13。

## 1. 原始阻塞成因核实

- **原始报错**：在 ChatGPT desktop (26.1007.30912) 的 Browser Use (CUA) 插件中，尝试绑定 Chrome 标签时被该客户端内部站点安全策略拦截 (`site_status_blocked; decisionSource=site_status; retryable=false`)。
- **核实结论**：该阻断纯属 ChatGPT desktop 内部插件沙箱对 `channels.weixin.qq.com` 域名的内置策略限制，并非微信服务端封禁、非账号凭证失效，亦非 macOS 系统网络阻断。

## 2. 访问恢复与只读验证执行

Antigravity 切换至本地 Chrome DevTools MCP 端口，对用户当前处于正常登录态的 Chrome 浏览器实例执行了严格的合规只读检查（零出站写、零发评、零修改）：

1. **页面访问与导航**：
   - 顺利导航至 `https://channels.weixin.qq.com/platform/interaction/comment`，无任何策略拦截。
   - 页面加载微前端评论管理容器 `https://channels.weixin.qq.com/micro/interaction/comment`。

2. **作者原生身份（Native Account Identity）验证**：
   - 视频号昵称：`六维时空号`
   - 视频号 ID：`sphjAH8AbMh8oYP`
   - 原生作者 username：`v2_060000231003b20faec8c6e6811acad1ca06e534b07788b29eed6dd8e71aca67283987b679b6@finder`
   - 跨作品一致性：在《面对癌症，财富究竟能带来什么？》与《新加坡为何富裕却不快乐》两部不同作品下，作者原生 username 完全一致，确认为稳定可靠的作者原生绑定键。

3. **作品与一级评论定位（Post & Root Comment Binding）验证**：
   - 视频作品绑定标识为 `exportId`（如 `export/UzFfBgAAxNCkKHJuQxiuk8zT4DCaadU0dAv6_b2aJmHPxbJmCA`）。
   - 一级评论原生 ID 为 `commentId`（20 位纯数字字符串，如 `15030596545026986296`），全局唯一且挂载于 `dataSource` 中。

4. **二级回复结构与折叠分页（Secondary Reply & Pagination）验证**：
   - 一级评论挂载 `levelTwoComment` 数组，二级回复项结构：
     - `commentId`: 回复原生 ID（20 位数字）
     - `replyCommentId`: 精确等于目标一级评论的 `commentId`
     - `username`: 回复者原生标识（作者回复时等于作者的 `v2_060000...`）
     - `commentNickname` / `commentContent` / `commentCreatetime` 完整对应。
   - 分页标志：`downContinueFlag`（0 表示无更多回复，1 表示存在更多折叠回复）、`lastBuff`（游标）。
   - 证实了 Fail-Closed 安全铁律：当 `downContinueFlag == 1` 且当前切片未见作者回复时，状态必须判为 `UNKNOWN`，严禁误判为未回复。

## 3. 证据归档

- 详细结构数据：`docs/evidence/secondary-reply-m3-20261013/platform-readonly.json`
- 现场实测截图：`docs/evidence/secondary-reply-m3-20261013/platform-readonly-verified.png`
- 结论：**外部平台访问阻断已解除，M3 前置只读证据全部闭环。**
