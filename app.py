import os
import json
import time
from datetime import datetime, timedelta, timezone
import requests
from fastapi import FastAPI, Request, BackgroundTasks
from google import genai
from google.genai import types

app = FastAPI()

# ================== কনফিগারেশন ==================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", "")
TELEGRAM_BOT_TOKEN = "8922611949:AAEhdH9PmWGKz2U1JVk4g3zmH5fAQZa6UOQ"
TELEGRAM_CHAT_ID = "1310445351"
META_VERIFY_TOKEN = "TASTY_MUSHROOM_SECRET_TOKEN"

# ডাটা ট্র্যাকিং
PROCESSED_MESSAGE_IDS = set()  # ডুপ্লিকেট মেসেজ রোধ করতে
PAUSED_USERS = {}              # { sender_id: paused_until_timestamp }
CONVERSATION_HISTORY = {}      # { sender_id: "হিস্ট্রি টেক্সট" }
DAILY_CUSTOMERS = {}           # { "YYYY-MM-DD": { sender_id: time } }

# বাংলাদেশ টাইমজোন (UTC+6)
BD_TZ = timezone(timedelta(hours=6))

client = None
if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Gemini Client Init Error: {e}")

SYSTEM_INSTRUCTION = """
তুমি 'Tasty Mushroom'-এর প্রফেশনাল ও আন্তরিক কাস্টমার সার্ভিস অ্যাসিস্ট্যান্ট।
ঠিকানা: ০৪ নং ওয়ার্ড, আগারের পার, কুকরুল, রংপুর সিটি কর্পোরেশন, রংপুর।

প্রোডাক্ট ও দাম:
- Fresh Mushroom (তাজা মাশরুম): ৪০০ টাকা/কেজি (৫০০ গ্রাম = ২০০ টাকা)
- Dry Mushroom (শুকনা মাশরুম): ২০০০ টাকা/কেজি
- Mushroom Chips (মাশরুম চিপস): ২৫ টাকা/পিস (বা প্যাকেটভেদে ১০০ টাকা)
- Mushroom Powder (মাশরুম পাউডার): ২০০০ টাকা/কেজি
- Spawn (বীজ): ৩০ টাকা/পিস, Mother Spawn: ৪০ টাকা/পিস
- ডেলিভারি চার্জ: রংপুর সিটির ভেতরে ৩০-৬০ টাকা।

অর্ডার নেওয়ার নিয়ম:
কাস্টমারের নাম, মোবাইল নম্বর, ঠিকানা এবং পণ্যের নাম ও পরিমাণ নিশ্চিত হলে সরাসরি অর্ডারটি কনফার্ম করবে এবং ধন্যবাদ জানাবে।
এবং উত্তরের একদম শেষে অবশ্যই নিচের ট্যাগটি নিখুঁতভাবে যুক্ত করবে:
:::ORDER_CONFIRMED:::{"name": "...", "mobile": "...", "address": "...", "product": "...", "amount": "...", "note": "..."}:::END:::

হ্যান্ডওভার নিয়ম:
কাস্টমার মানুষের সাথে কথা বলতে চাইলে বা জটিল অভিযোগ করলে বলবে প্রধান প্রতিনিধি যোগাযোগ করছেন এবং শেষে ট্যাগ দেবে:
:::HANDOVER_NEEDED:::{"reason": "কাস্টমার প্রতিনিধির সাথে কথা বলতে চেয়েছেন"}:::END:::
"""

def get_bd_time():
    return datetime.now(BD_TZ)

def send_telegram_alert(html_text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": html_text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Alert Error: {e}")

def send_fb_message(recipient_id: str, message_text: str):
    if not PAGE_ACCESS_TOKEN:
        print("ERROR: PAGE_ACCESS_TOKEN is missing!")
        return
    url = f"https://graph.facebook.com/v20.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text},
        "messaging_type": "RESPONSE"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"FB Message Send Exception: {e}")

def process_customer_message(sender_id: str, user_text: str):
    """ব্যাকগ্রাউন্ডে নিরাপদে মেসেজ প্রসেস করা"""
    now_bd = get_bd_time()
    today_str = now_bd.strftime("%Y-%m-%d")
    current_time_str = now_bd.strftime("%I:%M %p")

    if today_str not in DAILY_CUSTOMERS:
        DAILY_CUSTOMERS[today_str] = {}

    if sender_id not in DAILY_CUSTOMERS[today_str]:
        DAILY_CUSTOMERS[today_str][sender_id] = current_time_str

    # কমান্ড: দৈনিক রিপোর্ট
    if user_text.lower() == "#report":
        count = len(DAILY_CUSTOMERS[today_str])
        report_text = f"📊 <b>Tasty Mushroom ডেইলি রিপোর্ট ({today_str})</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        report_text += f"👥 <b>মোট কাস্টমার:</b> {count} জন\n\n"
        for idx, (cid, ctime) in enumerate(DAILY_CUSTOMERS[today_str].items(), 1):
            report_text += f"{idx}. ID: <code>{cid}</code> — সময়: {ctime}\n"
        send_telegram_alert(report_text)
        send_fb_message(sender_id, f"আজকের মোট কাস্টমার: {count} জন। রিপোর্ট টেলিগ্রামে পাঠানো হয়েছে।")
        return

    # কমান্ড: ম্যানুয়াল কন্ট্রোল
    if user_text.lower() == "#stop":
        PAUSED_USERS[sender_id] = time.time() + (24 * 3600)
        send_fb_message(sender_id, "অটো-অ্যাসিস্ট্যান্ট বন্ধ করা হয়েছে। আমাদের প্রতিনিধি যোগাযোগ করবেন।")
        return
    elif user_text.lower() == "#start":
        PAUSED_USERS.pop(sender_id, None)
        send_fb_message(sender_id, "অটো-অ্যাসিস্ট্যান্ট পুনরায় চালু করা হয়েছে।")
        return

    # পজ স্ট্যাটাস চেক
    if sender_id in PAUSED_USERS and time.time() < PAUSED_USERS[sender_id]:
        return

    prev_context = CONVERSATION_HISTORY.get(sender_id, "")
    prompt_to_send = f"{prev_context}\nCustomer: {user_text}\nAssistant:"

    reply_text = ""
    if client:
        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt_to_send,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.7
                )
            )
            reply_text = response.text
        except Exception as ge:
            print(f"Gemini API Error: {ge}")
            reply_text = "আপনার মেসেজের জন্য ধন্যবাদ! কী পণ্য নিতে চান জানালে এখনই ব্যবস্থা নিচ্ছি।"
    else:
        reply_text = "Tasty Mushroom-এ স্বাগতম!"

    # ১. হিউম্যান টেকওভার অ্যালার্ট
    if ":::HANDOVER_NEEDED:::" in reply_text:
        try:
            parts = reply_text.split(":::HANDOVER_NEEDED:::")
            reply_text = parts[0].strip()
            PAUSED_USERS[sender_id] = time.time() + 1800
            
            alert = (
                "⚠️ <b>হিউম্যান সাপোর্ট অ্যালার্ট!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>কাস্টমার আইডি:</b> <code>{sender_id}</code>\n"
                f"💬 <b>মেসেজ:</b> {user_text}\n"
                f"⏰ <b>সময়:</b> {current_time_str}\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "📌 <i>বট ৩০ মিনিটের জন্য পজ করা হয়েছে।</i>"
            )
            send_telegram_alert(alert)
        except Exception as e:
            print(f"Handover err: {e}")

    # ২. অর্ডার কনফার্মেশন অ্যালার্ট
    if ":::ORDER_CONFIRMED:::" in reply_text:
        try:
            parts = reply_text.split(":::ORDER_CONFIRMED:::")
            clean_reply = parts[0].strip()
            json_part = parts[1].split(":::END:::")[0].strip()
            order_data = json.loads(json_part)

            alert_msg = (
                "🚨 <b>নতুন অর্ডার প্রাপ্তি! (Tasty Mushroom)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>নাম:</b> {order_data.get('name', 'N/A')}\n"
                f"📞 <b>মোবাইল:</b> {order_data.get('mobile', 'N/A')}\n"
                f"📍 <b>ঠিকানা:</b> {order_data.get('address', 'N/A')}\n"
                f"🛒 <b>পণ্য ও পরিমাণ:</b> {order_data.get('product', 'N/A')}\n"
                f"💰 <b>মূল্য/নোট:</b> {order_data.get('amount', 'N/A')} | {order_data.get('note', '')}\n"
                f"⏰ <b>অর্ডারের সময়:</b> {current_time_str}\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )
            send_telegram_alert(alert_msg)
            reply_text = clean_reply
        except Exception as e:
            print(f"Order err: {e}")

    CONVERSATION_HISTORY[sender_id] = f"{prev_context}\nCustomer: {user_text}\nAssistant: {reply_text}"[-1500:]
    send_fb_message(sender_id, reply_text)

@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {"status": "Tasty Mushroom Bot is Running Live!"}

@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        return int(challenge)
    return {"error": "Invalid verification token"}

@app.post("/webhook")
async def handle_meta_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    try:
        if data.get("object") == "page":
            for entry in data.get("entry", []):
                for messaging_event in entry.get("messaging", []):
                    sender_id = messaging_event.get("sender", {}).get("id")

                    if messaging_event.get("message", {}).get("is_echo"):
                        continue

                    if "message" in messaging_event and "text" in messaging_event["message"]:
                        msg_id = messaging_event["message"].get("mid")
                        
                        # ডুপ্লিকেট মেসেজ ফিল্টার (মেটা রিট্রাই করলেও দুইবার চলবে না)
                        if msg_id:
                            if msg_id in PROCESSED_MESSAGE_IDS:
                                continue
                            PROCESSED_MESSAGE_IDS.add(msg_id)
                            if len(PROCESSED_MESSAGE_IDS) > 2000:
                                PROCESSED_MESSAGE_IDS.clear()

                        user_text = messaging_event["message"]["text"].strip()
                        # ব্যাকগ্রাউন্ডে প্রসেস হবে যাতে মেটা টাইমআউট না দেয়
                        background_tasks.add_task(process_customer_message, sender_id, user_text)

        return {"status": "EVENT_RECEIVED"}
    except Exception as e:
        print(f"Webhook processing error: {e}")
        return {"status": "ERROR"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
