# ChmlFrp 每日自动签到

基于 **GitHub Actions + Playwright + 通义千问 AI 视觉** 的 ChmlFrp 每日自动签到方案。每天北京时间 0:05 自动登录 ChmlFrp 面板完成签到，并把**积分明细邮件**发送到你的邮箱，全程无需登录面板确认。

> 签到获得的积分可在 ChmlFrp「增值中心」兑换会员时长（会员：32M 带宽 / 16 条隧道 / 会员节点）。

## 功能特性

- ✅ 每天定时自动签到（北京时间 0:05）
- ✅ 自动登录（账号密码 → OAuth2 MFA 邮箱验证码）
- ✅ 自动读取 QQ 邮箱验证码并填入
- ✅ 极验 4 代验证码 AI 视觉识别（通义千问 qwen-vl-plus）
- ✅ 签到后自动发送**结果邮件**：签到前总积分 / 本次获得积分 / 累计签到次数 / 签到后总积分 / 是否成功（时间精确到秒）

## 工作原理

```text
GitHub Actions (每天 0:05 触发)
  └─ 打开面板 panel.chmlfrp.net → 跳转 OAuth2 登录页 account.qzhua.net
      └─ 填入账号密码 → 点击"登 录"
          └─ 跳转 MFA 页面 → 切换"邮箱验证码"模式
              └─ IMAP 读取 QQ 邮箱最新验证码 → 填入 → 确认
                  └─ 跳回面板 → 移除公告弹窗
                      ├─ 点"签到信息"→ 读【签到前总积分/累计次数】
                      ├─ 点"签到"→ 读【本次获得XX点积分】
                      ├─ 再点"签到信息"→ 读【签到后总积分/累计次数】
                      └─ 组装邮件 → SMTP 发送到 SMTP_TO
```

> 积分数据一律以面板 **"签到信息"统计弹窗** 为准（"累计签到积分 / 累计签到次数"），不使用首页"积分数"卡片（该卡片有更新延迟）。

## 前置条件

| 项目 | 说明 |
|---|---|
| GitHub 账号 | 免费，用于跑 Actions |
| ChmlFrp 账号 | 需已开启邮箱验证（MFA），登录密码已知 |
| QQ 邮箱 | 用于接收验证码，需开启 IMAP 并生成授权码 |
| 通义千问 API Key | 免费额度够用，用于识别极验验证码 |

## 快速开始

### 1. Fork 本仓库

点击右上角 **Fork** 到你的 GitHub 账号下。

### 2. 开启 GitHub Actions

进入你 Fork 后的仓库 → **Actions** 页签 → 如果提示 "Workflows aren't being run"，点 **"I understand my workflows, go ahead and enable them"**。

> ⚠️ Fork 的仓库默认**禁用**定时任务，必须在 Actions 页手动点一次 **Enable workflow** 才能激活 cron 定时。

### 3. 配置 Secrets

进入仓库 **Settings → Secrets and variables → Actions → New repository secret**，逐个添加：

| Secret 名 | 必填 | 说明 |
|---|---|---|
| `CHML_USERNAME` | ✅ | ChmlFrp 登录用户名/邮箱 |
| `CHML_PASSWORD` | ✅ | ChmlFrp 登录密码 |
| `CHML_URL` | ✅ | `https://panel.chmlfrp.net/home` |
| `EMAIL_ADDRESS` | ✅ | QQ 邮箱地址（如 `123456789@qq.com`） |
| `EMAIL_IMAP_PASSWORD` | ✅ | QQ 邮箱 IMAP 授权码（非 QQ 密码） |
| `AI_BASE_URL` | ✅ | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `AI_API_KEY` | ✅ | 通义千问 API Key（[获取地址](https://bailian.console.aliyun.com/?apiKey=1#/api-key)） |
| `AI_MODEL` | ✅ | `qwen-vl-plus` |
| `TOTP_SECRET` | ⬜ 可选 | 如使用 TOTP 验证器（本方案默认用邮箱验证码，可不填） |
| `SMTP_HOST` | ⬜ 推荐 | 结果邮件发件 SMTP，QQ 邮箱填 `smtp.qq.com` |
| `SMTP_USER` | ⬜ 推荐 | 发件邮箱账号（如 QQ 邮箱） |
| `SMTP_PASS` | ⬜ 推荐 | 发件邮箱 SMTP 授权码（QQ 授权码与 IMAP 通用） |
| `SMTP_TO` | ⬜ 推荐 | **接收签到结果邮件的邮箱** |

> 💡 结果邮件（推荐配置）：不配 `SMTP_*` 也能签到，但只能看日志；配置后每天签到完成会把积分明细邮件发到 `SMTP_TO`（如 `admin@77boss.cn`）。发件用 QQ 邮箱时，`SMTP_USER`=QQ邮箱、`SMTP_PASS`=同一个 16 位授权码。

### 4. 获取 QQ 邮箱 IMAP 授权码

1. 浏览器打开 **mail.qq.com** 并登录
2. **设置 → 账户**
3. 找到 **"POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务"**
4. 开启 **"IMAP/SMTP服务"** → 点 **"生成授权码"**（需手机验证）
5. 得到 **16 位授权码**（形如 `abcdefghijklmnop`），填入 `EMAIL_IMAP_PASSWORD`

### 5. 手动触发一次测试

进入 **Actions** → 左侧 **ChmlFrp自动签到** → 右侧 **Run workflow** → 绿色按钮 **Run workflow**。

等待约 2-3 分钟，看到绿色 Success 即成功。

### 6. 验证结果

1. 查收**结果邮件**：签到完成后 `SMTP_TO` 会收到一封邮件，**邮件标题一眼可辨成败**：
   - 成功：`【ChmlFrp签到成功】2026-09-07 00:05:06`
   - 失败：`【ChmlFrp签到失败】2026-09-07 00:05:06`

   正文含：
   ```
   签到状态：成功
   签到时间：2026-09-07 00:05:06
   签到前总积分：284
   本次签到获得：152 积分
   累计签到次数：3 次
   签到后总积分：436
   ```
2. 或在 Actions 点开本次运行 → 展开 **"执行签到"** 步骤 → 看日志末尾"邮件内容"段
3. 或登录 [ChmlFrp 面板](https://panel.chmlfrp.net/home) → 点"签到信息"核对积分

### 7. 定时任务

工作流已内置 cron：`5 16 * * *`（UTC）＝ 北京时间每天 **0:05**。Fork 后点过一次 Enable workflow 即生效，无需其他配置。

---

## 常见踩坑点及解决方案

### 坑 1：登录按钮文字是"登 录"（中间有空格）

登录页按钮文字为 `登 录`，直接匹配 `"登录" in text` 会**匹配不到**，反而会误命中"通过 Apple 登录"按钮，导致跳转到 appleid.apple.com 登录失败。

**解决**：匹配前先去掉所有空格（`txt.replace(" ","")`），并排除 Apple/QQ/微信/Github/Google 等第三方登录按钮，再选文字最短的候选按钮。

### 坑 2：账号登录后跳转 MFA 二次验证页面

ChmlFrp 使用轻爪（QZhua）账号体系，开启双重验证后，账号密码正确会跳转 `account.qzhua.net/mfa`，需要再输入验证码。

**解决**：脚本自动识别 `/mfa` 页面 → 切换到"邮箱验证码"模式 → 读邮箱提取验证码填入。（TOTP 方案因 secret 与页面显示不一致等原因易失败，邮箱方案更稳。）

### 坑 3：IMAP 用中文搜索条件报 ASCII 编码错误

`mail.search(None, 'SUBJECT "验证"')` 会报错：
```
'ascii' codec can't encode characters in position 13-14
```

**解决**：不要用 IMAP 搜索条件传中文。改用 `mail.search(None, "ALL")` 取最近 30 封，在 Python 里用中文关键词过滤主题/发件人。

### 坑 4：GitHub Actions 截图文字全是乱码（方块/问号）—— 仅恢复截图调试时需要

> 当前版本已**不自动上传截图**，改为日志文字输出判断结果，此坑不再影响日常使用。仅当你想临时恢复截图上传做调试时需要注意：

GitHub Actions 的 Ubuntu 容器默认**没有中文字体**，headless Chromium 渲染中文会变成方块。这不影响脚本逻辑（`get_by_text` 读的是 DOM 不是渲染画面），但截图没法看。

**解决**：workflow 的"安装依赖"步骤加：
```bash
sudo apt-get install -y fonts-noto-cjk
```

### 坑 5：登录后中央弹窗遮罩挡住签到按钮，点击超时

面板是 Naive UI，登录后自动弹出公告弹窗，`.n-modal-mask` 遮罩会拦截所有点击，导致 `click` 一直 "intercepts pointer events" 超时。

**解决**：用 JS 强制删除弹窗/遮罩 DOM：
```js
document.querySelectorAll('.n-modal-mask').forEach(e => e.remove());
document.querySelectorAll('.n-modal-container').forEach(e => e.remove());
document.querySelectorAll('.n-overlay, .n-drawer-mask').forEach(e => e.remove());
```

### 坑 6：workflow 的 env 缩进错误导致环境变量没传进去

`env:` 前多了缩进空格会让 YAML 解析失败或环境变量不生效（表现为脚本报"未配置 TOTP_SECRET/邮箱未配置"）。

**解决**：`env:` 必须和 `name:`、`run:` 同级缩进（都是 6 个空格），子项统一 10 个空格：
```yaml
      - name: 执行签到
        env:
          CHML_USERNAME: ${{ secrets.CHML_USERNAME }}
        run: python checkin.py
```

### 坑 7：签到按钮找不到（"签到"和"签到信息"两个按钮）

面板首页右上角有 **"签到"** 和 **"签到信息"** 两个按钮，`get_by_text("签到", exact=False)` 会同时匹配两个，导致点击错误元素或找不到。

**解决**：用 `get_by_text("签到", exact=True)` 精确匹配，并校验 `inner_text` 去掉空格后等于 `"签到"`。

### 坑 8：极验验证码识别失败

极验 4 代有滑块/文字点选/图标点选等多种类型，纯 API 无法绕过，必须浏览器自动化 + AI 视觉识别。

**解决**：脚本用通义千问 `qwen-vl-plus` 截图识别类型（slider/click/icon/space），再模拟滑块拖动或点击。失败会自动重试 3 次。若你的账号验证码过于复杂，可考虑第三方打码平台（YesCaptcha/CapSolver）替换 AI 识别。

### 坑 9：MFA 每次跑发两封验证码邮件

切换"邮箱验证码"选项卡时系统可能已自动发送一封，脚本又点"重新发送"就变成两封。

**解决**：脚本优化为先等 5 秒读邮箱，能读到自动发送的验证码就不再点发送按钮；读不到才点。

### 坑 10：Fork 后 Actions 定时任务不执行

Fork 的仓库默认禁用 workflow 定时，且 GitHub 会暂停 60 天未活动的 cron 任务。

**解决**：在 Actions 页手动 **Enable workflow** 一次；保持仓库活跃（偶尔手动跑一次）避免被暂停。

---

## 项目结构

```text
ChmlFrp-Checkin/
├── checkin.py                    # 主脚本（Playwright 自动化签到）
├── requirements.txt              # Python 依赖
├── README.md                     # 本文件
├── SKILL.md                      # 可复用 Skill 说明（供 AI Agent 加载复用）
└── .github/
    └── workflows/
        └── checkin.yml           # GitHub Actions 定时任务
```

## 免责声明

本脚本仅用于自动化每日签到，请遵守 ChmlFrp 平台服务条款，合理使用积分。涉及账号密码请妥善保管在 GitHub Secrets（加密存储），勿写入代码或公开仓库。
