import os, json, time, base64, requests
from playwright.sync_api import sync_playwright

# ========== 配置（从 GitHub Secrets 读取） ==========
USERNAME = os.environ.get("CHML_USERNAME", "")
PASSWORD = os.environ.get("CHML_PASSWORD", "")
DASHBOARD_URL = os.environ.get("CHML_URL", "https://www.chmlfrp.net/")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "qwen-vl-plus")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_TO = os.environ.get("SMTP_TO", "")

def ai_analyze_image(image_b64, prompt):
    """调用通义千问视觉模型分析图片，返回JSON指令"""
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": AI_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
            ]
        }],
        "temperature": 0.1
    }
    try:
        r = requests.post(f"{AI_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=60)
        result = r.json()
        text = result["choices"][0]["message"]["content"]
        # 提取JSON
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except Exception as e:
        print(f"AI调用失败: {e}")
    return None

def send_email(subject, body):
    """发送邮件通知"""
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, SMTP_TO]):
        print("邮件未配置，跳过通知")
        return
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = SMTP_TO
    try:
        server = smtplib.SMTP_SSL(SMTP_HOST, 465)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, SMTP_TO, msg.as_string())
        server.quit()
        print("邮件通知已发送")
    except Exception as e:
        print(f"邮件发送失败: {e}")

def solve_geetest(page):
    """处理极验4代验证码，最多重试3次"""
    for attempt in range(3):
        print(f"极验验证尝试 {attempt+1}/3")
        time.sleep(2)
        
        # 检查是否已经验证通过（签到成功弹窗或验证码消失）
        try:
            page.wait_for_selector(".geetest_wrap", timeout=3000)
        except:
            print("验证码已消失，可能已通过")
            return True
        
        # 截取验证码区域
        try:
            captcha = page.locator(".geetest_wrap")
            if not captcha.is_visible():
                print("验证码不可见")
                time.sleep(1)
                continue
            screenshot_bytes = captcha.screenshot()
            img_b64 = base64.b64encode(screenshot_bytes).decode()
        except Exception as e:
            print(f"截图失败: {e}")
            time.sleep(1)
            continue
        
        # AI分析验证码
        prompt = """你是一个验证码识别专家。请分析这张极验验证码截图，判断验证码类型并给出操作指令。

常见类型：
1. slider（滑块拼图）：需要拖动滑块到缺口位置
2. click（文字点选）：需要按顺序点击图中的文字
3. icon（图标点选）：需要按顺序点击相同的图标
4. space（仅需点击按钮）：直接点击验证按钮

请严格返回以下JSON格式（不要返回其他内容）：
{
  "type": "slider或click或icon或space",
  "slider_target_x": 数字,  // 仅slider：缺口在截图中的x坐标（像素）
  "slider_start_x": 数字,   // 仅slider：滑块起始x坐标
  "click_points": [[x1,y1],[x2,y2]],  // 仅click/icon：需要点击的坐标列表（按顺序）
  "confidence": 0.0到1.0    // 你对判断的置信度
}

坐标以截图左上角为原点，单位为像素。请仔细观察图片后给出精确坐标。"""
        
        result = ai_analyze_image(img_b64, prompt)
        if not result:
            print("AI分析失败，重试")
            time.sleep(2)
            continue
        
        print(f"AI判断: type={result.get('type')}, confidence={result.get('confidence')}")
        
        try:
            if result["type"] == "space":
                # 直接点击验证按钮
                btn = page.locator(".geetest_btn")
                if btn.is_visible():
                    btn.click()
                    time.sleep(2)
                    
            elif result["type"] == "slider":
                # 滑块拖动
                slider = page.locator(".geetest_slider_button")
                if slider.is_visible():
                    box = slider.bounding_box()
                    start_x = box["x"] + box["width"] / 2
                    start_y = box["y"] + box["height"] / 2
                    # 计算目标距离（AI给的是截图内坐标，需要换算）
                    captcha_box = page.locator(".geetest_wrap").bounding_box()
                    target_x = captcha_box["x"] + result["slider_target_x"]
                    distance = target_x - start_x
                    
                    # 模拟人类拖动轨迹（先快后慢，带抖动）
                    steps = 30
                    for i in range(steps):
                        progress = (i + 1) / steps
                        # 缓动函数：先快后慢
                        ease = 1 - (1 - progress) ** 3
                        current_x = start_x + distance * ease
                        # 加微小Y抖动
                        current_y = start_y + (0.5 - (i % 3) * 0.3) * 2
                        if i == 0:
                            page.mouse.move(start_x, start_y)
                            page.mouse.down()
                        page.mouse.move(current_x, current_y)
                        time.sleep(0.02 + (i / steps) * 0.03)
                    page.mouse.up()
                    time.sleep(3)
                    
            elif result["type"] in ["click", "icon"]:
                # 文字/图标点选
                captcha_box = page.locator(".geetest_wrap").bounding_box()
                points = result.get("click_points", [])
                for i, (px, py) in enumerate(points):
                    abs_x = captcha_box["x"] + px
                    abs_y = captcha_box["y"] + py
                    page.mouse.click(abs_x, abs_y)
                    time.sleep(0.5)
                # 点击确认按钮（如果有）
                confirm = page.locator(".geetest_commit")
                if confirm.is_visible():
                    confirm.click()
                time.sleep(3)
                
        except Exception as e:
            print(f"执行操作失败: {e}")
            time.sleep(2)
            continue
        
        # 检查验证结果
        time.sleep(2)
        try:
            page.wait_for_selector(".geetest_wrap", timeout=2000)
            # 验证码还在，可能失败了，点刷新重试
            refresh = page.locator(".geetest_refresh")
            if refresh.is_visible():
                refresh.click()
            time.sleep(1)
        except:
            print("极验验证通过！")
            return True
    
    print("极验验证3次均失败")
    return False

def main():
    result_msg = ""
    success = False
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage"
        ])
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="zh-CN"
        )
        # 隐藏webdriver特征
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en']});
            window.chrome = {runtime: {}};
        """)
        
        page = context.new_page()
        
        try:
            # 1. 打开官网
            print(f"打开 {DASHBOARD_URL}")
            page.goto(DASHBOARD_URL, timeout=30000)
            time.sleep(3)
            
            # 2. 点击"管理面板"进入登录页
            try:
                panel_btn = page.get_by_text("管理面板", exact=False)
                if panel_btn.is_visible():
                    panel_btn.first.click()
                    time.sleep(3)
                    page.wait_for_load_state("networkidle", timeout=10000)
            except:
                print("未找到管理面板按钮，尝试直接在当前页登录")
            
            # 3. 输入用户名密码登录
            print("输入登录信息")
            # 尝试多种选择器
            username_input = page.locator("input[type='text'], input[name='username'], input[placeholder*='用户'], input[placeholder*='账号']").first
            password_input = page.locator("input[type='password'], input[name='password'], input[placeholder*='密码']").first
            
            username_input.fill(USERNAME)
            time.sleep(0.5)
            password_input.fill(PASSWORD)
            time.sleep(0.5)
            
            # 点击登录按钮
            login_btn = page.locator("button:has-text('登录'), button:has-text('登 录'), .login-btn, [type='submit']").first
            login_btn.click()
            print("点击登录")
            time.sleep(5)
            
            # 4. 处理登录时的极验验证码
            try:
                if page.locator(".geetest_wrap").is_visible():
                    print("登录需要验证码，处理中...")
                    solve_geetest(page)
                    time.sleep(3)
            except:
                pass
            
            # 5. 等待登录成功（URL变化或出现用户信息）
            page.wait_for_load_state("networkidle", timeout=15000)
            time.sleep(3)
            print(f"当前URL: {page.url}")
            
            # 6. 寻找签到按钮并点击
            print("寻找签到按钮...")
            sign_clicked = False
            
            # 尝试多种签到按钮文本
            for text in ["每日签到", "签到", "立即签到", "去签到"]:
                try:
                    btn = page.get_by_text(text, exact=False)
                    if btn.is_visible() and btn.count() > 0:
                        btn.first.click()
                        print(f"点击了'{text}'按钮")
                        sign_clicked = True
                        break
                except:
                    continue
            
            if not sign_clicked:
                # 尝试找包含"签"字的可点击元素
                try:
                    btns = page.locator("button, a, .btn, [class*='sign'], [class*='check']")
                    count = btns.count()
                    for i in range(count):
                        txt = btns.nth(i).inner_text()
                        if "签" in txt:
                            btns.nth(i).click()
                            print(f"点击了签到相关按钮: {txt}")
                            sign_clicked = True
                            break
                except Exception as e:
                    print(f"查找签到按钮异常: {e}")
            
            if not sign_clicked:
                result_msg = "未找到签到按钮，可能页面结构已变更"
                page.screenshot(path="error.png")
                send_email("ChmlFrp签到失败", result_msg)
                browser.close()
                return
            
            time.sleep(3)
            
            # 7. 处理签到时的极验验证码
            try:
                if page.locator(".geetest_wrap").is_visible():
                    print("签到需要极验验证，处理中...")
                    geetest_ok = solve_geetest(page)
                    if not geetest_ok:
                        result_msg = "极验验证失败，签到未完成"
                        page.screenshot(path="geetest_fail.png")
                        send_email("ChmlFrp签到失败", result_msg)
                        browser.close()
                        return
            except:
                print("未检测到极验验证码，可能直接签到成功")
            
            time.sleep(3)
            
            # 8. 确认签到结果
            page.screenshot(path="result.png")
            result_text = page.inner_text("body")
            
            if any(k in result_text for k in ["签到成功", "已签到", "签到完成", "获得积分", "积分+"]):
                success = True
                result_msg = "签到成功！"
                print(result_msg)
            elif "今日已签" in result_text or "已经签到" in result_text:
                success = True
                result_msg = "今日已签到"
                print(result_msg)
            else:
                result_msg = "签到结果不确定，请查看截图"
                print(result_msg)
            
        except Exception as e:
            result_msg = f"脚本异常: {str(e)}"
            print(result_msg)
            try:
                page.screenshot(path="error.png")
            except:
                pass
        
        browser.close()
    
    # 邮件通知
    status = "成功" if success else "失败"
    send_email(f"ChmlFrp每日签到 - {status}", result_msg)
    
    if not success:
        exit(1)

if __name__ == "__main__":
    main()
