# AutoTeam 账号管理重构 - 编排执行进度

> 总指挥：Claude Code (sonnet)
> 执行人：Codex (gpt-5.4) via `ccw cli --tool codex` 后台调用
> 起始日期：2026-05-03
> 工作分支：`acc`
> CSV 进度回写：04-AutoTeam-账号管理重构-TODO.csv (status / notes / commit_sha / evidence)

## 编排原则

1. 阶段化串行 + 阶段内并行：8 个阶段严格串行；阶段内互不冲突的任务由 Codex 并发承接
2. 同文件冲突：改动同一文件的任务必须串行（cpa_batch.py / api.py / account_inventory.py / account_health.py / account_cleaner.py / account_credentials.py / account_exports.py）
3. P0 验收：Codex 完成后由总指挥 `uv run pytest <相关用例>` 通过；涉及前端文件的任务必须 `cd web && npm run build` 通过
4. P1 验收：阶段末聚合一次完整 `uv run pytest` + `npm run build`
5. 每条任务一次 commit，commit message 含 `AT-XXX` 引用
6. 任务完成回写 CSV：status (`done`/`failed`/`skipped`), notes, commit_sha, evidence (相关测试用例 / 构建日志摘要)
7. 数据安全：accounts.json / auths/ 不存在则跳过备份；任何 Codex 任务禁止真实运行 CPA 远端操作

## 阶段编排

### Phase 0 - 准备
- 扩展 CSV 列 (done)
- 落盘编排计划 (done)
- 抽查 ccw + codex 工具链 (done, ccw v3.4.0, codex 主备 gpt-5.4)

### Phase 1 - 数据契约层 (并行可，共 3 任务)
- AT-001 src/autoteam/account_models.py 四轴状态枚举 + V2 数据结构 (P0)
- AT-002 src/autoteam/account_classifier.py classify_account (P0)
- AT-036 src/autoteam/account_store.py 旧 status 映射到四轴 (P0)
- 阶段验收：`uv run pytest tests/unit/test_account_classifier.py`（先建空骨架），`uv run pytest -q` 不应回归

### Phase 2 - 数据清理与认证识别 (并行批 + 串行批)
- 并行批 A：
  - AT-003 account_cleaner.py 自动备份 (P0)
  - AT-006 account_credentials.py 文件类型识别 (P0)
- 串行批 B（依赖 A）：
  - AT-004 account_cleaner.py dry-run 扫描 (P0)
  - AT-005 account_cleaner.py 邮箱去重合并 (P0)
  - AT-007 account_credentials.py auth_file 迁移 (P0)
  - AT-008 account_cleaner.py 分类重算 (P0)
- 阶段验收：dry-run 用 fixture 跑通，apply 输出稳定

### Phase 3 - 母号 + 邮箱分配 (全并行)
- AT-009 account_admin.py role=main 模型 (P0)
- AT-010 account_admin.py session 摘要 + main auth 引用 (P0)
- AT-011 account_email_allocator.py 50 个一组 (P0)
- AT-012 mo_email.py NAME_PATTERN 配置 (P1)
- 阶段验收：单测覆盖 allocator 边界（第 51 个换前缀）

### Phase 4 - 注册/RT/CPA/Sub2API 流程接入 (cpa_batch.py 串行 + account_remote.py 并行)
- AT-013 cpa_batch.py 注册成功写 registration_status=registered (P0)
- AT-014 cpa_batch.py RT 提取后写 oauth_rt + rt_obtained_at (P0)
- AT-015 cpa_batch.py CPA 上传成功调用 mark_inventory (P0)
- AT-016 account_remote.py 记录 sub2api 状态 (P1)
- 阶段验收：`uv run pytest tests/unit/test_manager_*.py tests/unit/test_sync_targets.py`

### Phase 5 - 库存 / 售卖 / 失效 (account_inventory.py 与 account_health.py 内串行，文件间并行)
- AT-017 account_inventory.allocate_account (P0)
- AT-018 account_inventory.release_account (P1)
- AT-019 account_inventory.sell_account (P0)
- AT-020 sync_targets.py sold/sync_disabled 保护 (P0)
- AT-021 account_health.py 401/auth_error/deactivated (P0)
- AT-022 account_health.py quota vs invalid 区分 (P0)
- 阶段验收：sold 账号无法被 allocate；quota 不归 invalid

### Phase 6 - HTTP API (api.py 全部串行)
- AT-023 GET /api/accounts (P0)
- AT-024 GET /api/accounts/{email} (P0)
- AT-025 /api/accounts/clean/dry-run + /apply (P0)
- AT-026 allocate / release / sell / mark-invalid / repair-oauth (P0)
- 阶段验收：`uv run pytest tests/unit/test_api_status.py` + 新增 test_accounts_api.py

### Phase 7 - 前端账号管理中心 (并行)
- AT-027 web/src/components/Sidebar.vue 入口 (P1)
- AT-028 web/src/components/AccountManagement.vue 五类 tab (P0)
- AT-029 web/src/components/AccountTable.vue 表格 + 批量 (P0)
- AT-030 web/src/components/AccountDrawer.vue 详情抽屉 (P1)
- AT-031 web/src/components/AccountCleanPage.vue 清理三步 (P1)
- 阶段验收：`cd web && npm run build` 通过；`src/autoteam/web/dist/` 更新

### Phase 8 - 导出 / 事件 / 测试 / 文档 (account_exports.py 内串行)
- AT-032 account_exports.py 库存 CSV (P0)
- AT-033 account_exports.py 已售 CSV (P1)
- AT-034 account_exports.py 导入 dry-run (P1)
- AT-035 data/account-ledger 事件日志 (P1)
- AT-037 tests/test_account_classifier.py (P0)
- AT-038 tests/test_account_cleaner.py (P0)
- AT-039 tests/test_accounts_api.py (P1)
- AT-040 llmdoc/architecture/account-management.md (P1)
- 阶段验收：全量 `uv run pytest` 通过；llmdoc 索引更新

## 执行日志

| 时间 | 阶段 | 操作 | 结果 |
|------|------|------|------|
| 2026-05-03 | Phase 0 | 扩展 CSV / 落盘计划 | done |
