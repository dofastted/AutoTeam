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

- `web/src/components/Dashboard.vue`: 账号统计、账号列表、登录、移出、删除、导出。
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
