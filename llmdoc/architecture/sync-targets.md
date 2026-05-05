# 远端同步

## 分发入口

`src/autoteam/sync_targets.py`: 根据运行配置决定启用 CPA、Sub2API 或两者。

- `SYNC_TARGET_CPA` 控制 CPA。
- `SYNC_TARGET_SUB2API` 控制 Sub2API。
- 未显式设置开关时，存在完整连接配置会被视为启用。

## 当前同步模型

前台账号操作不应等待 CPA / Sub2API 完整同步完成。新增账号、恢复账号、上传单个认证文件后，应先把本地账号状态和 `rt_auth_file` 保存好，再创建后台同步任务。

推荐把同步分成两类任务：

- 前台任务：注册、登录、恢复、移出、删除、Team 状态读取。
- 后台同步任务：CPA 文件上传、Sub2API 账号创建或更新、远端数量核对、失败重试。

后台同步只按差异上传：

- 先读取本地 `accounts.json` 中未禁用同步的 `active` 账号。
- 只选择存在可上传 OAuth RT 文件的账号。主字段是 `rt_auth_file`；旧 `auth_file` 只在内容确认含 `refresh_token` 且不是 ChatGPT session 时作为兼容候选。
- 读取 CPA / Sub2API 远端列表，以邮箱和文件名匹配。
- 远端已有同邮箱或同名文件时跳过，远端缺失时上传或更新。
- 默认不删除远端文件。删除必须走单独的清理任务，并带明确确认。
- `sold` 或 `sync_disabled=true` 的账号不上传、不更新。
- `session_auth_file` 只作为 ChatGPT Web session 备份，普通同步、库存同步和额度检查都不能把它当上传凭证。

错误处理默认采用暂停优先：

- 网络错误、HTTP 429、HTTP 5xx 可按配置自动重试。
- 同一账号连续失败达到上限时，记录错误并暂停该批任务。
- 认证文件缺失、token 无效、配置缺失属于不可自动修复错误，应立即暂停。
- 暂停记录写入任务状态，前端只负责显示错误和恢复按钮。

当前代码里 `/api/sync/cpa` 只同步 `active` 账号的本地 OAuth RT 文件，不启动浏览器、不补 OAuth，也不删除远端文件。要补传 `standby` 账号的 CPA 文件，应新增只上传、不删除的增量补传任务。

## CPA

`src/autoteam/cpa_sync.py`: 负责 CPA 认证文件列表、上传、删除、下载、去重、正向同步、反向同步、主号文件同步。

`CPA_URL` 是 CLIProxyAPI API 根地址。配置时也允许粘贴人工管理页 `http://host:8317/management.html#/auth-files`；`src/autoteam.config` 会在运行时归一化为 `http://host:8317`。后端上传、下载、列表和删除都调用 `/v0/management/auth-files` 系列接口，不把浏览器 hash 当作 HTTP 路径。

上传请求使用较长超时。若上传请求超时但随后在 CPA 文件列表中能看到同名文件，`upload_to_cpa` 按成功处理，避免服务端已经写入而本地误标失败。

正向同步 `sync_to_cpa`：

- 读取本地账号。
- 只上传未禁用同步的 active 账号 OAuth RT 认证文件。
- 跳过只有 `session_auth_file` 或缺少 OAuth RT 文件的账号，并在结果中返回跳过原因。
- 不删除 CPA 远端文件。
- 返回上传、跳过和本地去重等统计结果。

库存同步 `maintain_cpa_inventory`：

- 只读取 `usage_status=inventory`、`cpa_status=success`、未禁用同步的账号。
- 只上传含 `refresh_token` 的 OAuth RT 文件，不上传 ChatGPT session 备份文件。
- 云端本地库存少于 100 时补传本地库存文件。
- 本地多余库存继续保留在 `accounts.json` 和 `auths/`，不主动从本地删除。

401 清理 `delete_http401_from_cpa`：

- 调用 CPA 的 `DELETE /v0/management/auth-files/401`。
- CPA 返回文件名时，本地同名账号写为 `status=unavailable`、`sync_disabled=true`、`unavailable_reason=http_401`。

失效 RT 清理 `cleanup_invalid_cpa_refresh_tokens`：

- 下载 CPA 远端 auth 文件，只处理含 `refresh_token` 的 OAuth 文件。
- 直接请求 OpenAI token refresh，不依赖 CPA 是否已把错误写入内存状态。
- 遇到 HTTP 401、`refresh_token_reused`、`token_invalidated` 或 `token_revoked` 时删除 CPA 文件。
- 对本地同名账号写 `status=unavailable`、`sync_disabled=true`、`unavailable_reason=http_401`。
- refresh 成功时会把新 access token 和新 refresh token 重新上传到 CPA，避免消耗有效 RT 后不保存。
- 上传 CPA 成功后，如果 `auths/<name>` 在本地已存在（即本地账号在用同一个文件），会原子写回新 token（`tempfile + replace + ensure_auth_file_permissions`），避免下一轮本地 refresh 再次用已被 OpenAI 单次失效的旧 RT 触发 401。本地写回失败只记 `failed`，不阻断后续清理。

本地失效目录标记 `mark_unusable_account_deactivated_from_dir`：

- 默认读取 `auths/unusable/account_deactivated`。
- 按文件 JSON 内的 `email` 或 `codex-{email}-{plan}-{hash}.json` 文件名解析邮箱。
- 匹配本地 `accounts.json` 后写 `status=unavailable`、`sync_disabled=true`、`unavailable_reason=account_deactivated`。
- 该动作只处理本地账号状态，不删除本地 auth 文件。

已售账号：

- `POST /api/accounts/{email}/sell` 调用 `src/autoteam/sync_targets.py` (`delete_account_from_configured_targets`)。
- CPA 侧按邮箱或本地 auth 文件名删除远端文件。
- 删除后本地账号标记为 `sold` 和 `sync_disabled=true`，后续 `/api/sync/cpa` 不会重新上传。

增量补传 CPA 文件时，应新增独立入口。该入口只做上传：

- 匹配范围：`active` 与可复用 `standby`。
- 匹配键：优先邮箱，其次认证文件名。
- 已存在：跳过。
- 不存在：上传本地 OAuth RT 文件。
- 上传成功后可写 `cpa_uploaded_at` 与独立同步任务记录。
- 上传失败按 `SYNC_AUTO_RETRY` 与 `SYNC_FAILURE_POLICY` 处理。

HTTP 入口：

- `/api/sync`: 按已启用目标上传本地 OAuth RT 文件到 CPA / Sub2API。
- `/api/sync/cpa`: 只上传本地 OAuth RT 文件到 CPA，账号池操作页的 CPA 推送按钮使用这个入口。
- `/api/sync/cpa-stock`: 维护 CPA 云端库存，目标为 100 个库存 RT 文件。
- `/api/sync/cpa/cleanup-401`: 清理 CPA 远端 401 文件，并按返回名单标记本地账号不可用。
- `/api/sync/cpa/cleanup-invalid-rt`: 直接刷新 CPA OAuth RT 文件，删除明确失效的远端文件。
- `/api/accounts/mark-unusable/account-deactivated`: 按 `auths/unusable/account_deactivated` 标记本地账号不可用。
- `/api/sync/sub2api`: 只上传本地 OAuth RT 文件到 Sub2API，账号池操作页和同步中心的 Sub2API 推送按钮使用这个入口。

RT 恢复入口不属于远端同步入口：

- `/api/accounts/rt-recovery/scan`: 只扫描缺 RT、401 需要重取 RT、已失效和不可恢复账号，不写远端。
- `/api/accounts/rt-recovery/start`: 人工启动恢复任务。流程会先重建 MoEmail、查 Deactivated 邮件，命中则本地标记失效并释放 Team 席位；未命中才获取 OAuth RT。该入口只写本地账号和 auth 文件，不自动上传 CPA / Sub2API。
- `/api/accounts/rt-recovery/mark-deactivated`: 把扫描出的 deactivated 账号标记不可用，并按实现参数释放 Team 席位；它不是 CPA / Sub2API 删除入口。
- `/api/accounts/{email}/rt-recovery`: 单账号恢复入口，边界与批量 start 相同。

反向同步 `sync_from_cpa` 是恢复入口：

- 下载 CPA 中的 `codex-*.json`。
- 按账号去重。
- 比较 `last_refresh` 和 `expired`。
- CPA 文件更旧时保留本地文件。
- 新导入账号默认写为 standby。
- 它不属于普通上传同步，不会用 session 备份生成远端文件。

单账号 CPA 认证入口：

- `src/autoteam/api.py` (`post_account_cpa_auth`): 面向 Web OAuth 页。仅允许 active 席位账号。若本地已有 OAuth RT 文件则直接上传；若只有 session 备份或本地缺少 RT 文件，则自动执行 Codex OAuth，确认 `plan_type=team` 后上传。
- `src/autoteam/cpa_batch.py` (`run_cpa_batch`): 批量直注账号在注册成功后保存 ChatGPT Web session 备份，再通过 Codex OAuth callback 生成 OAuth RT 文件并上传 CPA。
- `src/autoteam/cpa_batch.py` (`_CpaUploadWorker`): 每个账号 CPA 上传成功后，若 Sub2API 已启用，会调用 `src/autoteam/sub2api_sync.py` (`sync_account_to_sub2api`) 单独同步该账号。

## Sub2API

`src/autoteam/sub2api_sync.py`: 负责登录 Sub2API、读取 OpenAI OAuth 账号、上传账号池认证文件、同步主号认证文件、处理 `SUB2API_GROUP`。

`SUB2API_GROUP` 可填分组名或分组 ID，多个值用逗号分隔。同步时会保留用户手工绑定的其他分组，只替换 AutoTeam 管理的分组绑定。分组不存在时，账号推送和按邮箱去重仍会继续，返回结果的 `warnings` 会说明已跳过分组绑定。

账号池推送到 Sub2API 时，以邮箱为去重键。若远端已有同邮箱 OpenAI OAuth 账号，会更新已有账号而不是新建；AutoTeam 自己标记的重复账号会删除多余项。同步 payload 按 `C:\Users\Administrator\Downloads\sub2api示列.json` 的 OpenAI OAuth 账号结构生成，固定写入 `model_mapping`、`privacy_mode=training_off`、`openai_oauth_responses_websockets_v2_mode=off`、并覆盖基础调度字段。当前普通同步只创建或更新本地 active 账号，不删除远端缺失账号。

`sold` 或 `sync_disabled=true` 不会进入 Sub2API 同步目标。卖出账号时，`delete_account_from_sub2api` 只删除 AutoTeam 管理的 pool 账号，匹配邮箱或 `autoteam_auth_file`。

Sub2API 与 CPA 应共用后台同步任务模型。前台账号操作只提交同步请求；后台任务按邮箱增量创建或更新 Sub2API 账号，并在成功后写 `sub2api_synced_at`。Sub2API 失败不应回滚已完成的 CPA 上传，但应写入任务警告或暂停原因。

## 主号同步

主号认证文件由 `src/autoteam/codex_auth.py` (`save_main_auth_file`) 保存为 `auths/codex-main-*.json`。

`src/autoteam/sync_targets.py` (`sync_main_codex_to_configured_targets`) 会把主号文件同步到已启用远端。CPA 侧实现是 `src/autoteam/cpa_sync.py` (`sync_main_codex_to_cpa`)。

账号池操作页的 OAuth 凭证推送按钮使用 `/api/sync/main-codex/saved`，只上传本地已有主号凭证，不启动浏览器登录。没有本地主号凭证时，返回错误并要求先到配置面板完成主号 Codex 登录。
