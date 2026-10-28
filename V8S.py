import time
import logging
from openai import OpenAI
from playwright.sync_api import sync_playwright

try:
    from best_price_mcp import compare_price
except ImportError:
    print("❌ 缺少依赖库，请先运行: pip install best-price-mcp")
    exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# ==================== 配置区 ====================
DEEPSEEK_API_KEY = "sk-你的DeepSeek密钥"  # 你的 DeepSeek API Key
USER_DATA_DIR = "./steam_browser_profile"
CHECK_INTERVAL = 3
MIN_REPLY_GAP = 4
# ================================================

print("🤖 正在初始化 DeepSeek 客户端...")
ai_client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

# 增加 active 状态，默认 True (开启)
bot_state = {
    "model": "deepseek-chat",
    "active": True  
}

def search_product_price(query):
    print(f"🔍 正在电商平台比价: {query} ...")
    try:
        result = compare_price(query=query)
        if result:
            print("✅ 比价成功！")
            return str(result)
        else:
            print("⚠️ 比价库未返回有效结果。")
            return ""
    except Exception as e:
        print(f"⚠️ 比价失败: {e}")
        return ""

def get_latest_chat_messages(page):
    return page.evaluate("""() => {
        const msgNodes = document.querySelectorAll(
            '.msgText, div[class*="chat_message_text"], div[class*="msgText"]'
        );
        let texts = [];
        msgNodes.forEach(node => {
            const txt = node.innerText ? node.innerText.trim() : "";
            if (txt && txt.length > 0) texts.push(txt);
        });
        return texts.slice(-15);
    }""")

def find_chat_textarea(page):
    selectors = ["textarea.FcUxYTJ41iw-", "form textarea", "textarea[class*='chatTextarea']", "textarea[placeholder]", "textarea"]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible(): return el
        except Exception: continue
    return None

def send_message(page, text):
    textarea = find_chat_textarea(page)
    if not textarea: return False
    try:
        textarea.click()
        textarea.fill(text)
        time.sleep(0.3)
        page.keyboard.press("Enter")
        time.sleep(0.3)
        return True
    except Exception as e:
        print(f"⚠️ 发送失败: {e}")
        return False

def generate_and_send_reply(page, msg_text, processed_messages):
    print(f"\n📩 [处理消息]: {msg_text}")

    # ==================== 核心修改：开关机与指令拦截 ====================
    
    # 1. 唤醒指令 (无论当前是啥状态，只要看到就唤醒)
    if any(kw in msg_text for kw in ["启动大肥鱼", "唤醒大肥鱼", "开启大肥鱼"]):
        bot_state["active"] = True
        reply_text = "大肥鱼已上浮！🐟 有什么要整的，尽管问！"
        print("🔄 状态: 已启动 (Active=True)")
        if send_message(page, reply_text):
            processed_messages.add(reply_text)
            print("✅ [发送成功]")
        return True

    # 2. 休眠指令
    if any(kw in msg_text for kw in ["关闭大肥鱼", "大肥鱼闭嘴", "休眠大肥鱼"]):
        bot_state["active"] = False
        reply_text = "收到，大肥鱼先潜回水底了... 🤫 有事发'启动大肥鱼'叫我。"
        print("🔄 状态: 已休眠 (Active=False)")
        if send_message(page, reply_text):
            processed_messages.add(reply_text)
            print("✅ [发送成功]")
        return True

    # 3. 如果机器人处于休眠状态，直接忽略后续所有消息，不再往下执行
    if not bot_state["active"]:
        # 这里不需要打印太多信息防止控制台刷屏，静默跳过即可
        return False

    # 4. 模型切换指令
    if any(kw in msg_text for kw in ["切换深度思考", "用R1", "使用推理"]):
        bot_state["model"] = "deepseek-reasoner"
        reply_text = "收到！已切换至深度思考模型 (R1)，现在回话可能会慢一点，让我先想想..."
        print(f"🔄 模型已切换为: {bot_state['model']}")
        if send_message(page, reply_text):
            processed_messages.add(reply_text)
            print("✅ [发送成功]")
        return True

    elif any(kw in msg_text for kw in ["切换闲聊模式", "切换普通模式", "用V3", "使用快速"]):
        bot_state["model"] = "deepseek-chat"
        reply_text = "收到！已切回闲聊模式 (V3)，继续嗨！"
        print(f"🔄 模型已切换为: {bot_state['model']}")
        if send_message(page, reply_text):
            processed_messages.add(reply_text)
            print("✅ [发送成功]")
        return True
    # ================================================================

    # 只有活着且没触发指令，才继续往下走正常的回复逻辑
    system_prompt = (
        "你是一个活跃在 Steam 游戏群里的 AI 群友，名字叫 Deepseek_大肥鱼。\n"
        "如果群友是在闲聊，请用简短、幽默、口语化的一句话吐槽，不超过30个字。"
    )

    search_keywords = ["价格", "多少钱", "参数", "配置", "发售", "报价", "怎么样"]
    if any(kw in msg_text for kw in search_keywords):
        price_data = search_product_price(msg_text)
        if price_data:
            system_prompt += (
                f"\n\n【实时电商比价数据】：\n{price_data}\n"
                "请根据上述比价数据，准确报出价格（特别是到手价），并附带一句幽默、调侃的吐槽。"
            )
        else:
            print("⚠️ 未获取到有效比价数据，AI 将凭自身知识库回答。")

    try:
        print(f"🧠 正在使用模型 [{bot_state['model']}] 生成回复...")
        response = ai_client.chat.completions.create(
            model=bot_state["model"],  
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f'群友说："{msg_text}"。请回复：'},
            ],
            max_tokens=800, 
            temperature=0.8,
        )
        reply_text = response.choices[0].message.content.strip()
    except Exception as ai_err:
        err_msg = str(ai_err)
        if "Insufficient Balance" in err_msg or "402" in err_msg:
            print("\n⚠️ 余额不足！暂停 30 秒...")
            time.sleep(30)
        else:
            print(f"❌ 调用失败: {err_msg}")
            time.sleep(10)
        return False

    print(f"🤖 [AI 回复]: {reply_text}")

    if send_message(page, reply_text):
        processed_messages.add(reply_text)
        print("✅ [发送成功]")
        return True
    return False

def run_persistent_bot():
    print("\n🚀 正在启动自动化浏览器...")
    with sync_playwright() as p:
        browser_context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            viewport={"width": 1280, "height": 800},
        )

        page = browser_context.new_page()
        page.goto("https://steamcommunity.com/chat/")

        time.sleep(3)
        while "login" in page.url:
            print("⏳ 等待你在浏览器中完成 Steam 登录...")
            time.sleep(3)

        print("🟢 浏览器已就绪！")
        
        print("\n⏳ 正在等待页面完全加载 (强制静默 10 秒)...")
        time.sleep(10)
        
        processed_messages = set()
        current_msgs = get_latest_chat_messages(page)
        for m in current_msgs:
            processed_messages.add(m)

        print(f"🔇 已彻底忽略加载出的 {len(processed_messages)} 条历史消息。")
        print("\n" + "="*40)
        print("🎧 正式开始监听新消息...")
        print(f"👉 当前使用模型: {bot_state['model']} | 状态: 活跃")
        print("💡 提示:")
        print("   - 发 '关闭大肥鱼' 可让其休眠闭嘴")
        print("   - 发 '启动大肥鱼' 可将其唤醒")
        print("   - 发 '切换深度思考' 或 '切换闲聊模式' 可切换模型")
        print("="*40 + "\n")
        
        last_reply_time = time.time()

        while True:
            try:
                if time.time() - last_reply_time < MIN_REPLY_GAP:
                    time.sleep(2)
                    continue

                current_msgs = get_latest_chat_messages(page)

                for msg_text in current_msgs:
                    if msg_text in processed_messages:
                        continue

                    processed_messages.add(msg_text)
                    success = generate_and_send_reply(page, msg_text, processed_messages)
                    
                    # 只有在真实发送了消息（不论是回复还是开机提示），才刷新冷却时间
                    if success:
                        last_reply_time = time.time()
                        break

                time.sleep(CHECK_INTERVAL)

            except KeyboardInterrupt:
                print("\n🛑 停止运行。")
                break
            except Exception as e:
                time.sleep(2)

        browser_context.close()

if __name__ == "__main__":
    run_persistent_bot()
