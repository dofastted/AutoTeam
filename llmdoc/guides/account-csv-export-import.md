# 账号 CSV 导出导入指南

适用范围：导出库存账号、导出已售账号、预览外部 CSV 导入结果。

## 1. 现状

CSV 能力都在 `src/autoteam/account_exports.py`：

- `export_inventory_csv`，`src/autoteam/account_exports.py:121`
- `export_sold_csv`，`src/autoteam/account_exports.py:158`
- `dry_run_import_csv`，`src/autoteam/account_exports.py:197`

当前仓库里没有把这三个函数接成公开 HTTP API。它们目前是库函数和测试覆盖能力，测试见 `tests/unit/test_account_exports.py`。

## 2. 导出库存 CSV

库存导出只收 `category=inventory` 且不是主号的记录，见 `src/autoteam/account_exports.py:90-91`。

导出列头固定为：

- `email`
- `password`
- `cpa_json_path`
- `auth_file_path`
- `plan_type`
- `registered_at`
- `updated_at`
- `note`

定义见 `src/autoteam/account_exports.py:10-19`。

导出时优先取 V2 凭证路径：

- `credentials.cpa_archive.path/file`
- `credentials.oauth_rt.path/file`

如果没有，再回退到旧平铺字段：

- `cpa_json`
- `rt_auth_file`
- `auth_file`

实现见 `src/autoteam/account_exports.py:132-137`。

## 3. 导出已售 CSV

已售导出接受三种识别方式，见 `src/autoteam/account_exports.py:94-101`：

- `usage_status=sold`
- 旧 `status=sold`
- `sale.sold_at` 存在

列头固定为：

- `email`
- `sold_at`
- `sold_to`
- `sale_price`
- `sale_note`
- `sale_batch_id`
- `plan_type`
- `original_inventory_at`

定义见 `src/autoteam/account_exports.py:21-30`。

`sold_to` / `sale_price` / `sale_note` / `sale_batch_id` 会优先取 `sale` 嵌套块，再回退到旧平铺字段，见 `src/autoteam/account_exports.py:169-187`。

## 4. 跑外部 CSV 导入 dry-run

导入预览只解析文本，不写 `accounts.json`。入口是 `dry_run_import_csv`。

默认必填列只有 `email`，见 `src/autoteam/account_exports.py:197-202`。

返回结构包括：

- `headers`
- `row_count`
- `to_add`
- `conflicts`
- `missing_fields`
- `invalid_rows`
- `summary`

实现见 `src/autoteam/account_exports.py:213-297`。

冲突规则：

- 同邮箱已存在本地账号，记 `duplicate_email`
- 同一个 CSV 里邮箱重复，记 `duplicate_in_csv`
- 缺必填列，记入 `missing_fields`
- CSV 结构坏掉或额外值溢出，记入 `invalid_rows`

邮箱比较按小写处理，见 `src/autoteam/account_exports.py:208-212` 和 `src/autoteam/account_exports.py:271-284`。

## 5. 使用时要注意

- 库存导出不会带主号，见 `tests/unit/test_account_exports.py:58`
- 导出优先认 V2 嵌套字段，但仍兼容旧平铺字段，见 `tests/unit/test_account_exports.py:83` 和 `tests/unit/test_account_exports.py:103`
- 当前没有“导入 apply”实现，只有 dry-run 预览
- 这些函数默认返回 UTF-8 BOM 文本，参数 `encoding` 默认 `utf-8-sig`

如果后面要把 CSV 接到 HTTP API，先保持这套列头和冲突口径不变，再补对应的权限和主号保护。
