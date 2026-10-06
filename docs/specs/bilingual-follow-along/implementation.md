# 首版本地制作实现

日期：2026-10-07。作者：Codex，精确模型标识未知。用户以“继续”确认规格后实施。本文区分已实现工程路径与未完成的真实素材验收。

## 入口

所有素材在独立作业目录内复制、哈希和冻结；不会把新内容写入发现、发布数据库或调度器。项目 venv 使用已有 Pillow/jsonschema，不安装或升级生产模型依赖。

```bash
PYTHONPATH=src .venv/bin/python -m cli.main follow-along-init /path/to/new-job \
  --audio /path/to/audio.wav --video /path/to/performer.mp4 \
  --english /path/to/english.txt --chinese /path/to/chinese.txt \
  --english-font /path/to/english.ttf --chinese-font /path/to/chinese.ttc \
  --title 'Song title' --objective '听清弱读并跟唱' --mode singing \
  --duration-seconds 30 --same-recording

PYTHONPATH=src .venv/bin/python -m cli.main follow-along /path/to/new-job/timeline.json \
  --target-stage package
```

`--same-recording` 是作者对音视频版本、显式偏移和逐行翻译对应的声明，程序不会声称已自动识别版本。不同版本需先人工确认映射。偏移以 `--audio-start`、`--video-start` 指定；首版非零 PTS 起点、非 1 速率、多人物/多 clip、动态 header 等情况拒绝处理。

初始化生成 draft：每个非空英文行和中文行是一对作者确认的意群，数量必须相等。所有词时间为 null、状态 unaligned。以 Unicode code point 保存全文 span，标点与换行保留。初次制作会在对齐阶段进入 NEEDS_REVIEW，直至提供可信词界或配置离线对齐。

## 对齐入口与人工修订

已有手工/观测词界时，在每个 word 中填写 `interval`、`timing_status=manual|observed` 和本地 `evidence_ref`（uri + SHA256），cue 区间须包含其词界。证据文件记录作者、时间轴版本、基准素材哈希、旧/新词界与修订理由。格式完整只能证明文件和数值一致，不能证明标注准确，仍需真实参考样本验收。

WhisperX 的入口配置是单独的本地 JSON：

```json
{
  "python": "/path/to/isolated-whisperx/bin/python",
  "model_directory": "/path/to/frozen-local-ctc-model",
  "nltk_directory": "/path/to/offline-nltk-data",
  "package_version": "EXACT_INSTALLED_VERSION"
}
```

```bash
# init 时加 --vocals /path/to/corresponding-vocals.wav
# 在 draft 中给每个 cue 填入粗窗口；单窗 <=30s，有序、不重叠。
PYTHONPATH=src .venv/bin/python -m cli.main follow-along /path/to/new-job/timeline.json \
  --aligner-config /path/to/aligner.json --target-stage align
```

适配器读取本地权重指纹、指定安装版本、CPU 实际设备和原始字符结果。worker 强制离线模型、检查已安装的 NLTK 数据，不自动安装或下载。生产 Python 的模块路径传给独立 worker，确保音频解码也受 FFmpeg 守卫控制；模型锁 FD 继承给 worker，父进程退出不会提前释放推理名额。

粗窗口是显式输入，不做 ASR 自动定位重复副歌。数字、词表外发音等必须给出可逆 `alignment_text`；不允许将缺失字符或 WhisperX 的 word interpolation 当作 observed。WhisperX API 与插值风险根据[上游实现](https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py)核对；本机尚未安装/执行，不能据此宣布模型兼容或歌声精度达标。

当前分离实现为 provided-stem 路径与 `StemSeparator` 协议，尚未包含已验证的 Demucs/UVR 自动分离后端。提供人声只代表作者指定来源，实际清晰度与分离伪影需要听审。原混音的 16k 副本在报告中明确标为 mixed analysis copy，不能称为 clean vocals。

## 模块与真实能力

| 模块 | 实现及边界 |
| --- | --- |
| contracts.py | Schema + 引用/哈希/根目录约束、来源完整覆盖、词顺序、时间映射、motion 范围；拒绝正式使用合成示例 |
| job.py | 输入音视频/逐行双语文本/字体，真实解码计数音频样本，生成 draft |
| audio.py | 48k stereo 原声副本、16k mono PCM16 分析副本、独立 stems 增益、两遍 loudnorm、母带与 AAC 回测 |
| alignment.py / whisperx_adapter.py | 手工/观测证据导入、完整原词 ID 校验、隔离模型协议与原始 chars 闸门 |
| chunking.py | 基于真实宽度、语法启发式、停顿与合法边界的 DP；视觉折行不改变中文语义块 |
| layout.py / font_coverage.py | 同字体度量/图集、OpenType cmap 缺字检查、真实墨迹溢出检查；不可拆中文超长时要求子句映射 |
| timing.py | 有理数帧时钟、半开词界、REST、Bezier 求逆、指数端点正规化、无状态 seek、快速切句连续性 |
| renderer.py | 有界可见图集缓存和 RGBA 管道、人物 cover/焦点裁切/圆角 padding、静态 header、双语空间 opacity/边缘 mask、活动词 sweep |
| qa.py | 渲染前全帧活动双语块、安全区、图层碰撞；编码后尺寸、帧数/帧率、48k stereo、音画漂移、响度、真峰值及完整解码 |
| cache.py / follow_along_manager.py | 分阶段内容寻址、完整 manifest/哈希复核、内核进程锁、文件 fsync、同卷目录提交、故障诊断保留及独立回执 |

当前不支持有界 ducking envelope 和 fade；请求时明确拒绝，不会用 compressor 比率冒充最大降幅。原混音模式不得独立调节声部。字体 weight 由提供的字体文件决定，不合成字重；首版字距、阴影偏移/模糊要求零。

raw bilingual cue 分段由作者意群映射约束；DP 已用于英文视觉折行，并提供合法边界端口。自动语法分析器、ASR 粗定位、跨意群中文重组、子窗口缓存、自动分离和编辑器桥均为后续工作，不能把接口存在当成后端已验证。

## 缓存与失败收据

```text
prepare -> [provided-stem preparation] -> align -> resolve
prepare / stems -> mix
resolve + mix -> preflight -> render -> package
```

不同 stage 只哈希相关输入；实现文件指纹参与对应 stage revision。新字号/字体不重新对齐；音频目标改变不重新对齐或排版；中文文本不参与英语对齐 key。Schema、实际证据与来源完整性每次入口都重新检查。成功 package 暴露视频、完整 timeline 和 QA 路径。

所有输出在作业 `.follow-along/cache/` 中，`.follow-along/receipt-*.json` 记录本次状态。失败的 staging 目录保留为 `failed-*`；缺失、额外或哈希损坏的产物不命中缓存。内核锁不会被基于时间的 lease 过期接管，因而不需要用不可靠 PID 文件推断陈旧 worker。锁等待 60s，FFmpeg/模型执行超时独立计算；不自动重试 OOM/缺词/输入错误。

`LOCAL_PACKAGE_READY` 只表示本地媒体 QA 合格；真实歌曲词界准确率、听审、资源基准和平台发布仍是独立证据。
