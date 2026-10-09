# TED/TEDx 原片去开场等待验证

作者：Codex；2026-10-09。当前核验基线为2754c62；实现已现场核对。以下为本轮新证据，替代首版三样本/108测试结论。无下载、付费服务、平台投稿或历史重发。

## 发现与修复

- **视觉保护缺失**：`0lQtYesj_yI` 和 `-_GCY_ZQyUs` 首次讲话前含仅出现一次的主题/讲者卡片。v1拟剪7.148/6.668秒，会删去这些信息；不能把“没有讲话”视为“内容无效”。v2只删除完整音画匹配登记品牌前缀的区间，未知开场保留。没有使用OCR、角色分类或语言模型。
- **时间轴校验漏口**：旧起止检查可被NaN绕过，也允许两条流共同偏离零起点。现在拒绝非有限值、未知起点和异常时间基。
- **整片结束时间误报**：真实11分钟原片`535jVKx0_DI`裁剪后视频起点0.04秒、时长663.48秒，音频起点0、时长663.575011秒。旧代码比较时长得到95ms而回退；真实末端差为55ms。修复为“起点＋时长”，保留原有80ms容差，未放宽门槛。
- **二创旧策划脚本复用**：裁剪素材有绑定但V2脚本缺少策划来源指纹时，旧代码可继续采用旧时间点。现在重建该脚本，已缓存增强成片的通用采用校验也要求同一策划指纹，避免提前返回绕过；策划失败按既有机制退回基础成片，绝不拼接错误时间轴。
- v2配方、模板摘要及实际模型完整性纳入缓存检查；失败收据增加可区分的原因码。

## 真实素材与边界

从本地131条TED/TEDx原片目的性选30条，各只读提取前40秒进入严格测试沙盒。六条模板参考的完整原片另作字节复制；六条整片前缀摘要均与摘录一致。一个完整原片实际编码及全片解码。

采样覆盖品牌音乐、观众掌声、短问候、立即讲话、访谈、黑场转场、唱歌和手风琴表演、开场独有文字。预期边界按“完整保留/已确认品牌区间末端”制定；**没有30条首音素人工标注**。早期含混信号不能当作已证实弱人声；独立真实弱声、音频先出及纯无声演示覆盖不足，列入研究。原始字幕用于参考，跳过空白滚动cue和转录者署名，不能把第一个cue时间当首次讲话真值。

最终**6条裁剪、24条自动保留**。五条v1拟剪开场因无登记音画匹配保留；包括两条独有文字反例。六条剪裁素材包含模板参考，不能据此计算泛化准确率或宣传零误删率。品牌后仍有部分等待，这是主动接受的漏剪。

| 素材ID | 预期安全区间末端 / 实际切点 | 处理秒数 | 结果 |
| --- | --- | --- | --- |
| `1qmF_znXxrE` | 0 / 0.0 | 0.974 | SPEECH_AT_START_OR_SMALL_GAIN |
| `Uk31lVtda2g` | 8.5 / 8.5 | 4.922 | VERIFIED_AV_PREFIX |
| `6xbG8OLQYys` | 7 / 7 | 6.426 | VERIFIED_AV_PREFIX |
| `1aY-puP8oOw` | 0 / 0.0 | 0.169 | SPEECH_AT_START_OR_SMALL_GAIN |
| `txf8CrI5z-k` | 0 / 0.0 | 0.167 | SPEECH_AT_START_OR_SMALL_GAIN |
| `y64RDBeR19c` | 0 / 0.0 | 0.17 | SPEECH_AT_START_OR_SMALL_GAIN |
| `n4WktuDT49I` | 0 / 0.0 | 0.168 | SPEECH_AT_START_OR_SMALL_GAIN |
| `535jVKx0_DI` | 10.5 / 10.5 | 1.693 | VERIFIED_AV_PREFIX |
| `2SS8xDcsXCM` | 0 / 0.0 | 0.175 | UNCERTAIN_EARLY_VOICE |
| `AlY6ztT12Ps` | 0 / 0.0 | 0.191 | UNVERIFIED_AV_PREFIX |
| `P1hob_amyIg` | 0 / 0.0 | 0.18 | SPEECH_AT_START_OR_SMALL_GAIN |
| `rU-Awn4m2VY` | 0 / 0.0 | 0.169 | SPEECH_AT_START_OR_SMALL_GAIN |
| `DTwHfQR-_Ac` | 8.5 / 8.5 | 2.988 | VERIFIED_AV_PREFIX |
| `BDA2oTj_6KI` | 0 / 0.0 | 0.164 | UNVERIFIED_AV_PREFIX |
| `CfuEK3U6Bog` | 8 / 8 | 5.595 | VERIFIED_AV_PREFIX |
| `1eCX3na89-U` | 0 / 0.0 | 0.165 | SPEECH_AT_START_OR_SMALL_GAIN |
| `27SwlEfTbUI` | 0 / 0.0 | 0.164 | SPEECH_AT_START_OR_SMALL_GAIN |
| `2L5jOA6JnHc` | 8.5 / 8.5 | 4.389 | VERIFIED_AV_PREFIX |
| `PKN3b8hmzWg` | 0 / 0.0 | 0.234 | SPEECH_AT_START_OR_SMALL_GAIN |
| `Lk7d0xG3AZk` | 0 / 0.0 | 0.181 | UNVERIFIED_AV_PREFIX |
| `0lQtYesj_yI` | 0 / 0.0 | 0.166 | UNVERIFIED_AV_PREFIX |
| `-_GCY_ZQyUs` | 0 / 0.0 | 0.165 | UNVERIFIED_AV_PREFIX |
| `81iS7JsTGmk` | 0 / 0.0 | 0.162 | SPEECH_AT_START_OR_SMALL_GAIN |
| `Hd8npxrnpuo` | 0 / 0.0 | 0.167 | SPEECH_AT_START_OR_SMALL_GAIN |
| `jCbITOCoxpo` | 0 / 0.0 | 0.168 | SPEECH_AT_START_OR_SMALL_GAIN |
| `gduYQKmz05M` | 0 / 0.0 | 0.166 | SPEECH_AT_START_OR_SMALL_GAIN |
| `9Ff4S1FJdRM` | 0 / 0.0 | 0.165 | SPEECH_AT_START_OR_SMALL_GAIN |
| `5SNEMFH7NlE` | 0 / 0.0 | 0.181 | SPEECH_AT_START_OR_SMALL_GAIN |
| `pT0HuZM4Tf0` | 0 / 0.0 | 0.184 | UNCERTAIN_EARLY_VOICE |
| `oyRxhiAC9u8` | 0 / 0.0 | 0.168 | SPEECH_AT_START_OR_SMALL_GAIN |

登记前缀：Uk31lVtda2g 8.5s、6xbG8OLQYys 7s、535jVKx0_DI 10.5s、DTwHfQR-_Ac 8.5s、CfuEK3U6Bog 8s、2L5jOA6JnHc 8s。2L5jOA6JnHc实际匹配Uk31lVtda2g的相同8.5秒音画，收据明确记录reference_id。匹配不依赖当前视频ID。

所有30个测试源摘录前后SHA256不变；六个完整原片副本摘要前后不变。六个裁剪副本及整片均完整解码退出0；媒体起止、时长通过校验。没有修改生产原片。

## 音频、字幕与二创证据

六条副本的前15秒与原片对应保留区间，在现有离线Whisper base下前五个词一致；前5秒波形最佳相关度0.999665–0.999997，±16ms范围搜索得到采样步长1ms下最佳延迟0ms。ASR可同时错读同一词（如Ayurveda），这检验保留区间一致性，不代表首字识别准确率。

隔离回归119项覆盖原片重合保护、短问候、未知音画变化、模型及缓存损坏、异常后重试、非零/非有限时间轴、原片/ASS/竖版绑定、二创策划指纹、开关关闭、历史/章节/人工范围及就绪分发。新增真实FFmpeg裁剪副本+零起点ASS的V2二创合成回归：正文约12秒，导读/片尾仍完整、内容保持，三级收据有效，总时长对应首/正文/尾段。二创测试配音及词时码使用明确离线替身；不宣称检验过生产付费TTS或真实新任务整链路。导读绘制、旁白及合成实现文件没有改动。

最终入口：
```bash
.venv/bin/python scripts/run_isolated_tests.py --media -- -q \
  tests/unit/test_speech_opening.py tests/unit/test_insight_editorial.py \
  tests/unit/test_insight_processor.py tests/unit/test_insight_processor_v2.py \
  tests/unit/test_insight_advisory.py tests/unit/test_pipeline_title_consistency.py \
  tests/unit/test_video_slicer.py tests/unit/test_ready_publication_dispatch.py
```
结果：**119 passed in 35.29s，退出0，无跳过**；严格读写/网络/信号边界探针退出0。
测试证据根：`/private/tmp/video-pytest-tsppf2hd/`；源清单SHA256：`8b8291ad85acfeaae9cc6d58fc333e9db3a7309e1df92eafc1f2e156411af44c`。
真实媒体证据根：`/private/tmp/video-pytest-6g797my5/sandbox/tmp/final-openings/`。对应去开场可执行代码与最终版本相同；随后新增二创缓存策划凭证采用校验已通过最终回归。联系图和原始字幕在同沙盒`ted-openings/`。临时媒体证据可能随系统清理消失；逐样本摘要/切点/耗时/故障码已[随代码归档](ted-opening-results-2026-10-09.json)，[案例清单](ted-opening-cases-2026-10-09.json)提供预期和样本摘要。

## 成本与复现

40秒摘录的保留路径约0.16–0.24秒（首次模型导入约0.97秒），裁剪路径约1.69–6.43秒，含检测/模板解码/编码/校验；不是纯VAD速度。完整参考前缀摘要校验约0.71–1.35秒/次，未知同格式开场可能尝试多种模板长度。

`535jVKx0_DI`整片674.075秒：额外加工**28.748秒**，全片解码2.944秒；原片44,700,213字节，副本67,412,193字节（增加一份约67.4MB文件，副本约为原片1.51倍）。片头减少10.5秒。这里只测一条完整原片，不能线性保证所有视频成本。保留原片与精确副本，暂不合并最终编码，避免破坏统一时间映射。

复现：先用项目隔离入口建立源码/离线模型沙盒，再只读复制有合法本地来源的40秒摘录及指定整片到沙盒tmp；在该沙盒profile内运行：
```bash
PYTHONPATH=src .venv/bin/python scripts/verify_ted_openings.py \
  --cases docs/verification/ted-opening-cases-2026-10-09.json \
  --media-root <沙盒tmp中的素材目录> --output-root <沙盒tmp中的新证据目录> \
  --full-case 535jVKx0_DI --audio-integrity
```
这里的`.venv/bin/python`指宿主已安装解释器，运行cwd须是隔离repo；使用runner生成的显式环境清单及sandbox-exec profile。工具拒绝没有隔离marker的工作区，核对输入摘要，失败不绕过。媒体不入Git，工具不访问生产DB或网络。

## 交付边界

实现提交 `dfd9f7c540dcb40cd36dfe4212a6d8f4c7931e8b`，在活动任务为0并持有`output/pipeline.lock`排他锁时，从主干`2c9287c`快进合入；保留并行任务的两个版式脚本提交。`git push origin main`成功。此报告的后续归档提交仅修改文档与证据，不改变已验证代码。

2026-10-09 08:54:30（Asia/Shanghai）运行回读：`./vpanel ui restart`退出0，控制器由PID35423切换为52511，:9100健康，`/api/stats`活动任务0。只读主干解释器核验得到`ENABLE_TED_OPENING_TRIM=true`、`speech-opening-v2`、离线模型摘要匹配、六条前缀模板，模块实际路径位于生产主干目录。模板清单SHA256为`b17075ca3b502b1d7dcedd36d3a9c5c18249470cad929f76b46ea7ece36a55c4`。

已确认新进程及代码入口采用；没有触发新视频完整加工，也没有发布或重发。代码采用、加工完成、平台受理及公开播放分别判断。[具体研究任务](../specs/ted-opening-trim.md)已有当前处置、缺失证据及未来验收标准，无人工确认环节。


## 2026-10-09 下午：审查修复与生产采用

本轮修复两个代码审查问题：

- 裁剪外层超时即使关闭全局PID追踪也清理独立进程组，避免遗留FFmpeg持有共享执行槽。隔离测试实际启动Python子进程及持槽后代，再验证下一任务能取得同一内核锁；覆盖正常SIGTERM及拒绝SIGTERM后强制终止，不能以子进程启动失败代替清理证据。
- 本任务裁剪目录与来源绑定接入整片硬重置；删除基础成片失败时保留输入，章节重置保护父缓存。未引用、终态、全部文件超过3天的缓存随既有原片归档TTL回收；近期、未知、失败/未完成、二创固定或已有成片绑定继续保留。符号链接/路径逃逸回归使用合成故障夹具，与真实TED样本证据分开。

媒体与流水线隔离回归：**159 passed in 56.77s，退出0，无跳过**；严格读写/网络/信号边界探针退出0。入口为上文8个测试文件加 `tests/unit/test_speech_opening_runtime.py` 和 `tests/unit/test_ffmpeg_slot.py`，仍使用 `scripts/run_isolated_tests.py --media`。证据根 `/private/tmp/video-pytest-o018o5bw/`；源清单SHA256 `b694648937c35240a0d5b0828625913553cb818163321122c2995505a70cb758`。

本轮没有修改VAD、模板、裁剪配方或二创渲染。30条真实样本、6条裁剪及整片成本沿用上文归档证据，不将此次159项回归算作新增真实样本。绑定副本继续占用存储；解除这类历史依赖另列研究任务。TTL随新归档触发，不宣称持续后台全目录扫描。


2026-10-09 **16:46:52（Asia/Shanghai）已再次部署采用**：生产主干从 `bd7ff6d` 快进到实现提交 `013db8455d4fc9955d35c86c53082ebf8b6a880c`，`git push origin main`退出0。部署期间持有 `output/pipeline.lock` 排他锁，合入/重启前活动任务0；生产无关 `.gitignore` 的SHA256前后不变，其他未提交工作保留。

`./vpanel ui restart`退出0，控制器PID从52511切换为**65646**，:9100 `/api/stats` HTTP200。随后运行回读：控制器cwd为 `/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing`；生产解释器核验 `ENABLE_TED_OPENING_TRIM=true`，配方v2、模型摘要正确、六条模板清单摘要与上午一致；管理器及缓存清理模块路径均属于生产主干，裁剪调用明确强制进程组保护。现有全局SIGTERM开关为true，本轮未改变配置；隔离测试另外证明其为false时新保护仍有效。

自动入口保持现有行为：控制器启动自动调度及队列轮询，后台预加工入口导入同一主干管理器；后续新整片会自动执行开场检查，无需人工确认。重启后正常队列回读已有1条PUBLISHING任务；本轮未手动创建、重发或提交视频任务。不把该既有队列活动当作新TED整链路证据。自然新TED任务的完整加工、平台受理和公开播放仍需分别核验；本轮已证实代码部署、配置开启及运行入口采用。

此部署归档只更新文档，不再重启服务。
