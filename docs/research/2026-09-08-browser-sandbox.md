---
created_by: Unknown_Model_fast
created_at: 2026-09-08T12:09:00+08:00
---

# 浏览器隔离启动探针

目标：验证不开放网络和正式数据能否启动 headless Chromium。

方法：调用现有 runner 创建一次性源码和 profile；在沙盒启动已安装 Playwright Chromium，加载内联 HTML 并检查标题和标题元素。每次最多 25 秒，均未连接正式服务。

证据：
- `/private/tmp/video-pytest-yxcok3xg/`：退出 1，符号路径许可不匹配外置盘真实缓存，ICU 无法读取。
- `/private/tmp/video-pytest-wmink12p/`：解析真实目录后启动成功，创建页面失败。
- `/private/tmp/video-pytest-mo_f2xgp/`：退出 124；DEBUG 日志明确拒绝 `org.chromium.Chromium.MachPortRendezvousServer.<pid>`，子进程无法交换端口。
- `/private/tmp/video-pytest-9rec49sk/`：只增加上述名称模式的 Mach lookup，1.226 秒、退出 0；真实标题和 h1 均为 Isolated Browser Probe，浏览器正常退出。

[Chromium 官方源码](https://chromium.googlesource.com/chromium/src/%2B/refs/tags/140.0.7319.0/base/apple/mach_port_rendezvous_mac.cc)将端口按预登记 PID 保存，并按请求的 audit token PID 取回；[官方沙盒策略](https://chromium.googlesource.com/chromium/src/%2B/refs/heads/main/sandbox/policy/mac/common.sb)也显式允许此服务。源码版本与本机 148 不同，因此这里只用作机制解释，不作为对已安装二进制完整安全审计的替代。

结论：采用一次性浏览器运行包复制（本机 19 文件、199614542 字节），精确执行路径与文件 SHA；仅在显式 browser 模式添加 rendezvous 名称许可。其他系统服务继续拒绝。它避免测试写入共享缓存，仍需补真实浏览器网络/文件拒绝探针和全部行为验收。

| Version | Date | Author | Description |
|---|---|---|---|
| 1.0 | 2026-09-08 | Unknown_Model_fast | 记录只读依赖与最小 IPC 探针结果、证据和局限 |
