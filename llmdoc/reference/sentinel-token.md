# Sentinel Token Reference

> `src/autoteam/sentinel.py` 的实现细节，当前文件头说明写明它移植自 `https://github.com/leetanshaj/openai-sentinel`

## Token 结构

`src/autoteam/sentinel.py` (`get_sentinel_token`) 返回的是 JSON 字符串，不是 base64 包，也不是 header 内嵌 JSON 对象。当前字段固定为：

- `p`: Proof-of-Work token，格式是 `gAAAAAC` 前缀加上 base64 结果。
- `t`: Turnstile `dx` 字段，来自 sentinel server 响应里的 `turnstile.dx`。
- `c`: server token，来自 sentinel server 响应里的 `token`。
- `id`: `device_id`，调用方通常会与 `oai-did` cookie 对齐。
- `flow`: 当前认证流程名，例如 `authorize_continue`。

若 sentinel server 请求失败或返回非 200，返回值仍然是同样结构的 JSON 字符串，只是 `t` 和 `c` 为空字符串。

## PoW 参数

PoW 生成由 `src/autoteam/sentinel.py` (`generate_pow_token`, `_generate_answer`) 完成。当前稳定参数如下：

- 哈希算法：`hashlib.sha3_512`
- 难度串：固定 `0fffff`
- 判定方式：`hash_value[:diff_len] <= bytes.fromhex(diff)`
- 最大迭代次数：`MAX_ITERATION = 500000`
- token 前缀：`gAAAAAC`

找不到满足难度的答案时，不再报错，而是走 fallback：

- 固定前缀：`wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D`
- 后半段：`base64.b64encode(f'"{seed}"'.encode())`

随后仍然会把这个 fallback 结果拼成 `gAAAAAC...` 风格的 `p` 字段。

## 浏览器环境模拟常量

`src/autoteam/sentinel.py` 内部当前导出的环境指纹源包括：

- `CORES = [8, 16, 24, 32]`
- `CACHED_SCRIPTS`
- `CACHED_DPL`
- `NAVIGATOR_KEYS`
- `DOCUMENT_KEYS`
- `WINDOW_KEYS`

`_build_config(user_agent)` 每次会：

1. 选一个屏幕尺寸和脚本指纹组合。
2. 调 `_get_parse_time()` 生成 ET 时区时间串。当前实现固定 `GMT-0500 (Eastern Standard Time)`。
3. 组合 `user_agent`、语言、指纹 key、核心数等字段。
4. 产出一个 list，后续序列化后参与 PoW 哈希。

当前实现不是完整浏览器对象模拟，而是用几组固定离散值加随机抽样，构造一个足够像浏览器环境的配置数组。

## Sentinel Server 接口

`get_sentinel_token(...)` 请求的服务端接口固定为：

- 方法：`POST`
- 端点：`https://sentinel.openai.com/backend-api/sentinel/req`
- 超时：`30` 秒

当前请求头要求：

- `Origin: https://sentinel.openai.com`
- `Referer: https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6`
- `Content-Type: text/plain;charset=UTF-8`
- `User-Agent: <调用时传入的 UA>`

当前请求体是 `json.dumps(...)` 后的纯文本，不是 `json=` 提交：

- `{"p": <pow_token>, "id": <device_id>, "flow": <flow>}`

当前响应处理只读取两个字段：

- `token` → 映射到返回值中的 `c`
- `turnstile.dx` → 映射到返回值中的 `t`

若响应体不是合法 JSON，代码会把它当空对象处理，最后仍返回带空 `c/t` 的 sentinel token。

## 调用约束

- `device_id` 不能为空。空值会触发 `ValueError("get_sentinel_token requires non-empty device_id")`。
- 调用侧应优先复用 session 里的 `oai-did` cookie；`src/autoteam/protocol_oauth.py` (`_inject_sentinel_token`) 当前就是这样做的。
- sentinel server 故障不应中断 OAuth。上层必须允许 PoW-only 降级。

## 当前接入点

当前只有 `src/autoteam/protocol_oauth.py` (`_inject_sentinel_token`) 直接消费这个模块，并把结果写到 `openai-sentinel-token` header。已覆盖的请求点见 [automation-flow.md](../architecture/automation-flow.md)。
