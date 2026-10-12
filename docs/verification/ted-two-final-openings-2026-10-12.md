# 两条 TED 完整成片、开头清理及生产采用验收

作者：Codex（具体模型身份未确认）；2026-10-12。用户已授权完成实片验证、主干交付及上线，不设人工确认环节。验证输出全部位于外置盘的独立目录，不修改生产原片、历史成片、任务状态或投稿。

## 结果与成片

此前两条自然生产任务都进入了清理入口，但返回 `UNVERIFIED_AV_PACKAGING`；原因是其包装没有可验证模板，并非检测开关关闭。本轮仅登记两段经过声画和边界核验的包装。使用现有生产清理、竖版字幕、来源绑定、互动层和最终文件选择模块，重新生成两条完整竖版副本，并完成媒体验证。

| 视频 | 原片保留区间（秒） | 最终整片时长 | 证据 |
| --- | --- | --- | --- |
| 职场对话三步开场 `CKAyfGItpgg` | `[3.50, 667.457596)` | 663.973991秒 | [完整成片](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/verification/ted-two-openings-2026-10-12/finals/CKAyfGItpgg_vertical_interactive.mp4)、[画面对照](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/verification/ted-two-openings-2026-10-12/CKAyfGItpgg-final-evidence.jpg) |
| 照护如何塑造领导力 `65LZk_S9HBY` | `[10.00, 933.860136)` | 923.875011秒 | [完整成片](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/verification/ted-two-openings-2026-10-12/finals/65LZk_S9HBY_vertical_interactive.mp4)、[画面对照](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/verification/ted-two-openings-2026-10-12/65LZk_S9HBY-final-evidence.jpg) |

第一条去掉3.50秒品牌包装，保留讲者淡入及首句“I want to be long-winded and unclear”。第二条去掉10.00秒品牌、日期、活动使命和赞助包装，保留舞台淡入、`Caregiving is Leadership`舞台文字及首句“I did locker room interviews with the likes of Michael Jordan, Dr. J. and Magic Johnson”。声音先于完整舞台画面，切点没有为等画面而后移。两条均保留原片全部剩余区间，没有裁尾；第二条原结尾的 TEDx 卡也保留。

## 完整讲话、字幕与二创保护

- 原片、旧双语 ASS、旧基础竖版和旧互动成片逐一 SHA256 对照，本轮前后字节不变。最终两条新副本完整 `ffmpeg -xerror ... -f null -` 解码通过。
- 原片从切点到结束与新基础竖版逐秒音频对照：第一条663个有声窗口，最低归一化波形相关度0.985325、中位数0.999616；第二条922个窗口，最低0.970397、中位数0.999329。原片与新最终互动成片也作独立对照：分别657、917个有声窗口，最低0.984549、0.970119，中位数0.999582、0.999306。五个已知互动提示音秒窗口单独排除；这些秒仍由基础竖版全程对照覆盖。相关度用于检查音频连续性，不是识别准确率。
- 音视频均从0秒起，最终时长与原片减切点分别相差16.395ms、14.875ms；视频末端与音频末端分别差73.991ms、85.478ms，属于帧/AAC补包差异。没有改变生产副本的严格校验规则。完整音频样本长度、每秒对照和完整解码共同验证讲话没有丢段。
- 复用历史双语译文，按切点整体前移并截取合法时间范围；288、196条字幕文字全部保留，逐条时码与预期映射误差均为0ms。由真实竖版处理器烧录，抽取开头、正文和结尾画面人工观察，配合来源画面对应检查。没有冒称重新完成整片 ASR 或翻译，也没有修订历史译文自身的识别/时间误差。
- 本地 Whisper base 对原片和成片的开头、结束段辅助复核；首句和结束段锚点均保留。第二条最后18秒主要为掌声，短窗口会幻觉识别，改为对应的60秒真实结束段后两边转录一致。原始转录归档，不把 ASR 幻觉、VAD 概率或局部字幕当完整讲话的唯一证明。
- 两条原任务均无独立二创导读，验证没有新增导读。已核对 `insight_editorial.resolve_inputs` 指向同一裁剪素材及映射 ASS；二创导读、正文和结尾的完整合成及缓存绑定，由隔离媒体回归验证。该回归使用合成正文与本地 TTS/时码替身，属于链路保护证据，不是假称两条自然素材含有导读。

详细数据见 [结构化报告](ted-two-final-openings-2026-10-12.json)、外置盘 [成片验证原始结果](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/verification/ted-two-openings-2026-10-12/finals/results.json) 和 [独立音频/字幕/画面对照](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/verification/ted-two-openings-2026-10-12/final-comparison.json)。

## 自动规则与生产采用

两段新增参考分别为 `TED-particle-brand-50fps`（3.50秒）和 `TEDxSIUC-2026-brand-sponsor-opening`（10.00秒）。现有逻辑精确匹配完整原生画面、全部声道及流参数；视频 ID/标题不参与裁剪判断，改名副本仍匹配。不同编码、音轨、文字或讲话使模板失配，自动保留原片。

生产包装目录 SHA256：`8f5477baee66fa289d786a9aa504572637a555f40436f1eae0822a788dfd406b`。旧目录为 `e7ce1d73ff271f042c311e1772ea25a4bed2f1c006a993b580a407976dc44a2d`；旧六段前缀目录摘要不变。尾部仍只有 NorthernQuarter 原7.72秒模板，没有扩大到其他尾部或正文导流。

在生产主干空闲、流水线锁取得、面板 active=0、就绪执行者心跳新鲜且无当前任务时，原子替换目录。生产 Python 模块没有改动；清理子进程每次读取目录，因此既有常驻服务无须重启。不能以启动时旧 Git 版本判断数据未采用。

实际生产目录 `/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing` 的 `_prepare_speech_opening` 和受跟踪子进程，使用真实配置、无强制启用，在独立目录重新生成两条完整原片副本；实际偏移分别为3.50、10.00秒，结束边界等于完整原时长。验证生产选定副本摘要与用于制作上述成片的副本摘要逐字节相同。未知真实短片 `Hgh8L_aNiCA` 自动返回原片；256字节合成损坏夹具返回输入并记录 `UNAVAILABLE_ValueError / MISSING_AV_STREAM`。诊断不初始化生产 DAL，不调用发布入口。

未成片任务的旧“保留原片”收据会因目录摘要变化失效，并在下一次准备时重新判断；已有成片及就绪重试仍使用原有效素材绑定。新整片的字幕、基础竖版和二创共同使用本次选定素材；人工范围和章节任务仍跳过。以上两条历史任务保留原状态，本次交付为独立验证副本。

生产证据分别见 [原子部署记录](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/verification/ted-two-openings-2026-10-12/deployment.json)、[实际入口记录](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/verification/ted-two-openings-2026-10-12/production-entry/production-entry.json)、[提交推送与最终运行回读](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/verification/ted-two-openings-2026-10-12/delivery.json)。入口验收证明生产已采用模板；本次没有触发自然新任务、投稿或重发，不将其等同于后续自然发布完成。

## 回归与可复现方法

本轮34条可用真实原片：32条检测回归中6条匹配、26条保留，另两条新增参考匹配并完成全长成片。全部原片摘要不变。覆盖品牌音乐、掌声、含混人声、短问候、立即讲话、先声后画、舞台渐变、音乐演示及重要开场文字。新增参考不算独立留出集；结果是逐样本证据，不是通用准确率。真实明细见 [real-regression.json](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/verification/ted-two-openings-2026-10-12/real-regression.json)。

项目隔离入口74项媒体相关测试和20项就绪重试测试通过，共94项。覆盖缓存损坏、异常重试、资源不足回退、源绑定、开关兼容、二创完整合成和提交文件选择。沙盒探针确认外部读写、网络和外部信号被拒绝。初次测试曾受本机空间不足影响，返回原片；外置盘迁移后重跑通过，失败日志也保留。归档的空间不足收据来自合成资源故障测试，不冒称为最初失败测试的直接收据。

```sh
.venv/bin/python scripts/run_isolated_tests.py --media -- -q \
  tests/unit/test_ted_source_cleanup.py tests/unit/test_speech_opening.py \
  tests/unit/test_speech_opening_runtime.py tests/unit/test_insight_processor_v2.py \
  tests/unit/test_insight_editorial.py
.venv/bin/python scripts/run_isolated_tests.py -- -q tests/unit/test_ready_publication_dispatch.py
```

实片脚本 [ted_two_final_media.py](tools/ted_two_final_media.py) 读取生产原片/历史 ASS，写入独立外置盘目录。新验证目录不带 `--resume`；仅恢复本次完整渲染且重新核验媒体与绑定时显式使用该参数。记录中的复用是本次新生成产物，不是原历史成片。模型使用本地已安装 `base.pt`，不调用付费服务。

实际生产入口脚本 [ted_production_entry.py](tools/ted_production_entry.py) 的复现命令：

```sh
PYTHONPATH=src .venv/bin/python -u docs/verification/tools/ted_production_entry.py \
  --root /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing \
  --output /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/verification/ted-two-openings-2026-10-12/production-entry
```

目录已存在时须显式加 `--resume`；会再次校验缓存/原片摘要并记录当前主干和运行状态。完整媒体生成期间的短窗口 ASR、最终 AAC 尾点校验误用及恢复日志一并保留；修正的是诊断方法，没有放宽生产裁剪保护。

## 成本与剩余研究

外置盘迁移13份已有验证文件，共158,791,228字节，逐文件摘要复核后才删除内部盘对应副本；随后新媒体、测试归档和入口输出也直接写外置盘。第一条额外源副本114,992,740字节，分析0.812秒、编码加完整解码115.650秒；第二条199,086,912字节，分析0.827秒、编码加解码90.557秒。这是清理额外成本，不能当作整条字幕/竖版流水线总耗时。保留一次精确编码和稳定绑定，不为几秒片头采用未经证实的编码融合。

| 研究任务 | 当前处置和缺少证据 | 未来验收 |
| --- | --- | --- |
| 不同转码、音轨和活动包装 | 精确匹配不到就保留；两条新增样本均为参考，不能证明跨视频覆盖率 | 独立真实留出素材标注全部开头讲话、重要文字及无声正文，逐条记录误删/漏剪和耗时；修改任意声道人声或正文画面必须保留 |
| 弱声、声音先于画面和重要开场文字 | 保留渐变和未知开头，不进一步追切 | 用独立反例核验所有首字音素和正文画面；没有可靠低成本方案时继续保留 |
| 减少编码及存储成本 | 保留当前副本和来源绑定；不能先删仍被成片引用的缓存 | 比较多时长/帧率的整体成本，同时通过首字、音画/字幕同步、缓存损坏和重试；收益明确才变更 |
| 自然后续任务 | 已部署并通过实际入口；本轮不为了观察而触发投稿 | 后续正常任务回读收据、素材绑定及最终成片；加工、平台受理及公开播放分别记录 |

尾部扩展、正文导流语义删除、半句话处理和角色判断不纳入本轮；不设置待人工确认队列。
