# 账号 Ledger 追踪指南

适用范围：为新接入点补账号事件审计，或离线查询某个账号的历史动作。

## 1. 现状

ledger 模块已经独立实现，入口在 `src/autoteam/account_ledger.py`：

- 写入：`append_event`，`src/autoteam/account_ledger.py:33`
- 读取：`read_events`，`src/autoteam/account_ledger.py:82`

落盘目录默认是 `data/account-ledger`，按天拆成 `YYYY-MM-DD.jsonl`，见 `src/autoteam/account_ledger.py:20`。

当前它还没有自动接到这些流程：

- `cpa_batch`
- `account_inventory`
- `account_health`
- 账号详情 API 的 `events`

这不是推测，`GET /api/accounts/{email}` 现在固定返回 `events: []`，见 `src/autoteam/api.py:2110`。

## 2. 什么时候手动接入

如果你新增的动作需要追溯是谁、什么时候、对哪个账号做了什么，就在动作真正成功落库之后手动调用 `append_event`。

适合接的点：

- 注册成功后
- RT 文件补齐后
- 进库存后
- 分配 / 释放后
- 标记失效后
- 售卖后

不适合接的点：

- 还没落库的预检
- 失败会重试的中间步骤
- 纯前端开关切换

## 3. 写事件的最小要求

`append_event` 的参数：

- `event_type`
- `email`
- `actor`
- `payload`
- `ledger_dir`
- `now`

字段定义见 `src/autoteam/account_ledger.py:33-57`。

建议约定：

- `event_type` 用稳定短词，比如 `register`、`inventory`、`allocate`
- `actor` 写来源，比如 `api`、`auto_check`、`manual`、`system`
- `payload` 只写和追溯有关的最少信息，比如 `allocation_id`、`reason`、`project`

事件 ID 由模块自己生成，格式是 `evt_<unix>_<6hex>`，见 `src/autoteam/account_ledger.py:25`。

## 4. 读某个账号的历史

查单个账号历史时，用 `read_events(email=...)`。

如果只想看某段时间，再补：

- `since_ts`
- `until_ts`

读取时会：

- 跳过坏行
- 只保留时间字段合法的记录
- 按 `ts`、`event_id` 升序排序

实现见 `src/autoteam/account_ledger.py:60-105`。

## 5. 接入时的边界

- `append_event` 只是本地 jsonl 追加，不会回写 `accounts.json`
- `read_events` 是全量扫目录后过滤，不是索引库
- 现在没有任何自动补写历史事件的迁移器
- API 和前端都还没把真实 ledger 展示出来

所以现在 ledger 的定位是“底层能力已就绪，调用方按需接入”。

## 6. 测试参考

现有测试在 `tests/unit/test_account_ledger.py`，覆盖了：

- 写单条事件
- 同文件连续追加
- 按邮箱过滤
- 按时间范围过滤
- 坏行容错
- 排序稳定性

如果你给新流程接 ledger，至少补一条“动作成功后真的写出事件”的测试。
