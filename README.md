# 🔥 抖音自动续火花

> 定时自动向抖音好友发送消息，保持火花不断。基于 Playwright 模拟真实浏览器操作，配合 GitHub Actions 定时运行，**无需服务器长期在线**。
>
![douyin-auto-fire-banner.svg](https://img.908988.xyz/file/教程/douyin-auto-fire/5pdab8It.svg)

## 已实现功能

- ⏰ **定时自动发送**：通过 GitHub Actions 定时触发，支持自定义 cron 表达式和时区
- 💬 **多种消息类型**：支持发送文字、图片（PNG/JPG/GIF/WebP）、抖音原生表情
- 🎲 **随机消息**：消息支持配置 `random` 类型，每次从候选中随机选择一条
- 👥 **多好友支持**：可为多个好友配置各自的消息内容
- 🧪 **Dry Run 模式**：只验证登录状态和好友定位，不真实发送，安全上线
- 🔒 **防重复发送**：按任务+日期+好友+消息记录发送历史，避免重复触发导致刷屏
- 🔔 **钉钉通知**：发送结果通过钉钉机器人推送，含成功/失败名单和失败截图
- 🛡️ **失败诊断**：失败时自动保存日志、页面截图和 Playwright trace，便于排查
- 👤 **登录凭证灵活**：支持 Cookie 或浏览器存储状态（Storage State），可选无头模式
- ⏱️ **模拟真人操作**：随机发送间隔、输入与发送节奏

> `DOUYIN_COOKIE` 是登录凭证，请只保存在 GitHub Secrets 中，不要提交到仓库或公开分享。

## 技术栈与依赖

| 类别 | 内容 |
| --- | --- |
| 语言 | Python 3.11+ |
| 浏览器自动化 | [Playwright](https://playwright.dev/python/)（Chromium，无头模式） |
| 定时调度 | GitHub Actions `schedule`（支持自定义 cron 与时区） |
| 环境变量 | python-dotenv（.env 文件支持） |
| 时区解析 | tzdata（Asia/Shanghai 等） |
| 通知 | 钉钉机器人 Webhook（HMAC-SHA256 签名） |
| 平台 | Windows / macOS / Linux 均可运行，CI 使用 ubuntu-latest |

主要依赖（`requirements.txt`）：

```text
playwright>=1.54,<2
python-dotenv>=1.1,<2
tzdata>=2025.2
```

## 使用教程

## 1. Fork 并启用 Actions

先 Fork 本仓库，然后进入自己 Fork 后的仓库：
![image.webp](https://img.908988.xyz/file/教程/douyin-auto-fire/DKPd0GVi.webp)

`Actions` → 启用工作流。

## 2. 获取抖音 Cookie

1. 在电脑浏览器登录抖音网页版，并确认私信页面可以正常打开。
2. 使用 Cookie-Editor 等工具导出当前站点 Cookie。
3. [Cookie-Editor工具地址](https://chromewebstore.google.com/detail/hlkenndednhfkekhgcdicdfddnkalmdm?utm_source=item-share-cb)
  ![image.webp](https://img.908988.xyz/file/教程/douyin-auto-fire/STZqIxDn.webp)
4. 导出格式选择 **JSON**，复制完整的 JSON 数组。
![image.webp](https://img.908988.xyz/file/教程/douyin-auto-fire/1rilVYmK.webp)
![image.webp](https://img.908988.xyz/file/教程/douyin-auto-fire/QKQHfndn.webp)
格式类似：

```json
[
  {
    "name": "xxx",
    "value": "xxx",
    "domain": ".douyin.com",
    "path": "/"
  }
]
```

必须是完整的 `[ ... ]` 数组，不是 `name=value` 形式。

## 3. 配置 GitHub Secrets

进入：

`Settings` → `Secrets and variables` → `Actions` → `New repository secret`

![image.webp](https://img.908988.xyz/file/教程/douyin-auto-fire/aiPBHuxJ.webp)
![image.webp](https://img.908988.xyz/file/教程/douyin-auto-fire/BKtXckyQ.webp)

需要添加：

| Secret | 内容 | 必需 |
| --- | --- | --- |
| `DOUYIN_COOKIE` | 上一步导出的 Cookie JSON | 是 |
| `DOUYIN_CONFIG` | 完整发送配置 JSON | 是 |
| `DINGTALK_WEBHOOK` | 钉钉机器人 Webhook | 否 |
| `DINGTALK_SECRET` | 钉钉机器人 Secret | 否 |

钉钉通知不用就不要配置；需要使用时，两个钉钉 Secret 必须同时填写。
**若有多个账号就是用下面[多账号](#10-多账号可选)的配置文件变量名称**  网页操作起来还是很简单的

### DOUYIN_CONFIG 示例

支持普通文字和抖音原生表情：

```json
{
  "friends": ["好友昵称"],
  "messages": [
    {"type": "text", "value": "续火花 ✨"},
    {"type": "sticker", "value": "比心"}
  ],
  "stickers": {
    "比心": {
      "label": "比心",
      "category": "常用",
      "fallback_index": 3
    }
  },
  "send_interval_seconds": {
    "min": 3,
    "max": 8
  },
  "prevent_duplicates": false
}
```

原生表情配置说明：

- `type: "sticker"`：发送抖音原生表情。
- `value`：对应 `stickers` 中的表情名称。
- `label`：抖音表情面板中显示的名称，程序优先按名称查找。
- `category`：表情所在分类，例如 `常用`。
- `fallback_index`：按名称找不到时使用的备用序号，从 `0` 开始。

不同账号的表情顺序可能不同，`fallback_index` 需要按自己的抖音表情面板调整。

第一次建议只配置 **1 个好友** 测试。修改好友、消息或表情时，直接更新 `DOUYIN_CONFIG` Secret 即可。

**不会配置可以使用[config.json生成器](https://douyin-config.pages.dev/)**  网页操作起来还是很简单的

生成器的很多表情的都是货不对板  比心是可以正常使用的 文字没有问题

## 4. 先运行 Dry Run

进入：

`Actions` → `Send Douyin Messages` → `Run workflow`

第一次把：

```text
dry_run = true
```

再运行工作流。
![image.webp](https://img.908988.xyz/file/教程/douyin-auto-fire/NLFF8g94.webp)

Dry Run 会检查登录状态和好友定位，**不会发送消息**。

如果运行失败，点进本次 Workflow Run，查看 `send` → `Run` 的日志。

## 5. 测试真实发送

Dry Run 成功后，再手动运行一次：

```text
dry_run = false
```

这次会真实发送消息。

建议仍然只保留一个测试好友，确认发送对象、文字和原生表情都正确后，再增加好友。

## 6. 定时运行

定时配置在：

```text
.github/workflows/send.yml
```

当前配置：

```yaml
schedule:
  - cron: "0 0 * * *"
    timezone: "Asia/Shanghai"
```

表示 **每天北京时间 00:00** 自动运行。

例如改成每天北京时间 08:30：

```yaml
schedule:
  - cron: "30 8 * * *"
    timezone: "Asia/Shanghai"
```

格式为：

```text
分钟 小时 * * *
```

定时触发会直接真实发送，不会自动 Dry Run。

## 7. Cookie 失效

如果日志提示登录失效或安全验证：

1. 在浏览器重新登录抖音；
2. 重新导出 Cookie JSON；
3. 更新 GitHub Secret `DOUYIN_COOKIE`；
4. 先手动运行一次 `dry_run = true`。

GitHub Actions 不会自动扫码登录，也不会绕过验证码或安全验证。

## 8. 失败日志

工作流失败时会上传 `artifacts/`，其中可能包含：

- `run.log`
- `result.json`
- `screenshots/`
- `traces/`

失败 Artifact 保留 3 天。截图和日志可能包含聊天隐私，请勿公开分享。

## 9. 隐私保护

为了保护好友隐私，GitHub Actions 日志及公开诊断文件不会显示真实好友昵称。

好友将按照任务配置顺序显示为：

```text
好友01
好友02
好友03
```

实际发送和好友搜索仍使用真实昵称。

钉钉私人通知仍显示真实好友名称。

失败诊断 Artifact 保留 3 天。

## 10. 多账号（可选）

> 升级后**完全向后兼容**：没有多账号配置时自动使用旧单账号模式，
> 现有的 `DOUYIN_COOKIE` / `DOUYIN_CONFIG` Secret 与 `python run.py` 保持不变。



### GitHub Actions 使用

无需修改 workflow。在仓库设置中按账号添加 Secret（可选，旧用户不配置
即保持单账号模式）。每个账号两个 Secret，内容与旧的 `DOUYIN_COOKIE` /
`DOUYIN_CONFIG` 完全一致：

| Secret | 内容 |
| --- | --- |
| `DOUYIN_COOKIE_ACCOUNT1` | 账号1 的 Cookie JSON 数组 |
| `DOUYIN_CONFIG_ACCOUNT1` | 账号1 的完整发送配置 JSON |
| `DOUYIN_COOKIE_ACCOUNT2` | 账号2 的 Cookie JSON 数组 |
| `DOUYIN_CONFIG_ACCOUNT2` | 账号2 的完整发送配置 JSON |
| `DOUYIN_COOKIE_ACCOUNT3` ~ `ACCOUNT5` | 以此类推，当前最多 5 个账号 |

workflow 会自动为每个配齐了 Cookie 与 Config 的账号生成
`config/accounts.json` 与对应的 `.env.accountN`，无需手动维护这些文件。
要求：

- 账号从 `ACCOUNT1` 开始连续编号，允许跳过（例如只配置 ACCOUNT1 和 ACCOUNT3）。
- 某个账号只配置了 Cookie 或 Config 其中一个，workflow 会直接报错提示，
  防止账号被静默漏跑。
- 旧的 `DOUYIN_COOKIE` / `DOUYIN_CONFIG` Secret 无需删除；检测到多账号
  配置时自动使用多账号模式。
- **老用户追加账号**：没有配置 `DOUYIN_COOKIE_ACCOUNT1` / `DOUYIN_CONFIG_ACCOUNT1`
  时，旧的 `DOUYIN_COOKIE` / `DOUYIN_CONFIG` 会自动作为账号1，因此老用户
  只需要直接添加 `ACCOUNT2`（及以上）的 Secret 即可。
  建议之后有空把旧配置复制成 `ACCOUNT1` 对，避免将来删除旧 Secret 时账号1
  从清单中消失。

### 失败隔离与退出码

- 某个账号失败（Cookie 失效、好友不存在、发送异常等）**不影响其他账号**，串行继续执行。
- 全部账号成功 → 退出码 `0`；存在任意失败 → 退出码 `1`（与单账号语义一致）。
- 每个账号的钉钉通知使用各自 env 中的 `DINGTALK_WEBHOOK` / `DINGTALK_SECRET`。

## 注意

- Cookie 和配置不要直接提交到仓库。
- 修改好友或表情配置后建议重新 Dry Run。
- 同一个账号不要同时运行多个定时器，避免重复发送。
- GitHub-hosted runner 的网络环境变化可能触发抖音安全验证。


## 友情链接

- [LINUX DO](https://linux.do/) - 新的理想型社区


## License

本项目采用 [MIT License](LICENSE)。
