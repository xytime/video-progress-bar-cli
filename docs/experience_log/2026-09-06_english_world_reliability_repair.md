# 2026-09-06 英语世界日更中断：调查与修复

| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-06 | Codex | 记录事故证据、六项修复、验证边界及存量成片恢复入口。 |

## 已确认的故障链

所有时间均为 Asia/Shanghai；数据库时间戳为 UTC。

1. **05:30 的生产实际触发了。** `output/english_world_daily/run_2026-09-06_053005.log` 记录来源 `eF5tl9SVZhY` 的制作。生产代理把含 `$2`、`$250` 的正文嵌入 shell 双引号 `python -c`，shell 展开位置参数后，正文中的金额消失，逐词时间线仍保留金额。渲染器报 `timeline='$2', page='a'`。这是输入序列化损坏，不能据此认定原视频不合格。
2. **金额修复后还有排印撇号兼容缺陷。** 旧比较器把 `here’s` 变成 `heres`，而 `here's` 保留撇号。模型和渲染现在共用归一化函数。对原始事件数据恢复两个金额后，145 个时间词与 145 个红线坐标全部匹配；没有放松真实缺词检查。
3. **09:15 监控误认早班缺席。** 已安装 LaunchAgent 是 05:30/16:30，监控代码与仓库模板仍以 07:00/16:30 为准，因而又发起了制作。
4. **补跑的成片已经成功制作。** `iQHP4VBYhdM`，标题“91 岁徒步者的坚持”，30.867 秒。09:28:25 建立审核项 `eb79ead3978e4560ba8080725a48414f`；09:28:31 第一条 Telegram 投稿前审计通知发生 `SSLError`，上传器尚未被调用。当前账本仍是 `READY_FOR_REVIEW`，投稿尝试为 0，原生作品 ID 为空。
5. **旧交付逻辑无法续接。** 审核项在通知前落库，重进后 `_created_now=False`，自动提交被禁止；宿主的同源保护又在通知器之前直接跳过。通知失败被错误归类为 `FAILED_COORDINATOR`，失败通知还声称没有成片。

## 修复后的行为

- **文本契约：** `StudyCardContent.from_mapping` 在昂贵富化/渲染前检查正文与逐词内容；模型与渲染兼容 Unicode 撇号。生产提示要求安全 JSON/heredoc 写法，并仅允许同源序列化损坏修复后重新过全部门禁。
- **交付恢复：** 新审核项持久化 `delivery_policy` 和 QA 报告路径。通知步骤先原子领取再发送；已接受步骤复用 message ID，确定未发出的建连超时可续接，`UNKNOWN/IN_FLIGHT` 不盲重发。宿主只允许相同完整包指纹续接，同源的其他成片仍受保护。日更优先续接过去 24 小时未完成的新协议自动交付请求，不重新调用生产代理。暂停发布时，READY 意图也不会因通知已发送而丢失。
- **投稿防重：** 自动意图只消费 READY 或已批准项，SUBMITTING 和终态仅回报事实。原有原子投稿领取、公共窗口、内容审查和原生 ID 规则继续生效。最终 QA 在投稿领取前复核，失败不消耗新的投稿尝试。
- **调度：** `ENGLISH_WORLD_DAILY_SLOTS=05:30,16:30` 为安装与监控的共用配置；监控发现已安装 plist 与配置不符时禁止错误补跑。安装器同时核验实际文件的时刻和运行路径。本机实际 plist 已匹配，无需重新启动正在使用的服务。
- **失败分类：** 新请求分别记录来源质量与内部/通路故障。内部渲染、正文序列化故障不再要求淘汰来源七天。今天早班请求已补充逐来源分类，保留原始副本，`eF5tl9SVZhY` 已退出错误排除名单。
- **QA 指纹：** MP4、manifest、timeline 三份文件在音频 QA 前后计算 SHA256；记录请求、宿主交付、最终投稿均复核。旧的仅绑定路径的 PASS 必须重新质检，不能补造指纹后当作有效 QA。
- **状态证据：** 每个交付节点记录成片、通知和平台状态；完成通知失败保留已记录的投稿事实。监控能识别成片就绪但宿主交付中断，失败通知不再推断“无成片/未投稿”。

依赖保持单向：`scripts → delivery_progress → db / telegram_delivery → config`；`scripts → qa_integrity → package_integrity`；`models / template_a → text_normalization`；`installer / monitor → daily_schedule → config`。

## SSL 调查边界

旧通知适配器只保存了 `SSLError` 类名，底层异常链已丢失，无法事后确定是证书、握手 EOF 还是中间通路瞬断。不能把它猜成代码证书配置错误。

本次核验 macOS HTTP/HTTPS/SOCKS 系统代理均关闭；项目 venv 对 Telegram 公共入口的 GET、POST、GET 连续返回 HTTP 200，YouTube HTTPS 也返回 200。探测没有携带 Bot 凭据、没有发送消息，因而不代表 Bot API 投递成功。未修改代理、DNS、TLS 证书校验或网络配置。

适配器现在保存不含 URL/token 的底层异常类别链，只对 requests 明确保证未发送的 `ConnectTimeout` 最多重试三次；附件每次回卷，读超时和 SSL 不确定结果不盲重发。

## 实际产物与验证

- 今日已有成片重新执行本地 Whisper small QA：**PASS**，末词 `Woo!` 完整，`trailing_words=[]`，输出 30.867 秒。新报告为 `output/study_cards/2026-09-06/iQHP4VBYhdM/qa/final_audio_qa_fingerprinted.json`，标准报告已更新为此次真实执行结果。
- 成片 SHA256：`fc0998790f6e8ea56775c7fde9ebf8f8d3a3ee8c285c7c29c69ca637be5ffccb`。完整现有投稿包也通过指纹预检，复用原审核 ID，没有重新调用封面供应商。
- 损坏来源的修正输入单独保存在 `output/study_cards/2026-09-06/eF5tl9SVZhY/timeline_text_repaired.json`，原始损坏时间线保留。只验证模型与静态红线映射，没有额外生产另一条成片。
- 事故原始请求/回执、旧 QA、公共 HTTPS 探测和恢复预检保存在 `output/english_world_daily/incident_2026-09-06/`。原补跑回执补记为 `INCOMPLETE / QA_PASSED / AUDIT_NOTIFICATION_UNKNOWN`，明确这是根据现有证据修正状态，不是新 API 回执。
- **219 项测试、20 项子测试全部通过**，覆盖整个英语世界模块、学习卡、音频 QA、词汇富化、Telegram bot 与发布窗口调度；全部使用本地文件/临时数据库和替代发送器。检查安装脚本语法、plist 和 diff 空白错误。

## 存量包的恢复边界

今天这条旧审核项没有持久自动交付意图，本次修复没有给历史项自动新增发布授权，也没有发送 Telegram 或提交视频号/抖音。

新协议包可以使用 `scripts/run_english_world_daily.py --resume-delivery-request <项目日志目录中的具名.delivery-request.json>`，该入口持有原日更锁，完全跳过生产代理，只消费原包；通知结果未知时仍停止。不能通过该入口把另一条同源视频或旧的未知投稿重新发送。

今天的旧包已达到可复核、可交付的状态。后续若明确要求恢复外部交付，应使用原审核项及其完整包，先处理旧审计通知的不确定状态，再走既有具名审核/投稿入口；不应重做视频或清空来源保护。
