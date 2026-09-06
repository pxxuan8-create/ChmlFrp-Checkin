# -*- coding: utf-8 -*-
"""
ChmlFrp 每日自动签到脚本（GitHub Actions 版）
================================================
流程：打开面板 -> 账号密码登录 -> OAuth2 MFA 邮箱验证码 -> 进入面板
      -> 读"签到信息"弹窗(签到前积分/次数) -> 点击签到
      -> 读签到结果弹窗(本次获得积分) -> 再读"签到信息"(签到后积分/次数)
      -> 组装邮件 -> SMTP 发送到指定邮箱

依赖环境变量（由 GitHub Actions Secrets 注入）：
  CHML_USERNAME         ChmlFrp 登录用户名/邮箱
  CHML_PASSWORD         ChmlFrp 登录密码
  CHML_URL              面板地址，默认 https://panel.chmlfrp.net/home
  EMAIL_ADDRESS         QQ 邮箱地址（用于接收 MFA 验证码）
  EMAIL_IMAP_PASSWORD   QQ 邮箱 IMAP 授权码（不是 QQ 密码）
  AI_BASE_URL           通义千问 OpenAI 兼容接口地址
  AI_API_KEY            通义千问 API Key
  AI_MODEL              AI 视觉模型，默认 qwen-vl-plus
  SMTP_HOST             邮件通知 SMTP 服务器（如 smtp.qq.com）
  SMTP_USER             发件邮箱账号（QQ 邮箱）
  SMTP_PASS             发件邮箱 SMTP 授权码
  SMTP_TO               收件邮箱（签到结果通知）
"""

import os, json, time, base64, requests, sys, re
import imaplib, email
from email.header import decode_header
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

USERNAME = os.environ.get("CHML_USERNAME", "")
PASSWORD = os.environ.get("CHML_PASSWORD", "")
PANEL_URL = os.environ.get("CHML_URL", "https://panel.chmlfrp.net/home")
EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS", "")
EMAIL_IMAP_PASSWORD = os.environ.get("EMAIL_IMAP_PASSWORD", "")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "qwen-vl-plus")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_TO = os.environ.get("SMTP_TO", "")

BJ_TZ = timezone(timedelta(hours=8))


def bj_now():
    """北京时间 yyyy-MM-dd HH:mm:ss"""
    return datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")


def ai_analyze_image(image_b64, prompt):
    """调用通义千问视觉模型分析极验验证码截图"""
    headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": AI_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
        ]}],
        "temperature": 0.1
    }
    try:
        r = requests.post(f"{AI_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=60)
        text = r.json()["choices"][0]["message"]["content"]
        start, end = text.find("{"), text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except Exception as e:
        print(f"AI调用失败: {e}")
    return None


def send_email(subject, body):
    """SMTP 发送签到结果邮件（QQ 邮箱发件，465 SSL）"""
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, SMTP_TO]):
        print(f"[邮件] 未完整配置 SMTP，本次不发送。收件人应为: {SMTP_TO}")
        print(f"[邮件] 邮件主题: {subject}")
        print(f"[邮件] 邮件内容:\n{body}")
        return False
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, SMTP_USER, SMTP_TO
    try:
        server = smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=30)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, SMTP_TO, msg.as_string())
        server.quit()
        print(f"[邮件] 已发送到 {SMTP_TO}")
        return True
    except Exception as e:
        print(f"[邮件] 发送失败: {e}")
        return False


def fetch_email_code(since_utc=None):
    """
    从 QQ 邮箱读取最新的 QZhua/ChmlFrp 验证邮件，提取 6 位验证码。
    - 不用 IMAP 中文搜索（会触发 ASCII 编码错误），直接取最近 30 封在 Python 里过滤。
    - 只认最近 10 分钟内的验证邮件。
    - since_utc: 若指定，只接受邮件 Date >= since_utc - 60秒 的新邮件，
      避免在频繁测试时读到上一轮遗留的旧验证码。
    """
    if not EMAIL_ADDRESS or not EMAIL_IMAP_PASSWORD:
        print("邮箱未配置")
        return None

    imap_server = "imap.qq.com"
    imap_port = 993

    try:
        mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        mail.login(EMAIL_ADDRESS, EMAIL_IMAP_PASSWORD)
        mail.select("INBOX")

        result, data = mail.search(None, "ALL")
        if result != "OK" or not data[0]:
            print("收件箱为空")
            mail.logout()
            return None

        ids = data[0].split()
        latest_ids = ids[-30:] if len(ids) >= 30 else ids
        latest_ids.reverse()  # 最新的在前

        import datetime as _dt
        from email.utils import parsedate_to_datetime

        for eid in latest_ids:
            result, msg_data = mail.fetch(eid, "(RFC822)")
            if result != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])

            subject = ""
            subj_parts = decode_header(msg["Subject"])
            for part, enc in subj_parts:
                if isinstance(part, bytes):
                    try:
                        subject += part.decode(enc or "utf-8", errors="ignore")
                    except:
                        subject += part.decode("utf-8", errors="ignore")
                else:
                    subject += part

            from_addr = msg.get("From", "")
            from_lower = from_addr.lower()

            is_verify_email = any(k in subject for k in ["验证", "验证码", "code", "Code", "CODE", "动态码"]) or \
                              any(k in from_lower for k in ["qzhua", "chmlfrp"])

            if not is_verify_email:
                continue

            try:
                msg_date = parsedate_to_datetime(msg["Date"])
                if since_utc is not None and msg_date < since_utc - timedelta(seconds=60):
                    # 太旧：本次 MFA 流程开始前的邮件（很可能是上一次运行遗留）
                    print(f"  跳过旧验证码邮件: 主题='{subject}', Date={msg_date}")
                    continue
                if (_dt.datetime.now(_dt.timezone.utc) - msg_date).total_seconds() > 600:
                    continue
            except:
                pass

            print(f"找到候选邮件: 主题='{subject}'")

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    ctype = part.get_content_type()
                    if ctype in ["text/plain", "text/html"]:
                        try:
                            payload = part.get_payload(decode=True)
                            charset = part.get_content_charset() or "utf-8"
                            body += payload.decode(charset, errors="ignore")
                        except:
                            pass
            else:
                try:
                    payload = msg.get_payload(decode=True)
                    charset = msg.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="ignore")
                except:
                    pass

            body_clean = re.sub(r"<[^>]+>", " ", body)
            body_clean = re.sub(r"\s+", " ", body_clean)

            patterns = [
                r"验证码[：:\s是为]+(\d{6})",
                r"验证代码[：:\s是为]+(\d{6})",
                r"动态码[：:\s是为]+(\d{6})",
                r"code[：:\s是为]+(\d{6})",
                r"(\d{6})",
            ]
            for pat in patterns:
                match = re.search(pat, body_clean, re.IGNORECASE)
                if match:
                    code = match.group(1)
                    print(f"提取到验证码: {code}")
                    mail.logout()
                    return code

        print("最近30封邮件中未找到有效验证码")
        mail.logout()
        return None

    except Exception as e:
        print(f"读取邮箱失败: {e}")
        return None


def solve_geetest(page):
    """处理极验 4 代验证码（AI 视觉识别 + 模拟操作）"""
    for attempt in range(3):
        print(f"极验验证尝试 {attempt+1}/3")
        time.sleep(2)
        try:
            page.wait_for_selector(".geetest_wrap", timeout=3000)
        except:
            print("验证码已消失，可能已通过")
            return True
        try:
            captcha = page.locator(".geetest_wrap")
            if not captcha.is_visible():
                time.sleep(1)
                continue
            img_b64 = base64.b64encode(captcha.screenshot()).decode()
        except Exception as e:
            print(f"截图失败: {e}")
            continue
        prompt = """你是验证码识别专家。分析这张极验验证码截图，判断类型并给出操作指令。
类型：slider(滑块拼图)、click(文字点选)、icon(图标点选)、space(仅需点按钮)
返回严格JSON：
{"type":"slider或click或icon或space","slider_target_x":数字,"slider_start_x":数字,"click_points":[[x,y]],"confidence":0.0-1.0}
坐标以截图左上角为原点，像素为单位。"""
        result = ai_analyze_image(img_b64, prompt)
        if not result:
            time.sleep(2)
            continue
        print(f"AI判断: type={result.get('type')}, conf={result.get('confidence')}")
        try:
            if result["type"] == "space":
                btn = page.locator(".geetest_btn")
                if btn.is_visible(): btn.click()
                time.sleep(2)
            elif result["type"] == "slider":
                slider = page.locator(".geetest_slider_button")
                if slider.is_visible():
                    box = slider.bounding_box()
                    sx, sy = box["x"]+box["width"]/2, box["y"]+box["height"]/2
                    cbox = page.locator(".geetest_wrap").bounding_box()
                    tx = cbox["x"] + result["slider_target_x"]
                    dist = tx - sx
                    for i in range(30):
                        prog = (i+1)/30
                        ease = 1-(1-prog)**3
                        cx = sx + dist*ease
                        cy = sy + (0.5-(i%3)*0.3)*2
                        if i==0:
                            page.mouse.move(sx, sy)
                            page.mouse.down()
                        page.mouse.move(cx, cy)
                        time.sleep(0.02+(i/30)*0.03)
                    page.mouse.up()
                    time.sleep(3)
            elif result["type"] in ["click","icon"]:
                cbox = page.locator(".geetest_wrap").bounding_box()
                for px, py in result.get("click_points", []):
                    page.mouse.click(cbox["x"]+px, cbox["y"]+py)
                    time.sleep(0.5)
                confirm = page.locator(".geetest_commit")
                if confirm.is_visible(): confirm.click()
                time.sleep(3)
        except Exception as e:
            print(f"执行操作失败: {e}")
            time.sleep(2)
            continue
        time.sleep(2)
        try:
            page.wait_for_selector(".geetest_wrap", timeout=2000)
            refresh = page.locator(".geetest_refresh")
            if refresh.is_visible(): refresh.click()
            time.sleep(1)
        except:
            print("极验验证通过！")
            return True
    print("极验验证3次均失败")
    return False


def handle_mfa(page):
    """
    处理 OAuth2 MFA 二次验证（邮箱验证码方式）。
    - 记录流程开始时间，只接受"本次流程开始后"发出的验证码邮件，
      避免频繁测试时读到上一轮遗留的旧验证码（旧码已失效会导致提交失败）。
    - 最多重试 3 次：读新码 -> 填入 -> 提交；失败则点"重新发送"再试。
    """
    if "/mfa" not in page.url:
        print("未检测到 MFA 页面，跳过")
        return True

    if not EMAIL_ADDRESS or not EMAIL_IMAP_PASSWORD:
        print("未配置邮箱，无法处理 MFA")
        return False

    print("检测到 MFA 页面，使用邮箱验证码方式")

    # 记录 MFA 流程开始时间（在切选项卡自动发码之前）
    mfa_start = datetime.now(timezone.utc)
    time.sleep(2)

    # 切换到邮箱验证码模式
    email_mode = False
    for text in ["邮箱验证码", "邮箱", "Email", "EMAIL"]:
        try:
            el = page.get_by_text(text, exact=False)
            if el.count() > 0:
                for i in range(el.count()):
                    if el.nth(i).is_visible():
                        el.nth(i).click()
                        print(f"点击了'{text}'选项")
                        email_mode = True
                        time.sleep(2)
                        break
                if email_mode:
                    break
        except:
            continue

    def click_send_code():
        """点击'发送验证码/重新发送'按钮"""
        send_clicked = False
        for text in ["发送验证码", "获取验证码", "发送", "重新发送", "获取"]:
            try:
                btn = page.get_by_text(text, exact=False)
                if btn.count() > 0:
                    for i in range(btn.count()):
                        if btn.nth(i).is_visible():
                            btn.nth(i).click()
                            print(f"点击了'{text}'按钮")
                            send_clicked = True
                            time.sleep(2)
                            break
                    if send_clicked:
                        break
            except:
                continue
        return send_clicked

    def read_new_code():
        """只读本次 MFA 流程开始后到达的新验证码"""
        return fetch_email_code(since_utc=mfa_start)

    def fill_and_submit(code):
        """填入验证码并提交，返回 True 表示提交动作已执行"""
        time.sleep(1)
        all_inputs = page.locator("input")
        digit_inputs = []
        for i in range(all_inputs.count()):
            try:
                inp = all_inputs.nth(i)
                itype = (inp.get_attribute("type") or "text").lower()
                if itype in ["text", "tel", "number"] and inp.is_visible():
                    iname = (inp.get_attribute("name") or "").lower()
                    if "csrf" not in iname and "continue" not in iname and "finger" not in iname:
                        digit_inputs.append(inp)
            except:
                pass

        print(f"找到 {len(digit_inputs)} 个可见输入框")
        filled = False

        if len(digit_inputs) >= 6:
            print("使用6框模式输入")
            for i, ch in enumerate(code[:6]):
                try:
                    digit_inputs[i].click()
                    time.sleep(0.1)
                    digit_inputs[i].type(ch, delay=30)
                except Exception as e:
                    print(f"输入第{i+1}位失败: {e}")
            filled = True
        elif len(digit_inputs) >= 1:
            print("使用单框模式输入")
            digit_inputs[0].click()
            time.sleep(0.1)
            digit_inputs[0].type(code, delay=50)
            filled = True

        if not filled:
            print("无法填入验证码")
            return False

        time.sleep(1)
        submit_clicked = False
        for text in ["确认", "验证", "提交", "登录", "继续", "下一步", "Verify", "Submit"]:
            try:
                btn = page.get_by_text(text, exact=False)
                if btn.count() > 0:
                    for i in range(btn.count()):
                        if btn.nth(i).is_visible():
                            btn.nth(i).click()
                            print(f"点击了'{text}'按钮")
                            submit_clicked = True
                            break
                    if submit_clicked:
                        break
            except:
                continue
        if not submit_clicked:
            print("未找到确认按钮，按回车")
            page.keyboard.press("Enter")
        return True

    # 主重试循环
    for attempt in range(1, 4):
        print(f"===== MFA 验证码尝试 {attempt}/3 =====")

        # 1. 先读新码（切换选项卡可能已自动发送；时间过滤只认新邮件）
        time.sleep(3)
        code = read_new_code()
        if not code:
            print("未读到新验证码，点击发送...")
            click_send_code()
            for i in range(12):
                print(f"等待新验证码邮件... ({i+1}/12)")
                code = read_new_code()
                if code:
                    break
                time.sleep(5)

        if not code:
            print("60秒内未收到新验证码邮件")
            continue

        # 2. 填入并提交
        fill_and_submit(code)
        time.sleep(5)
        print(f"MFA提交后URL: {page.url}")

        if "/mfa" not in page.url:
            print("MFA 验证通过！")
            return True

        print(f"尝试{attempt}失败，仍在 MFA 页面（可能验证码过期/填错），重试...")
        # 失败：点"重新发送"拿新码，进入下一轮
        try:
            click_send_code()
        except:
            pass
        time.sleep(2)

    print("MFA 3次尝试均失败")
    return False


def remove_modal_overlays(page):
    """用 JS 移除 Naive UI 弹窗/遮罩，避免拦截点击"""
    try:
        removed = page.evaluate("""() => {
            let n = 0;
            document.querySelectorAll('.n-modal-mask').forEach(e => { e.remove(); n++; });
            document.querySelectorAll('.n-modal-container').forEach(e => { e.remove(); n++; });
            document.querySelectorAll('.n-overlay, .n-drawer-mask, .n-drawer').forEach(e => { e.remove(); n++; });
            return n;
        }""")
        print(f"JS移除弹窗/遮罩: {removed}个")
        time.sleep(1)
    except Exception as e:
        print(f"JS移除弹窗异常: {e}")


def close_popover(page):
    """关闭当前可能打开的 popover/弹窗：按 Escape + 点击页面空白处"""
    try:
        page.keyboard.press("Escape")
        time.sleep(0.5)
    except:
        pass
    try:
        # 点击页面中央空白区域关闭
        page.mouse.click(400, 250)
        time.sleep(0.5)
    except:
        pass


def get_sign_info(page):
    """
    打开"签到信息"弹窗（统计信息），读取：
      - 累计签到积分（当前总积分，以此为准）
      - 累计签到次数
      - 上次签到时间
    返回 dict；读取失败返回 None。
    """
    info = None
    try:
        # 先移除可能遮挡的弹窗
        remove_modal_overlays(page)
        time.sleep(0.5)
        btn = page.get_by_text("签到信息", exact=True).first
        btn.click(timeout=5000)
        time.sleep(1.5)
        body = page.inner_text("body")
        m_pts = re.search(r"累计签到积分[：:]\s*(\d+)", body)
        m_cnt = re.search(r"累计签到次数[：:]\s*(\d+)", body)
        m_time = re.search(r"上次签到时间[：:]\s*([\d\-]+)", body)
        info = {
            "points": m_pts.group(1) if m_pts else None,
            "count": m_cnt.group(1) if m_cnt else None,
            "last_sign": m_time.group(1) if m_time else None,
        }
        print(f"签到信息: 累计积分={info['points']}, 累计次数={info['count']}, 上次签到={info['last_sign']}")
    except Exception as e:
        print(f"读取签到信息失败: {e}")
    finally:
        close_popover(page)
    return info


def parse_sign_reward(page):
    """
    解析签到结果弹窗，返回 (状态, 获得积分, 备注)
      状态: 'success' 签到成功 / 'already' 今日已签到 / 'failed' 未签到
    """
    status, reward, note = "failed", 0, ""
    try:
        body = page.inner_text("body")
        m_reward = re.search(r"本次签到获得(\d+)点积分", body)
        m_ok = re.search(r"签到成功", body)
        m_already = re.search(r"今日已签|已经签到|今日已签到", body)

        if m_reward:
            reward = int(m_reward.group(1))
        if m_ok:
            status = "success"
            note = f"本次签到获得{reward}点积分"
        elif m_already:
            status = "already"
            reward = 0
            note = "今日已签到"
        else:
            status = "failed"
            note = "未检测到签到成功弹窗"
        print(f"签到结果: status={status}, reward={reward}, note={note}")
    except Exception as e:
        print(f"解析签到结果异常: {e}")
    return status, reward, note


def main():
    result_msg, success = "", False
    sign_before = {"points": None, "count": None, "last_sign": None}
    sign_after = {"points": None, "count": None, "last_sign": None}
    reward = 0
    sign_status = "failed"
    note = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--no-sandbox","--disable-blink-features=AutomationControlled","--disable-dev-shm-usage"
        ])
        context = browser.new_context(
            viewport={"width":1280,"height":800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="zh-CN"
        )
        context.add_init_script("""
            Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
            Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
            Object.defineProperty(navigator,'languages',{get:()=>['zh-CN','zh','en']});
            window.chrome={runtime:{}};
        """)
        page = context.new_page()
        try:
            # 1. 打开面板
            print(f"打开面板: {PANEL_URL}")
            page.goto(PANEL_URL, timeout=30000, wait_until="domcontentloaded")
            for i in range(12):
                if "qzhua" in page.url or "login" in page.url:
                    break
                time.sleep(1)
            time.sleep(4)
            print(f"登录页URL: {page.url}")

            # 2. 登录
            all_inputs = page.locator("input")
            input_count = all_inputs.count()
            username_input = None
            password_input = page.locator("input[type='password']").first
            try:
                password_input.wait_for(state="visible", timeout=5000)
                print("找到密码框")
                for i in range(input_count):
                    try:
                        inp = all_inputs.nth(i)
                        itype = (inp.get_attribute("type") or "text").lower()
                        if itype in ["text","email","tel","username"] and inp.is_visible():
                            username_input = inp
                            print(f"找到用户名框: input[{i}]")
                            break
                    except:
                        continue
            except Exception as e:
                print(f"找密码框异常: {e}")

            if not username_input:
                for i in range(input_count):
                    try:
                        inp = all_inputs.nth(i)
                        if inp.is_visible():
                            username_input = inp
                            break
                    except:
                        continue

            if not username_input or not password_input:
                result_msg = "未找到用户名或密码输入框"
                page.screenshot(path="error_no_input.png")
                print(result_msg)
                browser.close()
                sys.exit(1)

            print("输入用户名...")
            username_input.click()
            time.sleep(0.3)
            username_input.type(USERNAME, delay=50)
            time.sleep(0.5)
            if username_input.input_value() != USERNAME:
                username_input.fill(USERNAME)
                time.sleep(0.3)

            print("输入密码...")
            password_input.click()
            time.sleep(0.3)
            password_input.type(PASSWORD, delay=50)
            time.sleep(0.5)
            print(f"密码框当前值长度: {len(password_input.input_value())}")

            # 点击登录（排除第三方）
            login_btn = None
            all_buttons = page.locator("button")
            btn_count = all_buttons.count()
            candidates = []
            for i in range(btn_count):
                try:
                    btn = all_buttons.nth(i)
                    if btn.is_visible():
                        txt = btn.inner_text(timeout=500).strip()
                        txt_nospace = txt.replace(" ", "").replace("\u3000", "")
                        is_third_party = any(k in txt for k in ["Apple", "QQ", "微信", "WeChat", "Github", "Google", "第三方"])
                        if not is_third_party and ("登录" in txt_nospace or "登陆" in txt_nospace or "Sign" in txt):
                            candidates.append((i, btn, len(txt)))
                except:
                    continue
            if candidates:
                candidates.sort(key=lambda x: x[2])
                login_btn = candidates[0][1]
                print(f"选中登录按钮: button[{candidates[0][0]}]")
            if not login_btn:
                for i in range(btn_count):
                    try:
                        btn = all_buttons.nth(i)
                        if btn.is_visible():
                            login_btn = btn
                            break
                    except:
                        continue
            if not login_btn:
                print("未找到按钮，按回车提交")
                page.keyboard.press("Enter")
            else:
                print("点击登录按钮")
                login_btn.click()

            time.sleep(6)
            print(f"点击后URL: {page.url}")

            # 3. 登录时极验验证码
            try:
                if page.locator(".geetest_wrap").is_visible():
                    print("登录需要极验验证码")
                    solve_geetest(page)
                    time.sleep(3)
            except Exception as e:
                print(f"检查验证码异常: {e}")

            # 4. MFA 邮箱验证码
            if "/mfa" in page.url:
                if not handle_mfa(page):
                    result_msg = "MFA 二次验证失败"
                    page.screenshot(path="error_mfa.png")
                    print(result_msg)
                    send_email(f"【ChmlFrp签到失败】{bj_now()}", build_mail_body(False, bj_now(), sign_before, 0, sign_after, result_msg))
                    browser.close()
                    sys.exit(1)
                time.sleep(3)

            # 5. 等待登录跳回面板
            print("等待登录跳转...")
            for i in range(20):
                if "panel.chmlfrp.net" in page.url and "login" not in page.url and "qzhua" not in page.url:
                    break
                time.sleep(1)
            time.sleep(3)
            print(f"当前URL: {page.url}")

            if "qzhua" in page.url or "login" in page.url or "/mfa" in page.url:
                result_msg = "登录失败，仍在认证页面"
                page.screenshot(path="error_login_fail.png")
                print(result_msg)
                send_email(f"【ChmlFrp签到失败】{bj_now()}", build_mail_body(False, bj_now(), sign_before, 0, sign_after, result_msg))
                browser.close()
                sys.exit(1)

            # 6. 移除面板弹窗，等面板加载
            print("面板已进入，移除弹窗...")
            remove_modal_overlays(page)

            # 等签到按钮出现
            for wait_i in range(15):
                try:
                    if page.get_by_text("签到", exact=True).count() > 0:
                        print("签到按钮已出现")
                        break
                except:
                    pass
                time.sleep(2)

            # 7. 【签到前】读签到信息弹窗（签到前总积分 / 累计次数）
            print("===== 读取签到前信息 =====")
            sign_before = get_sign_info(page)

            # 8. 点击签到
            print("===== 点击签到 =====")
            sign_clicked = False
            sign_btn = None
            try:
                for sel in [page.get_by_text("签到", exact=True), page.get_by_text("签 到", exact=True)]:
                    cnt = sel.count()
                    for i in range(cnt):
                        try:
                            el = sel.nth(i)
                            if el.is_visible():
                                t = el.inner_text(timeout=300).strip()
                                if t.replace(" ", "") == "签到":
                                    sign_btn = el
                                    break
                        except:
                            pass
                    if sign_btn:
                        break
            except:
                pass

            if sign_btn:
                try:
                    sign_btn.click(timeout=5000)
                    print("已点击签到按钮")
                    sign_clicked = True
                except Exception as e:
                    print(f"点击签到失败: {e}，尝试强制点击")
                    try:
                        sign_btn.click(force=True, timeout=3000)
                        print("强制点击成功")
                        sign_clicked = True
                    except:
                        pass

            if not sign_clicked:
                result_msg = "未找到签到按钮"
                page.screenshot(path="error_no_sign.png")
                print(result_msg)
                send_email(f"【ChmlFrp签到失败】{bj_now()}", build_mail_body(False, bj_now(), sign_before, 0, sign_after, result_msg))
                browser.close()
                sys.exit(1)

            # 9. 等待签到结果（含极验）
            time.sleep(3)
            try:
                if page.locator(".geetest_wrap").is_visible():
                    print("签到需要极验验证")
                    if not solve_geetest(page):
                        result_msg = "极验验证失败"
                        page.screenshot(path="geetest_fail.png")
                        print(result_msg)
                        send_email(f"【ChmlFrp签到失败】{bj_now()}", build_mail_body(False, bj_now(), sign_before, 0, sign_after, result_msg))
                        browser.close()
                        sys.exit(1)
            except:
                print("未检测到极验验证码")

            time.sleep(3)
            sign_status, reward, note = parse_sign_reward(page)
            # 关闭签到结果弹窗
            close_popover(page)
            time.sleep(1)

            # 10. 【签到后】再读签到信息弹窗（签到后总积分 / 累计次数）
            print("===== 读取签到后信息 =====")
            sign_after = get_sign_info(page)

            # 11. 判定成功
            if sign_status in ("success", "already"):
                success = True
                if sign_status == "success":
                    result_msg = "签到成功"
                else:
                    result_msg = "今日已签到"
            else:
                result_msg = "签到失败（未检测到签到成功）"
            print(result_msg)

            # 12. 组装并发送邮件
            body = build_mail_body(success, bj_now(), sign_before, reward, sign_after, result_msg + ("，"+note if note else ""))
            subject = f"【ChmlFrp签到{'成功' if success else '失败'}】{bj_now()}"
            print("===== 邮件内容 =====")
            print(subject)
            print(body)
            print("=====================")
            send_email(subject, body)

        except Exception as e:
            result_msg = f"脚本异常: {str(e)}"
            print(result_msg)
            import traceback
            traceback.print_exc()
            try:
                page.screenshot(path="error.png")
            except:
                pass
            body = build_mail_body(False, bj_now(), sign_before, 0, sign_after, result_msg)
            send_email(f"【ChmlFrp签到失败】{bj_now()}", body)

        browser.close()

    if not success:
        sys.exit(1)


def build_mail_body(success, ts, before, reward, after, note=""):
    """
    组装邮件正文。
      success: bool 是否成功
      ts: 北京时间字符串
      before: 签到前信息 dict（points/count）
      reward: 本次获得积分
      after: 签到后信息 dict（points/count）
      note: 附加说明
    """
    b_points = before.get("points") if before else None
    b_count = before.get("count") if before else None
    a_points = after.get("points") if after else None
    a_count = after.get("count") if after else None

    status = "成功" if success else "失败"
    lines = []
    lines.append("=" * 30)
    lines.append(f"ChmlFrp 每日自动签到")
    lines.append("=" * 30)
    lines.append(f"签到状态：{status}")
    lines.append(f"签到时间：{ts}")
    lines.append(f"签到前总积分：{b_points if b_points is not None else '--'}")
    lines.append(f"本次签到获得：{reward} 积分")
    lines.append(f"累计签到次数：{a_count if a_count is not None else (b_count if b_count is not None else '--')} 次")
    lines.append(f"签到后总积分：{a_points if a_points is not None else '--'}")
    if note:
        lines.append(f"备注：{note}")
    lines.append("")
    lines.append("(积分数据以面板'签到信息'统计为准)")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
