# 2026-05-04 auths 扁平页文档补记

本轮只更新 llmdoc。新账号管理页以 `auths/` 文件扫描为列表来源，不再沿用旧五 tab `accounts.json` 生命周期视图。后续排查账号管理页时先区分 `/api/auths/accounts` 文件视图和 `/api/accounts` 生命周期视图；Dashboard 只看统计卡片，TeamMembers 只看真实 Team member，不再混 pending invite。

## 2026-05-04 复审与修复

本轮复审把 auth 文件统计拆成两个口径：`*_files` 只表示文件数量，`accounts_*` 表示按邮箱主分类后的账号数量。主分类不再因为根目录存在 active 文件就优先归为 active，而是由 `_bucket_primary_category(categories)` 按 `sold` > `tradable` > `unusable` > `archive` > `active` 判断，避免同一邮箱已进入 `sold/` 后仍在页面上显示为 active。

Dashboard 的 Team 统计改为优先读取 `_format_team_payload` 返回的 `total` 和 `invites` 整数，只有字段缺失时才按 `members[].type` 兜底。TeamMembers 只保留 `m.type === "member"`，因为 invite 已由后端明确打 `type="invite"`，不能再把缺少 type 的旧数据当 member。

单测补到 `tests/unit/test_api_auths_endpoints.py`，覆盖 `_parse_auth_filename`、`_bucket_primary_category`、`_scan_auths_files` 的缺目录和跨目录优先级，以及 `/api/auths/accounts` 的筛选、搜索、排序、分页、错误分支和 `/api/auths/stats`。本轮 29 个相关测试已通过。
