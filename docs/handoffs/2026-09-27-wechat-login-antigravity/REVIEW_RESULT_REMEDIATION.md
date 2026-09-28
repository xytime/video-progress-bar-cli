# 整改候选独立审查

审查者：Codex。开发执行：Antigravity。用户已授权审查通过后的上线。

## 候选 1：REQUEST_CHANGES

- 提交：`548a243beaadb0203519b559bdee63cd5120dae3`。
- 此提交不获上线、生产会话替换或重启放行。
- 已向正在执行的 Antigravity CLI 会话发送具体整改要求，继续开发。

### 阻断项

1. `wechat_uploader._wait_and_save_login` 仍仅等待 URL，未验证发布控件、未验证独立新上下文复用就更新授权并通知；原子保存失败回退直接覆盖旧 state。`_stamp_login_success` 元数据失败仍回退更新 legacy marker。失败被写成成功。
2. `wechat_auth_state.evaluate_wechat_session_status` 对缺失验证、陈旧验证和 `INVALID_ORIGIN` 可返回绿色；无授权 marker 但已验证会话被武断判断未授权；网络超时被无依据描述为不影响会话。
3. 元数据路径将 `wechat.json` 和 `wechat_state.json` 映射到同名文件，身份只记录 basename；任意自定义 state 会继承/改写同目录生产 marker/flags。原子 replace 未保护读改写并发。授权事件伪造保活时间。
4. 失败记录含原始异常/完整 URL 的自由文本，读取未验证时间戳范围或记录身份。只截断字符串不构成凭证脱敏。
5. 保活来源只检查 hostname，控件接受泛化 file input/发表按钮；跳转后及保存前没有重新核验官方 HTTPS 源和发布页，可能保存失效/错误页面。失败分类不准确。
6. 报告未覆盖实际调度开关、下次检查、自动尝试及锁等待；错误来源浏览器测试允许 `NETWORK_TIMEOUT` 替代，证据不足。

### 下一验收阶段

先修正并提交精确候选、差异与测试回执，由 Codex 重新独立审查。代码通过后可签发明确范围的真实会话验证放行；真实平台验证及独立复用通过后，才签发生产采用放行。上线前再次检查流水线空闲，保护主目录其他任务的未提交改动，最后核实新进程与实际运行结果。

## 候选 3：代码 PASS；仅放行受锁保护的真实登录验收

- 冻结提交：`3054114c91c636fd5833c693c13bd82f015016d3`，基线 `aa58c8068951d6ec941d63334b55a7b042ae4ae0`。
- Codex 独立单元回执 `/private/tmp/video-pytest-067ltdwu`：159 passed、20 subtests passed、2 warnings；边界探针与 pytest 均退出 0。
- Codex 独立浏览器回执 `/private/tmp/video-pytest-0fvnvevu`：18 passed；新增管理页 case 因测试 Cookie 格式无效失败，修正为标准空白状态后在 `/private/tmp/video-pytest-yc2i9ey0` 独立补验 1 passed、7 deselected。合计 19 个浏览器场景通过，分别绑定回执，不声称单次全通过。
- 八个业务文件与 067ltdwu 成功快照逐字一致：uploader、keepalive、独立 verifier、bot formatter/telegram_bot、auth_state/page_contract、web app。最后变更只修正管理页测试状态构造。
- 已核查旧失败不报绿、严格官方来源与发布控件、状态身份和原子写入、授权后新上下文复用、过期 flag 文案、管理页 DOM 异常失败，以及 29 秒迟到允许后及时检查。
- 仅放行 Antigravity 使用已审候选执行有界真实验收：生产规范 state 路径的 WeChatSessionLock、旧会话只读验证、空白自定义会话桌面快捷授权、实际授权元数据及独立新上下文复用。执行脚本本身须经 Codex 核查正确的生产路径、失败非零返回、已启用桌面开关与脱敏输出。
- 仍未放行合入主干、推送、生产凭据替换或服务重启；真实验收通过后另记生产 PASS。禁止视频上传、评论/联系人消息、强制修改阈值、历史续投或改写 Codex 审查结论。
- 11:41 生产仍有 1 个 TRANSCRIBING/FFmpeg 任务；上线前必须重新确认空闲，保留主干其他任务提交及 topic_clues 未跟踪工作。回滚使用明确集成提交的 revert，禁止 reset --hard。
