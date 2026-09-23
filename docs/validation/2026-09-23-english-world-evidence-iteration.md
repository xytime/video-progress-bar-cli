# 英语世界证据与修订优化验收

作者：Codex。日期：2026-09-23。代码提交：`f9ca4446a4825843bf624b9fa675e46d3da7d681`，基于 `1d7407d`。

## 结果

最终隔离验收 **244 passed**，包含真实 Chromium 渲染和浏览器边界检查。
证据目录：`/private/tmp/video-pytest-2lc4ud0d`，pytest 耗时 52.62 秒。
隔离源码清单 SHA-256：`5d5062d7890cd6bce1e525d988265e7680a37da49f5bb7d6a24075a0abe6a75b`。

最初外层沙箱阻止 `sandbox-exec` 启动，测试未执行；随后在外层之外调用原隔离器，
操作系统边界探针通过后才执行 pytest。没有绕过项目隔离机制。

## 完成的修复

1. ASR 不再为孤立零宽词猜测 0.05 秒时长。原始证据先保存；同源任务只允许一次已下载 medium 复核，small 失败证据仍可追溯，成功后保持 medium 模型证据，失败或中断不因换目录重复运行。
2. 封面中英文绑定同一完整段落；修订后重新冻结封面及投稿文案。合法 `U . S .` 不再误判为残缺。Pillow 使用可读字号完整排版，Chromium 检查实际文本区域；放不下就拒绝，禁止裁切审校后的内容。
3. 分段找不到安全边界时明确停止，取消最终按词数硬切的后门。
4. 音标保留原值、规则及版本；规范化可确认的 schwa 编码，含义不明的点号保留并标记，只有标点或空白的音标拒绝。没有宣称这些处理能够证明所有音标正确。
5. 自动修订前验证本次完成回执、报告与输入指纹、原始审校缓存及预算，并持久预占唯一修订。转录疑点不能用改译文掩盖；失败目标未改变时不再消耗复审预算。最终修改记录包含词性、音标、英文标题、封面及绝对来源区间。

## 验收范围

- 原有来源恢复、语言预算、模板与两平台封面相邻回归。
- 协调器入口：真实词典、布局、指纹和审校账本，替换供应商与子进程边界；首次 FAIL 后恰好一次修订，第二轮 PASS 可继续，第二轮 FAIL 终止，原审校计数为 2。
- 过期报告、运行错误回执、缓存不一致、次数耗尽、任务在途/终止、原声疑点均在生成修订前拒绝。
- 跨目录 ASR 复核成功复用和失败不重试，small 原始证据保留。
- 真实 Chromium 完整段落截图、超长段落拒绝，以及 Pillow 实际输出；两种产物均目视检查完整双语文本。

执行参数为 `scripts/run_isolated_tests.py --browser -- -q`，覆盖：
`test_english_world_boost_pipeline.py`、`test_english_world_programmatic_daily.py`、
`test_learning_dictionary.py`、`test_english_world_language_qa.py`、`test_english_world_cover.py`、
`test_english_world_source_resolution.py`、`test_english_world_recovery_guards.py`、
`test_study_card_template_a.py`、`test_cover_v2.py`、`test_english_world_douyin_cover.py`，
以及浏览器测试 `test_english_world_cover_overflow.py` 和 `test_browser_isolation.py`。

## 尚不能据此声称

这些测试没有调用真实 AGY，没有重跑今晨四条候选的原始媒体，也没有平台上传或公开回读。
它们不能证明四条候选均可恢复，更不能证明每日双更已经稳定。
首次实际新任务的来源、语言、音频、视觉与交付结果仍须分别观察；代码采用与 Git 推送状态以交付时的实际回执为准。
