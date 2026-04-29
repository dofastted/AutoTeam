# 远端同步

## 分发入口

`src/autoteam/sync_targets.py`: 根据运行配置决定启用 CPA、Sub2API 或两者。

- `SYNC_TARGET_CPA` 控制 CPA。
- `SYNC_TARGET_SUB2API` 控制 Sub2API。
- 未显式设置开关时，存在完整连接配置会被视为启用。

## CPA

`src/autoteam/cpa_sync.py`: 负责 CPA 认证文件列表、上传、删除、下载、去重、正向同步、反向同步、主号文件同步。

正向同步 `sync_to_cpa`：

- 读取本地账号。
- 修复断裂的 `auth_file` 路径。
- 只上传 active 账号认证文件。
- 删除 CPA 中本地管理账号但不再 active 的文件。
- 返回上传、删除、本地去重等统计结果。

HTTP 入口：

- `/api/sync`: 按已启用目标同步 CPA / Sub2API。
- `/api/sync/cpa`: 只同步 CPA，账号池操作页的 CPA 推送按钮使用这个入口。
- `/api/sync/sub2api`: 只同步 Sub2API，账号池操作页和同步中心的 Sub2API 推送按钮使用这个入口。

反向同步 `sync_from_cpa`：

- 下载 CPA 中的 `codex-*.json`。
- 按账号去重。
- 比较 `last_refresh` 和 `expired`。
- CPA 文件更旧时保留本地文件。
- 新导入账号默认写为 standby。

单账号 CPA 认证入口：

- `src/autoteam/api.py` (`post_account_cpa_auth`): 面向 Web OAuth 页。仅允许 active 席位账号。若本地有 auth 文件则上传；若没有则自动执行 Codex OAuth，确认 `plan_type=team` 后上传。
- `src/autoteam/cpa_batch.py` (`run_cpa_batch`): 批量直注账号在注册成功后优先使用 ChatGPT Web session 生成本地 auth 文件，再上传 CPA；该批量路径不依赖 Codex OAuth callback。

## Sub2API

`src/autoteam/sub2api_sync.py`: 负责登录 Sub2API、读取 OpenAI OAuth 账号、上传账号池认证文件、同步主号认证文件、处理 `SUB2API_GROUP`。

`SUB2API_GROUP` 可填分组名或分组 ID，多个值用逗号分隔。同步时会保留用户手工绑定的其他分组，只替换 AutoTeam 管理的分组绑定。分组不存在时，账号推送和按邮箱去重仍会继续，返回结果的 `warnings` 会说明已跳过分组绑定。

账号池推送到 Sub2API 时，以邮箱为去重键。若远端已有同邮箱 OpenAI OAuth 账号，会更新已有账号而不是新建；AutoTeam 自己标记的重复账号会删除多余项。

## 主号同步

主号认证文件由 `src/autoteam/codex_auth.py` (`save_main_auth_file`) 保存为 `auths/codex-main-*.json`。

`src/autoteam/sync_targets.py` (`sync_main_codex_to_configured_targets`) 会把主号文件同步到已启用远端。CPA 侧实现是 `src/autoteam/cpa_sync.py` (`sync_main_codex_to_cpa`)。

账号池操作页的 OAuth 凭证推送按钮使用 `/api/sync/main-codex/saved`，只上传本地已有主号凭证，不启动浏览器登录。没有本地主号凭证时，返回错误并要求先到配置面板完成主号 Codex 登录。
