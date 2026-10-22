# Windows 电脑部署教程

本教程介绍如何在 Windows 电脑上运行 `douyin-auto-fire`，支持扫码登录、Cookie 登录、单账号、多账号、钉钉通知、Dry Run 和任务计划程序定时运行。

> Windows 电脑需要在任务执行时保持开机并联网。第一次建议先配置 1 个账号、1 个好友、1 条文字消息，先把单账号跑通，再增加多账号或通知。

---

## 1. 安装 Python

建议 Python 3.11 或更高版本：

**https://www.python.org/downloads/**

安装时勾选：

```text
Add Python to PATH
```

检查：

```powershell
python --version
```

---

## 2. 安装 Git

**https://git-scm.com/download/win**

检查：

```powershell
git --version
```

也可以直接从 GitHub 下载 ZIP，但长期使用更推荐 Git clone，后续更新更方便。

---

## 3. 下载项目

```powershell
git clone https://github.com/unmev/douyin-auto-fire.git
cd douyin-auto-fire
```

建议放在固定路径，例如：

```text
C:\douyin-auto-fire
```

---

## 4. 创建虚拟环境

```powershell
py -3.11 -m venv .venv
```

如果只有一个 Python：

```powershell
python -m venv .venv
```

---

## 5. 安装依赖和 Chromium

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

---

## 6. 单账号：配置发送内容

```powershell
Copy-Item config.example.json config.json
notepad config.json
```

也可以使用配置生成器：

**https://douyin-config.pages.dev/**

一个最简单的配置：

```json
{
  "friends": ["好友昵称"],
  "messages": [
    {"type": "text", "value": "续火花 ✨"}
  ],
  "send_interval_seconds": {
    "min": 3,
    "max": 8
  },
  "prevent_duplicates": false
}
```

---

## 7. 单账号：扫码登录

Windows 推荐先使用项目自带登录脚本：

```powershell
.\.venv\Scripts\python.exe scripts\login.py
```

浏览器打开后扫码登录，确认进入抖音首页，再回到终端按 Enter。

成功后生成：

```text
storage-state.json
```

> `storage-state.json` 相当于登录凭证，不要上传或分享。

---

## 8. 第一次运行 Dry Run

```powershell
.\.venv\Scripts\python.exe run.py --dry-run
```

Dry Run 会检查登录状态、好友定位和配置，但不会真正发送消息。

成功后再运行：

```powershell
.\.venv\Scripts\python.exe run.py
```

---

## 9. 无头模式

日常自动运行建议在根目录创建 `.env`：

```powershell
notepad .env
```

写入：

```env
HEADLESS=true

DINGTALK_WEBHOOK=
DINGTALK_SECRET=
```

之后浏览器会在后台运行。

---

## 10. 使用 Cookie 登录（可选）

如果不想使用扫码生成的 `storage-state.json`，也可以用 Cookie。

详细获取步骤参考：[GitHub Actions 教程 - 获取 Cookie](github-actions.md#3-获取抖音-cookie)

在 `.env` 中写入单行 JSON：

```env
DOUYIN_COOKIE=[{"name":"xxx","value":"xxx","domain":".douyin.com","path":"/"}]
HEADLESS=true
```

如果同时存在有效的 `storage-state.json`，程序会优先使用它。想完全改用 Cookie，可以删除：

```powershell
Remove-Item storage-state.json
```

---

## 11. 消息通知（可选）

### 钉钉机器人

在 `.env` 中填写：

```env
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxxx
DINGTALK_SECRET=SECxxxx
```

两个参数必须同时填写。通知会包含任务模式、成功/失败人数和失败原因。

如果不需要通知，两个值保持为空即可。

### 通用 Webhook（企业微信、飞书、Telegram 等）

项目支持向任意 Webhook 端点发送通知，适用于企业微信、飞书、Slack、Discord、Telegram 等平台。

在 `.env` 中添加：

```env
# 必需：Webhook 地址
WEBHOOK_URL=https://example.com/webhook

# 可选：自定义消息模板（JSON 格式）
WEBHOOK_TEMPLATE={"text":"任务 {task_id} {status}"}

# 可选：自定义 HTTP 请求头
WEBHOOK_HEADERS={"Authorization":"Bearer token"}
```

#### 配置示例

**企业微信群机器人**
```env
WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY
WEBHOOK_TEMPLATE={"msgtype":"text","text":{"content":"🔥 抖音任务 {task_id}\n\n{status}\n✅ 成功: {success_count}\n❌ 失败: {failed_count}\n\n⏰ {timestamp}"}}
```

**飞书群机器人**
```env
WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_KEY
WEBHOOK_TEMPLATE={"msg_type":"text","content":{"text":"🔥 抖音任务 {task_id}\n\n{status}\n✅ 成功: {success_count}\n❌ 失败: {failed_count}\n\n⏰ {timestamp}"}}
```

**Telegram Bot**
```env
WEBHOOK_URL=https://api.telegram.org/botYOUR_BOT_TOKEN/sendMessage
WEBHOOK_TEMPLATE={"chat_id":"YOUR_CHAT_ID","text":"🔥 抖音任务 {task_id}\n\n{status}\n✅ 成功: {success_count}\n❌ 失败: {failed_count}\n\n⏰ {timestamp}"}
```

#### 模板变量

- `{task_id}` - 任务 ID
- `{status}` - 执行状态
- `{success_count}` - 成功数量
- `{failed_count}` - 失败数量
- `{timestamp}` - 时间戳

#### 测试配置

```powershell
python scripts/check_webhook.py
```

多账号模式下，全局 `.env` 的通知配置会被账号继承；如果某个账号需要单独通知，可以在该账号自己的 `.env.account*` 文件中覆盖。

---

## 12. 多账号（可选）

Windows 也支持多账号。只要项目根目录存在：

```text
config\accounts.json
```

程序就会自动进入多账号模式，并串行执行所有启用账号。

### 12.1 创建目录

```powershell
New-Item -ItemType Directory -Force config\tasks | Out-Null
New-Item -ItemType Directory -Force storage_state | Out-Null
```

### 12.2 创建 `config\accounts.json`

```powershell
notepad config\accounts.json
```

示例：

```json
{
  "accounts": [
    {
      "id": "account1",
      "enabled": true,
      "env_file": ".env.account1"
    },
    {
      "id": "account2",
      "enabled": true,
      "env_file": ".env.account2"
    }
  ]
}
```

如果暂时不运行某个账号：

```json
"enabled": false
```

### 12.3 每个账号创建独立环境文件

账号 1：

```powershell
notepad .env.account1
```

推荐使用独立 Cookie：

```env
DOUYIN_COOKIE=[{"name":"账号1Cookie","value":"xxx","domain":".douyin.com","path":"/"}]
TASK_CONFIG=config/tasks/account1.json
```

账号 2：

```powershell
notepad .env.account2
```

```env
DOUYIN_COOKIE=[{"name":"账号2Cookie","value":"xxx","domain":".douyin.com","path":"/"}]
TASK_CONFIG=config/tasks/account2.json
```

如果账号 2 使用独立钉钉机器人，可以追加：

```env
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxxx
DINGTALK_SECRET=SECxxxx
```

### 12.4 每个账号创建任务配置

```powershell
notepad config\tasks\account1.json
notepad config\tasks\account2.json
```

每个账号可以配置不同好友、消息、发送间隔和防重复设置。

### 12.5 使用独立扫码登录状态（可选）

当前 `scripts\login.py` 默认只生成根目录的 `storage-state.json`，因此多账号最省事的方式是每个账号直接使用 Cookie。

如果你已经自行准备了独立 Storage State，也可以在账号 env 中指定：

```env
DOUYIN_STORAGE_STATE=storage_state/account1.json
TASK_CONFIG=config/tasks/account1.json
```

Cookie 和 Storage State 二选一即可。

### 12.6 测试多账号

```powershell
.\.venv\Scripts\python.exe run.py --dry-run
```

日志会出现类似：

```text
多账号模式：共 2 个启用账号
[account1] ...
[account2] ...
```

运行产物默认分开保存：

```text
artifacts\account1\
artifacts\account2\
```

确认正常后：

```powershell
.\.venv\Scripts\python.exe run.py
```

> 删除或重命名 `config\accounts.json` 后，程序会恢复单账号模式。

---

## 13. 配置 Windows 任务计划程序

按 `Win + R`，输入：

```text
taskschd.msc
```

点击“创建基本任务”，名称例如：

```text
Douyin Auto Fire
```

触发器选择“每天”，设置运行时间。

### 程序或脚本

假设项目位于 `C:\douyin-auto-fire`：

```text
C:\douyin-auto-fire\.venv\Scripts\python.exe
```

### 添加参数

```text
run.py
```

### 起始于

```text
C:\douyin-auto-fire
```

> “起始于”必须填写项目根目录，否则程序可能找不到 `.env`、`config.json` 或 `config\accounts.json`。

单账号和多账号都使用同一个 `run.py`，不需要为每个账号创建多个计划任务。

### 自动识别待续火花好友（可选）

如果希望每天运行前从私信列表中识别灰色火花，只向当天需要续火花的好友发送原生表情，可以使用项目提供的 PowerShell 包装脚本：

```powershell
.\\login-local.ps1
.\\run-streaks-local.ps1
```

`run-streaks-local.ps1` 会先扫描私信列表，再生成本地 `config.json` 并调用现有发送流程。它不会把好友名单、登录状态、日志、截图或 Trace 写入 Git；这些本地运行文件已在 `.gitignore` 中排除。Windows 任务计划程序中应将“程序或脚本”设置为 `pwsh.exe`，参数设置为 `-File "D:\\douyin-auto-fire\\run-streaks-local.ps1"`，并把“起始于”设置为项目根目录。

---

## 14. 测试任务计划程序

找到刚创建的任务，右键“运行”。

查看单账号日志：

```powershell
Get-Content .\artifacts\run.log -Tail 100
```

多账号日志：

```powershell
Get-Content .\artifacts\account1\run.log -Tail 100
Get-Content .\artifacts\account2\run.log -Tail 100
```

---

## 15. 登录失效

单账号扫码模式可以重新运行：

```powershell
.\.venv\Scripts\python.exe scripts\login.py
```

多账号 Cookie 模式则重新导出对应账号 Cookie，更新 `.env.account1`、`.env.account2` 等文件。

更新后先执行：

```powershell
.\.venv\Scripts\python.exe run.py --dry-run
```

---

## 16. 更新项目

```powershell
cd C:\douyin-auto-fire
git pull
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Playwright 版本变化后：

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

这些本地敏感文件已被 `.gitignore` 忽略：

```text
.env
.env.account*
config.json
config\accounts.json
config\tasks\
storage-state.json
storage_state\
artifacts\
```

---

## 常用命令

```powershell
# 单账号扫码登录
.\.venv\Scripts\python.exe scripts\login.py

# Dry Run（单账号 / 多账号都会自动识别）
.\.venv\Scripts\python.exe run.py --dry-run

# 正式运行
.\.venv\Scripts\python.exe run.py

# 查看主日志
Get-Content .\artifacts\run.log -Tail 100

# 更新项目
git pull
```

---

## 注意事项

- Cookie、Storage State、`.env`、`.env.account*` 和钉钉密钥不要公开。
- 多账号是串行执行，不会同时并发登录多个抖音账号。
- 同一个抖音账号不要在多台机器同时运行自动发送任务。
- 日志、截图和 Trace 可能包含聊天信息，请勿直接公开。

---

## 其他部署方式

- [GitHub Actions 部署](github-actions.md)
- [Docker 部署](docker.md)
- [Linux 云服务器部署](server.md)
- [返回项目主页](../README.md)
