import os
import json
import requests
from fastapi import FastAPI, Request
from google import genai
from google.genai import types

app = FastAPI()

# ================== কনফিগারেশন ==================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = "8922611949:AAEhdH9PmWGKz2U1JVk4g3zmH5fAQZa6UOQ"
TELEGRAM_CHAT_ID = "1310445351"
META_VERIFY_TOKEN = "TASTY_MUSHROOM_SECRET_TOKEN"

# Gemini ক্লায়েন্ট
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

SYSTEM_INSTRUCTION = """
তুমি 'Tasty Mushroom'-এর প্রফেশনাল ও আন্তরিক কাস্টমার সার্ভিস অ্যাসিস্ট্যান্ট।
লোকেশন: ০৪ নং ওয়ার্ড, আগারের পার, কুকরুল, রংপুর সিটি কর্পোরেশন, রংপুর।

তোমার দায়িত্ব:
১. কাস্টমারকে মাশরুমের পুষ্টিগুণ, স্বাস্থ্যগত উপকারিতা ও সহজে রান্নার নিয়ম বুঝিয়ে বলা।
২. প্রোডাক্ট ও রেট ক্যাটালগ:
   - Fresh Mushroom (তাজা মাশরুম): ৪০০ টাকা/কেজি (৫০০ গ্রাম = ২০০ টাকা)
   - Dry Mushroom (শুকনা মাশরুম): ২০০০ টাকা/কেজি
   - Mushroom Chips (মাশরুম চিপস): ২৫ টাকা/পিস (বা প্যাকেটভেদে ১০০ টাকা)
   - Mushroom Powder (মাশরুম পাউডার): ২০০০ টাকা/কেজি
   - Spawn (স্পন/বীজ): ৩০ টাকা/পিস
   - Mother Spawn: ৪০ টাকা/পিস
   - Mushroom Fry, Nimki, Pickle, Soup Mix
৩. ডেলিভারি চার্জ: রংপুর সিটির ভেতরে ৩০-৬০ টাকা, বাইরের জন্য কুরিয়ার প্রযোজ্য।
৪. কাস্টমার অর্ডার ফাইনাল করতে চাইলে ৪টি তথ্য নিশ্চিত করবে:
   - নাম
   - মোবাইল নম্বর
   - পূর্ণাঙ্গ ঠিকানা
   - পণ্যের নাম ও পরিমাণ
৫. অর্ডার নিশ্চিত হলে উত্তরের একদম শেষে এই স্পেশাল ট্যাগটি যুক্ত করবে:
   :::ORDER_CONFIRMED:::{"name": "...", "mobile": "...", "address": "...", "product": "...", "amount": "...", "note": "..."}:::END:::
"""

def send_telegram_alert(order_data: dict):
    """অর্ডার কনফার্ম হলে আপনার টেলিগ্রামে অ্যালার্ট পাঠায়"""
    message = (
        "🚨 *নতুন অর্ডার প্রাপ্তি! (Tasty Mushroom)*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *নাম:* {order_data.get('name', 'N/A')}\n"
        f"📞 *মোবাইল:* {order_data.get('mobile', 'N/A')}\n"
        f"📍 *ঠিকানা:* {order_data.get('address', 'N/A')}\n"
        f"🛒 *পণ্য ও পরিমাণ:* {order_data.get('product', 'N/A')}\n"
        f"💰 *মূল্য/নোট:* {order_data.get('amount', 'N/A')} | {order_data.get('note', '')}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📲 *আপনার সিস্টেমে এন্ট্রি দিন: ?page=order*"
    )
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Alert Error: {e}")

@app.get("/")
async def root():
    return {"status": "Tasty Mushroom Bot is Running Live!"}

@app.get("/webhook")
async def verify_webhook(request: Request):
    """Meta Webhook ভেরিফিকেশন"""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    
    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        return int(challenge)
    return {"error": "Invalid verification token"}

@app.post("/webhook")
async def handle_message(request: Request):
    """মেসেজ হ্যান্ডলার"""
    data = await request.json()
    try:
        # মেসেজ প্রসেসিং
        user_message = data.get("message", "হ্যালো")
        
        if client:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_message,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.7
                )
            )
            reply_text = response.text
        else:
            reply_text = "API Key সংযুক্ত করা হয়নি।"
        
        if ":::ORDER_CONFIRMED:::" in reply_text:
            parts = reply_text.split(":::ORDER_CONFIRMED:::")
            clean_reply = parts[0]
            json_part = parts[1].split(":::END:::")[0]
            order_data = json.loads(json_part)
            
            send_telegram_alert(order_data)
            reply_text = clean_reply
            
        return {"status": "success", "reply": reply_text}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
