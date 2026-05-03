# Automation Watchdog Operations

## watchdog_rerun_session_only.sh

`scripts/watchdog_rerun_session_only.sh` 是一次性脚本。它等待指定 `cpa-batch` run 退出运行态后，再触发 `scripts/backfill_session_only_oauth.sh` 的 Codex 执行 prompt。

### 关键环境变量

| 变量 | 默认值 | 说明 |
|------|------|------|
| `RUN_ID` | `6cd96d6df18a` | 要监控的 `cpa-batch` run id |
| `API_BASE` | `http://127.0.0.1:8788` | AutoTeam API 地址 |
| `POLL_INTERVAL` | `60` | 轮询间隔，单位秒 |
| `POLL_MAX_SECONDS` | `86400` | 硬上限，默认 24 小时 |

### 行为

1. 切到仓库根目录，读取 `.env` 中的 `API_KEY`。
2. 轮询 `GET /api/cpa-batch/runs/$RUN_ID`。
3. 只要状态还是 `running`、`pending` 或空串，就继续等待。
4. 状态一旦变成其他值，先退出轮询。
5. 再调用 `/api/tasks` 做第二次确认；如果还有运行中的 `cpa-batch` 或 `cpa-auth` 任务，就直接退出，不触发后续补传。
6. 确认没有阻塞任务后，用 `nohup codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check` 执行 `.tmp/codex-runs/rerun-A-only.prompt.md`。
7. 等待 `codex exec` 子进程退出，并把它的退出码原样传回脚本调用方。

### 运行产物

脚本当前会写这些文件：

- `.tmp/watchdog-rerun-A.log`
- `.tmp/watchdog-rerun-A.state`
- `.tmp/codex-runs/rerun-A-only.pid`
- `.tmp/codex-runs/rerun-A-only-<timestamp>.log`
- `.tmp/codex-runs/rerun-A-only-<timestamp>.last_message`

其中 `.tmp/watchdog-rerun-A.log` 是主日志，状态变化和 codex 启动、退出码都会写进去。

### 单次触发边界

这个脚本不是守护进程，只会在本次 run 离开 `running/pending` 后最多触发一次。如果达到 `POLL_MAX_SECONDS` 仍未结束，会退出码 `2` 结束；如果二次确认发现还有 `cpa-batch` 或 `cpa-auth` 任务在跑，会退出码 `3` 结束。

## backfill_session_only_oauth.sh 状态接受范围

`scripts/backfill_session_only_oauth.sh` 当前轮询单账号任务结果时，接受下面几类状态：

- 成功：`success`、`completed`
- 失败终止：`failed`、`error`

这次改动的关键点是把 `completed` 纳入成功分支，和 API 任务枚举对齐。以后如果任务状态再扩展，例如加 `done`，需要同步改两处判断：

- 提前跳出轮询的状态集合
- 记为成功的状态集合

## 使用前提

- `uv run autoteam api` 对应的服务要能从 `API_BASE` 访问。
- `.env` 必须存在，且有 `API_KEY`。
- `.tmp/codex-runs/rerun-A-only.prompt.md` 必须已经准备好。
- 本机 `codex` 命令要可执行。

## 常见误用

- 不要把它当持续巡检。持续恢复应该走现有 hook 或另建定时器。
- 不要跳过 `/api/tasks` 的二次确认。只看 run 状态，可能会和仍在执行的 `cpa-auth` 打架。
- 不要把 `API_BASE` 默认为 `8787`。当前脚本写死的默认端口是 `8788`，使用前要确认对应服务真跑在这个端口。
