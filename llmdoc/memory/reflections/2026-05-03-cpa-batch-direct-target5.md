# CPA 批量直注 target=5 验证：链路通但出现 run 状态死锁与 about-you 卡死

## 背景

- 时间：2026-05-03 15:54-16:17（北京时间）。
- 实例：AutoTeam `127.0.0.1:8788`，PID `1561`，15:34 启动。
- 入口：`POST /api/tasks/cpa-batch`，参数为 `{"join_mode":"direct","target":5,"batch_size":5,"parallel_workers":1,"continue_on_error":true}`。
- 任务标识：`task_id=88f434727b05`，`run_id=d02ef7b1f6c1`。
- 本次关键运行参数：`FILL_BATCH_SIZE=100`、`BROWSER_PARALLEL_WORKERS=1`、`PLAYWRIGHT_BROWSER_MODE=visible`、`OUTBOUND_PROXY_POOL=http://127.0.0.1:10808`、`SYNC_TARGET_CPA=true`、`SYNC_TARGET_SUB2API=true`、`SUB2API_GROUP=openai`。这些参数与 `llmdoc/must/runtime-facts.md` 中对 direct 单窗口串行处理、出口代理和 CPA / Sub2API 同步的描述一致。

## 操作

1. 用 direct 模式做 `target=5` 的单窗口顺序验证，链路按 `src/autoteam/cpa_batch.py:1281` 的 `run_cpa_batch` 主流程推进。
2. 每个账号在 `src/autoteam/cpa_batch.py:536` 的 `_create_direct_account` 中完成邮箱创建、账号落库、注册、session 备份和浏览器内 OAuth RT 提取。
3. 直接注册核心在 `src/autoteam/manager.py:1548` 的 `_register_direct_once`。它会完成邮箱页、密码页、验证码、about-you、workspace 选择、`admin/members` 检查，并在成功后继续做浏览器内 Codex PKCE OAuth。
4. Codex OAuth RT 由 `src/autoteam/protocol_oauth.py:1178` 的 `run_protocol_oauth_login_with_browser_context` 在已登录的浏览器上下文内拿 callback，再交换 `/oauth/token` 得到 `refresh_token`。
5. CPA 校验和上传由 `src/autoteam/cpa_batch.py:1137` 的 `_verify_and_upload_cpa` 完成。成功后写入 `cpa_status=success`、`usage_status=inventory`、`cpa_uploaded_at`。
6. Sub2API 单账号同步由 `src/autoteam/cpa_batch.py:1234` 的 `_sync_cpa_account_to_sub2api` 调 `src/autoteam/sub2api_sync.py:821` 的 `sync_account_to_sub2api` 完成。

## 结果

- 链路本身已跑通，成功 `2/5`。
- `aqw-833@gymbro.cloud` 用时约 89 秒，窗口为 15:54:57-15:56:26。
- `aqw-834@gymbro.cloud` 用时约 93 秒，窗口为 15:56:28-15:58:01。
- 两个成功账号都完整经过下面链路：
  - MoEmail 创建邮箱。
  - 直接注册，过程中切到密码注册入口、设置密码、输入验证码、填写 about-you 年龄，随后进入 `chatgpt.com`。
  - 访问 `https://chatgpt.com/admin/members` 确认 workspace 可用，这和 `src/autoteam/manager.py:1993` 之后的校验逻辑一致。
  - 提取 ChatGPT session 备份，再在同一个浏览器上下文中调用 `src/autoteam/protocol_oauth.py:1178` 拿到 OAuth RT 文件。
  - CPA 上传成功，远端文件数从 `203` 变成 `205`。
  - Sub2API 成功创建账号到 `group=openai`。
- 本地状态也符合预期：两者在 `accounts.json` 中都写成 `status=active`、`plan_type=team`、`cpa_status=success`、`usage_status=inventory`，并有 `cpa_uploaded_at` 与 `sub2api_synced_at`。

## 问题

### 1. task stopped 但 run 仍 running

- 现象：Playwright Chromium 使用 `user-data-dir=/tmp/autoteam-chromium-profile` 时浏览器卡死，被外部 `kill -KILL` 强杀后，再调用 `/api/tasks/stop-all`，任务 `88f434727b05` 立即变成 `status=stopped` 并写入 `finished_at`；但 run `d02ef7b1f6c1` 长时间保留 `status=running`、`pause_requested=true`、`finished_at=None`，且统计停在 `attempted=4`、`succeeded=2`、`failed=2`。
- 影响：前端会一直把该 run 显示在“运行中批次”；同模式下次想新开批次，往往要先重启服务，或先 resume 再等它自然收尾。
- 代码定位：
  - `src/autoteam/cpa_batch.py:1441-1683` 的 `run_cpa_batch` 只会在正常返回、异常抛出或 finally 走到时写 run 终态并清理遗留账号状态。
  - `src/autoteam/cpa_batch.py:139-140` 的 `CpaBatchHooks.pause` 只会把 run 写成 `paused`，前提是主线程还能走到该分支。
  - `src/autoteam/flow_runs.py:125-158` 的 `fail_running_flow_accounts` 只负责账号级 `running` 记录清理，不负责把 run 顶层 `status` 改成终态。
  - `src/autoteam/cpa_batch.py:1294-1296` 只有 resume 时才会先调用 `fail_running_flow_accounts(run_id)`。
- 根因判断：从代码和现象看，外部强杀浏览器后，主任务线程没有及时走到 `run_cpa_batch` 的终态写回和 finally 清理，所以 task 已停，但 run 顶层状态没有兜底回写。这一点和 `llmdoc/must/runtime-facts.md` 中“恢复前会清理遗留 running 账号”并不冲突，但说明当前清理只覆盖 resume 路径，没有覆盖外部强杀后的顶层 run 收尾。

### 2. 连续直注时 about-you 后卡死

- 异常账号：`aqw-835@gymbro.cloud`，第 4 次 attempt，对应日志区间约为 15:58:04-16:04:30+。
- 关键现象：
  - 15:58:11 到达邮箱页，URL 为 `https://chatgpt.com/auth/login`。
  - 15:58:16 点击 Continue 后进入 `https://auth.openai.com/email-verification`。
  - 同一时刻记录了“密码页检测状态: code”，随后出现“未检测到密码输入框，跳过”。
  - 15:58:21 输入验证码 `470624`。
  - 15:58:30 到达 `https://auth.openai.com/about-you` 并填入年龄 `38`。
  - 之后 15 分钟以上没有新的 `[直接注册]`、Codex、CPA 日志，浏览器层 hung 住；`accounts.json` 中该账号一直停在 `status=pending`，`session_auth_file=None`、`rt_auth_file=None`。
- 对比已成功账号：
  - `aqw-833@gymbro.cloud` 与 `aqw-834@gymbro.cloud` 在 `src/autoteam/manager.py:1774-1889` 这段逻辑里都能检测到密码注册入口，进入 `https://auth.openai.com/create-account/password`，完成真实密码设置，再继续验证码和 about-you。
  - `aqw-835@gymbro.cloud` 走到了 `src/autoteam/manager.py:1798` 对应的“未检测到密码输入框，跳过”分支，随后 about-you 后没有继续进入 workspace 确认、session 提取和浏览器内 OAuth。
- 代码定位：
  - `src/autoteam/manager.py:1935-1944` 负责执行 `_complete_direct_about_you`。
  - `src/autoteam/manager.py:1951-1986` 负责 about-you 之后的 workspace / organization 处理。
  - `src/autoteam/manager.py:2035-2036` 在最终 URL 未进入 ChatGPT 时会判定“注册可能未完成”。
  - `src/autoteam/chatgpt_api.py:1425` 的 `complete_workspace_selection` 是 about-you 后进入有效 workspace 的公共逻辑。
- 根因判断：更像是连续注册条件下触发了 OpenAI 的差异分支或风控分支。当前实现对“验证码页没有密码入口”这条线虽允许跳过，但 about-you 后的等待和回退还不够强；再加上 direct 单窗口复用同一个浏览器 `user-data-dir`，可能把前一个账号的 cookie、storage 或风险状态带到下一个账号。
- 旁证：用户提供的旧日志显示，`2026-04-30 02:01:49` 之前的 `aqw-393` 也走过“未检测到密码输入框，跳过”后未完成注册，说明这不是一次性噪声。

## 后续动作

- 文档侧先记录两条明确缺口，已同步到 `llmdoc/memory/doc-gaps.md`。
- 代码排查应优先看下面两处：
  - `src/autoteam/cpa_batch.py:1441-1683` 与 `src/autoteam/flow_runs.py:125-172`，确认外部强杀浏览器、随后 stop-all 的场景下，run 顶层 `status` 是否需要独立的 finally 兜底。
  - `src/autoteam/manager.py:1774-2036` 与 `src/autoteam/chatgpt_api.py:1425`，确认“未检测到密码输入框，跳过”后，about-you 提交后的下一页等待、超时、回退和 profile 清理策略。
- 下次复验建议保持同样入口：先跑 direct `target=1`，再跑 direct `target=5`，继续观察同一出口 IP、同一 `user-data-dir`、约 90 秒间隔时是否稳定复现。
