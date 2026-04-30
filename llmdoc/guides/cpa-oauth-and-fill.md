# CPA OAuth 与补位流程

## OAuth 登录页

`web/src/components/OAuthPage.vue`: 页面包含两部分。

- CPA 凭证检查：读取 `/api/accounts` 和 `/api/cpa/files`，对比 active 席位账号与 CPA 认证文件。
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
- 本地已有 `auth_file` 时直接上传 CPA。
- 本地没有 `auth_file` 时，按账号邮箱 provider 执行 Codex OAuth。
- OAuth 返回 `plan_type=team` 才继续上传。
- 上传失败会让后台任务失败。

## 批量 CPA JSON

后端入口：`src/autoteam/api.py` (`post_cpa_batch`)。

核心实现：

- `src/autoteam/cpa_batch.py` (`run_cpa_batch`): 默认每次新做 100 个可用 CPA JSON，固定每 20 个账号为一组。API 可传 `target=1` 和 `batch_size=1` 做单账号验证。
- `src/autoteam/cpa_batch.py` (`CpaBatchHooks`): 负责把任务阶段写入运行记录，并在每个账号阶段之间检查暂停请求。
- `src/autoteam/flow_runs.py`: 读写 `flow_runs.json`，保存运行记录、账号阶段、错误等级和 CPA 上传状态。
- `web/src/components/PoolPage.vue`: 账号池操作页提供直注 / 邀请选择、启动按钮、运行记录和账号明细。

直注和邀请流程创建邮箱后，会立刻把真实邮箱写入账号池和 `flow_runs.json`。后续注册、凭证保存、额度检查、CPA 上传各自写阶段事件，避免浏览器流程卡住时页面只看到 `attempt-*` 占位记录。

直注流程注册成功后优先保存 ChatGPT Web session 凭证：

- `src/autoteam/manager.py` (`_register_direct_once`): 注册完成后在关闭浏览器前回传 session bundle。
- `src/autoteam/codex_auth.py` (`build_chatgpt_session_auth_bundle`): 读取 `/api/auth/session` 的 `accessToken`、session cookie、账号 ID 和 `plan_type`。
- `src/autoteam/cpa_batch.py` (`_create_direct_account`): 将 session bundle 保存为 `auths/codex-{email}-{plan_type}-{hash}.json`。浏览器异常或 session 提取失败时重试当前邮箱账号。
- `src/autoteam/cpa_batch.py` (`_verify_and_upload_cpa`): 批量流程不再回退到浏览器 Codex OAuth；没有 session 凭证时直接失败并记录原因。
- `src/autoteam/cpa_batch.py` (`_CpaUploadWorker`): session 凭证保存后，CPA 额度检查和上传在内部 worker 线程执行；主线程可以继续注册后续账号。

成功条件：

- 账号已注册并进入 Team。
- 本地状态为 `active`。
- session 凭证或认证文件解析出的 `plan_type` 是 `team`。
- `check_codex_quota` 返回 `ok`。
- `upload_to_cpa` 返回成功。
- 若 Sub2API 已启用，CPA 上传成功后会尝试把该账号单独同步到 Sub2API；Sub2API 失败会写入警告事件，不回滚已完成的 CPA 上传。

注册阶段会对当前邮箱账号最多尝试 3 次。CPA 认证、额度检查或上传阶段失败时，会对同一个已知邮箱继续重试，累计失败 3 次后才把该账号记录为 `failed`。若连续 2 个账号都在注册阶段失败，批量任务会暂停，避免继续消耗新邮箱。若已完成账号的成功率接近跌破 95%，批量任务也会写入 `pause_requested` 并暂停。任务可通过 `/api/cpa-batch/runs/{run_id}/resume` 按原 run_id 继续执行。

暂停规则：

- 暂停请求由 `/api/cpa-batch/runs/{run_id}/pause` 写入 `flow_runs.json`。
- 当前浏览器阶段不强制中断；已提交的 CPA worker 会完成当前账号检查和上传。
- 阶段结束后不再创建下一个账号，运行记录标记为 `paused`。
- 服务启动时会把上次遗留的 `running` 批量记录标记为失败，并把仍在运行的账号记录写成严重错误。

## 历史账号 CPA / Sub2API 补传

历史账号补传和批量 CPA JSON 不是同一个任务。

批量 CPA JSON 用来新做账号：创建邮箱、注册、保存 session 凭证、检查额度、上传 CPA。

历史账号补传只处理本地已有 `auth_file` 的账号：

- 不打开浏览器。
- 不新建邮箱。
- 不注册新账号。
- 不删除 CPA 或 Sub2API 远端账号。
- 按邮箱和文件名匹配远端。
- 远端缺失时增量上传。

补传范围建议：

- `active` 账号必须包含。
- 可复用 `standby` 账号也应包含，因为它们已有 auth 文件，恢复时可以直接使用。
- `pending` 账号不应补传。
- 没有 `auth_file` 或本地文件不存在的账号只记录错误，不进入上传。

补传完成后：

- CPA 上传成功可写 `cpa_uploaded_at`。
- Sub2API 创建或更新成功可写 `sub2api_synced_at`。
- 写入账号字段时必须避免和正在运行的批量注册任务同时覆盖 `accounts.json`。

若前台页面只需要“开始补传”，后端应立即返回任务 ID，后续由任务历史或账号池页面显示进度。

## 重试开关建议

自动重试应分类型配置，不要只给一个简单布尔值。

推荐默认：

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

- 本地 `auth_file` 缺失。
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
- 每批结束后调用已启用远端同步。

默认值：

- `TEAM_TARGET_SEATS=999`
- `FILL_BATCH_SIZE=10`

## 日志与结果

每批补位会记录：

- 尝试数量。
- 成功数量。
- 失败数量。
- 成功率。
- CPA / Sub2API 同步结果。

后台任务最终结果包含 `attempted`、`succeeded`、`failed`、`success_rate` 和 `batches`。

## 修改注意

- 不要把 CPA 凭证检查做成直接删除远端文件。
- 不要让补满成员默认一次性冲到 `TEAM_TARGET_SEATS`。
- 批量 CPA JSON 是“新做账号”，不要复用已有 CPA 文件来抵扣 100 个目标。
- 历史账号补传应走增量上传任务，不要复用会删除非 active CPA 文件的同步入口。
- 若新增同步目标，先改 `src/autoteam/sync_targets.py`，再改 API 配置校验和前端配置页。
