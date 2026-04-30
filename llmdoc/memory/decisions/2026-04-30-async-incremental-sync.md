# 异步增量同步策略

## 结论

前台账号操作和 CPA / Sub2API 号池同步应分离。

前台操作只负责本地状态变更和必要的远端账号动作。CPA / Sub2API 同步由后台任务执行。

默认配置建议：

- `SYNC_EXECUTION_MODE=async`
- `SYNC_UPLOAD_STRATEGY=incremental`
- `SYNC_DELETE_MISSING=false`
- `SYNC_FAILURE_POLICY=pause`
- `SYNC_AUTO_RETRY=transient`
- `SYNC_RETRY_MAX_ATTEMPTS=3`
- `SYNC_RETRY_BACKOFF_SECONDS=5,30,120`
- `SYNC_PAUSE_ON_SUCCESS_RATE_BELOW=95`

## 原因

前台页面不能被 CPA / Sub2API 的网络请求拖慢。账号注册、恢复、手动 OAuth、Team 成员查看等操作完成本地状态后，应立即返回。

历史账号补传应只上传远端缺失项。CPA 远端可能已经有一部分认证文件，Sub2API 也可能已经有同邮箱账号。使用邮箱和文件名做差异匹配可以减少重复写入，也能避免误删。

默认不删除远端文件。删除 CPA 文件或 Sub2API 账号属于高风险动作，必须走独立任务。

自动重试只用于临时错误。网络超时、HTTP 429、HTTP 5xx 可重试；本地认证文件缺失、token 无效、配置缺失、OpenAI 注册页稳定返回错误不应自动重试。

错误默认暂停。暂停比持续失败更安全，能保留现场，减少新邮箱和账号资源消耗。

## 影响

后续新增同步任务时，应优先做后台任务接口，前端只显示任务状态、暂停、恢复和错误。

现有 `/api/sync/cpa` 只同步 active 且有删除非 active 远端文件的语义，不能作为历史账号补传入口。

历史账号补传需要新增只上传、不删除的增量任务。
