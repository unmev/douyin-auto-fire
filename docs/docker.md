# Docker 部署教程

本教程介绍如何使用 Docker 部署 `douyin-auto-fire`，支持单账号、多账号、钉钉通知和容器内 Cron 定时运行。

项目提供两套公共镜像：

- 国内环境推荐：`docker.cnb.cool/1mev/douyin-auto-fire:latest`
- 海外环境推荐：`ghcr.io/unmev/douyin-auto-fire:latest`

两套镜像内容一致，只是镜像仓库不同。Python、Playwright、Chromium 和项目代码都已经封装进镜像，**Docker 部署不需要下载完整源码仓库**。

> 第一次使用建议先配置 1 个账号、1 个好友、1 条文字消息，并先执行 Dry Run。单账号确认正常后，再增加多账号、原生表情、随机消息或钉钉通知。

---

## 1. 准备部署目录

```bash
mkdir -p ~/douyin-auto-fire/artifacts ~/douyin-auto-fire/config
cd ~/douyin-auto-fire
```

---

## 2. 下载 Compose 文件

### 国内服务器（推荐）

只从 CNB 下载一个 `docker-compose.yml`：

```bash
curl -fL https://cnb.cool/1mev/douyin-auto-fire/-/git/raw/main/docker-compose.yml -o docker-compose.yml
```

国内版默认使用：

```text
docker.cnb.cool/1mev/douyin-auto-fire:latest
```

整个 Docker 部署过程不需要 `git clone` 完整仓库。

### 海外服务器

```bash
curl -fL https://raw.githubusercontent.com/unmev/douyin-auto-fire/main/docker-compose.global.yml -o docker-compose.yml
```

海外版默认使用：

```text
ghcr.io/unmev/douyin-auto-fire:latest
```

---

## 3. 单账号：准备任务配置

创建：

```bash
nano config.json
```

也可以使用配置生成器：

**https://douyin-config.pages.dev/**

一个最简单的配置例如：

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

第一次建议只配置 1 个好友和 1 条文字消息。

---

## 4. 单账号：准备 Cookie

在电脑浏览器登录抖音网页版，使用 Cookie-Editor 导出完整 JSON。

创建：

```bash
nano cookie.json
```

将完整 Cookie JSON 粘贴进去并保存。

> Cookie 相当于账号登录凭证，请勿上传到 GitHub、CNB、Issue 或公开分享。

---

## 5. 创建 `.env`

```bash
nano .env
```

推荐内容：

```env
TZ=Asia/Shanghai
CRON_SCHEDULE=30 0 * * *
RUN_ON_START=false
HEADLESS=true
DOUYIN_COOKIE=/data/cookie.json
TASK_CONFIG=/app/config.json
ARTIFACTS_DIR=/app/artifacts

DINGTALK_WEBHOOK=
DINGTALK_SECRET=
```

`CRON_SCHEDULE=30 0 * * *` 表示每天 00:30 执行。

例如每天 08:00：

```env
CRON_SCHEDULE=0 8 * * *
```

例如每天 20:00：

```env
CRON_SCHEDULE=0 20 * * *
```

如果希望容器每次启动时先立即执行一次任务：

```env
RUN_ON_START=true
```

正常长期运行建议保持：

```env
RUN_ON_START=false
```

> `.env` 里的变量既对 `RUN_ON_START=true` 的启动运行生效，也对每天定时的
> cron 任务生效。容器启动时 `docker/entrypoint.sh` 会把容器环境写进
> `/run/douyin-auto-fire/env.sh`，cron 在执行任务前会加载它，
> 因此定时任务和手动执行（`docker exec`）拿到的环境变量完全一致。
> 详见 [15. 常见问题](#15-常见问题)。

---

## 6. 消息通知（可选）

### 钉钉机器人

如果希望每次任务结束后通过钉钉接收结果，在 `.env` 中填写：

```env
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxxx
DINGTALK_SECRET=SECxxxx
```

两个参数必须同时填写；只填一个会被程序判定为配置错误。

如果不需要通知，保持：

```env
DINGTALK_WEBHOOK=
DINGTALK_SECRET=
```

即可。

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

**Discord 频道**
```env
WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
WEBHOOK_TEMPLATE={"content":"🔥 **抖音任务 {task_id}**\n\n{status}\n成功: {success_count} | 失败: {failed_count}\n\n{timestamp}"}
```

#### 模板变量

可以在 `WEBHOOK_TEMPLATE` 中使用以下变量：

- `{task_id}` - 任务 ID
- `{status}` - 执行状态
- `{mode}` - 运行模式
- `{success_count}` - 成功数量
- `{failed_count}` - 失败数量
- `{total_count}` - 总数量
- `{timestamp}` - 时间戳
- `{results_json}` - 完整结果

如果不配置 `WEBHOOK_TEMPLATE`，将使用默认格式。

#### 测试配置

可以使用项目自带的测试脚本验证配置：

```bash
# 在容器外测试
python scripts/check_webhook.py

# 或在容器内测试
docker compose exec douyin-auto-fire python scripts/check_webhook.py
```

通知会包含本次任务模式、成功/失败人数和失败原因。Docker 环境下如果配置的是全局 `.env`，多账号默认都会继承同一个通知配置；如果希望不同账号使用不同通知，可以在对应账号的环境文件里单独覆盖这些变量。

---

## 7. 拉取镜像并启动

```bash
docker compose pull
docker compose up -d
```

查看状态：

```bash
docker compose ps
```

查看实时日志：

```bash
docker compose logs -f
```

国内版会拉取：

```text
docker.cnb.cool/1mev/douyin-auto-fire:latest
```

海外版会拉取：

```text
ghcr.io/unmev/douyin-auto-fire:latest
```

---

## 8. 第一次运行 Dry Run

不要第一次就直接真实发送。

```bash
docker exec -it douyin-auto-fire python run.py --dry-run
```

Dry Run 会检查：

- Cookie 是否有效；
- 是否能够进入抖音私信页；
- 是否能找到目标好友；
- 任务配置是否正确；
- 多账号模式下每个启用账号是否能够正常加载。

Dry Run 不会真实发送消息。

确认没有问题后，再运行：

```bash
docker exec -it douyin-auto-fire python run.py
```

---

## 9. 多账号（可选）

Docker 也支持多账号。程序只要检测到：

```text
/app/config/accounts.json
```

就会自动从单账号模式切换为多账号模式，并串行执行所有启用账号。一个账号失败不会阻止后面的账号继续运行。

### 9.1 推荐目录结构

宿主机可以整理成：

```text
douyin-auto-fire/
├── docker-compose.yml
├── .env
├── config.json                  # 单账号模式使用，多账号时可以保留
├── cookie.json                  # 单账号模式使用，多账号时可以保留
├── config/
│   ├── accounts.json
│   ├── accounts/
│   │   ├── account1.env
│   │   └── account2.env
│   ├── cookies/
│   │   ├── account1.json
│   │   └── account2.json
│   └── tasks/
│       ├── account1.json
│       └── account2.json
└── artifacts/
```

先创建目录：

```bash
mkdir -p config/accounts config/cookies config/tasks artifacts
```

### 9.2 创建 `config/accounts.json`

```bash
nano config/accounts.json
```

示例：

```json
{
  "accounts": [
    {
      "id": "account1",
      "enabled": true,
      "env_file": "/app/config/accounts/account1.env"
    },
    {
      "id": "account2",
      "enabled": true,
      "env_file": "/app/config/accounts/account2.env"
    }
  ]
}
```

`id` 主要用于日志和运行产物目录，建议使用简单英文或数字。

如果暂时不想运行某个账号，可以改成：

```json
"enabled": false
```

### 9.3 每个账号创建独立环境文件

账号 1：

```bash
nano config/accounts/account1.env
```

```env
DOUYIN_COOKIE=/app/config/cookies/account1.json
TASK_CONFIG=/app/config/tasks/account1.json
```

账号 2：

```bash
nano config/accounts/account2.env
```

```env
DOUYIN_COOKIE=/app/config/cookies/account2.json
TASK_CONFIG=/app/config/tasks/account2.json
```

如果两个账号都使用全局 `.env` 中的钉钉机器人，不需要重复填写钉钉变量。

如果账号 2 要使用独立机器人，可以在 `account2.env` 中追加：

```env
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxxx
DINGTALK_SECRET=SECxxxx
```

### 9.4 保存每个账号 Cookie

```bash
nano config/cookies/account1.json
nano config/cookies/account2.json
```

分别粘贴对应抖音账号导出的完整 Cookie JSON。

### 9.5 保存每个账号任务配置

```bash
nano config/tasks/account1.json
nano config/tasks/account2.json
```

每个账号可以配置完全不同的好友、消息、发送间隔和防重复设置。

### 9.6 测试多账号

```bash
docker compose up -d
docker exec -it douyin-auto-fire python run.py --dry-run
```

日志中会显示类似：

```text
多账号模式：共 2 个启用账号
[account1] ...
[account2] ...
```

多账号运行产物默认会分开保存：

```text
artifacts/account1/
artifacts/account2/
```

确认 Dry Run 正常后，再执行真实发送：

```bash
docker exec -it douyin-auto-fire python run.py
```

> 删除或重命名 `config/accounts.json` 后，程序会恢复到原来的单账号模式。

---

## 10. 宿主机文件说明

单账号最少需要：

```text
douyin-auto-fire/
├── docker-compose.yml
├── .env
├── config.json
├── cookie.json
├── config/
└── artifacts/
```

其中：

- `docker-compose.yml`：容器配置；
- `config.json`：单账号任务配置；
- `cookie.json`：单账号 Cookie；
- `.env`：时区、Cron、Headless、全局钉钉通知等；
- `config/`：多账号配置目录；
- `artifacts/`：日志、截图、Trace、历史记录等运行产物。

修改任务配置或 Cookie 后，下次运行会直接读取最新内容。

修改 `.env` 后建议重新创建容器：

```bash
docker compose up -d
```

---

## 11. 更新

正常更新程序只需要拉取最新版镜像：

```bash
docker compose pull
docker compose up -d
```

如果 Compose 文件本身有更新，可以重新下载。

国内：

```bash
curl -fL https://cnb.cool/1mev/douyin-auto-fire/-/git/raw/main/docker-compose.yml -o docker-compose.yml
docker compose pull
docker compose up -d
```

海外：

```bash
curl -fL https://raw.githubusercontent.com/unmev/douyin-auto-fire/main/docker-compose.global.yml -o docker-compose.yml
docker compose pull
docker compose up -d
```

本地 Cookie、任务配置、`.env` 和 `artifacts/` 不会因为更新镜像而丢失。

---

## 12. 常用命令

```bash
# 启动
docker compose up -d

# 查看状态
docker compose ps

# 查看实时日志
docker compose logs -f

# Dry Run
docker exec -it douyin-auto-fire python run.py --dry-run

# 立即真实运行一次
docker exec -it douyin-auto-fire python run.py

# 重启
docker compose restart

# 拉取最新版
docker compose pull

# 更新并启动
docker compose pull && docker compose up -d

# 停止并删除容器
docker compose down
```

---

## 13. 查看运行产物

单账号通常位于：

```text
./artifacts/
```

多账号通常位于：

```text
./artifacts/account1/
./artifacts/account2/
```

可能包含：

```text
run.log
result.json
history.json
screenshots/
traces/
```

如果发送失败，可以查看：

```bash
docker compose logs --tail=200
```

或对应账号的 `run.log`。

---

## 14. 国内 / 海外镜像说明

国内镜像：

```text
docker.cnb.cool/1mev/douyin-auto-fire:latest
```

海外镜像：

```text
ghcr.io/unmev/douyin-auto-fire:latest
```

GitHub Actions 会在相关代码更新时自动构建并同时推送到 GHCR 和 CNB。CNB 同时提供国内下载 `docker-compose.yml` 的地址，Docker 用户无需克隆完整源码。

---

## 15. 常见问题

### 定时任务每次都报「必须配置 DOUYIN_STORAGE_STATE 或 DOUYIN_COOKIE」

容器里的定时任务由 cron 拉起，而 **cron 启动的作业不会继承容器自身的环境变量**：
作业能拿到的变量只有 crontab 里显式写出来的部分，加上 cron 自己设置的
`HOME` / `LOGNAME` / `PWD` / `SHELL` / `PATH`。

所以 compose 里通过 `environment:` 传入的 `DOUYIN_COOKIE`、`TASK_CONFIG`、
`ARTIFACTS_DIR`、`HEADLESS`，以及镜像里定义的 `PLAYWRIGHT_BROWSERS_PATH`、
`PYTHONUNBUFFERED` 在定时任务里会全部丢失，定时任务必然失败；
而手动执行（`docker exec`）或 `RUN_ON_START=true` 却一切正常，
看起来像是 Cookie 过期或被风控。

镜像里的 `docker/entrypoint.sh` 会在容器启动时把容器环境写进
`/run/douyin-auto-fire/env.sh`，并让 crontab 在执行任务前加载它，
保证定时任务和手动执行的环境变量完全一致。

可以这样确认定时任务实际拿到的环境变量：

```bash
docker exec douyin-auto-fire cat /run/douyin-auto-fire/env.sh
docker exec douyin-auto-fire cat /etc/cron.d/douyin-auto-fire
```

如果升级镜像前定时任务一直失败，重新创建容器即可生效：

```bash
docker compose pull && docker compose up -d
```

> `/run/douyin-auto-fire/env.sh` 里包含 Cookie 等敏感信息，权限为 `0600`，
> 容器重启时会自动重新生成，不需要手工维护。

---

## 注意事项

- Cookie、账号环境文件和钉钉机器人密钥都属于敏感信息，不要提交到公开仓库。
- 同一个抖音账号不要同时运行多个实例，避免重复发送。
- 多账号会串行执行，不是同时开启多个浏览器并发发送。
- 服务器网络环境可能触发抖音安全验证。
- Cookie 失效后需要重新导出并替换对应账号的 Cookie 文件。
- `artifacts/` 中的日志、截图和 Trace 可能包含聊天相关信息，请勿随意公开。
