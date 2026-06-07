---
created_by: Gemini_3.1_Pro_High_planning
created_at: 2026-05-21T14:31:00+08:00
---

# Version History

| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 2.0.0 | 2026-06-07 | Claude_Sonnet_4.6_Thinking_planning | 记录 Gemini_3.5_Flash_planning 在 YouTube 插件中将 document 传入 injectStylesIntoShadow 导致 HierarchyRequestError 静默崩溃的 P0 问题 |
| 1.9.0 | 2026-06-07 | Gemini_3.5_Flash_planning    | 记录 Gemini_3.5_Flash_fast 在 YouTube 插件中直接向 innerHTML 写入导致 Trusted Types 限制拦截报错的问题 |
| 1.8.0 | 2026-06-07 | Gemini_3.5_Flash_planning    | 记录 Gemini_3.5_Flash_planning 在实现 yt-dlp curl 优化时产生 NameError 崩溃的问题 |
| 1.7.0 | 2026-06-01 | Gemini_3.5_Flash_planning    | 记录 Gemini_2.5_Flash_planning 因过度严格分离中英文输入导致中文安全审查漏检绕过问题 |
| 1.6.0 | 2026-05-27 | Gemini_3.5_Flash_planning    | 记录 Claude_Sonnet_4.6_Thinking_planning 正则漏配 live/ 及带参 URL 干扰裁剪问题 |
| 1.5.0 | 2026-05-27 | Gemini_3.1_Pro_High_planning | 记录 Gemini_3.5_Flash_planning TDD 假测试与嵌套事务冲突导致 OperationalError 问题 |
| 1.4.0 | 2026-05-27 | Unknown_Model_planning | 记录 Claude_Sonnet_4.6_Thinking_planning 优雅截断右倾偏斜及括号残留问题 |
| 1.3.0 | 2026-05-27 | Gemini_3.5_Flash_fast | 记录 Claude_Sonnet_4.6_Thinking_planning 黑名单机制导致手动加急视频静默失败的问题 |
| 1.2.0 | 2026-05-27 | Gemini_2.0_Flash_fast | 记录使用 nth-child 导致移动端表格布局脆弱的问题 |
| 1.1.0 | 2026-05-26 | Gemini_3.5_Flash_planning | 记录 Gemini_2.5_Pro 端口占用问题 |
| 1.0.0 | 2026-05-21 | Gemini_3.1_Pro_High_planning | 初始创建模型评估经验库 |

# Model Critique Log

## 对于【Gemini_3.1_Pro_High_planning】问题：
未有效识别底层翻译API（如基于页面的 deep-translator）被高频风控拦截时返回的 HTTP 500 Error HTML 页面内容。模型最初生成的异常捕获逻辑仅捕获了 Python 运行时异常，但未能过滤伪装成正常字符串返回 of "Error 500 / That's an error" 等报错文本，导致其直接被写入中文字幕并在渲染后输出，破坏了整条视频的观看体验。
**严重程度**：P1

对于【Gemini_3.5_Flash_planning】问题：1) TDD 测试假绿：在编写 `test_batch_insertion_and_cascade` 时，未实际执行批量插入并验证级联删除，仅断言方法存在，掩盖了深层崩溃；2) 隐式嵌套事务冲突：在 `database.py` 中手动执行 `BEGIN IMMEDIATE TRANSACTION;` 与 `sqlite3` 内置的事务机制产生冲突，容易引发 `sqlite3.OperationalError`；3) N+1 连接及锁争用：在 `batch_add_videos` 循环内部调用会开启新连接的方法 `is_blacklisted`，导致极高频率创建并竞争数据库连接。 严重程度：P1
4) NameError 崩溃：在 `pipeline_agent.py` 的 `download_video` 方法中，为 yt-dlp 引入 curl 外部下载器优化时，错误地使用了未定义的 `url` 变量，导致整个下载流程 NameError 崩溃。严重程度：P0

对于【Claude_Sonnet_4.6_Thinking_planning】问题：1) app.py并发场景下使用非原子查询判断任务状态导致并发启动多个处理进程; 2) 代码内联执行时未对外部输入使用JSON序列化，暴露注入风险; 3) telegram bot中使用了后端未定义/错误的查询标签名；4) 设计了黑名单墓碑机制以拦截已删除视频，但忽略了用户可能在 Telegram Bot 或 Web 端手动重新加急同一视频的情景，导致手动添加被黑名单拦截且 API 依然返回成功，造成静默失败。严重程度：P0/P1/P2
5) 在实现 `graceful_truncate_title` 优雅截断算法时，未对括号内辅助文本（如“尝试一下看看”、“Try It and See”）进行预处理过滤，导致封面展示多余噪声信息；且排序规则错误地采用了尾部优先（右倾偏斜）策略，导致丢弃了句首的核心主导半句（如“你越不关心”），仅截取了无完整语境语义的后半句（如“你就越快乐”），破坏了封面标题的逻辑完整性。严重程度：P1
6) 在 `telegram_bot.py` 中定义的 YouTube URL 匹配正则 `_YOUTUBE_RE` 仅匹配到视频 ID，且未支持直播回放 `live/` 路径。这导致了：a) live/ 路径直播归档 VOD 链接被完全忽略丢弃；b) URL 后面若携带其他查询参数（如 `&t=10s`, `&index=2`），其参数内容会残留并漏到 remaining_text 中，进而干扰裁剪提取逻辑 `parse_trim_params`，导致裁剪失败或获取到错误的时间范围。严重程度：P2

对于【Gemini_2.5_Pro_planning】问题：在重启 Video-precessing 的 Web 仪表盘服务时，未遵循项目规定的端口分配规则（见 PORTS.md），强行使用了已被 OptionSense 占用的 8080 端口，导致跨项目服务冲突。 严重程度：P1

对于【Gemini_2.0_Flash_fast / Gemini_2.5_Pro_planning】问题：在移动端响应式设计中，采用 `nth-child(n)` 伪类定位表格特定列。这种强耦合在 DOM 节点结构变动（如多选框列 of 显隐）时极易错位并导致手机视口排版崩塌。应当显式为单元格节点注入语义化 Class 类名（如 `.info-cell`, `.status-cell`），以提高响应式样式的鲁棒性。严重程度：P2



对于【微信视频号 Web 分类】问题：微信官方已经彻底移除了“视频分类”的下拉选择组件，全面转为根据视频描述（标题、描述文案、Hashtag）由平台算法进行自动归类。代码中强制寻找 UI 下拉框会导致超时失败。 严重程度：P1

对于【Gemini_2.5_Flash_planning】问题：
在 v2.11.0 中重构 Censor 审查输入时，过度严格地区分了中英文通道（仅将 zh_title 传入 zh_text，而将原始 title 传入 en_text）。由于手动添加、测试用例或尚未翻译完成的视频记录其 zh_title 为空，这导致原始中文标题被当作英文文本传入并完全跳过了中文违禁词/策略规则过滤，造成了严重的内容安全绕过隐患（并在运行 pytest 时导致 3 个 Censorship 整合测试全部失败）。应在 zh_title 为空但原始 title 含有中文时自动 fallback 检查。
**严重程度**：P1

## 对于【Gemini_3.5_Flash_fast】问题：
在 YouTube 像点赞/播放率指示条插件的实现中，直接向 `.innerHTML` 赋值拼装 HTML 字符串。由于 YouTube 网页启用了严格的 Trusted HTML (Trusted Types) 策略，任何未经受信任类型（Trusted Types）处理的原始 HTML 字符串写入均会被浏览器底层强行拦截并抛出 JavaScript Runtime Error。这导致在主页面上无法渲染指示条文本。应当完全使用标准的 DOM API（如 `document.createElement`, `.textContent`, `.appendChild`）来构建并挂载节点，以确保不受 Trusted Types 安全策略的影响。
**严重程度**：P1

## 对于【Gemini_3.5_Flash_planning】问题（YouTube 调用 injectStylesIntoShadow(document)）：
在实现 Light DOM 进度条渲染时，向 `injectStylesIntoShadow()` 传入了 `document` 对象。该函数内部直接调用 `shadowRoot.appendChild(style)`，而 `document.appendChild()` 在文档已有 `<html>` 根节点时会抛出 `HierarchyRequestError`。这个异常导致整个 `renderUI` 函数崩溃，且由于 `YT_RECEIVE_RATIO` 事件回调外没有 try/catch，错误被静默吐掉。结果：控制台完全无输出，表面看起来插件没有运行，极难定位。正确做法是：当 root 为 document 时应 append 到 `document.head` 或 `document.documentElement`，而非直接操作 document 节点本身。
**严重程度**：P0
