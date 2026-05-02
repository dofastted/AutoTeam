# CPA OAuth 与补位流程

## OAuth 登录页

`web/src/components/OAuthPage.vue`: 页面包含两部分。

- CPA 凭证检查：读取 `/api/accounts` 和 `/api/cpa/files`，分别显示 Session、OAuth RT、CPA、Sub2API 状态。
- 手动 OAuth：调用 `/api/manual-account/start` 生成 OAuth 链接，支持自动 callback 和手动粘贴 callback URL。

前端 API client 在 `web/src/api.js`：

- `getAccounts`
- `getCpaFiles`
- `startAccountCpaAuth`
- `startManualAccount`
- `submitManualAccountCallback`
- `cancelManualAccount`

## 单账号 CPA 认证

后端入口：`src/autoteam/api.py` (`post_account_cpa_auth`)。

规则：

- 只允许账号池里的 active 账号。
- 主号不能走该接口。
- 必须有 CPA 配置。
- 本地已有可用的 OAuth RT 文件时直接上传 CPA。
- 只有 `session_auth_file` 或缺少 RT 文件时，才按账号邮箱 provider 执行 Codex OAuth。
- OAuth 返回 `plan_type=team` 才继续上传。
- 成功后会写 `auth_file`、`rt_auth_file`，并保留已有 `session_auth_file`。
- 上传失败会让后台任务失败。

## 批量 CPA JSON

后端入口：`src/autoteam/api.py` (`post_cpa_batch`)。

核心实现：

- `src/autoteam/cpa_batch.py` (`run_cpa_batch`): 默认每次新做 100 个可用 CPA JSON，固定每 20 个账号为一组。API 可传 `target=1` 和 `batch_size=1` 做单账号验证。
- `src/autoteam/cpa_batch.py` (`CpaBatchHooks`): 负责把任务阶段写入运行记录，并在每个账号阶段之间检查暂停请求。
- `src/autoteam/flow_runs.py`: 读写 `flow_runs.json`，保存运行记录、账号阶段、错误等级和 CPA 上传状态。
- `web/src/components/PoolPage.vue`: 账号池操作页提供直注 / 邀请选择、启动按钮、运行记录和账号明细。

直注和邀请流程创建邮箱后，会立刻把真实邮箱写入账号池和 `flow_runs.json`。后续注册、凭证保存、额度检查、CPA 上传各自写阶段事件，避免浏览器流程卡住时页面只看到 `attempt-*` 占位记录。

直注流程注册成功后先确认 workspace，再保存 ChatGPT Web session 备份。注册浏览器不再打开 Codex OAuth，OAuth RT 由注册后的协议认证阶段获取：

- `src/autoteam/manager.py` (`_register_direct_once`): 注册完成后先访问 `https://chatgpt.com/admin/members`，确认 workspace 成员页可访问，再在关闭浏览器前回传 session bundle。
- `src/autoteam/chatgpt_api.py` (`complete_workspace_selection`): 处理注册后出现的 workspace / organization 选择页。直注和邀请注册都会尝试进入可用 Team workspace。
- `src/autoteam/codex_auth.py` (`build_chatgpt_session_auth_bundle`): 读取 `/api/auth/session` 的 `accessToken`、session cookie、账号 ID 和 `plan_type`。
- `src/autoteam/protocol_oauth.py` (`run_protocol_oauth_login_with_browser_context`): 复用注册成功后的浏览器 page/context 打开 PKCE Codex OAuth 链接，拦截 `http://localhost:1455/auth/callback` 获取 code，并用 `/oauth/token` 交换出 OAuth RT bundle。
- `src/autoteam/protocol_oauth.py` (`run_protocol_oauth_login`): 后备路径。使用账号邮箱、密码、邮箱 OTP、HTTP session、PKCE、Codex authorize 和 `/oauth/token` 获取 `refresh_token`，可复用 `session_auth_file` 中的 `session_token`、`account_id` 和 cookie 信息。
- `src/autoteam/cpa_batch.py` (`_create_direct_account`): 将 session bundle 保存为 `auths/codex-{email}-{plan_type}-{hash}-session.json`，写入 `session_auth_file`；同时保存浏览器内 PKCE 生成的 `auths/codex-{email}-{plan_type}-{hash}-oauth.json`，写入 `rt_auth_file`。浏览器异常、认证错误页、`admin/members` 不可访问、session 提取失败或 OAuth RT 生成失败时，当前邮箱直接失败并换下一个邮箱。
- `src/autoteam/cpa_batch.py` (`_create_direct_accounts_parallel`): 直注批量并行 worker。按窗口数拆分目标，每个 worker 单独创建邮箱、注册、保存 session 凭证。
- `src/autoteam/account_oauth.py` (`run_account_oauth_login`): 项目账号 OAuth RT 的共享实现。`/api/accounts/login` 和批量 CPA JSON 都调用它生成 OAuth RT 文件，成功后继续调用 `codex_auth.save_auth_file(..., source="oauth")`。
- `src/autoteam/cpa_batch.py` (`_verify_and_upload_cpa`): 通过 `select_oauth_rt_auth_file` 选择本地 OAuth RT 文件；旧 `auth_file` 只有内容确认是 OAuth RT 时才可作为兼容候选。缺少 OAuth RT 文件时调用协议认证生成 `auths/codex-{email}-{plan_type}-{hash}-oauth.json` 后再继续 CPA 上传。
- `src/autoteam/cpa_batch.py` (`_CpaUploadWorker`): 额度检查和 CPA 上传在内部 worker 线程执行，不占用注册浏览器槽位；只有账号缺 OAuth RT 文件时才调用后备协议认证。direct 单窗口 `parallel_workers=1` 时，当前账号必须完成注册、OAuth RT 文件落盘、CPA 上传和可选 Sub2API 同步，主线程才会创建下一个账号。direct 并行 `parallel_workers>1` 时，注册可并行，CPA worker 对已注册账号逐个检查额度和上传。

成功条件：

- 账号已注册并进入 Team，且 `https://chatgpt.com/admin/members` 可访问。
- 本地状态为 `active`。
- OAuth RT 文件解析出的 `plan_type` 是 `team`。
- `check_codex_quota` 返回 `ok`。
- `upload_to_cpa` 返回成功。
- 本地账号写入 `cpa_status=success` 和 `usage_status=inventory`。
- 若 Sub2API 已启用，CPA 上传成功后会尝试把该账号单独同步到 Sub2API；Sub2API 失败会写入警告事件，不回滚已完成的 CPA 上传。
- CPA / Sub2API 同步只使用本地已完成的 OAuth RT 认证文件。`session_auth_file` 只是 ChatGPT Web session 备份，不作为 CPA 上传文件。

注册阶段不重试同一个邮箱，也不通过 Team 成员检查兜底。`https://chatgpt.com/api/auth/error`、未识别邮箱步骤、浏览器异常、`admin/members` 不可访问或缺少 session 凭证都会让当前邮箱失败，后续继续创建新邮箱。注册后如果出现 workspace / organization 选择页，会先处理该页面；若账号没有进入有效组织，后续协议认证会记录 `no_valid_organizations` 并返回“未进入有效组织”的错误。协议认证、额度检查或上传阶段失败时，会对同一个已知邮箱继续重试，累计失败 3 次后才把该账号记录为 `failed`。若连续 2 个账号都在注册阶段失败，批量任务会暂停，避免继续消耗新邮箱。若已完成账号的成功率接近跌破 95%，批量任务也会写入 `pause_requested` 并暂停。任务可通过 `/api/cpa-batch/runs/{run_id}/resume` 按原 run_id 继续执行。

验证建议：

- 先调用 `POST /api/tasks/stop-all`，避免旧任务或巡检抢占任务。
- 先跑直注 `target=1`、`parallel_workers=1`，确认 `accounts.json` 同时有 `session_auth_file` 和 `rt_auth_file`，`auths/` 同时有 `*-session.json` 与 `*-oauth.json`，且只有 `*-oauth.json` 含 `refresh_token`。
- 再跑直注 `target=5`、`parallel_workers=1`，确认账号按“注册 -> 浏览器内 PKCE RT -> CPA 上传 -> Sub2API 同步”的顺序逐个完成。
- 日志中不应再出现 `codex_auth.login_codex_via_browser` 作为批量 CPA 补 RT 的执行来源。

暂停规则：

- 暂停请求由 `/api/cpa-batch/runs/{run_id}/pause` 写入 `flow_runs.json`。
- 当前浏览器阶段不强制中断；已提交的 CPA worker 会完成当前账号检查和上传。
- 阶段结束后不再创建下一个账号，运行记录标记为 `paused`。
- 服务启动时会把上次遗留的 `running` 批量记录标记为失败，并把仍在运行的账号记录写成严重错误。
- 恢复某个批量任务前，`src/autoteam/flow_runs.py` (`fail_running_flow_accounts`) 会先把该任务里遗留的 `running` 账号记录标记为失败，避免旧窗口状态一直显示运行中。

## 历史账号 CPA / Sub2API 补传

历史账号补传和批量 CPA JSON 不是同一个任务。

批量 CPA JSON 用来新做账号：创建邮箱、注册、保存 session 凭证、检查额度、上传 CPA。

历史账号补传只处理本地已有 OAuth RT 文件的账号：

- 不打开浏览器。
- 不新建邮箱。
- 不注册新账号。
- 不删除 CPA 或 Sub2API 远端账号。
- 按邮箱和文件名匹配远端。
- 远端缺失时增量上传。
- `rt_auth_file` 是主来源；旧 `auth_file` 只有内容确认含 OAuth `refresh_token` 且不是 ChatGPT session 时才可作为兼容来源。
- `session_auth_file` 只是 ChatGPT Web session 备份，不能上传 CPA / Sub2API。

补传范围建议：

- `active` 账号必须包含。
- 可复用 `standby` 账号也应包含，因为它们已有 auth 文件，恢复时可以直接使用。
- `pending` 账号不应补传。
- 没有 OAuth RT 文件或本地文件不存在的账号只记录跳过原因，不进入上传。

## 一次性补救脚本

仅用于「服务已经在跑、需要对账号池做一次性补救」的场景。详细参数见 `llmdoc/reference/config-data-files.md` 的「运维脚本」一节。

`scripts/recreate_permanent_mailboxes.py`：把已过期的临时 MoEmail 邮箱重建为 `expiryTime=0` 永久邮箱，并把新 `mail_account_id` 写回 `accounts.json`。账号 `password` 仍可用、但 MoEmail 邮箱已自毁、OTP 永远收不到时使用。

`scripts/backfill_session_only_oauth.sh`：为只有 `session_auth_file`、缺 OAuth RT 的账号顺序调用 `POST /api/accounts/{email}/cpa-auth` 并轮询任务结果。服务端 `_playwright_lock` 全局串行，脚本一次只跑一个账号。

补传完成后：

- CPA 上传成功可写 `cpa_uploaded_at`。
- Sub2API 创建或更新成功可写 `sub2api_synced_at`。
- 写入账号字段时必须避免和正在运行的批量注册任务同时覆盖 `accounts.json`。

若前台页面只需要“开始补传”，后端应立即返回任务 ID，后续由任务历史或账号池页面显示进度。

## 重试开关建议

自动重试应分类型配置，不要只给一个简单布尔值。

建议默认：

- `SYNC_AUTO_RETRY=transient`
- `SYNC_RETRY_MAX_ATTEMPTS=3`
- `SYNC_RETRY_BACKOFF_SECONDS=5,30,120`
- `SYNC_FAILURE_POLICY=pause`
- `SYNC_PAUSE_ON_SUCCESS_RATE_BELOW=95`

含义：

- `off`: 不自动重试，失败后暂停。
- `transient`: 只重试网络错误、HTTP 429、HTTP 5xx、远端短暂不可用。
- `always`: 所有错误都按次数重试，不建议默认启用。

不应自动重试的错误：

- 本地 OAuth RT 文件缺失。
- auth JSON 无法解析。
- 缺少 CPA / Sub2API 配置。
- OAuth token 明确无效。
- OpenAI 注册页稳定返回 `https://chatgpt.com/api/auth/error`。

可以自动重试的错误：

- 请求超时。
- HTTP 429。
- HTTP 502 / 503 / 504。
- CPA / Sub2API 短暂连接失败。

## 补满成员

后端入口：`src/autoteam/manager.py` (`cmd_fill`)。

未传目标时：

- 读取当前 Team 成员数。
- 本次目标为当前人数加 `FILL_BATCH_SIZE`。
- 本次目标不会超过 `TEAM_TARGET_SEATS`。

传入目标时：

- 目标会被限制在 `1..MAX_TEAM_SEATS`。
- 实际执行仍按 `FILL_BATCH_SIZE` 记录每批结果。
- 每批结束后把本地 OAuth RT 文件上传到已启用远端。

默认值：

- `TEAM_TARGET_SEATS=999`
- `FILL_BATCH_SIZE=10`

## 日志与结果

每批补位会记录：

- 尝试数量。
- 成功数量。
- 失败数量。
- 成功率。
- CPA / Sub2API 上传结果。

后台任务最终结果包含 `attempted`、`succeeded`、`failed`、`success_rate` 和 `batches`。

## 本地 hook 监督

`tools/codex-hook/check_and_invoke.py` 会按 `.autoteam-hook/runtime/campaign.json` 的配置定时巡检。

当前默认：

- 每 10 分钟触发一次。
- 优先检查当前 managed run 是否还在运行。
- 没有运行中的 run 时，优先恢复未完成 run；没有可恢复 run 时再启动新批次。
- 如果启动新批次遇到 API 409，但 `/api/tasks` 显示已有 `cpa-batch` 在运行，hook 会把该任务的 `run_id` 追加到 `managed_run_ids`，避免后续统计继续停在旧 run。
- 检查成功账号是否已经写入 `plan_type`、`rt_auth_file`、`cpa_uploaded_at`、`qualified_at`。
- 通过 `/api/cpa/files` 检查 CPA 远端是否已经存在对应 auth 文件，避免只看本地成功状态。

## 修改注意

- 不要把 CPA 凭证检查做成直接删除远端文件。
- 不要让补满成员默认一次性冲到 `TEAM_TARGET_SEATS`。
- 批量 CPA JSON 是“新做账号”，不要复用已有 CPA 文件来抵扣 100 个目标。
- 历史账号补传应走增量上传任务，不要复用会删除非 active CPA 文件的同步入口。
- 若新增同步目标，先改 `src/autoteam/sync_targets.py`，再改 API 配置校验和前端配置页。
