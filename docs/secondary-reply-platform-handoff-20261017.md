# 视频号真实验证交接：宿主访问仍受阻

记录：Codex，2026-10-17。此文件供用户自行处理或交给其选择的执行者；没有向其他执行者发送消息。

## 本次实际结果

工作区 `/Users/ryusei/.codex/worktrees/c446/Video-precessing`，分支 `task/secondary-reply-m0-m2`。检查时 HEAD 为 `0930157`，工作区干净；业务代码基线 `34ad0bb`，已有隔离回归 198 passed，证据由根目录 candidate.json 索引。本次只更新交接文档，不重跑已通过的测试。

2026-10-17 通过宿主 CUA 对 Chrome 已存在的视频号标签执行一次 getTab，页面内容读取前即失败。关键原始错误如下：

```text
Browser Use rejected this action due to browser security policy.
Reason: The site-safety policy blocks this action; no user permission prompt or Auto-review was attempted.
Browser use could not acquire authority to observe page content.
The site safety gate did not grant access for https://channels.weixin.qq.com.
```

工具同时明确禁止以间接执行、raw CDP、其他浏览器表面等绕过。因此已停止，不重试、不换通道。此次没有拿到真实页面内容，不能判断当前微信登录状态或账号可用性。此阻断发生在宿主授权层，不是自动审批拒绝，也没有可供用户批准的弹窗。

历史 browser-access-diagnosis.md 中 DevTools 可访问的记录不能证明本次宿主 CUA 已恢复，也不能证明当前代码正式适配器的验收完成。当前继续保持 ENGINEERING_REVIEW_CANDIDATE_PLATFORM_PENDING，m3_ready=false。

## 恢复途径与边界

官方浏览器文档提供 Settings → Computer Use → 对应浏览器 Manage 的站点许可管理，但这只处理站点许可。官方配置文档明确 access=allow 仍需继续经过正常审批与策略检查；本次错误不能据此推断为用户黑名单，也不能承诺修改 allow 能解除。

- 浏览器许可说明：https://learn.chatgpt.com/docs/chrome-extension
- 配置语义：https://learn.chatgpt.com/docs/config-file/config-reference

未查到可由本项目解除 site-safety gate 的受支持设置。若请求宿主维护方核查，提供上面的域名、日期、错误原文和“仅只读校准自有作品评论”的用途即可，不提供登录凭据。只有宿主允许访问后才在本会话恢复浏览器验证；用户自行处理所得证据可供后续代码审查，但不改写本会话的访问结论。

## 交接验收目标（不重新规划，不包含发送授权）

在执行环境本身允许访问的前提下，沿用上述工作区和既定单账号、单条、人工审批范围，集中完成：

1. 刷新原生作者身份、目标 exportId、一级 commentId 及完整原文；历史候选在 `docs/evidence/secondary-reply-review-20261017/human-review-package.json`，不能直接当作新鲜事实。
2. 校准目标父评论内真实回复控件、编辑器和提交控件的唯一绑定。记录脱敏 DOM/截图和选择器依据；验证其他父评论或同文评论不会误选。不得点击提交或触发 create_comment。无法唯一定位则明确失败，不按序号猜测。
3. 用正式适配器的只读会话验证原生作者已回复、完整分页后的未回复，以及分页未完成时 UNKNOWN；全新会话重读仍能绑定相同作品与父评论。提供调用入口、代码提交、时间、结构化结果与脱敏证据。手写探针或截图不能替代正式适配器结果。
4. 若需修复，保持未知状态拒绝发送和只读写请求拦截，补针对性回归并通过隔离测试。将新的源码提交与实测证据绑定，明确没有真实发送。
5. 汇总为一份单条试发审核包：目标身份与原文、最终中英回复及正文哈希、最新只读预检、代码版本、测试证据、单条执行及结果不明时仅对账的流程。交用户审核前不导入发送审批、不打开生产发送开关、不发送、不启用自动任务。

本次只能交付工程审核材料及此交接单；真实控件校准、正式适配器真实只读验证、最终单条试发准入均未完成。
