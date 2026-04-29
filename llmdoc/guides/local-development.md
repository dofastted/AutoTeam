# 本地开发指南

## 安装

- Python 依赖：`uv sync --dev`
- Playwright 浏览器：`uv run playwright install chromium`
- 前端依赖：在 `web/` 下执行 `npm ci`

## 常用命令

- 启动后端和内置前端：`uv run autoteam api`
- 运行全部单元测试：`uv run pytest`
- 运行前端开发服务：在 `web/` 下执行 `npm run dev`
- 构建前端：在 `web/` 下执行 `npm run build`

## 前端开发

Vite 开发服务端口是 `5173`，`/api` 代理到 `http://localhost:8787`。调前端页面时通常需要后端也在 `8787` 运行。

`npm run build` 会更新 `src/autoteam/web/dist/`。如果提交前端改动，检查构建产物是否属于当前任务。

## 测试建议

- 修改账号状态、补位、轮转：优先跑 `tests/unit/test_manager_fill.py`、`tests/unit/test_manager_rotate.py`、`tests/unit/test_manager_reinvite.py`。
- 修改 API 任务、配置、自动巡检：优先跑 `tests/unit/test_api_status.py` 和 `tests/unit/test_api_playwright_cleanup.py`。
- 修改同步目标：优先跑 `tests/unit/test_sync_targets.py`、`tests/unit/test_sub2api_sync.py`，CPA 逻辑可补 `cpa_sync` 相关测试。
- 修改邮箱 provider：跑对应 `test_mo_email.py`、`test_cloudmail.py`、`test_cloudflare_temp_email.py`。

## 故障排查

- Web 页面报 401：先确认 `API_KEY` 和 localStorage。
- 浏览器任务卡住：先看 `/api/tasks` 和 `/api/logs`，再看 `screenshots/`。
- OAuth callback 不回来：确认 `localhost:1455` 是否能从浏览器所在机器访问，并检查 `PLAYWRIGHT_PROXY_BYPASS` 是否包含 `localhost,127.0.0.1`。
