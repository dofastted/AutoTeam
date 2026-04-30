# 从零开始部署 AutoTeam

本文档带你从一台全新的 VPS 或本地机器开始，完成 AutoTeam 的安装、配置、管理员登录、首次补号与日常使用。

## 前置条件

在开始之前，你需要准备好以下服务：

| 服务 | 说明 | 获取方式 |
|------|------|---------|
| **ChatGPT Team 订阅** | 管理员主号，需要有 Team 订阅 | [chatgpt.com](https://chatgpt.com) |
| **临时邮箱服务** | 推荐 Mo Email；也可使用 CloudMail / Cloudflare Temp Email | 自建或已有 API |
| **CLIProxyAPI** | Codex 代理与认证文件同步目标 | 自建 [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) |
| **VPS / 本地机器** | 推荐 Ubuntu 22.04+；也支持 Windows / macOS | 任意云服务商 / 本地电脑 |
| **域名** | 用于 CloudMail 临时邮箱与 Verified Domains | 任意域名注册商 |

> 建议使用住宅 IP 或干净的 VPS IP，避免被 OpenAI / Cloudflare 标记。

## 准备工作

### 1. 准备临时邮箱服务

推荐先使用 Mo Email。你需要准备：

- API 地址（如 `https://mo.gymbro.cloud`）
- API Key
- 邮箱域名（如 `gymbro.cloud`）

如果继续使用 CloudMail，可参考 CloudMail 官方文档完成搭建：https://doc.skymail.ink/guide/dashboard

### 2. 设置 OpenAI Verified Domains

由于重复邀请有概率触发 `"unable to invite user due to an error."` 错误（[参考](https://community.openai.com/t/email-invite-error-in-chatgpt-business/1378252)），需要设置域名验证让账号自动加入 Team：

1. 打开 ChatGPT → Settings → Account
2. 找到 **Verified Domains**，点击 **Verify new domain**
3. 输入你的域名（如 `your-domain.com`）
4. 在 Cloudflare（或你的 DNS 服务商）添加 OpenAI 要求的 DNS 记录
5. 回到 ChatGPT 点击 **Check**，验证通过后状态变为 verified
6. 进入 Workspace → Identity & Access，打开 **Automatic account creation**

这样使用该域名邮箱注册的 ChatGPT 账号会自动加入 Team workspace，不需要手动邀请。

### 3. 搭建 CLIProxyAPI

参考 CPA 项目文档完成搭建：https://github.com/router-for-me/CLIProxyAPI

搭建完成后你会得到：
- CPA 地址（如 `http://127.0.0.1:8317`）
- 管理密钥（`secret-key`）

## 第一步：安装

### 方式一：直接部署

```bash
# 克隆项目
git clone https://github.com/cnitlrt/AutoTeam.git
cd AutoTeam

# Linux 一键安装（uv、依赖、Playwright、pre-commit）
bash setup.sh
```

Windows / macOS 可直接执行：

```bash
uv sync
uv run playwright install chromium
```

> Windows / macOS 不需要 xvfb。Linux 无图形环境时项目会自动处理虚拟显示。

### 方式二：Docker 部署

```bash
git clone https://github.com/cnitlrt/AutoTeam.git
cd AutoTeam
mkdir -p data
docker compose up -d
```

## 第二步：配置

### 直接部署

启动任何命令时会自动进入配置向导：

```bash
uv run autoteam api
```

按提示依次填入：

```text
=== AutoTeam 首次配置 ===

  Mo Email API 地址: https://mo.gymbro.cloud
  Mo Email API Key: your_api_key
  Mo Email 邮箱域名（如 gymbro.cloud）: gymbro.cloud
  Mo Email 邮箱名前缀（如 abc）: abc
  CPA 管理密钥: your_cpa_key
  API 鉴权密钥 [回车自动生成]:
```

配置会自动验证邮箱服务和 CPA 的连通性，失败会提示具体原因。

### Docker 部署

方式一：编辑配置文件

```bash
cp .env.example data/.env
nano data/.env   # 填入实际配置
docker compose restart
```

方式二：Web 页面配置

直接打开 `http://your-server:8787`，会显示配置向导页面，在浏览器中填写。

如果你需要让 AutoTeam 的外部流量走宿主机代理，请先确认容器内可以解析并访问宿主机代理地址（例如 `host.docker.internal`，或你自己提供的宿主机网关别名）。

然后在 `data/.env` 中加入：

```dotenv
OUTBOUND_PROXY_POOL=http://host.docker.internal:1080
OUTBOUND_PROXY_BYPASS=localhost,127.0.0.1,::1
```

`OUTBOUND_PROXY_POOL` 会影响 OpenAI/ChatGPT、邮箱服务、CPA 和 Sub2API；Playwright 浏览器在 `PLAYWRIGHT_PROXY_URL` 留空时也会跟随它。如果只想覆盖浏览器，可以单独设置：

```dotenv
PLAYWRIGHT_PROXY_URL=http://username:password@host.docker.internal:1080
```

> 注意：Playwright / Chromium 不支持带认证的 socks5，因此不要写成 `socks5://username:password@host:port`。

## 第三步：管理员登录

配置完成后，需要先用 ChatGPT Team 管理员账号登录。

### 通过 Web 面板

1. 打开 `http://your-server:8787`
2. 输入 API Key 进入面板
3. 进入「配置面板 → 管理员 / 主号」
4. 输入管理员邮箱，点击「开始登录」
5. 按提示输入密码或邮箱验证码
6. 选择 Team workspace（如 `Idapro`）
7. 登录成功后会自动保存到 `state.json`

### 通过命令行

```bash
uv run autoteam admin-login --email your-admin@example.com
```

## 第四步：首次轮转

```bash
uv run autoteam rotate 5
```

或在 Web 面板「账号池操作」页点击「智能轮转」。

首次运行会：
1. 同步 Team 实际成员到本地
2. 检查所有 active 账号额度
3. 移出额度低于阈值的账号
4. 优先复用 standby 中额度已恢复的旧号
5. 不够时自动创建新账号
6. 上传 active 账号的本地 OAuth RT 文件到 CPA

> **注意：**
> `rotate 5` / `fill 5` 中的 `5` 指的是 **Team 总人数目标**，不是“本地管理账号数量”。
> 如果 Team 中已经有 owner / 外部成员，它们也会计入总数。

## 第五步：日常使用

### 方式一：API 模式（推荐）

```bash
uv run autoteam api
```

API 模式下：
- Web 面板集中管理日常操作
- 后台自动巡检（默认每 5 分钟）
- 可在「账号池操作」页新做 100 个 team 账号 CPA JSON，并查看账号明细和错误等级
- 可在「同步中心」中上传本地 OAuth RT 文件；从 CPA 拉回本地用于恢复
- 可在「OAuth 登录」页手动导入账号

### 方式二：手动执行

```bash
uv run autoteam status      # 查看状态
uv run autoteam check       # 检查额度
uv run autoteam rotate 5    # 智能轮转
uv run autoteam fill        # 按 FILL_BATCH_SIZE 执行一批补位
uv run autoteam sync        # 上传本地 OAuth RT 文件到已启用远端
uv run autoteam pull-cpa    # 从 CPA 拉回本地，用于恢复
```

## 常见流程

### 添加更多账号

```bash
uv run autoteam rotate 8   # 补满到 8 个总席位
# 或
uv run autoteam fill       # 按 FILL_BATCH_SIZE 执行一批补位
# 或
uv run autoteam add        # 自动注册并添加一个
# 或
uv run autoteam manual-add # 手动 OAuth 导入一个账号
```

### 清理多余账号

```bash
uv run autoteam cleanup 5  # 保留 5 个总席位
```

### 从 CPA 恢复 OAuth RT 文件到本地

```bash
uv run autoteam pull-cpa
```

或在 Web 面板「同步中心」页点击「拉取 CPA」。

该操作会：
- 从 CPA 下载 `codex-*.json`
- 清理同账号重复文件
- 按本地命名规范重写到 `auths/`
- 将新导入账号补进 `accounts.json`（默认标记为 `standby`）

## 下一步

- [配置详解](configuration.md)
- [工作原理](architecture.md)
- [API 文档](api.md)
- [常见问题](troubleshooting.md)
