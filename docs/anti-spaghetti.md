# Anti-Spaghetti 静态扫描

使用项目 `.venv`，只读取目标源码，不导入目标模块、不加载业务 settings、不运行流水线。

```bash
./vpanel craft --check src/video_processing/core
./vpanel craft '有空格的路径/example.py' other.py
.venv/bin/python scripts/anti_spaghetti.py --check src/
```

`craft` / `antishit` 全局别名继续指向现有 vpanel。相对路径和默认 `src/` 均以调用者目录解析；跨项目无需该项目也有 vpanel。包装器自身位置仅用于选择扫描器及解释器，craft 不进入其他命令的 output 初始化流程。

| 退出码 | 含义 |
| --- | --- |
| 0 | 扫描完整且当前模式未触发失败；普通模式即使命中依赖规则仍只报告 |
| 1 | --check 下命中已实现的本地依赖规则 |
| 2 | 无效/空目标、读取/解码/语法/遍历失败、部分扫描不完整；优先于 1 |

尺寸告警始终不阻断。阈值是函数 60 行、类 400 行、类 16 个直接方法、5 个具名参数、4 层控制流；超过才提示。行数包含函数/类体内注释和空行。参数包含位置专用和关键字专用；直接实例/类方法排除 self/cls，静态方法及嵌套函数不排除；不计 *args/**kwargs。函数体嵌套从 0 计，elif 同级，try/except/finally 与 match/case 各作为一层，支持 async with/for。别名装饰器的运行语义不推断。

仅当文件位于扫描器所属 Video-precessing 根目录内，且核心源码标记存在时，启用项目规则：`src/video_processing/core`、`db`、`src/config` 不得静态依赖本地 `scripts`、`src/cli`、`src/web`。路径按完整段匹配，导入目标须在本地存在；同时解析仓库根与 src 导入布局，以及相对文件位置。`click` 不因名称前缀被当作 `cli`。规则不覆盖项目全部依赖方向或环路。

不会导入模块来推测动态 import、sys.path 修改或装饰器别名。无法解析的导入不作为确定性违规，已扫描只表示 AST 处理完成。报告不证明行为等价、整体架构健康或所有依赖合法，也没有基线/增量能力。

目录扫描排除隐藏目录、虚拟环境、构建缓存、draft-code 和 scratch。未排除的目录符号链接会报告不完整，需显式指定；文件符号链接按真实路径去重。所有成功扫描的文件都打印绝对路径。

技能维护源为本仓库 `.agents/skills/anti-spaghetti/SKILL.md`；全局安装文件是发布副本。更新维护源后复制到已安装宿主，再做格式校验和逐文件一致性核对。不要在副本中独立修订，也不要把文件一致等同于宿主已加载。

现有 Antigravity 副本可核对：

```bash
cmp .agents/skills/anti-spaghetti/SKILL.md "$HOME/.gemini/config/skills/anti-spaghetti/SKILL.md"
```

测试使用 `scripts/run_isolated_tests.py -- -q tests/unit/test_anti_spaghetti.py`。隔离 runner 将 vpanel/vhelp 作为只读源码快照纳入，以便真实包装器在临时项目中接受测试。
