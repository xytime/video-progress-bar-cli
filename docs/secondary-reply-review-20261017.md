# 视频号二级回复：人工审核包 (Milestone 3 Canary Ready)

编制：Codex，2026-10-17。范围：已授权的单账号、人工确认正文、单条试运行路径。

## 当前裁定

- 状态：**M3_CANARY_REVIEW_PACKAGE_READY** (m3_ready=true)
- 真实平台只读校准与状态核验：**已完成** (`output/secondary_reply_evidence/20261017_075912_84a34013/platform_verification.json`)
- 隔离回归：**221 passed**, 0 failed, 0 skipped (耗时 248.54s)
- 受测快照哈希：`ae264352be0704223b13fad60c842256802e18ff52219ad73ee58aff173fb16e` (687 个源码/脚本/测试/配置文件 0 不匹配)
- 发送开关：默认代码与运行环境严格保持 `false` (`enable_wechat_secondary_reply=false`, `enable_wechat_secondary_reply_live_submission=false`)
- 真实出站写操作：**零次** (网络前拦截守卫与路由硬阻断 `**/comment/create_comment*` 100% 生效)

## 本轮工作与修复总结

1. **真实平台只读控件校准 (R1 / M1)**:
   - 解决嵌套结构 `.action-item > .action-icon` 触发的选择器联合碰撞 (count=2)，修复为优先级候选独立求值。
   - 确定并校准真实微信 DOM 控件选择器：
     - 回复触发图标：`.action-icon.weui-icon-outlined-comment`
     - 回复编辑器：`textarea[placeholder*='回复'], textarea[data-comment-editor], textarea.weui-desktop-form__textarea` (及 `.edit-area`)
     - 提交按钮：`.create-ft .tag-wrap.primary, .weui-desktop-btn_primary:text-is('评论')` (及 `.weui-desktop-btn_primary`)
   - 实现可复用的只读命令行工具 `scripts/wechat_secondary_reply.py verify-platform` / `calibrate-dom`，未来 Agent 可直接通过 CLI 进行只读校准与回验。

2. **正式适配器真实平台只读验证 (R2 / M2)**:
   - 原生作者身份核验：`localStorage.getItem('finder_username')` 与 DOM `.account-info .name` 成功匹配 `v2_060000231003b20faec8c6e6811acad1ca06e534b07788b29eed6dd8e71aca67283987b679b6@finder` 与 `六维时空号` (`identity_verified: true`)。
   - 目标作品与父评论新鲜度比对：成功定位目标视频 `export/UzFfBgAAxOClNFsoN2Spk8zT4DCaVikQXENps3YeyGFwg_SlGQ`，抓取父评论 `15031175812304083586` 163 字符原文，全文无差匹配 (`text_matched: true`, `fresh: true`)。
   - 三态状态判定：目标父评论 `downContinueFlag == 0`，作者尚未回复，准确分类为 `NOT_REPLIED`。
   - 独立全新会话回读一致：多会话执行 `author_reply_state` 与 `lookup_reply` 均一致返回 `NOT_REPLIED` 与 `found=False`。
   - 结构化证据落盘：脱敏证据 `platform_verification.json` 与 1920x1080 截图保存在 `output/secondary_reply_evidence/20261017_075912_84a34013/`。

3. **目标回归测试与哈希同步 (R3 / M3)**:
   - 新增 `tests/browser/test_secondary_reply_adapter_adversarial.py` (覆盖选择器联合碰撞修复、三态回复分类、Fail-Closed 阻断与端到端 BrowserSecondaryReplyPlatform 校准)。
   - 新增 `tests/unit/test_secondary_reply_cli_real_entry.py` (覆盖 `verify-platform` / `calibrate-dom` 参数校验、契约结构与零写验证)。
   - 隔离测试套件执行通过率 100% (221 passed, 0 failed)。
   - 源码清单 SHA256 同步至 `candidate.json` 与 `source-verification.json`。

## 单条 Canary 审核包详情

- **作者账号**: `sphjAH8AbMh8oYP` (`六维时空号`, `v2_060000231003b20faec8c6e6811acad1ca06e534b07788b29eed6dd8e71aca67283987b679b6@finder`)
- **目标作品**: `export/UzFfBgAAxOClNFsoN2Spk8zT4DCaVikQXENps3YeyGFwg_SlGQ` ("面对癌症，财富究竟能带来什么？")
- **目标父评论 ID**: `15031175812304083586`
- **目标评论作者**: `隽永`
- **目标评论原文**:
  > B 我保留意见，大多数人都不具备演讲者的医学背景或者查询更多资料的条件以及跟专家讨论的能力，决定权还是在于治疗的医生。当然，财富确实可以获得更多的信息，更有助于自我的判断，以及心理安慰。另外，不同癌症的特点和治疗方式以及生存期都是不一样的，特别是像这种晚期肺癌，包括胰腺癌，经过统计存活率是很低的。所以我觉得她的观点比较泛泛。
- **候选双语回复**:
  - 中文: `谢谢补充。您提到的病种差异和信息获取门槛，是原视频值得补充说明的限制条件。`
  - 英文: `Thanks for adding this. Differences between cancers and barriers to information deserve clearer attention in the video.`
  - 组合正文:
    ```text
    谢谢补充。您提到的病种差异和信息获取门槛，是原视频值得补充说明的限制条件。
    Thanks for adding this. Differences between cancers and barriers to information deserve clearer attention in the video.
    ```
- **正文校验哈希**: `ea5f09f481dd9a2fa2f5d89cfcd8a6fc46ac7e502c543e0ecda0703a6e2d67f7`
- **确认前缀 SHA12**: `ea5f09f481dd`
- **审批状态**: `NOT_APPROVED` (等待单条人工授权)

## 后续单条发送与对账执行流程 (供人工执行参考)

当且仅当获得人工单条发送授权时，执行以下受控步骤：
1. **本地审批**:
   ```bash
   WECHAT_REPLY_ACCOUNT_KEY="sphjAH8AbMh8oYP" \
   WECHAT_REPLY_AUTHOR_FINDER_ID="v2_060000231003b20faec8c6e6811acad1ca06e534b07788b29eed6dd8e71aca67283987b679b6@finder" \
   PYTHONPATH=src .venv/bin/python scripts/wechat_secondary_reply.py approve --task-id <TASK_ID> --confirm-reply-sha12 ea5f09f481dd
   ```
2. **临时启用发送开关并提交单条**:
   ```bash
   ENABLE_WECHAT_SECONDARY_REPLY=true \
   ENABLE_WECHAT_SECONDARY_REPLY_LIVE_SUBMISSION=true \
   WECHAT_REPLY_ACCOUNT_KEY="sphjAH8AbMh8oYP" \
   WECHAT_REPLY_AUTHOR_FINDER_ID="v2_060000231003b20faec8c6e6811acad1ca06e534b07788b29eed6dd8e71aca67283987b679b6@finder" \
   PYTHONPATH=src .venv/bin/python scripts/wechat_secondary_reply.py submit --task-id <TASK_ID>
   ```
3. **若遇超时或 UNCERTAIN 状态，只对账不重发**:
   ```bash
   WECHAT_REPLY_ACCOUNT_KEY="sphjAH8AbMh8oYP" \
   WECHAT_REPLY_AUTHOR_FINDER_ID="v2_060000231003b20faec8c6e6811acad1ca06e534b07788b29eed6dd8e71aca67283987b679b6@finder" \
   PYTHONPATH=src .venv/bin/python scripts/wechat_secondary_reply.py reconcile-platform --task-id <TASK_ID> --confirm-readonly-platform-access
   ```
