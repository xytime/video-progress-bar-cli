# 商品配置发布接入状态（2026-10-11）

维护者：Codex；精确模型身份未知。

生产 main 为 6ce81b2；本工作区是隔离候选，未上线。线上 API 本轮回读 publisher_connected=false、last_selection=null。保存配置当前不会改变实际发布选品。

已同步生产完整商品目录导入功能、页面和固定测试夹具，保留 legacy ProductCatalog 契约，新增五类视频使用三本旧书之外商品的集成测试。167 项隔离单元/API/Chromium 测试通过：/private/tmp/video-pytest-k1idkfv3/receipt.json。这不是平台验收。

候选在开始选品时加载一次配置；已发布视频不追溯修改，已经开始选品的任务保持旧快照，尚未选品的任务使用最近保存版本。通用与英语世界入口传递对应上下文。不可用候选种子覆盖线上用户配置。

上线缺口：旧适配器用书名查本地目录补 ID；候选必须从最终绑定组件读取实际 ID 和完整名称。现有 product_frame_content.html 与 product_frame_data.json 均不含最终绑定卡片，不能证明候选的 data-product-id 或链接参数真实存在。需要最终绑定组件脱敏 DOM、商品身份来源和选择/确认/清空证据，不能用目录或旧 BOUND 回执替代。

此前宿主拒绝的真实站点操作不能换通道绕过。本轮没有访问该站点、启动发布器、正式发布、修改生产配置或重启服务。

后续：在允许环境取得最终绑定组件证据，修正并夹具验证适配器；选择性合入两入口、上传器、适配器和编排，保留线上配置与目录；确认运行版本后才标记连接；首条正常任务的配置采用、实际绑定、平台受理和作品回读分别验收。


## P1 确认后的更新

生产 main 已推进到 2fff558，独立管理功能上线（商品资料、影响预览、历史恢复和等待参数）。本候选已同步其 optional library/wait_policy 契约，避免发布时读取新配置失败；用户真实配置仍未复制到候选。P0 与 P1 联合隔离测试见 /private/tmp/video-pytest-n0n0erge/receipt.json。

P1 等待模块与接口已具备，但没有连接两种发布入口的真实调度；不能把 scheduler_connected 或 publisher_connected 手动改成 true 代替验收。工程师接入契约详见 wechat-product-link-2026-10-10.md 的最新 P1 实施记录。同步与平台最终绑定身份仍待真实证据。
