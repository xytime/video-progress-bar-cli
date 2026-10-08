# 华尔街事实炸弹 A/B 运营

作者：Codex；2026-10-09。视觉模板和配对规则见 `docs/specs/wallstreet-paired-ab.md`。

程序复用现有每分钟 cron 和常驻发布执行者，启动独立短进程读取持久队列。
关闭 Codex 不影响运行；主机、已有调度、平台登录与策划/配音服务须可用。
当前外部字幕策划授权待用户回复；`WALLSTREET_AB_REMOTE_PLANNING_AUTHORIZED=false`。
新 B 正常入队，但缺少本地脚本时保留待授权加工状态，A 继续正常发布；不得换供应商绕过。
用户明确同意将公开视频标题、字幕和二创脚本交给现有 AGY 服务后，才启用该配置。
已存在的本地审核 V2 脚本可继续制作、发布。本次最新 B 已通过此路径完成。
运行采用看 `output/ready_publications_status.json` 和 `output/wallstreet_worker_status.json` 的代码版本，
二创执行者按需退出后心跳停止，并由下一次巡检再次启动，不能把旧心跳当作存活证明。

```sh
PYTHONPATH=src .venv/bin/python scripts/run_wallstreet_ab.py --report
PYTHONPATH=src .venv/bin/python scripts/run_wallstreet_ab.py --pause
PYTHONPATH=src .venv/bin/python scripts/run_wallstreet_ab.py --activate
PYTHONPATH=src .venv/bin/python scripts/run_wallstreet_ab.py --retry-render 加工任务ID
```

暂停只停止新作品入组，不撤销已受理任务，也不重发已公开版本。首次启用时刻不会因恢复而改写。
修复加工失败原因后，可立即重试处于 RETRY 的加工任务；该命令不重置平台投稿。
正常 A 与独立 B 分别使用原生作品 ID；A 确认公开后同平台 B 至少等待 6 小时。
结果不明只读回查；只有票据证明抖音浏览器未启动时才能撤销票据并重新领取。
其他结果不明的任务不能重传；有明确原生 ID 后，以下命令只读核验后才能恢复绑定：

```sh
PYTHONPATH=src .venv/bin/python scripts/run_wallstreet_ab.py --bind-publication 2 --platform-post-id 原生作品ID
```

用户具名授权单条仅 B 时，可登记：

```sh
PYTHONPATH=src .venv/bin/python scripts/run_wallstreet_ab.py --enqueue-b-only YouTube视频ID
```

此命令同时阻止普通 A 自动提交；需要先完成共享素材加工，重复登记复用现有 B。
命令说明不是授权发布任意作品。使用前仍须对应用户发布授权及既有平台启用配置。

指标采用后台真实数据导入，尚未宣称自动抓取。示例 JSON：

```json
{
  "publication_id": 2,
  "platform_post_id": "实际原生作品ID",
  "horizon_hours": 24,
  "captured_at": 1791565400,
  "values": {"views": 1000, "likes": 20, "comments": 5, "shares": 8, "favorites": null},
  "evidence_path": "/实际后台导出或截图证据路径"
}
```

```sh
PYTHONPATH=src .venv/bin/python scripts/run_wallstreet_ab.py --import-metrics 真实快照.json
PYTHONPATH=src .venv/bin/python scripts/run_wallstreet_ab.py --report
```

示例数值必须替换为实际观测。以每版公开后 24/72/168 小时分开导入；同一时点累计值更新而不相加。
缺失字段填 null。报告区分平台原生发布时间和首次观察公开时间，并保留实际作品年龄。
同账号自然流量和固定先 A 后 B 存在时效及受众重叠偏差；20 组为复盘节点，不保证统计显著性。
