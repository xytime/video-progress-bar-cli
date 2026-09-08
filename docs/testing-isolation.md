---
created_by: Unknown_Model_fast
created_at: 2026-09-08T11:46:30+08:00
---

# 测试隔离入口

使用项目虚拟环境执行：

```bash
.venv/bin/python scripts/run_isolated_tests.py -- -q tests/unit --ignore=tests/unit/test_dashboard_interactions.py
.venv/bin/python scripts/run_isolated_tests.py -- --collect-only -q
.venv/bin/python scripts/run_isolated_tests.py -- -q tests/unit/test_test_sandbox.py
.venv/bin/python scripts/run_isolated_tests.py --browser -- -q tests/unit/test_dashboard_interactions.py tests/browser
```

影子工作区可以使用正式工作区的 `.venv/bin/python`，依赖只读，源码来自当前 runner 所在工作区。`--timeout 180` 放在分隔符 `--` 之前，后面传 pytest 参数。返回值保留 pytest 退出码；超时为 124、启动失败 127、隔离不可用为 2。禁止降级为裸 pytest。

每次创建 `/private/tmp/video-pytest-*/`，保留 `source-manifest.json`、`sandbox.sb`、`boundary-probe.log`、`pytest.log`、`receipt.json` 和 `sandbox/pytest.xml`。快照包含受维护的源码、测试与资源，也包含未提交且未被忽略的新文件；不复制正式 output、.env 及其变体、secrets。仅 `.env.example` 是公开模板例外。源链接被拒绝，依赖 venv 是工具显式创建的只读映射。不要把生成目录加入仓库；测试完成后按需人工清理指定运行目录。

测试子进程使用明确的环境允许清单，业务密钥、代理、PYTEST_ADDOPTS 和自动插件不会继承。显式加载现有 pytest-asyncio 插件。HOME 保持真实路径，供 Path.home() 常量解析，沙盒仍禁止读取或修改用户数据。系统目录、Python 和虚拟环境依赖只读；写入仅在本次 sandbox 根与 /dev/null。网络、向其他沙盒外进程发信号均被拒绝。默认模式拒绝所有 Mach lookup；浏览器模式只有下述 Chromium 名称例外。正式项目 output 的内容不在读取允许清单内。

正式 pytest 收集前，conftest 检查工具目录结构和外部无敏感 canary 的实际读取拒绝。runner 更早验证外部读写、网络、信号与子进程继承。这样即使业务模块默认构造 PipelineDB 或导入 web.app，它们也只初始化快照下的数据库。它是每次运行隔离，测试之间的默认库仍可能共享；需要彼此隔离的测试应继续使用 tmp_path/显式 DAL 注入。

验收分层：

| 范围 | 命令/状态解释 |
|---|---|
| 非浏览器单测 | 第一条命令；必须报告最终退出码、通过/失败/跳过数量，子测试单独计数 |
| 全量收集 | 第二条命令；收集成功不等于执行通过 |
| 浏览器交互 | 第四条命令；使用临时 Chromium 快照，dashboard 的 HTTP 请求由测试夹具接管，另有真实 OS 网络与外部 canary 文件拒绝断言 |
| 媒体集成 | `tests/integration/`、`tests/dragoneye/` 及根目录媒体测试须独立验收本地字体、渲染器、模型和样本；生产素材与密钥不会自动映射 |

浏览器模式显式传 `--browser`（位于 `--` 前）；不自动下载、不修改宿主缓存。runner 按当前 venv 的 Playwright 元数据选择已安装 headless shell，将约 200 MB 依赖复制到本次 sandbox/browser，散列复制字节并保留 `browser-runtime.json`；测试使用该精确路径，并校验实际浏览器版本。符号链接迁移过的缓存先解析根路径，运行包内部链接拒绝。缺依赖、未知 revision 覆盖和未启用此模式均明确失败，不转为 skip。当前支持 macOS arm64/x86_64 默认 Playwright 缓存布局；自定义缓存尚未适配。

Mach 许可仅匹配 `org.chromium.Chromium.MachPortRendezvousServer.<数字PID>`，用于浏览器与子进程交换端口；这不是仅允许本次 PID 的 OS 规则，不能当成对其他 Chromium IPC 完全隔离的证明。其协议机制与启动探针见 [研究记录](research/2026-09-08-browser-sandbox.md)。其他应用与系统通知/钥匙串等服务不在许可名单内；浏览器核心进程可能记录这些拒绝，页面控制台错误另行断言。网络拒绝依然覆盖浏览器，测试必须得到权限拒绝错误，不能以连接失败或超时替代。

桌面/窄屏交互截图与 JSON 位于 `sandbox/qa/browser/`，由本次测试生成，不写入仓库。截图用于查看实际效果；通过功能断言不等于移动端完整 UX 验收。完整单测加浏览器可运行 `--browser -- -q tests/unit tests/browser`，媒体集成仍属独立范围。

边界：此工具适用于当前 macOS 开发主机，不是跨平台容器、恶意代码执行服务或资源配额系统。超时清理工具创建的进程组；自行创建新会话的后代仍继承沙盒限制，但不承诺被组清理覆盖。它不消除测试内部状态污染，也不证明平台发布成功。大规模渲染和模型性能测试仍应避开线上加工。

## Version History
| Version | Date | Author | Description |
|---|---|---|---|
| 1.0 | 2026-09-08 | Unknown_Model_fast | 记录隔离入口、证据、测试分层和明确限制 |
| 1.1 | 2026-09-08 | Unknown_Model_fast | 增加明确浏览器模式、依赖快照、IPC 例外和真实边界/截图验收 |
