# 原审计命中证据补齐与验收

编写：Codex，2026-10-17。用户确认最小范围：补齐真实命中词、字幕时间、上下文和规则依据，隔离测试后原生维护采用。#6134 保持失败、不重试，不新增历史内容自动豁免，不改评分、时长、热度、内容门槛及发布授权。

## 实现及证据边界

现有“复核放行”弹窗新增“原审计命中证据”，区分原审计与当前重扫标签。使用原输入哈希、规则指纹及判定核实只读回放；任一缺失或不一致明确显示无法核实，不把当前命中冒充原命中，不补造时间。原审计记录保持原样。新审计的原文摘录取自实际命中附近，避免固定截取开头遗漏命中。

共现解释与引擎共用原遍历顺序；没有改成最近词对，判定不变。VTT 保留排序、重叠自动字幕、实体解码及截断口径，仅增加 cue 时间绑定；无可核实 cue 就不显示推测时间。文本通过 textContent 展示，保留现有 P0 双确认；读取失败清除旧证据并禁用确认。

#6134（jD_5JhBOJWg）的原审计203为 `blocklist.P0.en.china_sensitive_negative_news`，规则版本 `1190d2cf041c1a84`、输入哈希 `9bc476d4bf798fac`。原遍历命中 China（00:06:21.280–00:06:23.630）和 killed（00:06:23.699–00:06:27.200），归一化间隔87≤240字符。上下文谈1910年肺鼠疫，但原规则没有历史内容自动豁免；本期不新增豁免。

## 隔离验收

整合副本包含生产1526份受维护文件及并行改动，再覆盖本期源码、模板和测试。首次专项因忽略规则漏带 VTT fixture 失败，已显式纳入原样 fixture，保留断言修复。

- 扩大回归 `video-pytest-demwxguh`：803 passed／12 warnings，runner exit0、隔离边界探针通过、沙箱回收；覆盖审核、关键词长期准入／账本、维护／部署及浏览器。
- 增加畸形空结束时间 VTT 的防护后，受影响回归 `video-pytest-tntqmy7_`：62 passed／6 warnings，runner exit0、边界探针通过、沙箱回收。该轮源码清单 SHA256 `a0e303807a7d310ed1d5184a4edc88687507ff183280f12ace00642537b96e7f`。两轮不是一次全量同快照测试，不相加冒称独立用例数。
- 三主题桌面1280×900、手机390×844共6张初始截图已回看；真实 Chromium 验证故障清理、注入文本不可执行、P0 双确认、只读GET不改变任务／审计／黑名单。生产实际长标签另有下述补测，初始截图不代替真实长标签验收。当前无浏览器插件，使用项目隔离 Playwright。手机模拟不等同真实 Safari。
- 生产实测发现原有标签云的长规则名 `china_sensitive_negative_news` 导致手机弹窗横向溢出，新增证据区本身未溢出。只补标签云 `overflow-wrap:anywhere`，并把真实长规则名加入浏览器样例，保留弹窗及标签云宽度断言。`video-pytest-ilxm0ifd`：4 passed／6 warnings，runner exit0、隔离探针通过、沙箱回收。采用清单 SHA256 `f3dff37e13141a8b2ca70da8fd2b65e1129872f18074d1450e3b2f9c4c599638`。此轮仅覆盖受影响浏览器测试，不冒称全量同快照回归。

[测试收据](evidence/censorship-hit-evidence/isolated-tests.json)；[浅色手机](evidence/censorship-hit-evidence/evidence-light-390.png)、[深色桌面](evidence/censorship-hit-evidence/evidence-dark-1280.png)、[高对比手机](evidence/censorship-hit-evidence/evidence-contrast-390.png)。

## 生产维护采用与真实验收

14:18现场：生产main284732b，六类存活角色真实birth/hash/cwd一致，来源hash `df911b5285c439f953ebe692ef0b7535f7aaf85a097ba157f95fb631e1f6dd2a`；RUNNING70、active=[]，宿主带时区窗口允许、完整LONG_TERM加载通过。轻量空闲不替代后续原生完整来源检查。

14:19 Cloud只读配额：搜索4/100、通用417/10,000；未读取凭据或密钥。26项dirty与1245条untracked须原样保留。#6134仍FAILED、bypass0、黑名单保留、无人工P0批准，账本仍5947／6134／6135。

两轮均使用全新 `--preserve-keyword-profile` 原生计划：正常 CSRF/CAS 控制面关闭准入／搜索，原生暂停新接纳、自然排空、正常停止、一致性备份、采用、维护启动、恢复调度及最终回读。未强杀、删锁、改指纹、修改或重放旧 journal。

| 采用 | 目标 | 原生计划 | 北京时间完成 | 结果 |
| --- | --- | --- | --- | --- |
| 命中证据功能 | b34e253 | 1e615194ecaa42e09042b0b91855c50f | 2026-10-17 14:22:18 | 九步 COMPLETE；resume 预检曾拒绝，先 status 确认，再原生完整检查通过后 recover |
| 长标签手机换行补修 | 0c73485 | ac690d3c2c5d48f6b82106006fdc1e30 | 2026-10-17 14:28:41 | 新计划九步 COMPLETE，独立最终回读通过 |

14:29最终回读：RUNNING74／IDLE，active=[]、unknown=[]；六类存活角色真实 birth/hash/cwd 一致。运行来源 hash `accd085cefebde8a5a550549a3b8d3e490db14935dc2247769396c1111e454d2`，纯模板补修未改变 Python 来源。完整 LONG_TERM 加载通过，配置 identity `0d370b08315fee81c05549f60fcc804a75b1cc992c420742d95bcc227b35a6bb`。正常控制面恢复 DISCOVERY_ONLY/version68、admission1/version22，调度自然状态 REFRESH_OR_ADMISSION；原有日20搜索／40详情及长期准入策略不变。

采用前后精确比对：26项 dirty 文件哈希、1245条 untracked 路径均保留；#6134整条任务、原审计、黑名单状态、人工P0批准状态及完整准入账本均未变。#6134仍 FAILED、bypass0、黑名单保留、无人工P0批准；没有重试、放行或退款。

真实生产浏览器读取失败列表中 #6134 的“复核放行”弹窗，1280×900和390×844均通过：原审计203、China／killed、两个VTT时间区间、87≤240字符、1910年上下文和规则版本均显示；两项P0确认默认未选、确认按钮禁用、取消正常关闭；页面／弹窗／证据区无横向溢出。浏览器只允许本机 GET/HEAD，未发业务写请求、无页面脚本异常；外部 Google 字体请求被验证脚本主动阻断，保留对应网络控制台记录。手机为 Chromium 视口模拟，不宣称真实 Safari／微信内置浏览器已验收。

入口：[生产失败任务筛选](http://127.0.0.1:9100/?view=videos&tab=error&created_window=all&search=jD_5JhBOJWg) → #6134 → 复核放行 → 原审计命中证据。查看无需勾选确认或执行放行。

证据：[首次采用回读](evidence/censorship-hit-evidence/production-20261017.json)、[补修最终回读](evidence/censorship-hit-evidence/production-layout-20261017.json)、[生产浏览器记录](evidence/censorship-hit-evidence/production-browser.json)、[桌面截图](evidence/censorship-hit-evidence/production-1280.png)、[手机截图](evidence/censorship-hit-evidence/production-390.png)。本期已完成确认范围；历史内容豁免及 #6134 重试均未实施。
