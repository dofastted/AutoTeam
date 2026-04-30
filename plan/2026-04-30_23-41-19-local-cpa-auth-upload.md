---
mode: plan
task: "Local CPA auth upload route"
created_at: "2026-04-30T23:41:19+08:00"
complexity: complex
---

# Plan: Local CPA Auth Upload Route

## Goal

- 废弃旧认证路线。注册只保存 ChatGPT session 备份，CPA / Sub2API 只上传本地已经完成的 OAuth RT 认证文件。
- `session_auth_file` 只作为注册备份和后续 OAuth 辅助材料，不再被任何同步流程当成可上传凭证。
- `rt_auth_file` 成为账号池 CPA / Sub2API 同步的主字段。
- `auth_file` 只保留兼容期语义，不能再作为同步主判断。
- 同步动作只上传本地已有文件，不启动浏览器，不补 OAuth，不从 CPA 拉回覆盖本地。

## Scope

In:

- `accounts.json` 认证字段语义收口。
- `src/autoteam/codex_auth.py` 认证文件保存和文件类型判断。
- `src/autoteam/manager.py` 注册、补位、复用和轮转中的认证字段写入。
- `src/autoteam/cpa_batch.py` 批量 CPA 任务中的 session、OAuth RT、CPA 上传阶段。
- `src/autoteam/cpa_sync.py` CPA 本地文件上传。
- `src/autoteam/sub2api_sync.py` Sub2API 本地文件上传。
- `src/autoteam/api.py` 单账号登录、单账号 CPA 认证上传、同步接口。
- Web 同步中心、OAuth 登录页和账号池操作页的按钮状态、返回结果展示。
- `docs/`、`llmdoc/`、单元测试和前端构建验证。

Out:

- 不改邮箱 provider。
- 不改 Team 成员增删核心逻辑，除非它仍依赖旧认证字段。
- 不提交真实 `.env`、`accounts.json`、`state.json`、`auths/` 或 token 文件。
- 不删除用户本地历史 auth 文件，只做识别、迁移元数据或报告。
- 不把 CPA 反向导入放入日常同步主流程。

## Assumptions / Dependencies

- `auths/codex-{email}-{plan_type}-{hash}-session.json` 是 ChatGPT session 备份文件。
- `auths/codex-{email}-{plan_type}-{hash}-oauth.json` 是 CPA / Sub2API 可上传的 OAuth RT 文件。
- 可上传文件必须含 `refresh_token`，且 `credential_source` 不能是 `chatgpt_session`。
- 单账号 `/api/accounts/{email}/cpa-auth` 属于“认证并上传”入口，允许缺 RT 时先跑 OAuth，再上传新生成的 RT 文件。
- 普通同步 `/api/sync/cpa`、`/api/sync/sub2api` 不允许启动浏览器或补 OAuth。
- `pull-cpa` 保留为人工恢复工具，但不属于新主流程。

## Phases

1. 定义 OAuth RT 文件选择契约。
   - 新增统一 helper，例如 `select_oauth_rt_auth_file(account)` 和 `is_uploadable_oauth_rt_file(path)`。
   - helper 优先读取 `rt_auth_file`。
   - 兼容期允许检查旧 `auth_file`，但必须确认文件含 `refresh_token` 且不是 session 文件。
   - 只有 `session_auth_file` 时必须返回不可上传。
   - 用单测先固定失败和成功场景。

2. 收口注册和登录写入。
   - 注册成功后只写 `session_auth_file`，不写 `auth_file=session_auth_file`。
   - OAuth 成功后写 `rt_auth_file`。
   - 兼容期可写 `auth_file=rt_auth_file`，但只能在 OAuth RT 成功后写。
   - `manual_account.py` 和 `/api/accounts/{email}/login` 只写本地 RT 文件，不自动同步远端。

3. 改 CPA 同步为只上传本地完成文件。
   - `cpa_sync.py` 全部改用统一 helper。
   - 缺 RT 的账号返回 skipped，原因使用 `missing_oauth_rt_file`。
   - session 文件返回 skipped，原因使用 `session_file_not_uploadable`。
   - 上传成功后写 `cpa_uploaded_at`。
   - 普通同步不删除远端文件；删除动作保留为独立清理入口。

4. 改 Sub2API 同步为同一规则。
   - `sub2api_sync.py` 全部改用统一 helper。
   - 全量同步缺 RT 时跳过。
   - 用户主动同步单账号缺 RT 时返回明确错误。
   - 批量 CPA 成功后的 Sub2API 同步只用刚生成的本地 RT 文件。
   - Sub2API 失败不回滚 CPA 成功状态，只记录错误或警告。

5. 做历史数据迁移和报告。
   - 扫描 `accounts.json`。
   - 若 `rt_auth_file` 为空而 `auth_file` 是有效 OAuth RT 文件，则补写 `rt_auth_file`。
   - 若 `auth_file` 指向 session 文件，不迁移为 RT。
   - 缺文件只记录报告，不删除账号。
   - 报告输出已迁移、只有 session、缺文件、可上传 RT、需要重新 OAuth 的数量。

6. 改 Web 状态和文案。
   - OAuth 登录页区分 session 备份、OAuth RT、CPA 已上传、Sub2API 已同步。
   - 同步中心按钮改为“上传本地 CPA 认证文件”和“上传本地 OAuth RT 到 Sub2API”这类明确动作。
   - CPA 拉取放入恢复类区域，不作为日常同步按钮。
   - 账号表不再只显示 `has_auth_file`，改为显示 session、RT、CPA、Sub2API 状态。

7. 删除旧路线代码。
   - 删除用 `auth_file` 直接判断可上传的路径。
   - 删除 `rt_auth_file -> auth_file -> session_auth_file` 这类候选顺序。
   - 删除同步阶段自动补 OAuth 的旧行为。
   - 删除 CPA 同步默认删除非 active 远端文件的普通同步语义。
   - 删除注册成功后用 Team 成员检查兜底判成功的旧成功分支。

8. 更新文档并完成验证。
   - 更新 `llmdoc/architecture/browser-and-oauth.md`。
   - 更新 `llmdoc/architecture/sync-targets.md`。
   - 更新 `llmdoc/architecture/account-lifecycle.md`。
   - 更新 `llmdoc/reference/config-data-files.md`。
   - 更新 `llmdoc/guides/cpa-oauth-and-fill.md`。
   - 更新 `docs/api.md`、`docs/configuration.md`、`docs/getting-started.md`、`docs/troubleshooting.md` 和 `README.md` 相关同步描述。

## Tests & Verification

- 认证文件选择契约 -> 新增或扩展 `tests/unit/test_codex_auth_session.py`、`tests/unit/test_auth_file_selection.py`。
- 注册和登录字段写入 -> 扩展 `tests/unit/test_manager_fill.py`、`tests/unit/test_manager_reinvite.py`、`tests/unit/test_manual_account.py`、API login 测试。
- CPA 同步只上传 RT 文件 -> 扩展 `tests/unit/test_cpa_sync.py`、`tests/unit/test_cpa_batch.py`、`tests/unit/test_api_cpa_batch.py`。
- Sub2API 同步只上传 RT 文件 -> 扩展 `tests/unit/test_sub2api_sync.py`。
- 前端状态和文案 -> `npm --prefix web run build`。
- 全量单测 -> `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit`。

## Issue CSV

- Path: `issues/2026-04-30_23-41-19-local-cpa-auth-upload.csv`
- Must share the same timestamp/slug as this plan.

## Tools / MCP

- `mcp__feedback.codebase_retrieval`: 语义检索认证、同步、API 和前端现有实现。
- `rg`: 查找剩余 `auth_file`、`session_auth_file`、`rt_auth_file` 判断点。
- `apply_patch`: 小范围编辑代码、文档、测试和计划文件。
- `pytest`: 后端单元测试。
- `npm --prefix web run build`: 前端构建验证。
- Windows Git: 按项目规则分文件暂存、提交和推送。

## Acceptance Checklist

- [ ] 注册成功后不会把 session 文件写入 `auth_file`。
- [ ] CPA 普通同步不会启动浏览器。
- [ ] Sub2API 普通同步不会启动浏览器。
- [ ] CPA / Sub2API 普通同步不会自动跑 OAuth。
- [ ] 只有 `rt_auth_file` 或可迁移的旧 OAuth RT 文件能上传。
- [ ] session 文件在任何同步路径都无法上传。
- [ ] 缺 RT 的账号会被标记为需要 OAuth。
- [ ] 单账号“认证并上传”仍能先 OAuth 再上传 CPA。
- [ ] 批量 CPA 仍能完成注册、OAuth RT、CPA 上传、可选 Sub2API 同步。
- [ ] `pull-cpa` 被标记为恢复工具，不参与日常同步主流程。
- [ ] 文档不再使用旧的 `auth_file` 主流程表述。
- [ ] 后端单测和前端构建通过。

## Risks / Blockers

- 老数据里 `auth_file` 可能同时指向 session 和 OAuth RT，所以迁移必须检查文件内容，不能只看字段名。
- 有些测试可能把 `auth_file` 当唯一字段，需要改成 `rt_auth_file` 或显式旧数据迁移场景。
- 前端已有展示可能只看 `has_auth_file`，需要改成更明确的 session、RT、CPA、Sub2API 状态。
- 如果 CPA 远端已有旧文件，同步要按邮箱和文件名跳过，不能重复上传。
- 如果用户还依赖 `auth_file` 导出给 Codex CLI，要保留导出兼容，不能直接破坏导出功能。

## Rollback / Recovery

- 每个 phase 单独提交。
- Phase 0 到 Phase 3 完成前不删除旧代码，只改调用路径和测试。
- Phase 4 迁移只改 `accounts.json` 元数据，不改 token 文件内容。
- 如果新同步失败，可以退回上一 commit，现有本地 `auths/` 文件不会被删除。
- CPA 远端删除动作不放在普通同步中，避免误删。
- 上线前先 dry-run 一次迁移报告，确认可上传数量和需 OAuth 数量。

## Checkpoints

- Commit after: Phase 0 认证文件选择契约。
- Commit after: Phase 1 字段写入收口。
- Commit after: Phase 2 CPA 同步新规则。
- Commit after: Phase 3 Sub2API 同步新规则。
- Commit after: Phase 4 迁移工具和报告。
- Commit after: Phase 5 前端状态改造。
- Commit after: Phase 6 和 Phase 7 清理旧路线并更新文档。
- Commit after: 全量测试和前端构建通过。

## References

- `llmdoc/startup.md`: 仓库读取顺序。
- `llmdoc/must/runtime-facts.md`: 当前 session 与 OAuth RT 文件事实。
- `llmdoc/architecture/browser-and-oauth.md`: 注册、Codex OAuth、手动 OAuth 入口。
- `llmdoc/architecture/sync-targets.md`: CPA / Sub2API 同步当前行为和推荐模型。
- `llmdoc/reference/config-data-files.md`: `accounts.json` 字段和 auth 文件命名。
