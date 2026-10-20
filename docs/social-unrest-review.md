# 社会动荡题材审查首期

本期实现经用户批准：双语词族/词形、局部上下文、源字幕预检、发布前复核和漏判/误判验证。维护者：Codex；2026-10-20。

截图中的通用违规说明不能证明具体命中原因。本类别表示本频道的保守平台题材风险，命中后进入人工复核，不宣称该新闻违法，也不按国家、人物或立场区别放行。

## 判定与输入

- `unrest`：骚乱、暴乱、抢掠、打砸抢、警民冲突，以及 riot/riots/rioting、looting/looted/looters、civil unrest、street clashes 等。
- `protest`：抗议、示威、游行、protest/protests/protesters/protesting/protested、demonstration/demonstrators/demonstrated 等，要求同句局部公共事件语境。
- `collective_action`：集会、罢工、rally/rallies/rallied/rallying、strike/strikes/strikers/striking，使用更窄的街头/群众/工人/工会语境。
- `mobilization`：起义、叛乱、造反、号召上街、推翻政权、uprising、insurrection、rebellion、overthrow、take to the streets、revolution，要求政权或街头动员语境。

不做整篇字幕的国名与事件词共现。默认同句两侧各 180 字符，字幕同时限制在真实 cue 起点前后 15 秒；文件、语言、视频与切片相互隔离。NFKC、大小写、中文空白归一化保留原文偏移。股市 rally、产品 demonstration 等只对准确短语消歧，不能给同句的真实骚乱整体豁免。历史排除只在该命中的局部语境生效；不修改既有 P0/P1/P2 的历史或歧义词规则。

源字幕预检完整读取源 VTT；发布阶段重新读取原始标题/描述、实际发布标题/文案、完整源 VTT、实际双语 ASS（热目录优先，其次原始归档、独立字幕证据）及封面文字文件。已记录的封面排版文字也参与审查。发布阶段切片不读取父片或其他切片字幕；缺少本切片的可定位完整字幕时停止投递。没有 OCR、自动画面识别或新模型调用。

新规则位于 `config/censor_rules.json` 的 `channel_policy.social_unrest`，有同内容内置默认值。沿用现有审查开关；只要违法审查或频道策略审查启用，该风险层就生效。老配置没有新字段时补默认；空词族或非法规则拒绝加载，沿用最后有效规则/默认规则。

## 动作和证据

P0 仍优先。新类别写 `censorship_incidents.stage=social_unrest, level=RISK`，当前待处理任务转为 `FAILED` 等待人工复核，保留分数，不加黑名单。记录命中词、原文片段、来源、审查阶段、输入指纹和规则指纹；复核接口在两指纹一致时重放原文偏移和真实 VTT/ASS 时间，无时间就不推测。

旧的频道信任名单、通用 bypass 和 CP fail-open 都不能跳过本类别。已有复核放行接口只在可重现证据时写入 `MANUAL_SOCIAL_UNREST_APPROVED`；审批绑定同 ID/切片的完整输入与规则指纹，文案、字幕或规则变化后必须重新复核。元数据阶段的批准不自动批准加工后发布包。

复核按原阶段和平台重建输入，包括快手专用文案。元数据审计字段沿用既有长度上限，超长字段无法复现完整指纹、无源 VTT 的音频备用文本无法定位等情况会显示 `UNAVAILABLE` 并拒绝泛化放行，需补齐可复现证据后重审。高互动列表把新风险归入规则拦截，沿用现有复核入口。

视频号在封面完成、实际上传前再次复核；抖音/快手复用其现有发布前审查入口。发布阶段证据缺失、解析失败或规则异常按 fail-closed 停止上传。没有迁移、批量回扫、历史状态重写或自动重新发布。

## 验收边界

隔离测试覆盖用户示例、中文通告摘要、词形、科技/金融隐喻、历史语境、跨句/跨文件/跨时间不共现、字幕 4 万字符以后的风险、实际封面文字、切片隔离、旧绕过失效、输入/规则变化使批准失效，以及实际发布边界不调用上传器。现有 P0、CP、源字幕、就绪发布及多平台回归继续运行。

2026-10-20 工作区隔离验收：16 个测试文件，378 passed（6 条既有弃用警告）。回执目录：`/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-q33co7ht`；源码清单 SHA256：`dfd7d6aecc943a672ff174802ea37c3a8f6e0be239f9968c1ef550daf8371a8e`。测试使用临时 SQLite 和真实 VTT/ASS，操作系统边界探针确认不能访问正式库或联网。

最终整合验收包含生产主目录当时已有的未提交代码，并在独立副本加入本次补丁：379 passed（6 条既有弃用警告）。回执：`/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-n34yhjfa/receipt.json`；源码清单 SHA256：`be623822f3889d3a9de0f3c07d422be45778cf3d7c9aa5498b0fd2978fe13c7d`。生产维护只读检查仍报告在途发布和 `LEGACY_WORKER` / `UNREGISTERED_PROCESS`，因此本次未改写生产 checkout、未重启服务、未恢复或触发历史任务；主干提交与生产采用分开记录。

测试通过只能证明这些样例与调用边界。规则可能漏掉新的隐语、转写错误或依赖画面的风险；不保证视频号接受，不把截图推测当成平台规则事实。常驻进程是否加载新代码需单独取得运行证据。
