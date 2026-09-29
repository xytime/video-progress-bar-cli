# FFmpeg 全局单名额与资源影子审计

作者：Codex（精确模型身份未知）。2026-09-29，用户明确批准 FFmpeg 立即强制串行；其余资源阈值继续影子模式。

## 执行边界

常规视频、英语世界、审核视频压缩、音频提取、切片、渲染与下载器内部 FFmpeg，共用本机当前用户的一个执行名额。同一时刻最多一个 FFmpeg 加工子进程；不同作业轮流启动自己的进程，不是把一个常驻 FFmpeg 进程用于全部不同命令。FFprobe、上传、网络 API 请求不占此名额。

入口为 `video_processing.core.ffmpeg_slot.GuardedPopen`，项目包导入时幂等安装；项目 venv 的启动钩子还覆盖独立 yt-dlp/Whisper 等第三方库启动路径，包括 imageio 的绝对路径 FFmpeg。只识别 FFmpeg 可执行文件；显式配置的自定义可执行文件名在调用方注册。统一默认路径使不同 checkout 也不能各占一个名额。

这项措施作用于项目 Python 执行环境。用户在终端直接启动的 FFmpeg、其他应用、自带未受管解释器、`shell=True` 或通过 `os.exec*` 绕过 Popen 的新入口不在覆盖范围。当前维护目录没有视频 shell 管道和并行 reader/writer FFmpeg 依赖。以后引入这类入口必须先接入守卫，不可使用系统原始 FFmpeg 绕过排队。

## 名额配置

唯一运行配置为 `~/Library/Application Support/VideoProcessing/ffmpeg-slot/resource-limits.json`，常规视频、英语世界、不同 checkout 和解释器共同读取：

```json
{
  "ffmpeg_slots": 1
}
```

默认和当前值均为 **1**。安装器首次创建文件；重装不会覆盖已有配置。允许 1–64 的整数，配置缺失或字段缺省回到 1；非法值、损坏 JSON 或不可读文件拒绝新的 FFmpeg 启动，并在状态中显示配置错误。此文件不含密钥，也不读取 `.env`，避免 Python 启动钩子加载完整应用配置。

部署此版本并重载旧解释器后，修改该文件对下一次准入生效，已排队任务也会重新读取。建议用临时文件 + 原子替换保存，避免半写入 JSON。调大可放行更多进程；调小时，已运行任务自然结束，现有占用降到新上限以下才放行下一项。不会杀进程。`/api/stats` 和发布巡检心跳回读配置路径、当前上限与错误；启动审计记录当次实际准入上限。

## 锁与取消

- 位置：`~/Library/Application Support/VideoProcessing/ffmpeg-slot/`。FIFO 等候票与执行锁使用内核 flock；不靠 PID 存在性或陈旧超时释放。
- 未获得名额时不会创建 FFmpeg；250 毫秒低频等待。实际参数、线程数、输出文件和检查点语义保持原样。
- FFmpeg 继承锁 FD；父进程异常退出时，其计算未结束便不会放行其他请求。正常 wait/poll 或对象释放关闭父进程副本。
- 等待者退出会释放票锁；下一请求剔除死亡等候票。超时/取消仍由原业务代码负责终止所属进程组；本机制不向其他业务发送信号。
- 锁目录无法访问时拒绝启动 FFmpeg，不悄悄放开并发。
- `last-start.json` 是最后启动证据，不代表该 PID 此刻仍活跃。最多保留 2048 条已完成等待记录；字段只有 PID、祖先 PID、起止时间，不记录参数、正文和密钥。

## 排队与现有超时

直接 `subprocess.run(timeout=...)` 在真正 Popen 创建后才开始执行预算。字幕上报有效阶段起点和累计等待，看门狗仍检查真实心跳；常规管线、英语世界程序化子阶段与外层协调器扣除后代 FFmpeg 的排队时间。真实卡死仍受原有超时保护。

英语世界当前运行采用 programmatic 协调器。旧 AGY CLI 自己的 `--print-timeout`、外部代理工具自行设置的命令时限不受本机制控制；若切回这些入口，需单独评估其等待预算。排队不保证提高吞吐量，只限制峰值并发。

## 安装与回读

在没有正在加工/提交的窗口合入主干，然后使用项目 venv：

```sh
.venv/bin/python scripts/install_ffmpeg_slot.py --install
```

安装器初始化上述共享配置，并写本项目 venv 的 `video_ffmpeg_slot.pth`；禁止改全局 Python。重建 venv 后须重新安装。存活的旧解释器不会热加载：应待业务空闲后重载相应服务，不能把提交代码等同于运行采用。

回读证据：新解释器的 Popen 类来自 `video_processing.core.ffmpeg_slot`；`/api/stats` 的 `resource_control.ffmpeg_guard_enabled`；`output/ready_publications_status.json` 的 guard 标记、PID 和 Git revision。第三方 yt-dlp 的 Popen 继承同一守卫。以两个低负载本地合成作业验证排队，不制作或发布业务视频。

回退时只回退这次提交并移除本次安装的 venv `.pth`，然后在空闲窗口重载。不要删除正在使用的 `execution.lock`：删除会创建新 inode，破坏互斥。

## 其余策略仍为影子模式

磁盘低于 15 GiB 告警并给出同卷清理候选；不自动删生产文件、不延后任务。每 60 秒采样内存、swap、磁盘与重型阶段重叠。没有自动杀进程、改线程、改交易守卫、修改发布额度或重试历史投稿。

下一批建议观察：本地 Whisper/ASR 模型推理并发（优先评估全局 1）；本地模型加载/本地 TTS；英语世界 Python 图像合成；多个浏览器/AGY/IDE 同时占用内存。云端 TTS/API 请求不应仅因名字相似就限流。先记录 RSS、等待、耗时和发布延迟，再决定是否强制。

单个 FFmpeg 仍可能使用多个线程或大量内存。本次限制降低并发峰值，不保证消除整机卡死；一分钟影子采样也无法保证捕获短尖峰或在 OS 完全冻结时发出告警。

## 验收

使用 `scripts/run_isolated_tests.py`，禁止在生产 checkout 裸跑 pytest。覆盖跨进程串行、等待与超时预算、父进程死亡后真实 FFmpeg 持锁、等待者死亡、创建失败、取消、FFprobe/非媒体进程不受限、字幕心跳与两条管线回归。调度单测固定测试环境中的交易守卫，避免真实交易时钟使故障用例被跳过；生产守卫没有改变。
