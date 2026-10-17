# 维护部署 v0.1 验收

记录：Codex，2026-10-13 14:19（北京时间）。依据用户已确认的 [v0.1 规格](../../specs/deployment-fail-closed-v0.1.md)。

结论：隔离故障验收、首次安装、新入口真实同版本维护循环均通过；首页和关键词入口在生产可用。搜索保持关闭，凭据归属与共享配额仍未核实。本次不执行真实搜索，也不创建验收用生产业务任务。

## 实现及测试

新增 `vpanel deploy plan/apply/status/recover`：以真实项目锁串行执行基线、冻结、停止、备份、采用、维护启动、恢复维护、恢复调度、最终验证。步骤失败立即停止，持久化回执；未知结果不盲目重放，不自动启动或解除维护。沿用原维护检查及源码指纹算法，没有忽略进程、改写角色锁、强杀或删锁。

数据库一致性备份封装于 DAL；正常退出核验 PID/birth/归属与 launchd 实际卸载。cron/plist 来源、实际加载配置、新增同项目服务、原启用/加载状态均参与核验；一次性 RunAtLoad 不集中补跑。目标源码必须和测试清单一致，重叠 dirty 只接受预先整合并测试的文件。

代码提交 `a1702a57bf7c6144498e2ff60cefacbc455344b2`。最终生产整合副本通过 **230 项**，包括部署故障、旧维护入口、真实 SQLite/WAL、真实进程/互斥、Git 三方整合、关键词/API、首页指标与数据库切片回归。4 条既有 FastAPI 生命周期弃用警告。OS 探针确认外部读写、网络、外部信号及子进程写入均被拒绝；探针 `-I` 模式有既有 `.pth` 导入告警，但探针成功、退出 0，原日志保留。macOS 服务故障注入使用受控替身；下述生产循环验证真实服务控制正常路径，不把隔离故障注入描述为生产故障测试。

测试清单 SHA-256：`9aae2cae7466337f3a36e9a27275647d9cbcc250d2b40b4af06654645f7afc18`。此前 119 项专项结果包含于本轮 230 项，不累加计数。

## 生产采用证据

首次安装与新入口验收分开记录。初次只读计划因 macOS `/var` 路径别名被符号链接防护拒绝，在任何维护/源码动作之前停止；改为真实规范路径后重新生成计划，未放宽防护。

首次安装用外部逐步控制器逐项调用已测适配器；维护核心始终加载生产原实现，新 DAL 备份静态方法来自已测整合副本。每次只执行一个动作，检查退出、结果和后置状态后才调用下一步。首次安装不宣称由尚未落地的 CLI 完成。私有回执目录 `~/Library/Application Support/VideoProcessing/deployments/deployment-v01-bootstrap-20261013-b`。

- 源码从 `6cf43c0` 快进到 `a1702a5`；本次严格在正常停止及 SQLite 备份验证成功之后采用，备份 integrity_check=ok。
- 新版在 MAINTENANCE 内启动，完整 inspection 通过，再按维护版本 CAS 恢复；原 cron 及七个 launchd 状态、加载配置回读通过。
- 七项原 tracked 开发改动保留。数据库文件采用已测三方整合结果；其余六项逐字保持，原未跟踪清单及全部运行源码核对通过。原 DB 文件另有私有副本，未 stash/reset 或覆盖无关工作。
- 随后直接从生产使用 `vpanel deploy plan/apply`，针对相同提交执行真实维护循环：九步全部完成，journal=COMPLETE、pending=null。私有目录 `~/Library/Application Support/VideoProcessing/deployments/deployment-v01-cycle-20261013`。
- 对已完成循环再次 apply，仅回读最终状态；journal 时间及步骤不变，没有再次备份、停机或采用。

最终运行指纹：`1ba394b75641dc4a09b0746ad7536d965266af719bd2f7370312264b13b6a7a4`。UI PID 34967、ready-worker PID 35304；六角色同指纹，PID/birth/cwd 一致。维护 RUNNING v8；搜索 OFF v7、search_open=false、can_enable=false、jobs=[]，配额日 2026-10-12（太平洋时间）搜索/详情均 0。维护期间 OFF 版本递增是既有关闭逻辑，不表示搜索曾开放。

恢复调度后曾观察到既有 wallstreet-render 自然运行并结束；本验收没有发起该业务，未干预。14:19 回读 active=[]。不宣称恢复 RUNNING 后整个生产永久没有其他任务。无来源证明的普通 status 返回 SOURCES_NOT_VERIFIED 是预期；部署各维护步骤使用当时新生成并校验通过的完整来源证明，不能拿普通 status 冒充 safe=true。

既有 bot EX_CONFIG 问题仍属另案，未宣称所有服务业务健康。

## 用户路径回读

浏览器刷新实际首页后显示“生产搜索关闭”；“建议先查看”按三类事项分组，指标显示入库批次及分子/分母。从首页直接点击“关键词追踪”成功到达工作台，明确列出凭据所属项目、共享配额及试运行前置条件；开启手动搜索和搜索候选按钮禁用，候选空态及尚无搜索记录正确。通过面包屑回首页成功。

本轮页面为只读复验，未重新在生产注入网络故障；错误提示与恢复行为沿用 v0.3.1 的实际浏览器验收，本轮相关单元/API 回归通过。截图见 `evidence/production-home.png` 与 `production-keyword.png`；运行/调度、保留清单、备份与步骤摘要见同目录 JSON。数据库、完整来源清单、plist 及 cron 原文留在私有目录，不提交密钥或数据库。

## 运维用法与下一步

```sh
./vpanel deploy plan --directory <新的私有绝对目录> --target <已确认提交> --tested-manifest <隔离测试source-manifest.json> --overlay <已测整合副本真实绝对路径>
./vpanel deploy apply --directory <同一目录>
./vpanel deploy status --directory <同一目录>
./vpanel deploy recover --directory <同一目录>
```

`plan` 仅在新私有目录生成计划，不改变运行。无重叠 dirty 可省略 overlay。必须先验收最终源码；不要把未验收的源码清单作为测试证据。apply 非零后先看 status 与现场；recover 重新核实后置事实，不能作为强制通过开关。部分采用/部分恢复无法消歧时保持现场，需具体核实后人工处置；首期无自动 Git/数据库回滚。

建议用户从首页完成入口验收。下一步补齐生产凭据到 Cloud 项目/凭据资源的非秘密证明与共享调用者清单；未核实前保持搜索关闭。未来运行中新增受指纹覆盖的 Python 仍会触发来源拒绝，应在维护窗口内采用，不能通过修改指纹算法规避。
