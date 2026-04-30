# 运行事实

- 项目根目录是 `/mnt/x/project/AutoTeam`。
- Python 包在 `src/autoteam/`，前端源码在 `web/src/`，前端构建产物写入 `src/autoteam/web/dist/`。
- 启动命令是 `uv run autoteam api`，默认 HTTP 端口是 `8787`。
- Vite 开发服务在 `web/vite.config.js` 中配置端口 `5173`，`/api` 代理到 `http://localhost:8787`。
- 首次启动只强制要求 `API_KEY`。邮箱服务、CPA、Sub2API、代理等运行项在执行对应功能时校验。
- `TEAM_TARGET_SEATS` 是 Team 总人数目标，默认 `999`。`FILL_BATCH_SIZE` 是补满成员每次最多新增账号数，默认 `10`。
- ChatGPT Team 中已有 owner 或外部成员也计入目标人数。轮转目标不是“本地管理账号数”。
- Playwright 默认隐藏运行。`PLAYWRIGHT_BROWSER_MODE=visible` 可显示窗口；`embedded` 当前按不弹窗处理。旧 `PLAYWRIGHT_HEADLESS=false` 仍兼容。配置入口是 `src/autoteam/config.py` (`get_playwright_launch_options`)。
- `BROWSER_PARALLEL_WORKERS` 控制账号补满、轮转和直注批量任务的新号创建并行窗口数，范围 `1..3`，默认 `1`。API 业务任务仍由 `src/autoteam/api.py` (`_playwright_lock`) 串行调度。
- `auths/codex-{email}-{plan_type}-{hash}.json` 是账号池认证文件。`auths/codex-main-*.json` 是主号认证文件。
- CPA 兼容文件由 `src/autoteam/codex_auth.py` (`save_auth_file`, `save_main_auth_file`) 写入，由 `src/autoteam/cpa_sync.py` 上传或拉回。
