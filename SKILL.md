---
name: chmlfrp-daily-checkin
description: ChmlFrp 内网穿透平台每日自动签到。当用户需要为 ChmlFrp（chmlfrp.net）账号实现每日自动签到、自动领取签到积分、兑换会员带宽，或复用本仓库的 GitHub Actions 自动化签到流程时使用。覆盖 OAuth2 登录、MFA 邮箱验证码自动读取、极验4代验证码 AI 视觉识别、每日定时调度全流程。
---

# ChmlFrp 每日自动签到（可复用 Skill）

为 ChmlFrp 账号搭建每日自动签到，签到积分可用于兑换会员（更大带宽 / 更多隧道）。

## 何时使用

- 用户要求给 ChmlFrp / 轻爪账号做"自动签到 / 每日签到 / 签到积分自动化"。
- 用户想复用这套 GitHub Actions 自动化签到方案到新账号、新仓库。
- 用户遇到 ChmlFrp 登录、MFA、验证码、Actions 配置相关报错需要排障。

## 核心事实（部署前必须确认）

| 项 | 值 |
|---|---|
| ChmlFrp 官网 | `https://www.chmlfrp.net` |
| 面板地址 | `https://panel.chmlfrp.net/home` |
| 登录页（OAuth2） | `account.qzhua.net`（轻爪账号体系，client_id=`019d40ca28217ab6bae2646ac81d021c`） |
| MFA 二次验证 | 账号开启双重验证后，登录跳转 `account.qzhua.net/mfa`，需邮箱/TOTP 验证码 |
| 签到按钮 | 面板首页右上角"签到"按钮（旁有"签到信息"） |
| 签到接口 | `POST https://cf-v2.uapis.cn/qiandao`（需 token + 极验4参数，无法纯 API 绕过） |
| 免费版 | 8Mbps / 4 隧道 / 不限流量；签到积分兑会员（32M / 16 隧道） |

## 架构与执行流程

```text
GitHub Actions (cron 0 1 * * * = 北京 9:00)
  └─ checkin.py (Playwright headless)
      1. 打开面板 → 自动跳转 OAuth2 登录页
      2. 填账号密码 → 点"登 录"（注意文字含空格）
      3. 若跳 /mfa → 切"邮箱验证码" → IMAP 读 QQ 邮箱验证码 → 填入确认
      4. 回面板 → JS 移除公告弹窗遮罩
      5. 精确匹配"签到"按钮 → 点击
      6. 极验4代 → 通义千问视觉识别(slider/click/icon/space) → 模拟操作
      7. 校验页面含"签到成功/已签到/获得积分" → 判定成功
```

## 部署步骤（对新账号/新仓库）

1. **Fork 本仓库**到目标 GitHub 账号。
2. **开启 Actions**：Fork 后定时任务默认禁用，必须在 Actions 页手动 Enable workflow 一次。
3. **配置 Secrets**（Settings → Secrets and variables → Actions → New repository secret）：

   | Secret | 必填 | 值 |
   |---|---|---|
   | `CHML_USERNAME` | ✅ | ChmlFrp 登录用户名/邮箱 |
   | `CHML_PASSWORD` | ✅ | ChmlFrp 登录密码 |
   | `CHML_URL` | ✅ | `https://panel.chmlfrp.net/home` |
   | `EMAIL_ADDRESS` | ✅ | 接收验证码的 QQ 邮箱 |
   | `EMAIL_IMAP_PASSWORD` | ✅ | QQ 邮箱 IMAP 授权码（非密码） |
   | `AI_BASE_URL` | ✅ | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
   | `AI_API_KEY` | ✅ | 通义千问 API Key（bailian.console.aliyun.com 获取） |
   | `AI_MODEL` | ✅ | `qwen-vl-plus` |
   | `TOTP_SECRET` | ⬜ | TOTP 方案可选（本方案默认邮箱验证码，可留空） |
   | `SMTP_*` | ⬜ | 邮件结果通知（可选） |

4. **开启 QQ 邮箱 IMAP**：mail.qq.com → 设置 → 账户 → 开启 IMAP/SMTP → 生成授权码。
5. **手动触发测试**：Actions → Run workflow → 等 2-3 分钟看 Success。
6. **验证**：点开本次运行 → 展开"执行签到"步骤 → 看日志末尾文字输出（`签到成功！`/`今日已签到`）；或登录面板账户页确认积分；配置了 SMTP_* 还会收到结果邮件。

## 必须遵守的约束 / 规范

- **账号密码等敏感信息只能放 GitHub Secrets**，严禁写入代码或公开仓库；脚本只通过环境变量读取。
- 极验4代无法用纯 API 绕过，必须走浏览器自动化 + AI 视觉；识别失败要有重试与失败退出，不要假成功。
- GitHub Actions 容器无中文字体，**必须安装 `fonts-noto-cjk`**，否则截图乱码（不影响逻辑但不可读）。
- 每次修改脚本后，验证方式必须是从 Actions 真实运行 + 回读日志末尾文字输出，不能只看 exit code。
- 定时任务用 cron，注意 GitHub 会对 60 天不活动的 cron 自动暂停。

## 关键实现细节（踩坑点与解决方案）

1. **登录按钮"登 录"含空格** → 匹配前去空格（`txt.replace(" ","")`），排除第三方（Apple/QQ/微信/Github/Google），候选按文字长度取最短。
2. **MFA 二次验证** → 账号密码通过后若 URL 含 `/mfa`，走邮箱验证码：切"邮箱验证码"选项卡 → 读邮箱验证码 → 填入 → 点确认。
3. **IMAP 中文搜索报 ASCII 编码错** → 禁用 `SUBJECT "验证"` 这类中文搜索条件；改 `search(None,"ALL")` 取最近 30 封在 Python 内过滤（主题/发件人关键词 + 10 分钟时效）。
4. **Actions 截图乱码**（当前已不上传截图；若恢复截图调试/上传）→ GitHub Actions 容器无中文字体，需在 workflow 装 `fonts-noto-cjk`，否则截图文字变方块。
5. **弹窗遮罩拦截点击（n-modal-mask intercepts pointer events）** → 用 `page.evaluate` 移除 `.n-modal-mask` / `.n-modal-container` / `.n-overlay`。
6. **"签到"与"签到信息"按钮混淆** → `get_by_text("签到", exact=True)` + 校验 `inner_text` 去空格 == "签到"。
7. **workflow env 缩进错误** → `env:` 必须与 `name:`/`run:` 同级缩进，否则环境变量不注入。
8. **每次跑发两封验证码邮件** → 切换邮箱模式后先读邮箱（系统可能已自动发送），读不到才点"重新发送"。
9. **极验识别失败** → AI 视觉识别 slider/click/icon/space 四类，模拟拖动/点选；重试 3 次。复杂验证码可换第三方打码平台。
10. **Fork 后 cron 不跑** → Actions 页手动 Enable workflow；保持仓库活跃。

## 排障速查（按日志关键字）

| 日志/报错 | 含义 | 处理 |
|---|---|---|
| `button[3]: text='通过 Apple 登录'` + 跳到 appleid | 登录按钮匹配错 | 修匹配逻辑（去空格+排除第三方） |
| `登录页URL: .../mfa` | 触发 MFA | 走邮箱验证码流程 |
| `'ascii' codec can't encode...` | IMAP 中文搜索 | 改 ALL 全量 + Python 过滤 |
| `n-modal-mask ... intercepts pointer events` | 弹窗遮罩挡点击 | JS 移除遮罩/弹窗 |
| `未配置 TOTP_SECRET / 邮箱未配置` | env 没注入 | 检查 workflow env 缩进与 Secrets |
| `签到结果不确定` | 签到后页面无成功关键字 | 看日志中"签到后页面文字"段；检查是否点了"立即签到/领取" |
| 截图全乱码 | 缺中文字体 | workflow 装 fonts-noto-cjk |
| 60s内未收到验证码邮件 | 邮件读取失败 | 检查 IMAP 授权码、邮箱过滤规则、发件人 |

## 交付要求

- 交付物：可运行的 GitHub 仓库（checkin.py + requirements.txt + workflow + README + 本 SKILL）。
- 交付后必须让用户验证一次真实运行：手动 Run workflow → 展开"执行签到"步骤 → 日志末尾出现 `签到成功！`/`今日已签到` 且账户积分到账。
- 若签到失败，要求用户提供 Actions 日志中"签到后页面文字"段（脚本会自动打印页面文字与可见按钮），据此精确定位（按钮文字/弹窗/验证码类型），再改脚本重跑。
