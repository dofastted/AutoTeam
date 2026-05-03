# API 与 Web 面板

## 后端

`src/autoteam/api.py`: FastAPI 应用，提供鉴权、配置、任务、账号、Team 成员、同步、日志、管理员登录、主号 Codex、手动 OAuth 等接口。

关键机制：

- API key 鉴权在 `auth_middleware`。
- 后台任务由 `_start_task` 创建，状态存入内存 `_tasks`。
- 浏览器相关任务受 `_playwright_lock` 控制。
- Playwright 同步 API 通过 `_PlaywrightExecutor` 在固定线程执行。
- 自动巡检线程由 `_auto_check_loop` 执行。
- 日志接口由 `_LogCollector` 写入内存缓冲。
- Team 成员 payload 通过 `_pick_joined_at(raw)` 从 `joined_at` / `created_at` / `member_since` / `join_date` / `added_at` 取入队时间；`_format_team_payload` 和 `_local_snapshot` 会把 `joined_at` 传给前端。
- Auth 文件盘点由 `_AUTHS_FILE_PATTERN`、`_AUTHS_KNOWN_SUBDIRS`、`_parse_auth_filename`、`_scan_auths_files`、`_bucket_primary_category`、`_bucket_to_record` 负责。已知 bucket 是 `active`、`sold`、`tradable`、`unusable`、`archive`。
- `_bucket_primary_category(categories)` 决定同一邮箱跨目录时的主分类，优先级是 `sold` > `tradable` > `unusable` > `archive` > `active`；空集合返回 `unknown`。因此根目录 active 文件不会覆盖 `sold/` 等分类目录。

新增 auth 文件只读接口：

- `GET /api/auths/stats`: 返回 auth 文件总数、OAuth 文件数、session 文件数、五类文件数、按邮箱主分类计数和唯一邮箱数。`*_files` 是文件口径，`accounts_*` 是账号口径。
- `GET /api/auths/accounts`: 返回按邮箱聚合的 auth 文件列表，支持 category、邮箱搜索、OAuth/session 三态筛选、排序和分页。默认隐藏 `archive`，`sold` / `tradable` / `unusable` 可通过 category 下拉查看。

接口字段见 `llmdoc/reference/auths-api.md`。

## 前端

`web/src/App.vue`: 顶层页面路由和状态刷新。

`web/src/api.js`: 后端 API client。所有请求走 `/api`，Vite 开发服务会代理到 `http://localhost:8787`。

主要页面：

- `web/src/components/Dashboard.vue`: 只显示卡片统计，不再放账号操作表。当前分三组：Account Status 5 项、Team 3 项、Auth files 5+3 项；组件自己在 `onMounted` 调 `getTeamMembers` 和 `getAuthsStats`。Team 统计优先读取后端 `total` / `invites` 整数字段，失败时才按 `members[].type` 过滤；Auth files 卡片主数字读取 `accounts_*`，次行显示 `unique_emails` 和 `total_files`。
- `web/src/components/TeamMembers.vue`: 显示真实 ChatGPT Team 成员和 pending invites。成员表分页 20 条一页；邀请表单独展示，取消邀请和移出成员都调用 `removeTeamMember`，payload 用 `type` 区分。
- `web/src/components/AccountManagement.vue`: 账号管理页分成本地账号表和认证文件盘点。本地账号表使用 `AccountTable` + `AccountDrawer`，数据来自 `/api/accounts`，提供登录、导出 Codex auth、移出 Team、标记已售、删除和详情操作。
- `web/src/components/AuthsTable.vue`: 扁平 auth 文件表，数据来自 `/api/auths/accounts`。支持 category 下拉、OAuth 三态、Session 三态、排序、邮箱搜索、facets badge、20/50/100/200 分页；现在只作为文件盘点，不直接打开账号详情。
- `web/src/components/PoolPage.vue`: 账号池操作入口，包含批量 CPA JSON 启动、运行记录和账号明细。
- `web/src/components/SyncPage.vue`: 同步操作入口。
- `web/src/components/OAuthPage.vue`: 手动 OAuth 登录和 CPA 凭证检查，区分 Session 备份、OAuth RT、CPA、Sub2API 状态。
- `web/src/components/TaskHistory.vue`: 后台任务状态。
- `web/src/components/LogViewer.vue`: 日志查看。
- `web/src/components/ConfigPage.vue`: 运行配置。

`web/src/api.js` 现在包含 `getAuthsStats()` 和 `getAuthsAccounts(params)`，分别对应 `/api/auths/stats` 和 `/api/auths/accounts`。

## 构建产物

`web/vite.config.js` 把前端构建输出到 `src/autoteam/web/dist/`。`npm run build` 会替换该目录下的 hash 文件。

后端静态文件服务使用 `src/autoteam/web/dist/index.html` 和 assets。

## 任务返回

后台任务接口返回 `202` 和 `task_id`。前端通过 `getTasks` 和 `getTask` 读取状态。任务失败时，错误字符串写入任务对象的 `error` 字段。

批量 CPA JSON 任务还会写入 `flow_runs.json`。页面通过 `/api/cpa-batch/runs` 和 `/api/cpa-batch/runs/{run_id}` 读取持久记录，避免只依赖内存任务历史。暂停请求通过 `/api/cpa-batch/runs/{run_id}/pause` 写入记录，任务会在当前账号阶段结束后停止继续新账号。

服务启动时，`src/autoteam/api.py` 会调用 `src/autoteam/flow_runs.py` (`mark_interrupted_running_runs`) 标记遗留的 `running` 批量记录为失败。账号池操作页显示邮箱创建、注册、OAuth、额度检查和 CPA 上传阶段。

`POST /api/cpa-batch/runs/{run_id}/resume` 会复用原 run 的 `join_mode`、`target`、`batch_size` 和 `parallel_workers`。恢复并行直注 run 时不能退回单窗口，否则页面显示和运行行为会与原 run 不一致。

## 前台操作与后台同步

前台账号操作应只等待本地状态变化完成，不应同步等待 CPA / Sub2API 的全量远端操作。推荐交互：

- 用户点击账号操作按钮。
- 后端完成本地账号状态、`rt_auth_file`、任务记录写入。
- 后端返回 `202` 或本地操作结果。
- 后台同步任务继续处理 CPA / Sub2API。
- 前端显示本地结果和后台同步任务状态。

适合异步的操作：

- CPA 文件增量上传。
- Sub2API 单账号创建或更新。
- 批量补传历史账号认证文件。
- 远端数量核对。
- 可自动重试的网络失败。

同步中心和账号池操作页的普通同步只上传本地 OAuth RT 文件。`session_auth_file` 只作为 ChatGPT Web session 备份显示，不能作为 CPA / Sub2API 上传来源。

不适合悄悄异步的操作：

- Team 移出或取消邀请。
- 删除远端 CPA 文件。
- 删除 Sub2API 账号。
- 改写 `.env` 或登录态。

`POST /api/accounts/login` 是本地 OAuth 验证任务：它启动账号自己的 Codex OAuth 登录，保存 OAuth RT 文件，更新本地账号状态，并保留旧 `session_auth_file`。它不要求 CPA / Sub2API 配置，也不自动同步远端。默认拒绝已售出或 `sync_disabled=true` 的账号；排查已标记失效账号时可显式传 `force=true` 重新跑本地 OAuth 验证。

`POST /api/accounts/check-deactivated-mail` 是同步确认操作：它先检查邮箱是否收到包含 `deactivated` 的邮件，再按参数决定是否释放 Team 席位和退役邮箱。

卖出账号接口 `POST /api/accounts/{email}/sell` 是同步确认操作：它不操作 Team 席位，只删除已启用 CPA / Sub2API 远端记录，然后把本地账号标记为 `sold`。

后台同步任务应有独立状态字段：

- `queued`
- `running`
- `paused`
- `completed`
- `failed`

错误策略：

- 可重试错误按配置自动重试。
- 连续失败达到上限时暂停任务。
- 不可重试错误立即暂停。
- 前端提供恢复按钮，不自动反复启动失败任务。
