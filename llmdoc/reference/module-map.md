# 模块地图

## 后端核心

- `src/autoteam/manager.py`: CLI 命令、轮转、补位、清理、注册、复用旧账号。
- `src/autoteam/api.py`: FastAPI、Web API、后台任务、自动巡检、日志、前端静态文件。
- `src/autoteam/accounts.py`: `accounts.json` 持久化和账号状态辅助函数。
- `src/autoteam/account_ops.py`: Team 成员读取、账号删除、远端资源清理。
- `src/autoteam/admin_state.py`: 管理员登录态 `state.json`。
- `src/autoteam/config.py`: `.env` 配置读取和 Playwright 启动选项。
- `src/autoteam/setup_wizard.py`: 首次配置和运行配置写入。

## 浏览器与认证

- `src/autoteam/chatgpt_api.py`: 管理员浏览器会话、ChatGPT Team 内部 API。
- `src/autoteam/codex_auth.py`: Codex OAuth、token refresh、额度查询、auth 文件写入。
- `src/autoteam/manual_account.py`: 手动 OAuth 链接、localhost callback、粘贴 callback。
- `src/autoteam/invite.py`: 邀请链接注册流程。
- `src/autoteam/display.py`: Linux 图形环境处理。

## 邮箱

- `src/autoteam/mail_provider.py`: 邮箱 provider 选择和账号级 provider 解析。
- `src/autoteam/mo_email.py`: Mo Email 客户端。
- `src/autoteam/cloudmail.py`: CloudMail 客户端。
- `src/autoteam/cloudflare_temp_email.py`: Cloudflare Temp Email 客户端。

## 同步目标

- `src/autoteam/sync_targets.py`: CPA / Sub2API 分发。
- `src/autoteam/cpa_sync.py`: CPA 文件上传、下载、删除、去重、主号同步。
- `src/autoteam/sub2api_sync.py`: Sub2API 登录、账号同步、分组处理。

## 前端

- `web/src/App.vue`: 顶层页面状态和导航。
- `web/src/api.js`: API client。
- `web/src/components/Dashboard.vue`: 账号列表和账号操作。
- `web/src/components/OAuthPage.vue`: 手动 OAuth 与 CPA 凭证检查。
- `web/src/components/TaskPanel.vue`: 账号池和同步按钮。
- `web/src/components/ConfigPage.vue`: 运行配置。
- `web/src/components/TeamMembers.vue`: Team 成员。
- `web/src/components/TaskHistory.vue`: 任务历史。
- `web/src/components/LogViewer.vue`: 日志查看。

## 测试

- `tests/unit/test_manager_fill.py`: 补位行为。
- `tests/unit/test_manager_rotate.py`: 轮转行为。
- `tests/unit/test_api_status.py`: API、自动巡检、配置行为。
- `tests/unit/test_sync_targets.py`: 同步目标开关。
- `tests/unit/test_sub2api_sync.py`: Sub2API。
- `tests/unit/test_api_main_codex_after_admin.py`: 主号 Codex。
