import os, json, time, base64, requests, sys
import pyotp
from playwright.sync_api import sync_playwright

USERNAME = os.environ.get("CHML_USERNAME", "")
PASSWORD = os.environ.get("CHML_PASSWORD", "")
PANEL_URL = os.environ.get("CHML_URL", "https://panel.chmlfrp.net/home")
TOTP_SECRET = os.environ.get("TOTP_SECRET", "")
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
    """处理 MFA 二次验证：自动生成 TOTP 验证码并填入"""
    if "/mfa" not in page.url:
        print("未检测到 MFA 页面，跳过")
        return True

    if not TOTP_SECRET:
        print("未配置 TOTP_SECRET，无法处理 MFA")
        return False

    print("检测到 MFA 页面，开始处理 TOTP 验证")
    time.sleep(3)
    page.screenshot(path="mfa_page.png")

    # 打印页面元素，方便调试
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
                print(f"  button[{i}]: text='{txt}'")
        except:
            pass

    # 如果有"验证器/TOTP/Authenticator"选项，先点击切换
    for text in ["验证器", "TOTP", "Authenticator", "身份验证器", "动态验证码"]:
        try:
            el = page.get_by_text(text, exact=False)
            if el.count() > 0 and el.first.is_visible():
                el.first.click()
                print(f"点击了'{text}'选项")
                time.sleep(2)
                break
        except:
            continue

    # 生成 TOTP 验证码（重试3次，防止刚好跨30秒边界）
    totp = pyotp.TOTP(TOTP_SECRET)
    code = None
    for attempt in range(3):
        code = totp.now()
        print(f"生成 TOTP 验证码: {code} (尝试{attempt+1})")
        # 验证一下还有效
        if totp.verify(code, valid_window=1):
            break
        time.sleep(1)

    if not code:
        print("TOTP 验证码生成失败")
        return False

    # 填入验证码：尝试多种输入框结构
    filled = False

    # 方式1：6个单独的输入框（常见于 MFA 页面）
    digit_inputs = []
    for i in range(all_inputs.count()):
        try:
            inp = all_inputs.nth(i)
            itype = (inp.get_attribute("type") or "text").lower()
            if itype in ["text", "tel", "number"] and inp.is_visible():
                # 排除隐藏的 csrf 等
                iname = (inp.get_attribute("name") or "").lower()
                if "csrf" not in iname and "continue" not in iname and "finger" not in iname:
                    digit_inputs.append(inp)
        except:
            pass

    print(f"找到 {len(digit_inputs)} 个可见数字输入框")

    if len(digit_inputs) >= 6:
        # 6个单独框，逐个输入
        print("使用6框模式输入")
        for i, ch in enumerate(code[:6]):
            try:
                digit_inputs[i].click()
                time.sleep(0.1)
                digit_inputs[i].type(ch, delay=30)
            except Exception as e:
                print(f"输入第{i+1}位失败: {e}")
        filled = True
    elif len(digit_inputs) == 1:
        # 一个输入框，输入完整6位
        print("使用单框模式输入")
        digit_inputs[0].click()
        time.sleep(0.1)
        digit_inputs[0].type(code, delay=50)
        filled = True
    else:
        # 兜底：找第一个可见 input，逐字输入（页面可能自动跳框）
        print("兜底模式：在第一个可见输入框输入完整验证码")
        for inp in digit_inputs:
            try:
                inp.click()
                time.sleep(0.1)
                inp.type(code, delay=50)
                filled = True
                break
            except:
                continue

    if not filled:
        print("无法填入验证码")
        page.screenshot(path="mfa_fill_fail.png")
        return False

    time.sleep(1)
    page.screenshot(path="mfa_filled.png")

    # 点击确认/提交按钮
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
        # 兜底：按回车
        print("未找到确认按钮，按回车")
        page.keyboard.press("Enter")

    time.sleep(5)
    page.screenshot(path="mfa_after_submit.png")
    print(f"MFA提交后URL: {page.url}")

    # 检查是否通过
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
            # 1. 打开面板，自动跳转 OAuth2 登录页
            print(f"打开面板: {PANEL_URL}")
            page.goto(PANEL_URL, timeout=30000, wait_until="domcontentloaded")
            for i in range(12):
                if "qzhua" in page.url or "login" in page.url:
                    break
                time.sleep(1)
            time.sleep(4)
            page.screenshot(path="step1_login.png")
            print(f"登录页URL: {page.url}")

            # 打印input信息
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

            # 2. 定位用户名密码框
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

            # 3. 输入用户名密码
            print("输入用户名...")
            username_input.click()
            time.sleep(0.3)
            username_input.type(USERNAME, delay=50)
            time.sleep(0.5)
            uname_val = username_input.input_value()
            print(f"用户名框当前值: '{uname_val}'")
            if uname_val != USERNAME:
                print("用户名填充不一致，尝试fill...")
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

            # 4. 点击登录按钮
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

            # 5. 处理登录时的极验验证码
            try:
                if page.locator(".geetest_wrap").is_visible():
                    print("登录需要极验验证码")
                    solve_geetest(page)
                    time.sleep(3)
                    page.screenshot(path="step2b_after_captcha.png")
            except Exception as e:
                print(f"检查验证码异常: {e}")

            # 5.5 处理 MFA 二次验证（新增）
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
                result_msg = "登录失败，仍在认证页面（账号密码错误/MFA失败/页面报错）"
                page.screenshot(path="error_login_fail.png")
                print(result_msg)
                send_email("ChmlFrp签到失败", result_msg)
                browser.close()
                sys.exit(1)

            # 7. 找签到按钮
            print("寻找签到按钮...")
            sign_clicked = False
            for text in ["每日签到", "立即签到", "去签到", "签到领", "签到"]:
                try:
                    btn = page.get_by_text(text, exact=False)
                    if btn.count() > 0:
                        for i in range(btn.count()):
                            if btn.nth(i).is_visible():
                                btn.nth(i).click()
                                print(f"点击了'{text}'")
                                sign_clicked = True
                                break
                        if sign_clicked:
                            break
                except:
                    continue

            if not sign_clicked:
                try:
                    btns = page.locator("button, a, [role='button']")
                    for i in range(btns.count()):
                        try:
                            txt = btns.nth(i).inner_text(timeout=500)
                            if "签" in txt:
                                btns.nth(i).click()
                                print(f"兜底点击签到: {txt}")
                                sign_clicked = True
                                break
                        except:
                            continue
                except Exception as e:
                    print(f"兜底查找异常: {e}")

            if not sign_clicked:
                result_msg = "未找到签到按钮"
                page.screenshot(path="error_no_sign.png")
                send_email("ChmlFrp签到失败", result_msg)
                browser.close()
                sys.exit(1)

            time.sleep(3)
            page.screenshot(path="step4_after_sign.png")

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
