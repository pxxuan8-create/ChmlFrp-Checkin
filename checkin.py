import os, json, time, base64, requests, sys, re
import imaplib, email
from email.header import decode_header
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


def ai_analyze_image(image_b64, prompt):
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
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, SMTP_TO]):
        print("邮件未配置，跳过通知")
        return
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, SMTP_USER, SMTP_TO
    try:
        server = smtplib.SMTP_SSL(SMTP_HOST, 465)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, SMTP_TO, msg.as_string())
        server.quit()
        print("邮件通知已发送")
    except Exception as e:
        print(f"邮件发送失败: {e}")


def fetch_email_code():
    """从QQ邮箱读取最新的QZhua/ChmlFrp验证邮件，提取6位验证码"""
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
        latest_ids.reverse()

        import datetime
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
                if (datetime.datetime.now(datetime.timezone.utc) - msg_date).total_seconds() > 600:
                    continue
            except:
                pass

            print(f"找到候选邮件: 主题='{subject}', 发件人='{from_addr}'")

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
        import traceback
        traceback.print_exc()
        return None


def solve_geetest(page):
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
    """处理 MFA 二次验证：邮箱验证码方式"""
    if "/mfa" not in page.url:
        print("未检测到 MFA 页面，跳过")
        return True

    if not EMAIL_ADDRESS or not EMAIL_IMAP_PASSWORD:
        print("未配置邮箱，无法处理 MFA")
        return False

    print("检测到 MFA 页面，使用邮箱验证码方式")
    time.sleep(3)
    page.screenshot(path="mfa_page.png")

    all_inputs = page.locator("input")
    print(f"MFA页面共有 {all_inputs.count()} 个input")
    for i in range(all_inputs.count()):
        try:
            inp = all_inputs.nth(i)
            itype = inp.get_attribute("type") or "text"
            iname = inp.get_attribute("name") or ""
            iplaceholder = inp.get_attribute("placeholder") or ""
            visible = inp.is_visible()
            print(f"  input[{i}]: type={itype}, name={iname}, placeholder={iplaceholder}, visible={visible}")
        except:
            pass

    all_buttons = page.locator("button")
    print(f"MFA页面共有 {all_buttons.count()} 个button")
    for i in range(all_buttons.count()):
        try:
            btn = all_buttons.nth(i)
            if btn.is_visible():
                txt = btn.inner_text(timeout=500)
                print(f"  button[{i}]: text='{txt[:80]}'")
        except:
            pass

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

    if not email_mode:
        print("未找到邮箱验证码选项，尝试直接发送")

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

    if not send_clicked:
        print("未找到发送按钮，可能已自动发送")

    code = None
    for attempt in range(12):
        print(f"等待验证码邮件... ({attempt+1}/12)")
        code = fetch_email_code()
        if code:
            break
        time.sleep(5)

    if not code:
        print("60秒内未收到验证码邮件")
        page.screenshot(path="mfa_no_email.png")
        return False

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
    page.screenshot(path="mfa_filled.png")

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

    time.sleep(5)
    page.screenshot(path="mfa_after_submit.png")
    print(f"MFA提交后URL: {page.url}")

    if "/mfa" in page.url:
        print("MFA 验证后仍在 MFA 页面，可能验证失败")
        return False
    print("MFA 验证通过！")
    return True


def main():
    result_msg, success = "", False
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
            page.screenshot(path="step1_login.png")
            print(f"登录页URL: {page.url}")

            all_inputs = page.locator("input")
            input_count = all_inputs.count()
            print(f"页面共有 {input_count} 个input")
            for i in range(input_count):
                try:
                    inp = all_inputs.nth(i)
                    itype = inp.get_attribute("type") or "text"
                    iname = inp.get_attribute("name") or ""
                    iplaceholder = inp.get_attribute("placeholder") or ""
                    visible = inp.is_visible()
                    print(f"  input[{i}]: type={itype}, name={iname}, placeholder={iplaceholder}, visible={visible}")
                except:
                    pass

            # 2. 定位用户名密码
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
                            print(f"兜底用第一个可见input[{i}]")
                            break
                    except:
                        continue

            if not username_input or not password_input:
                result_msg = "未找到用户名或密码输入框"
                page.screenshot(path="error_no_input.png")
                print(result_msg)
                send_email("ChmlFrp签到失败", result_msg)
                browser.close()
                sys.exit(1)

            # 3. 输入
            print("输入用户名...")
            username_input.click()
            time.sleep(0.3)
            username_input.type(USERNAME, delay=50)
            time.sleep(0.5)
            uname_val = username_input.input_value()
            print(f"用户名框当前值: '{uname_val}'")
            if uname_val != USERNAME:
                username_input.fill(USERNAME)
                time.sleep(0.3)

            print("输入密码...")
            password_input.click()
            time.sleep(0.3)
            password_input.type(PASSWORD, delay=50)
            time.sleep(0.5)
            pwd_val = password_input.input_value()
            print(f"密码框当前值长度: {len(pwd_val)}")
            page.screenshot(path="step1b_filled.png")

            # 4. 点击登录
            time.sleep(0.5)
            login_btn = None
            all_buttons = page.locator("button")
            btn_count = all_buttons.count()
            print(f"页面共有 {btn_count} 个button")
            candidates = []
            for i in range(btn_count):
                try:
                    btn = all_buttons.nth(i)
                    if btn.is_visible():
                        txt = btn.inner_text(timeout=500).strip()
                        txt_nospace = txt.replace(" ", "").replace("\u3000", "")
                        print(f"  button[{i}]: text='{txt}'")
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
                            print(f"兜底用第一个可见button[{i}]")
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
            page.screenshot(path="step2_after_login.png")
            print(f"点击后URL: {page.url}")

            # 5. 极验验证码
            try:
                if page.locator(".geetest_wrap").is_visible():
                    print("登录需要极验验证码")
                    solve_geetest(page)
                    time.sleep(3)
                    page.screenshot(path="step2b_after_captcha.png")
            except Exception as e:
                print(f"检查验证码异常: {e}")

            # 5.5 MFA 邮箱验证码
            if "/mfa" in page.url:
                if not handle_mfa(page):
                    result_msg = "MFA 二次验证失败"
                    page.screenshot(path="error_mfa.png")
                    print(result_msg)
                    send_email("ChmlFrp签到失败", result_msg)
                    browser.close()
                    sys.exit(1)
                time.sleep(3)

            # 6. 等待登录成功跳回面板
            print("等待登录跳转...")
            for i in range(20):
                if "panel.chmlfrp.net" in page.url and "login" not in page.url and "qzhua" not in page.url:
                    break
                time.sleep(1)
            time.sleep(3)
            page.screenshot(path="step3_panel.png")
            print(f"当前URL: {page.url}")

            if "qzhua" in page.url or "login" in page.url or "/mfa" in page.url:
                result_msg = "登录失败，仍在认证页面"
                page.screenshot(path="error_login_fail.png")
                print(result_msg)
                send_email("ChmlFrp签到失败", result_msg)
                browser.close()
                sys.exit(1)

            # 7. 等待面板加载
            print("等待面板加载并寻找签到按钮...")
            sign_clicked = False

            # 7a. 用JS强制移除登录后的公告弹窗/遮罩（Naive UI modal 会拦截点击）
            try:
                removed = page.evaluate("""() => {
                    let n = 0;
                    document.querySelectorAll('.n-modal-mask').forEach(e => { e.remove(); n++; });
                    document.querySelectorAll('.n-modal-container').forEach(e => { e.remove(); n++; });
                    document.querySelectorAll('.n-overlay, .n-drawer-mask').forEach(e => { e.remove(); n++; });
                    return n;
                }""")
                print(f"JS移除弹窗/遮罩: {removed}个")
                time.sleep(1)
            except Exception as e:
                print(f"JS移除弹窗异常: {e}")

            # 轮询等待"签到"按钮出现（面板是SPA，最多等30秒）
            sign_btn = None
            for wait_i in range(15):
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
                    if sign_btn:
                        print(f"找到签到按钮: '{sign_btn.inner_text().strip()}'")
                        break
                except:
                    pass
                time.sleep(2)

            if not sign_btn:
                print("未直接找到签到按钮，枚举页面含'签'的文字：")
                try:
                    body_txt = page.inner_text("body")
                    for line in body_txt.split("\n"):
                        if "签" in line:
                            print(f"  [文本] {line.strip()[:50]}")
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
                send_email("ChmlFrp签到失败", result_msg)
                browser.close()
                sys.exit(1)

            # 7b. 等签到弹窗出现，打印页面文字和所有可见按钮（定位签到动作按钮）
            time.sleep(3)
            print("===== 签到后页面文字(前1200字符) =====")
            try:
                body_txt = page.inner_text("body")
                print(body_txt[:1200])
                print("===== 结束 =====")
            except:
                pass
            try:
                all_btns = page.locator("button")
                print(f"===== 页面可见按钮({all_btns.count()}) =====")
                for i in range(all_btns.count()):
                    try:
                        if all_btns.nth(i).is_visible():
                            t = all_btns.nth(i).inner_text(timeout=300).strip()
                            if t:
                                print(f"  [按钮] '{t[:40]}'")
                    except:
                        pass
            except:
                pass

            # 7c. 点击签到弹窗里的动作按钮（立即签到/领取积分/确认签到）
            for text in ["立即签到", "签到领积分", "领取积分", "确认签到", "签到成功", "签到"]:
                try:
                    btn = page.get_by_text(text, exact=False)
                    if btn.count() > 0:
                        for i in range(btn.count()):
                            try:
                                if btn.nth(i).is_visible():
                                    t = btn.nth(i).inner_text(timeout=300).strip()
                                    btn.nth(i).click(timeout=1500)
                                    print(f"点击了'{t}'")
                                    time.sleep(2)
                                    break
                            except:
                                pass
                        break
                except:
                    continue

            # 8. 处理签到时的极验验证码
            try:
                if page.locator(".geetest_wrap").is_visible():
                    print("签到需要极验验证")
                    if not solve_geetest(page):
                        result_msg = "极验验证失败"
                        page.screenshot(path="geetest_fail.png")
                        send_email("ChmlFrp签到失败", result_msg)
                        browser.close()
                        sys.exit(1)
            except:
                print("未检测到极验验证码")

            time.sleep(3)
            page.screenshot(path="result.png")
            result_text = page.inner_text("body")

            if any(k in result_text for k in ["签到成功","已签到","签到完成","获得积分","积分+"]):
                success, result_msg = True, "签到成功！"
            elif "今日已签" in result_text or "已经签到" in result_text:
                success, result_msg = True, "今日已签到"
            else:
                result_msg = "签到结果不确定，请查看截图"
            print(result_msg)

        except Exception as e:
            result_msg = f"脚本异常: {str(e)}"
            print(result_msg)
            import traceback
            traceback.print_exc()
            try:
                page.screenshot(path="error.png")
            except:
                pass

        browser.close()

    status = "成功" if success else "失败"
    send_email(f"ChmlFrp每日签到 - {status}", result_msg)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
