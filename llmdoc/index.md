# AutoTeam llmdoc 索引

本目录为 AutoTeam 的 LLM 优先文档。先读 `llmdoc/startup.md`，再按任务进入对应文档。

## 启动入口

- `llmdoc/startup.md`: 每次进入仓库后的读取顺序。
- `llmdoc/must/runtime-facts.md`: 任务前必须知道的运行事实。
- `llmdoc/must/task-safety.md`: 修改代码、运行命令、处理敏感数据时的注意点。

## 项目概览

- `llmdoc/overview/project-overview.md`: 项目用途、边界、核心工作方式。

## 架构文档

- `llmdoc/architecture/account-lifecycle.md`: 账号状态、轮转、补位、清理。
- `llmdoc/architecture/browser-and-oauth.md`: Playwright、管理员登录、Codex OAuth、手动 OAuth。
- `llmdoc/architecture/outbound-proxy.md`: 后端外部请求、出口代理池、Playwright 代理继承。
- `llmdoc/architecture/sync-targets.md`: CPA / Sub2API 正向同步、CPA 反向导入、主号同步。
- `llmdoc/architecture/api-and-web.md`: FastAPI 后端、Vue 前端、任务与页面关系。

## 工作指南

- `llmdoc/guides/local-development.md`: 本地安装、测试、前端构建、启动。
- `llmdoc/guides/cpa-oauth-and-fill.md`: OAuth 登录页 CPA 凭证检查与 10 个一批补位流程。

## 参考

- `llmdoc/reference/config-data-files.md`: `.env`、`accounts.json`、`state.json`、`auths/` 等数据文件。
- `llmdoc/reference/module-map.md`: 主要 Python / Vue 模块职责。

## 记忆

- `llmdoc/memory/doc-gaps.md`: 仍需补强的文档项。
- `llmdoc/memory/decisions/`: 稳定决策记录。
  - `llmdoc/memory/decisions/2026-04-30-async-incremental-sync.md`: CPA / Sub2API 异步增量同步策略。
- `llmdoc/memory/reflections/`: 任务后的过程记录。

临时调查材料放在 `.llmdoc-tmp/investigations/`，不作为稳定文档读取。
