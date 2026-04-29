# 项目概览

AutoTeam 是面向 ChatGPT Team 的账号轮转与认证同步工具。

核心目标：

- 维护 ChatGPT Team 总人数在目标值附近。
- 检查 active 账号 Codex 额度，额度不足时移出 Team 并放回 standby。
- 优先复用额度恢复的 standby 账号，不够时创建新账号。
- 保存 Codex OAuth 认证文件，并同步到 CPA / Sub2API。
- 通过 Web 面板提供账号池、Team 成员、OAuth 登录、同步、配置、日志和任务历史。

主要入口：

- CLI 入口：`src/autoteam/manager.py` (`main`, `cmd_rotate`, `cmd_fill`, `cmd_check`, `cmd_cleanup`)。
- HTTP API：`src/autoteam/api.py`。
- 前端入口：`web/src/App.vue` 和 `web/src/api.js`。
- 配置读取：`src/autoteam/config.py`、`src/autoteam/setup_wizard.py`。

已有普通文档：

- `README.md`: 用户视角功能和快速开始。
- `docs/getting-started.md`: 首次部署流程。
- `docs/configuration.md`: 配置项、认证文件、本地数据文件。
- `docs/architecture.md`: 轮转、状态机、同步模型。
- `docs/browser-automation.md`: Playwright 和 OAuth 浏览器能力。
- `docs/api.md`: HTTP API。
- `docs/docker.md`: 容器部署。
- `docs/troubleshooting.md`: 常见故障。

当前 llmdoc 只记录可从代码和已有文档确认的事实。没有确认的线上行为不要写成事实。
