# 视频后台独立 YouTube 出口

2026-10-27 · Codex · 用户已确认实施。目标是让桌面代理客户端的切换、退出和端口变化不再影响后台 YouTube 获取。

```mermaid
flowchart LR
  A[后台发现 / 元数据 / 下载] --> B[127.0.0.1:9110]
  B --> C[独立 mihomo / en0]
  C --> D[自建 Hysteria2]
  D --> E[YouTube / googlevideo]
  F[猫熊或 Clash Mi] --> G[桌面应用网络]
```

## 运行约定

- `us.optionbank.video-egress` 是独立的用户 LaunchAgent，登录时启动，退出后由 launchd 拉起（ThrottleInterval 10 秒）。当前不承诺开机尚无人登录、休眠、断网时可用。
- 内核、配置和节点文件复制到 `~/.local/share/video-egress/`，不再引用桌面客户端运行文件。目录仅本人可读，节点文件权限 600，不纳入 Git。
- 代理仅监听 `127.0.0.1:9110`。控制面只有私有目录内的 Unix socket，不使用桌面 9090/19090 端口或其密钥。
- 唯一出站组 `VIDEO_SELF_ONLY` 只含指定自建节点；没有直连、付费节点或桌面代理回退。物理接口明确绑定 `en0`；更换联网接口需要重新配置并验收，不能任意跟随 TUN。
- 服务不设置系统代理、不启用 TUN、不监听系统 DNS。桌面 VPN 不负责其生命周期。若其他软件改变防火墙、物理路由或阻断自建服务器，仍可能失败。
- 获取前通过真实 YouTube TLS 连接和本机连接表核验出口。RSS、Data API、元数据查询和媒体下载共用此边界。下载失败继续遵循现有缓存和冷却逻辑，不触发发布或清除检查点。
- launchd 负责进程存活，不保证服务器、DNS、YouTube 服务或认证永不失效，也不会自动更换自建节点。内核采用固定副本；升级和节点变更须重新做下载验收。

## 运维

在项目根目录只读检查：

```sh
.venv/bin/python scripts/youtube_egress_service.py health
launchctl print gui/$(id -u)/us.optionbank.video-egress
```

首次安装使用 `scripts/youtube_egress_service.py install`，默认只预览，显式 `--execute` 才安装。传入已有节点文件和受信任内核的路径，不在命令行写凭据。已有安装会拒绝覆盖。运行配置的单一来源在 `settings.py`，对应 `.env.example` 的 `YOUTUBE_DOWNLOAD_PROXY`、`YOUTUBE_EGRESS_ROOT`、`YOUTUBE_EGRESS_INTERFACE` 和 `YOUTUBE_CONTROLLER_SOCKET`。

故障定位顺序：先运行 health，再检查监听和物理网卡，最后检查自建服务器。不要为了让健康检查变绿而取消出口保护。安装文件哈希保存在私有 manifest 中；无需输出节点文件或带签名的媒体 URL。

停止或重新加载服务应在后台获取空闲时进行。旧项目入口的两项值保存在私有 `project-before.json`，用于明确回滚；回到旧入口会重新依赖桌面客户端，不能作为自动兜底。后台代码采用走原生 deployment_control 流程，保存当前调度和授权状态。

## 实际验收证据

本机证据目录：`output/youtube-egress-acceptance-20261027/`，其中原始下载日志可能含临时签名 URL，不对外复制。

- 原目标视频 `AkTXAcMgO3E`：`continuous.mp4`，855.051610 秒，23,511,919 字节，AV1 视频和 AAC 音频；完整解码返回 0。
- 持续下载期间依次验证：猫熊 17890 → Clash Mi 7890 → 两个桌面入口均关闭 → 恢复猫熊。独立入口 9110 全程存在，媒体连接链均为指定自建节点 → `VIDEO_SELF_ONLY`。
- 三种客户端状态分别下载 20 秒真实音视频，各生成 573,304 字节 MP4。完整视频及片段只作本地验收，不进入发布队列。
- 切换结果、端口状态和媒体连接字节见 `roundtrip.json`，日常客户端最终恢复成功。
- 测试与运行采用是两种证据：隔离回归测试清单由 TestRuns 保存；后台常驻进程是否采用新代码，以原生部署 COMPLETE 回执为准。

本次覆盖当前安装版本和当前网络模式，没有实测主机重启、任意第三方 TUN、防火墙变更或自建服务器失效后的跨节点切换。
