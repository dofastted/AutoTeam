# AutoTeam 启动读取顺序

每次进入本仓库，先按下面顺序读取。

1. `llmdoc/must/runtime-facts.md`
2. `llmdoc/must/task-safety.md`
3. `llmdoc/overview/project-overview.md`

按任务继续读取：

- 账号轮转、补位、清理：读 `llmdoc/architecture/account-lifecycle.md`。
- 需要在 `cpa-batch` 运行期间清理失败账号：再读 `llmdoc/guides/account-cleanup-strategy.md`。
- 管理员登录、浏览器自动化、Codex OAuth：读 `llmdoc/architecture/browser-and-oauth.md`。
- 出口代理、OpenAI/邮箱/远端同步网络请求：读 `llmdoc/architecture/outbound-proxy.md`。
- CPA / Sub2API / auth 文件：读 `llmdoc/architecture/sync-targets.md` 和 `llmdoc/reference/config-data-files.md`。
- Web 页面或 HTTP API：读 `llmdoc/architecture/api-and-web.md`。
- 本地测试、构建、启动：读 `llmdoc/guides/local-development.md`。
- OAuth 登录页 CPA 凭证检查、10 个一批补位：读 `llmdoc/guides/cpa-oauth-and-fill.md`。

如果文档和代码冲突，以当前代码为准，并更新相关 llmdoc。
