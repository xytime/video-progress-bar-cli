# 字幕人工复核后放行一次

维护：Codex，2026-11-02。适用于尚未投稿的 `FAILED` / `PENDING` 任务；不代表内容审核豁免或平台发布许可。

1. 人工核对原片、错误及修复证据。用 `GET /api/videos/{youtube_id}/subtitle-review?slice_index=0` 取得当前 `review_token`、`expected_receipt_sha` 和 `releasable`。
2. 调用 `POST /api/videos/{youtube_id}/subtitle-release?slice_index=0`，JSON 必须包含：

   ```json
   {
     "expected_review_token": "GET 返回的 64 位摘要",
     "expected_receipt_sha": "GET 返回的 64 位摘要",
     "actor": "实际操作者或受托执行者",
     "reason": "已核实的画面证据、修复与单次试跑理由"
   }
   ```

3. 成功返回 `PENDING` / `allowed_claims: 1`，等待原调度器正常领取。24 小时内未领取则授权失效，重新核查；同一失败证据不能重复签发。不要在超时或断线后盲目重发 POST，先 GET 和查审计记录。

原错误、失败事件、翻译预算、原凭据和原期限均保留。有 recovery 行的任务仍绑定该行的最近凭据；没有行的旧失败则以任务主键、YouTube/切片身份、完整错误和最后失败事件序号计算 CAS 摘要。任何失败证据变化都会拒绝旧 token。

`subtitle_recovery_events` 追加 `RELEASED`，保留操作者、时间、原因、授权截止及覆盖的失败序号；原子状态领取在同一 SQLite 事务追加 `CLAIMED`。字幕成功的源文件绑定凭据验证后追加 `RESOLVED`，后续走正常审核。失败、超时或被重新排队不能自动续用已消费授权。GET 的 `last_release` 可回读最后一次放行审计。

`retry`、切片重试、恢复批次、`respec`、`reset-hard` 和自动加工/发布领取共用字幕门禁。已有平台意图/回执、忽略、黑名单、身份、内容审核和频道准入保护保持有效。维护期间不接受放行写入。`actor` 是后台可信操作者填写的审计标签，不冒充独立认证身份。

画面修复边界：微窄竖片最多容忍 2% 宽度差，按完整高度缩放后居中补边；超过边界继续转人工。画面标题须有有界时序、独立排版或配对文字证据；静止或不匹配 ASR 本身不足以放过。原 OCR 保留为避让障碍，标题不进入对白擦除掩膜；独立分类模块摘要进入处理计划与成片凭据。
