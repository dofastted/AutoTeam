# 远端同步

## 分发入口

`src/autoteam/sync_targets.py`: 根据运行配置决定启用 CPA、Sub2API 或两者。

- `SYNC_TARGET_CPA` 控制 CPA。
- `SYNC_TARGET_SUB2API` 控制 Sub2API。
- 未显式设置开关时，存在完整连接配置会被视为启用。

## 推荐同步模型

前台账号操作不应等待 CPA / Sub2API 完整同步完成。新增账号、恢复账号、上传单个认证文件后，应先把本地账号状态和 `auth_file` 保存好，再创建后台同步任务。

推荐把同步分成两类任务：

- 前台任务：注册、登录、恢复、移出、删除、Team 状态读取。
- 后台同步任务：CPA 文件上传、Sub2API 账号创建或更新、远端数量核对、失败重试。

后台同步只按差异上传：

- 先读取本地 `accounts.json` 中未禁用同步的 `active` 账号。
- 只选择存在 `auth_file` 且本地文件可读的账号。
- 读取 CPA / Sub2API 远端列表，以邮箱和文件名匹配。
- 远端已有同邮箱或同名文件时跳过，远端缺失时上传或更新。
- 默认不删除远端文件。删除必须走单独的清理任务，并带明确确认。
- `sold` 或 `sync_disabled=true` 的账号不上传、不更新。

错误处理默认采用暂停优先：

- 网络错误、HTTP 429、HTTP 5xx 可按配置自动重试。
- 同一账号连续失败达到上限时，记录错误并暂停该批任务。
- 认证文件缺失、token 无效、配置缺失属于不可自动修复错误，应立即暂停。
- 暂停记录写入任务状态，前端只负责显示错误和恢复按钮。

推荐配置：

- `SYNC_EXECUTION_MODE=async`: 默认异步。可选 `inline` 仅用于本地排查。
- `SYNC_UPLOAD_STRATEGY=incremental`: 默认差异上传。可选 `full` 只用于人工修复。
- `SYNC_DELETE_MISSING=false`: 默认不删除远端缺失匹配项。
- `SYNC_FAILURE_POLICY=pause`: 默认遇到不可自动修复错误暂停。可选 `continue` 只适合人工批量修复。
- `SYNC_AUTO_RETRY=transient`: 默认只重试网络、429、5xx。可选 `off`、`always`。
- `SYNC_RETRY_MAX_ATTEMPTS=3`: 单账号或单远端动作最多尝试 3 次。
- `SYNC_RETRY_BACKOFF_SECONDS=5,30,120`: 重试等待时间。
- `SYNC_PAUSE_ON_SUCCESS_RATE_BELOW=95`: 批量任务成功率低于阈值时暂停。

当前代码里 `/api/sync/cpa` 只同步 `active` 账号，并会删除本地管理但已非 active 的远端 CPA 文件。要补传 `standby` 账号的 CPA 文件，不应复用该接口；应新增只上传、不删除的增量补传任务。

## CPA

`src/autoteam/cpa_sync.py`: 负责 CPA 认证文件列表、上传、删除、下载、去重、正向同步、反向同步、主号文件同步。

正向同步 `sync_to_cpa`：

- 读取本地账号。
- 修复断裂的 `auth_file` 路径。
- 只上传未禁用同步的 active 账号认证文件。
- 删除 CPA 中本地管理账号但不再 active 的文件。
- 返回上传、删除、本地去重等统计结果。

已售账号：

- `POST /api/accounts/{email}/sell` 调用 `src/autoteam/sync_targets.py` (`delete_account_from_configured_targets`)。
- CPA 侧按邮箱或本地 auth 文件名删除远端文件。
- 删除后本地账号标记为 `sold` 和 `sync_disabled=true`，后续 `/api/sync/cpa` 不会重新上传。

增量补传 CPA 文件时，应新增独立入口，不改变 `sync_to_cpa` 的删除语义。该入口只做上传：

- 匹配范围：`active` 与可复用 `standby`。
- 匹配键：优先邮箱，其次认证文件名。
- 已存在：跳过。
- 不存在：上传本地 `auth_file`。
- 上传成功后可写 `cpa_uploaded_at` 与独立同步任务记录。
- 上传失败按 `SYNC_AUTO_RETRY` 与 `SYNC_FAILURE_POLICY` 处理。

HTTP 入口：

- `/api/sync`: 按已启用目标同步 CPA / Sub2API。
- `/api/sync/cpa`: 只同步 CPA，账号池操作页的 CPA 推送按钮使用这个入口。
- `/api/sync/sub2api`: 只同步 Sub2API，账号池操作页和同步中心的 Sub2API 推送按钮使用这个入口。

反向同步 `sync_from_cpa`：

- 下载 CPA 中的 `codex-*.json`。
- 按账号去重。
- 比较 `last_refresh` 和 `expired`。
- CPA 文件更旧时保留本地文件。
- 新导入账号默认写为 standby。

单账号 CPA 认证入口：

- `src/autoteam/api.py` (`post_account_cpa_auth`): 面向 Web OAuth 页。仅允许 active 席位账号。若本地有 auth 文件则上传；若没有则自动执行 Codex OAuth，确认 `plan_type=team` 后上传。
- `src/autoteam/cpa_batch.py` (`run_cpa_batch`): 批量直注账号在注册成功后优先使用 ChatGPT Web session 生成本地 auth 文件，再上传 CPA；该批量路径不依赖 Codex OAuth callback。
- `src/autoteam/cpa_batch.py` (`_CpaUploadWorker`): 每个账号 CPA 上传成功后，若 Sub2API 已启用，会调用 `src/autoteam/sub2api_sync.py` (`sync_account_to_sub2api`) 单独同步该账号。

## Sub2API

`src/autoteam/sub2api_sync.py`: 负责登录 Sub2API、读取 OpenAI OAuth 账号、上传账号池认证文件、同步主号认证文件、处理 `SUB2API_GROUP`。

`SUB2API_GROUP` 可填分组名或分组 ID，多个值用逗号分隔。同步时会保留用户手工绑定的其他分组，只替换 AutoTeam 管理的分组绑定。分组不存在时，账号推送和按邮箱去重仍会继续，返回结果的 `warnings` 会说明已跳过分组绑定。

账号池推送到 Sub2API 时，以邮箱为去重键。若远端已有同邮箱 OpenAI OAuth 账号，会更新已有账号而不是新建；AutoTeam 自己标记的重复账号会删除多余项。同步 payload 按 `C:\Users\Administrator\Downloads\sub2api示列.json` 的 OpenAI OAuth 账号结构生成，固定写入 `model_mapping`、`privacy_mode=training_off`、`openai_oauth_responses_websockets_v2_mode=off`、并覆盖基础调度字段。全量同步会删除本地管理范围内已非 active 的账号；单账号同步只创建或更新目标邮箱，不删除其他账号。

`sold` 或 `sync_disabled=true` 不会进入 Sub2API 同步目标。卖出账号时，`delete_account_from_sub2api` 只删除 AutoTeam 管理的 pool 账号，匹配邮箱或 `autoteam_auth_file`。

Sub2API 与 CPA 应共用后台同步任务模型。前台账号操作只提交同步请求；后台任务按邮箱增量创建或更新 Sub2API 账号，并在成功后写 `sub2api_synced_at`。Sub2API 失败不应回滚已完成的 CPA 上传，但应写入任务警告或暂停原因。

## 主号同步

主号认证文件由 `src/autoteam/codex_auth.py` (`save_main_auth_file`) 保存为 `auths/codex-main-*.json`。

`src/autoteam/sync_targets.py` (`sync_main_codex_to_configured_targets`) 会把主号文件同步到已启用远端。CPA 侧实现是 `src/autoteam/cpa_sync.py` (`sync_main_codex_to_cpa`)。

账号池操作页的 OAuth 凭证推送按钮使用 `/api/sync/main-codex/saved`，只上传本地已有主号凭证，不启动浏览器登录。没有本地主号凭证时，返回错误并要求先到配置面板完成主号 Codex 登录。
