# 视频号可配置选品交付

作者：Codex；2026-10-11。基线 main `d81b2db`；开发分支 `codex/wechat-product-config`。

用户已确认可配置方案并要求执行开发。当前完成候选代码和隔离验证，尚未切换生产或进行真实平台验收。生产主目录及正在进行的发布未改动。

## 行为与入口

唯一策略文件：`config/wechat_products.json`。依赖：`scripts → utils.wechat_product_config / wechat_product_selection / wechat_product_picker → core.wechat_product_policy`，路径由 Settings 提供。

- 固定优先级：单条 `--product-alias` > 来源频道 ID > 分类 > 默认。
- 初始映射：财经/华尔街→《股市趋势技术分析》；新闻/资讯/时事→维特根斯坦；其余→《思考快与慢》。沿用已核实商品 ID 与完整名称。
- 每条规则候选后追加全局默认并按 ID 去重。默认 30 秒/2 次，上限 60 秒/3 次；配置的默认候选必须在次数限制内可达。
- 规则支持新增商品别名、分类同义词、频道与备用默认。变更不需改业务代码；每条任务开始选品时加载一次不可变快照。
- `enabled=false` 商品不能被规则/default 引用。修改时同步调整引用；相同商品可以被不同规则共用。
- 默认要求挂载；关闭全局开关且未显式 `--require-product` 时阻止该条提交，不恢复无商品发布。
- 旧环境变量 `WECHAT_PRODUCT_TIMEOUT_SECONDS` 仅兼容读取，新逻辑预算完全由 JSON 决定。

## 本地维护命令

在包含此开发版本的 checkout 中执行。独立 worktree 没有自己的 venv，必须保留命令中的 `PYTHONPATH=src`，确保 venv 启动钩子导入当前 checkout；可将 `.venv/bin/python` 替换为生产目录的 venv Python 绝对路径。

```sh
PYTHONPATH=src .venv/bin/python scripts/wechat_product_config.py preview --category 财经
PYTHONPATH=src .venv/bin/python scripts/wechat_product_config.py preview --video-id VIDEO_ID
PYTHONPATH=src .venv/bin/python scripts/wechat_product_config.py preview --category 新闻 --product-alias finance
PYTHONPATH=src .venv/bin/python scripts/wechat_product_config.py status
```

`--video-id` 从本地 `output/VIDEO_ID_category.txt` 和 `output/VIDEO_ID.info.json` 读取输入，显式参数优先。预览不会访问平台，也不会写实际采用状态。

先复制策略为候选文件，更新 `version`、商品目录和规则，再校验/激活；不要直接编辑正在使用的文件：

```sh
PYTHONPATH=src .venv/bin/python scripts/wechat_product_config.py validate /absolute/path/to/candidate.json
PYTHONPATH=src .venv/bin/python scripts/wechat_product_config.py apply /absolute/path/to/candidate.json
```

`--config /absolute/path/to/active.json` 可在子命令前指定有效文件。apply 先验证完整配置后原子替换；失败退出码 2，并显示仍在生效的旧版本。首次缺配置或有效文件被直接破坏时阻止投稿。

现有 uploader 命令可附加 `--product-alias finance|news|default`；新增别名自动可用。预览与真实选择均使用同一决定函数。

## 证据与回退

实际选品写入投稿证据目录：

- `product_policy_snapshot.json`：冻结配置。
- `product_policy_adoption.json`：加载版本、内容摘要、匹配规则、输入、阶段和时间。
- `product_selection_receipt.json`：逐候选尝试、失败/回退原因、实际 ID 与完整名称。
- 原 `submission_receipt.json`：原生投稿 ID 关联同一配置摘要及表单商品身份。

全局 `output/wechat_product_runtime.json` 只由实际 uploader 选品调用写入。status 分开显示已保存版本和最近选品采用版本；STARTED/BOUND 仍不等于平台受理或播放页购买成功。新的配置不会改变已开始的选品，也不重发已受理视频。

若需撤回一份配置，用 apply 激活保留的上一份合法配置。代码上线前须保留已有运行基线；不要通过关闭开关实现空挂。

## 测试与上线缺口

测试命令：

```sh
PYTHONPATH=src .venv/bin/python scripts/run_isolated_tests.py --browser -- -q tests/browser/test_wechat_product_picker_browser.py tests/unit/test_wechat_product_selection.py tests/unit/test_wechat_product_picker.py tests/unit/test_wechat_product_config.py tests/unit/test_wechat_publications.py tests/unit/test_wechat_duplicate_guard.py tests/unit/test_wechat_upload_recovery.py tests/unit/test_wechat_publish_controls_contract.py
```

**最终隔离回归：173 passed（含 17 项真实 Chromium 合成页面测试）**。完整命令与哈希见本目录 `test-receipt.json`，输出见 `test-result.txt`。本地 CLI 实跑 preview 命中 finance，status 明确返回 `last_selection=null`、`adopted_by_last_selection=false`，未伪造生产采用。

浏览器测试使用隔离 Chromium、合成 DOM、独立上下文及全请求拦截，不连接真实平台。覆盖精确 ID、同名不同 ID、标题缺失/身份不明、iframe、二次确认、取消残留、默认回退、100ms 预算及 Playwright 异常转换；配置测试覆盖优先级、原子更新、冻结快照与采用记录。

**上线前仍缺真实页面接口验证**：新适配器只接受商品卡 DOM 中的实际 `data-product-id` 或商品链接中的 `product_id/productId` 加完整名称。现有本地交付报告未提供这些字段在当前发布表单中存在的证据。旧适配器由书名反查本地 ID 的做法已移除；如果平台只给书名，新版会以 `BindingIdentityUnavailable` 阻止提交。不能将合成 DOM 通过当成平台适配完成。

因此本轮保留候选分支，不替换正在发布的线上 uploader、不重启服务、不主动发正式测试。此前宿主浏览器安全拒绝所覆盖的真实平台操作，不通过 CLI/CDP/其他浏览器或委派绕过。此限制不影响本次已完成的代码、离线验证、Git 交付与本地预览。

后续完成上述平台接口验证后，再在发布空闲窗口合入 main；正常投稿回执应证明新版配置已采用，并分别取得平台受理、后台挂载、播放页购买入口证据。没有这些证据前不标记“上线验证完成”。
