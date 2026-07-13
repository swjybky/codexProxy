# Codex Proxy Desktop

一个只做 Codex 反向代理的本地桌面应用。客户端使用 OpenAI `Responses API`，应用把请求适配到 ChatGPT 订阅后端的 Codex API，并将普通响应或 SSE 流原样返回。

## 核心能力

- 仅开放 `POST /v1/responses` 与 `POST /v1/responses/compact`
- Bearer API Key 鉴权，同时支持本机与局域网访问
- 桌面管理令牌与客户端 API Key 分离，阻止其他网页读取密钥或触发管理操作
- 导入 `~/.codex/auth.json`、Codex CLI JSON 或 new-api Codex 渠道 Key JSON
- 使用 `refresh_token` 手动刷新 OAuth 凭证
- 凭证接近过期时自动刷新；上游首次返回 401 时刷新后重试一次
- 注入 Codex 上游所需的 `Authorization`、`chatgpt-account-id`、`OpenAI-Beta` 与 `originator`
- 强制 `store=false`，过滤 `max_output_tokens`、`temperature` 和非 Responses DTO 字段
- React 管理界面：服务状态、接入信息、凭证与适配设置

## 本地运行

```bash
# 1. 构建前端
cd web
npm install
npm run build
cd ..

# 2. 安装桌面依赖并启动
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py
```

不安装 pywebview 时，可以直接使用系统浏览器：

```bash
python3 run.py --browser
```

应用默认监听 `0.0.0.0:1455`。本机客户端可使用界面显示的 `http://127.0.0.1:1455/v1`，同一局域网内的客户端使用“局域网 Base URL”；两者都需要界面生成的 API Key。首次运行时，系统防火墙可能会询问是否允许局域网访问。

Linux Qt 模式包含 pywebview 6.2.1 与 PyQt6 6.11 的权限枚举兼容补丁，避免复制或 WebEngine 权限请求时因 `setFeaturePermission(..., int)` 导致进程崩溃。
桌面窗口、任务栏、Dock、可执行文件与浏览器页签统一使用蓝色闪电图标。

## 开发

后端与前端开发服务器分开启动：

```bash
python3 run.py --browser
cd web && npm run dev
```

Vite 开发界面会自动访问 `http://127.0.0.1:1455`。也可通过 `VITE_API_BASE_URL` 覆盖。
开发界面需要通过后端 `settings.json` 中的 `admin_token` 打开一次
`http://127.0.0.1:5173/#admin_token=<admin_token>`；令牌随后只保存在当前标签页的 `sessionStorage`。

验证命令：

```bash
python3 -m unittest discover -s tests -v
cd web && npm run lint && npm run build
```

## 数据目录

敏感凭证与设置保存在系统用户数据目录：

- Windows：`%APPDATA%/CodexProxy/`
- macOS：`~/Library/Application Support/CodexProxy/`
- Linux：`~/.local/share/codex-proxy/`

可用 `CODEX_PROXY_DATA_DIR` 临时覆盖。`credentials.json` 采用仅当前用户可读写的文件权限；界面与运行日志均不会返回 Token 内容。

## 桌面打包

图标已按平台分别接入：Windows 使用 `app-icon.ico`，macOS 使用
`app-icon.icns`，Linux/pywebview 使用透明 PNG。

Windows 10/11（Python 3.10+、Node.js 18+）：

```powershell
.\packaging\build_windows.ps1
```

产物位于 `dist/CodexProxy/`。运行桌面窗口需要 Microsoft Edge WebView2 Runtime。

Linux：

```bash
./packaging/build_linux.sh
```

产物位于 `dist/CodexProxy/`，并随包附带 freedesktop 启动器与
`hicolor` 应用图标资源。

macOS（需在 macOS 上执行）：

```bash
./packaging/build_macos.sh
```

产物位于 `dist/CodexProxy.app/`。

详细分层与协议设计见 [项目整体设计.md](./项目整体设计.md)。
