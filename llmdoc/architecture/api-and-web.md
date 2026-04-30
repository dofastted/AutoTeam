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

## 前端

`web/src/App.vue`: 顶层页面路由和状态刷新。

`web/src/api.js`: 后端 API client。所有请求走 `/api`，Vite 开发服务会代理到 `http://localhost:8787`。

主要页面：

- `web/src/components/Dashboard.vue`: 账号统计、账号列表、登录、移出、卖出、删除、导出。
- `web/src/components/TeamMembers.vue`: Team 成员和邀请。
- `web/src/components/PoolPage.vue`: 账号池操作入口，包含批量 CPA JSON 启动、运行记录和账号明细。
- `web/src/components/SyncPage.vue`: 同步操作入口。
- `web/src/components/OAuthPage.vue`: 手动 OAuth 登录和 CPA 凭证检查。
- `web/src/components/TaskHistory.vue`: 后台任务状态。
- `web/src/components/LogViewer.vue`: 日志查看。
- `web/src/components/ConfigPage.vue`: 运行配置。

## 构建产物

`web/vite.config.js` 把前端构建输出到 `src/autoteam/web/dist/`。`npm run build` 会替换该目录下的 hash 文件。

后端静态文件服务使用 `src/autoteam/web/dist/index.html` 和 assets。

## 任务返回

后台任务接口返回 `202` 和 `task_id`。前端通过 `getTasks` 和 `getTask` 读取状态。任务失败时，错误字符串写入任务对象的 `error` 字段。

批量 CPA JSON 任务还会写入 `flow_runs.json`。页面通过 `/api/cpa-batch/runs` 和 `/api/cpa-batch/runs/{run_id}` 读取持久记录，避免只依赖内存任务历史。暂停请求通过 `/api/cpa-batch/runs/{run_id}/pause` 写入记录，任务会在当前账号阶段结束后停止继续新账号。

服务启动时，`src/autoteam/api.py` 会调用 `src/autoteam/flow_runs.py` (`mark_interrupted_running_runs`) 标记遗留的 `running` 批量记录为失败。账号池操作页显示邮箱创建、注册、OAuth、额度检查和 CPA 上传阶段。

## 前台操作与后台同步

前台账号操作应只等待本地状态变化完成，不应同步等待 CPA / Sub2API 的全量远端操作。推荐交互：

- 用户点击账号操作按钮。
- 后端完成本地账号状态、`auth_file`、任务记录写入。
- 后端返回 `202` 或本地操作结果。
- 后台同步任务继续处理 CPA / Sub2API。
- 前端显示本地结果和后台同步任务状态。

适合异步的操作：

- CPA 文件增量上传。
- Sub2API 单账号创建或更新。
- 批量补传历史账号认证文件。
- 远端数量核对。
- 可自动重试的网络失败。

不适合悄悄异步的操作：

- Team 移出或取消邀请。
- 删除远端 CPA 文件。
- 删除 Sub2API 账号。
- 改写 `.env` 或登录态。

`POST /api/accounts/login` 是本地 OAuth 验证任务：它启动账号自己的 Codex OAuth 登录，保存 OAuth RT 文件，更新本地账号状态，并保留旧 `session_auth_file`。它不要求 CPA / Sub2API 配置，也不自动同步远端。

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
