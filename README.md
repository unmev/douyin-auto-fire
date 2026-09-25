# 🔥 抖音自动续火花

[![GitHub stars](https://img.shields.io/github/stars/unmev/douyin-auto-fire?style=flat-square)](https://github.com/unmev/douyin-auto-fire/stargazers)
![Visitors](https://visitor-badge.laobi.icu/badge?page_id=unmev.douyin-auto-fire)

> 定时自动向抖音好友发送消息，保持火花不断。基于 Playwright 模拟真实浏览器操作，可使用 GitHub Actions、Docker、云服务器或 Windows 电脑定时运行。

![douyin-auto-fire-banner.svg](https://img.908988.xyz/file/教程/douyin-auto-fire/5pdab8It.svg)

## 项目介绍

`douyin-auto-fire` 是一个基于 Python + Playwright 的抖音私信自动发送工具。

通过模拟浏览器操作，可以按照配置自动向指定好友发送文字、图片或抖音原生表情，并支持多种运行方式。

如果只是想快速使用，推荐 **GitHub Actions**：不需要自己购买服务器，也不需要电脑长期保持开机。已有 Linux 服务器或 NAS 的用户推荐使用 **Docker**，也可以使用传统 Python + systemd 方式部署到云服务器，或者直接在 Windows 电脑上运行。

> ⚠️ 本项目使用 Cookie / Storage State 作为登录凭证。请只保存在安全位置，不要提交到公开仓库，也不要分享给他人。

## ✨ 已实现功能

- ⏰ **定时自动发送**：支持 GitHub Actions、Docker Cron、systemd Timer 等方式定时运行
- 💬 **多种消息类型**：支持文字、图片（PNG/JPG/GIF/WebP）和抖音原生表情
- 🎲 **随机消息**：支持从多条候选消息中随机选择
- 👥 **多好友支持**：可以同时为多个好友配置发送任务
- 👤 **多账号支持**：GitHub Actions 当前最多支持 5 个抖音账号
- 🧪 **Dry Run 模式**：只验证登录状态和好友定位，不真实发送消息
- 🔒 **防重复发送**：支持记录发送历史，减少重复触发导致的重复发送
- 🔔 **钉钉通知**：支持通过钉钉机器人接收任务结果
- 🔗 **通用 Webhook**：支持企业微信、飞书、Slack、Discord、Telegram 等任意 Webhook 通知
- 🛡️ **失败诊断**：失败时可保存日志、页面截图和 Playwright Trace
- 🔐 **登录凭证灵活**：支持 Cookie 或浏览器 Storage State
- ⏱️ **模拟真人操作**：支持随机发送间隔和输入节奏

## 🚀 快速使用教程

根据自己的使用场景选择一种部署方式即可：

### ☁️ [GitHub Actions 部署 →](docs/github-actions.md)

**推荐大多数用户使用。** 无需服务器，电脑也不需要长期在线，Fork 后配置 Secrets 即可每天自动运行。

包含 Cookie 获取、配置生成、GitHub Secrets、Dry Run、定时任务、多账号和失败诊断等完整图文步骤。

### 🐳 [Docker 部署 →](docs/docker.md)

**推荐已有 Linux 服务器、NAS、1Panel 或宝塔环境的用户使用。** 镜像已经包含 Python、Playwright 和 Chromium，只需要在宿主机保存 `config.json`、`cookie.json` 和日志目录。

默认镜像：

```text
ghcr.io/unmev/douyin-auto-fire:latest
```

启动：

```bash
docker compose up -d
```

### 🖥️ [云服务器部署 →](docs/server.md)

适合希望使用传统 Python + systemd 方式部署的 Linux VPS / 云服务器用户。

使用 Python + Playwright + Headless Chromium 运行，并通过 `systemd Timer` 每天自动执行。教程包含环境安装、Cookie 配置、Dry Run、systemd 定时、日志查看和项目更新。

### 🪟 [Windows 电脑部署 →](docs/windows.md)

适合想先在自己的电脑上运行或长期使用 Windows 电脑挂机的用户。

支持直接运行项目自带的扫码登录脚本生成 `storage-state.json`，也可以使用 Cookie，并可通过 Windows 任务计划程序每天自动运行。

> 第一次使用无论选择哪种部署方式，都建议先配置 **1 个账号 + 1 个好友 + 1 条文字消息**，先执行 Dry Run，确认正常后再真实发送和增加其他配置。

## 📢 通知配置

项目支持任务完成后发送通知到多种平台：

- **通用 Webhook 配置** - 支持企业微信、飞书、Slack、Discord、Telegram 等任意 Webhook 端点
- **钉钉机器人** - 通过环境变量 `DINGTALK_WEBHOOK` 和 `DINGTALK_SECRET` 配置

通知功能完全可选，不配置不影响消息发送。


## 🔐 系统登录鉴权与安全

本项目具备防破解身份鉴权系统，用于在任务执行前保护运行凭证与操作权限：

- **首次启动初始化**：首次启动时自动引导配置用户名与密码（用户名 3-32 位，密码至少 8 位且包含字母与数字），凭证采用 **PBKDF2-HMAC-SHA256 (600,000 次哈希迭代 + 32 字节独立加盐)** 存储，绝不存留明文。
- **防暴力破解保护**：恒定时间比对防御时序侧信道攻击；连续输错 5 次密码将自动锁定 5 分钟，拒绝继续尝试。
- **忘记密码修改命令**：如果忘记密码，可通过专用管理命令随时重置并解除锁定状态：
  ```bash
  python run.py change-password
  # 或指定用户名与新密码重置：
  python run.py change-password --username admin --new-password YourNewPassword123
  ```
- **非交互式/自动化支持**：在定时任务、Docker 或 CI/CD 无人值守环境中，可通过环境变量或命令行进行初始化与鉴权：
  - 环境变量方式（配置在 `.env` 中）：
    ```bash
    APP_AUTH_USERNAME=admin
    APP_AUTH_PASSWORD=YourSecurePassword123
    ```
  - 命令行一键初始化：
    ```bash
    python run.py init-auth --username admin --password YourSecurePassword123
    ```

## 🛑 任务中断与超时保护 (防配置错误卡死)

针对配置错误（例如好友名称不存在、选择器失效、网络波动）可能导致的无限等待或重复重试，系统提供了完善的中断与超时保护机制：

- **超时自动中断 (`--timeout`)**：支持为测试（`--dry-run`）与真实发送设置全局最大执行时间，超时后优雅打断、释放浏览器并退出（返回状态码 124）：
  ```bash
  # 测试模式限时 30 秒，超时自动中断
  python run.py --dry-run --timeout 30

  # 真实执行限时 60 秒
  python run.py --timeout 60
  ```
  *(也可通过环境变量 `TASK_TIMEOUT=60` 或在 `config.json` 中配置 `"timeout_seconds": 60` 生效)*
- **遇到错误立即中断 (`--fail-fast`)**：开启后若遇到首个目标失败或配置异常，立即中断后续好友的处理，方便快速排查配置问题：
  ```bash
  python run.py --dry-run --fail-fast
  ```
- **安全信号中断 (Ctrl+C)**：随时可通过键盘 `Ctrl+C` 或 SIGINT/SIGTERM 中断任务，系统将安全关闭浏览器会话、释放 `run.lock` 文件锁，并在多账号模式下立即停止后续所有账号的执行（返回状态码 130）。
## 🧰 技术栈

| 类别 | 内容 |
| --- | --- |
| 语言 | Python 3.11+ |
| 浏览器自动化 | [Playwright](https://playwright.dev/python/) + Chromium |
| 定时调度 | GitHub Actions / Docker Cron / systemd Timer / Windows 任务计划程序 |
| 环境变量 | python-dotenv |
| 时区 | tzdata |
| 通知 | 钉钉机器人 / 通用 Webhook（企业微信、飞书、Slack 等） |
| 支持平台 | Windows / macOS / Linux / Docker |

主要依赖：

```text
playwright>=1.54,<2
python-dotenv>=1.1,<2
tzdata>=2025.2
```

## ⚠️ 注意事项

- Cookie、Storage State 和发送配置不要直接提交到公开仓库。
- 修改好友、消息或表情配置后，建议先运行一次 Dry Run。
- 同一个抖音账号不要同时运行多个自动发送任务，避免重复发送。
- GitHub-hosted Runner、Docker 主机或云服务器网络环境可能触发抖音安全验证。
- 如果 Cookie / Storage State 失效或抖音要求验证码，需要本人重新完成登录验证。
- 抖音网页结构发生变化时，自动化功能可能需要同步适配。

⭐ 支持一下

如果这个项目帮你省下了每天手动续火花的时间，欢迎点个 Star ⭐ 支持一下！

你的每一个 Star 都是我继续维护、修 Bug 和增加新功能的动力。

## Star History

<a href="https://www.star-history.com/?repos=unmev%2Fdouyin-auto-fire&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=unmev/douyin-auto-fire&type=date&theme=dark&legend=top-left&sealed_token=TkydV0nYtjJ4qP2Nb5Y9f7po-HgwD2pBSxu77UV_GBPhEVJk1qucxdlno9qqdKfANCMyyjgMRjk4QWqZlHQsHJbB3sEPxDIc3ExjCvi-uNJ1crMXnMCytA" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=unmev/douyin-auto-fire&type=date&legend=top-left&sealed_token=TkydV0nYtjJ4qP2Nb5Y9f7po-HgwD2pBSxu77UV_GBPhEVJk1qucxdlno9qqdKfANCMyyjgMRjk4QWqZlHQsHJbB3sEPxDIc3ExjCvi-uNJ1crMXnMCytA" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=unmev/douyin-auto-fire&type=date&legend=top-left&sealed_token=TkydV0nYtjJ4qP2Nb5Y9f7po-HgwD2pBSxu77UV_GBPhEVJk1qucxdlno9qqdKfANCMyyjgMRjk4QWqZlHQsHJbB3sEPxDIc3ExjCvi-uNJ1crMXnMCytA" />
 </picture>
</a>

## 友情链接

- [LINUX DO](https://linux.do/) - 新的理想型社区

## License

本项目采用 [PolyForm Noncommercial License 1.0.0](LICENSE)。

允许个人学习、研究、修改和非商业用途使用本项目；未经授权，不得将本项目或其衍生版本用于商业用途、收费服务、付费部署、倒卖或其他营利性场景。

如需商业授权，请联系项目维护者。
