# 任务安全

- Git 操作按项目规则走 Windows Git。不要用 `git add .`，只暂存当前任务文件。
- 不要提交真实 `.env`、账号密码、session token、OAuth token、CPA key、Sub2API 登录信息。
- `docs/cpa/.env` 属于示例/参考区域，改动前先确认是否包含真实值。
- `accounts.json`、`state.json`、`auths/`、`screenshots/` 是运行数据或敏感产物，默认不作为源码变更提交。
- 账号删除、Team 移出、CPA 删除属于会改变远端状态的操作。排查时优先读取状态，不要直接执行删除。
- `cmd_fill`、`cmd_rotate`、`cmd_cleanup` 会启动浏览器并可能改变 Team 成员。测试这类逻辑优先用单元测试 mock。
- 前端构建会删除旧 `src/autoteam/web/dist/assets/*` 并生成新 hash 文件。构建产物变化需要一并检查。
- 如果自动巡检、任务队列或浏览器任务失败，先看 `src/autoteam/api.py` 的任务状态和日志接口，再看具体 manager 流程。
