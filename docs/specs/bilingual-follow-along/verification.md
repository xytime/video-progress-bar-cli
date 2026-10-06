# 规格与首版验证记录

日期：2026-10-07。执行者：Codex；精确模型标识未知。

初次规格阶段只新增规格文件。未修改业务源码、配置、依赖、数据库、调度、常驻服务或平台状态；未下载/加载模型、执行分离/对齐、渲染媒体或发出通知。

## 初次规格证据

| 项目 | 结果 | 范围 |
| --- | --- | --- |
| 代码位置 | 已检查 | `study_cards/models.py`、`renderer.py`、`template_a.py`、`audio_qa.py`、`timeline_guard.py` 与 core audio_mixer / FFmpeg 守卫文档 |
| 先前规划 | 当前文件已回看 | VideoMaker 的 requirements、roadmap、toolchain-research 与 review；保留成熟工具、可复查、可替换的方向，本轮规格不代表批准旧规划 |
| 主机／venv | 已读取 | arm64，16 GiB，10 物理核；Python 3.12.4，torch 2.9.1，Pillow 11.3.0，jsonschema 4.26.0；whisperx/demucs/torchaudio 无安装元数据 |
| Schema 元规范 | PASS | 项目 `.venv/bin/python` 中使用 `Draft202012Validator.check_schema`；无项目业务模块导入 |
| 人工构造示例 | PASS | Schema 结构有效；2 个 cue、8 个词；没有真实素材/字形/词界证据 |
| 契约检查 | 14 项 PASS | 下列边界与示例自洽性；临时验证脚本，未加入产品源码或测试套件 |
| 真实媒体/模型 QA | NOT_RUN | 尚无首版实现、指定素材及人工参考词界；没有对齐精度或性能结果 |

14 项检查：

1. 未知根字段被拒绝。
2. resolved 阶段的 estimated 词界被拒绝。
3. resolved 阶段的空词时间被拒绝。
4. resolved 阶段的缺失 evidence_ref 被拒绝。
5. resolved 阶段的空 glyph_boxes 被拒绝。
6. `../` 素材路径被拒绝。
7. 嵌套目录中的 `../` 被拒绝。
8. 绝对素材路径被拒绝。
9. 远程素材 URL 被拒绝。
10. derived asset 缺失 source_time_map 被拒绝。
11. 零 fps 分母被拒绝。
12. 越界 cubic bezier 参数被拒绝。
13. draft 可以明确表达尚未对齐的词、空时间和空布局。
14. 构造示例的单词 span 与显示原文相符，所有词 interval 为正且落在对应 cue 内。

这些验证不覆盖真实文件引用、symlink containment、源素材对应、人工修订可信度、字形实际 bounds、motion 的逐帧几何、音频质量或恢复行为；均列入后续实现验收。示例的 `synthetic_contract_example=true`、假 hash 与不存在的 evidence 文件，应使正式制作的 host 闸门拒绝它，即使 JSON Schema 通过。

查阅的公开技术资料在 architecture.md/core-design.md 相关判断旁链接。上游主分支资料可能继续变化；实际部署须锁定版本和权重，不把文档能力当本机适配器验证结果。


## 用户确认后的实施验收（2026-10-07）

新增独立制作 namespace、编排器、两个本地 CLI 命令和离线模型 worker。无数据库、依赖安装、生产配置或运行调度变更；没有发布、通知、模型下载或模型加载。

最终命令：

```bash
.venv/bin/python scripts/run_isolated_tests.py -- -q tests/unit/test_follow_along.py tests/unit/test_ffmpeg_slot.py
```

**48 passed**。隔离沙盒边界 probe exit=0，pytest exit=0；测试证据见 [收据](evidence/isolated-test-receipt.json) 与 [日志](evidence/isolated-test-output.txt)。这批测试为 23 项新制作路径用例及 25 项既有 FFmpeg 名额回归，不是全部仓库回归。

覆盖：Schema/语义、合成示例正式制作拒绝、词界半开区间、休止与随机 seek、有理数帧时钟、五种 easing、快速切句连续性、完整产物缓存/损坏恢复、失败诊断保留/取消收据、词序列完整性、原始字符缺失拒绝、动态分段/合法边界、根目录 symlink 逃逸、模型依赖缺失、同组碰撞不能豁免、素材初始化不伪造词界、CLI 注册、按模块修订失效、中文修改复用英语对齐，以及真正的 MP4 编码/AAC 回测/完整解码。

真实编码工程夹具：10 秒，1080×1920，30 fps，300 帧，48k stereo AAC。视频是蓝色块，音频是 440Hz 正弦波，歌词和人工词界是人为构造。首次生成、完整 cache hit、改变音频目标后 prepare/align/resolve cache hit 均通过。编码后参数和 loudness 见 [媒体 QA](evidence/technical-media-qa.json)。[编码截图](evidence/technical-preview.png)已目视检查，圆角窗、双语字体、逐词高亮与安全区呈现符合工程计划。

仍为 NOT_RUN / NOT_MEASURED：真实讲话/歌唱的对齐误差、拖腔及重复副歌精度、实际 WhisperX 安装版本兼容、Demucs/UVR 自动分离、分离伪影/听审、长片峰值 RSS 与吞吐基准。当前只支持 supplied stems；有界 ducking/fade、ASR 粗定位和自主中文子句重组未实现，请勿按完整自动化生产验收理解接口存在。

真实样本入口已询问本地路径，尚未获得指定资产。上述工程结果不构成真实教育成片、运行服务采用或平台发布成功。
