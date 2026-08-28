import os
import json
import time
import requests
from fastapi import FastAPI, Request
from google import genai
from google.genai import types

app = FastAPI()

# ================== কনফিগারেশন ==================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", "")
TELEGRAM_BOT_TOKEN = "8922611949:AAEhdH9PmWGKz2U1JVk4g3zmH5fAQZa6UOQ"
TELEGRAM_CHAT_ID = "1310445351"
META_VERIFY_TOKEN = "TASTY_MUSHROOM_SECRET_TOKEN"

PAUSED_USERS = {}  # { sender_id: paused_until_timestamp }

client = None
if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Gemini Client Init Error: {e}")

SYSTEM_INSTRUCTION = """
তুমি 'Tasty Mushroom'-এর প্রফেশনাল ও আন্তরিক কাস্টমার সার্ভিস অ্যাসিস্ট্যান্ট।
ঠিকানা: ০৪ নং ওয়ার্ড, আগারের পার, কুকরুল, রংপুর সিটি কর্পোরেশন, রংপুর।

মূল দায়িত্ব ও নির্দেশিকা:
১. মাশরুমের স্বাস্থ্যগত উপকারিতা ও সাধারণ রান্নার নিয়ম সংক্ষেপে বুঝিয়ে বলা।
২. প্রোডাক্ট ক্যাটালগ ও মূল্য:
   - Fresh Mushroom (তাজা মাশরুম): ৪০০ টাকা/কেজি (৫০০ গ্রাম = ২০০ টাকা)
   - Dry Mushroom (শুকনা মাশরুম): ২০০০ টাকা/কেজি
   - Mushroom Chips (মাশরুম চিপস): ২৫ টাকা/পিস (বা প্যাকেটভেদে ১০০ টাকা)
   - Mushroom Powder (মাশরুম পাউডার): ২০০০ টাকা/কেজি
   - Spawn (বীজ): ৩০ টাকা/পিস
   - Mother Spawn: ৪০ টাকা/পিস
   - Mushroom Fry, Nimki, Pickle, Soup Mix
৩. ডেলিভারি চার্জ: রংপুর সিটির ভেতরে ৩০-৬০ টাকা।
৪. কাস্টমার অর্ডার ফাইনাল করতে চাইলে ৪টি তথ্য নেবে: নাম, মোবাইল নম্বর, ঠিকানা, পণ্যের নাম ও পরিমাণ।
৫. অর্ডার নিশ্চিত হলে উত্তরের একদম শেষে অবশ্যই এই ট্যাগটি যুক্ত করবে:
   :::ORDER_CONFIRMED:::{"name": "...", "mobile": "...", "address": "...", "product": "...", "amount": "...", "note": "..."}:::END:::
"""

def send_telegram_alert(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"Telegram response: {res.status_code}")
    except Exception as e:
        print(f"Telegram Alert Error: {e}")

def send_fb_message(recipient_id: str, message_text: str):
    if not PAGE_ACCESS_TOKEN:
        print("ERROR: PAGE_ACCESS_TOKEN is missing in Render Environment!")
        return
    url = f"https://graph.facebook.com/v20.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text},
        "messaging_type": "RESPONSE"
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"FB Send API Response [{res.status_code}]: {res.text}")
    except Exception as e:
        print(f"FB Message Send Exception: {e}")

@app.get("/")
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
async def handle_meta_webhook(request: Request):
    data = await request.json()
    print(f"Incoming Webhook Event: {json.dumps(data)}")
    
    try:
        if data.get("object") == "page":
            for entry in data.get("entry", []):
                for messaging_event in entry.get("messaging", []):
                    sender_id = messaging_event.get("sender", {}).get("id")
                    
                    # হিউম্যান টেকওভার চেক (পেজ এডমিন নিজে রিপ্লাই দিলে)
                    if messaging_event.get("message", {}).get("is_echo"):
                        recipient_id = messaging_event.get("recipient", {}).get("id")
                        PAUSED_USERS[recipient_id] = time.time() + (12 * 3600)
                        print(f"Admin replied. Bot paused for user {recipient_id}")
                        continue

                    if "message" in messaging_event and "text" in messaging_event["message"]:
                        user_text = messaging_event["message"]["text"].strip()
                        print(f"User ({sender_id}) sent: {user_text}")
                        
                        if user_text.lower() == "#stop":
                            PAUSED_USERS[sender_id] = time.time() + (24 * 3600)
                            send_fb_message(sender_id, "অটো-অ্যাসিস্ট্যান্ট সাময়িকভাবে বন্ধ করা হয়েছে। আমাদের প্রতিনিধি দ্রুত যোগাযোগ করবেন।")
                            continue
                        elif user_text.lower() == "#start":
                            PAUSED_USERS.pop(sender_id, None)
                            send_fb_message(sender_id, "অটো-অ্যাসিস্ট্যান্ট পুনরায় চালু করা হয়েছে।")
                            continue

                        if sender_id in PAUSED_USERS:
                            if time.time() < PAUSED_USERS[sender_id]:
                                print(f"User {sender_id} is currently paused.")
                                continue
                            else:
                                del PAUSED_USERS[sender_id]

                        # AI রেসপন্স জেনারেশন
                        reply_text = ""
                        if client:
                            try:
                                response = client.models.generate_content(
                                    model="gemini-2.5-flash",
                                    contents=user_text,
                                    config=types.GenerateContentConfig(
                                        system_instruction=SYSTEM_INSTRUCTION,
                                        temperature=0.7
                                    )
                                )
                                reply_text = response.text
                            except Exception as ge:
                                print(f"Gemini API Error: {ge}")
                                reply_text = "Tasty Mushroom-এ আপনাকে স্বাগতম! আমাদের প্রোডাক্ট ও সার্ভিসের বিস্তারিত জানতে আপনার প্রশ্নটি লিখুন।"
                        else:
                            reply_text = "Tasty Mushroom-এ স্বাগতম! আমরা তাজা মাশরুম, শুকনা মাশরুম ও মাশরুম চিপস সরবরাহ করি।"

                        # অর্ডার কনফার্মেশন চেক
                        if ":::ORDER_CONFIRMED:::" in reply_text:
                            try:
                                parts = reply_text.split(":::ORDER_CONFIRMED:::")
                                clean_reply = parts[0].strip()
                                json_part = parts[1].split(":::END:::")[0].strip()
                                order_data = json.loads(json_part)
                                
                                alert_msg = (
                                    "🚨 *নতুন অর্ডার প্রাপ্তি! (Tasty Mushroom)*\n"
                                    "━━━━━━━━━━━━━━━━━━━━\n"
                                    f"👤 *নাম:* {order_data.get('name', 'N/A')}\n"
                                    f"📞 *মোবাইল:* {order_data.get('mobile', 'N/A')}\n"
                                    f"📍 *ঠিকানা:* {order_data.get('address', 'N/A')}\n"
                                    f"🛒 *পণ্য ও পরিমাণ:* {order_data.get('product', 'N/A')}\n"
                                    f"💰 *মূল্য/নোট:* {order_data.get('amount', 'N/A')} | {order_data.get('note', '')}\n"
                                    "━━━━━━━━━━━━━━━━━━━━"
                                )
                                send_telegram_alert(alert_msg)
                                reply_text = clean_reply
                            except Exception as oe:
                                print(f"Order Parse Error: {oe}")

                        # ফেসবুকে মেসেজ পাঠানো
                        send_fb_message(sender_id, reply_text)

        return {"status": "EVENT_RECEIVED"}
    except Exception as e:
        print(f"Webhook processing error: {e}")
        return {"status": "ERROR"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
