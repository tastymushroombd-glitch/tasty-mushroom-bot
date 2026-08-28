import os
import json
import time
from datetime import datetime
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

# ডাটা ট্র্যাকিং মেমোরি
PAUSED_USERS = {}        # { sender_id: paused_until_timestamp }
CONVERSATIONS = {}       # { sender_id: [ {"role": "user"/"model", "text": "..."} ] }
DAILY_CUSTOMERS = {}     # { "YYYY-MM-DD": { sender_id: "First message time" } }

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

মূল নির্দেশনাবলী:
১. কাস্টমারের নাম, মোবাইল নম্বর, ঠিকানা এবং পণ্যের পরিমাণ—এই ৪টি তথ্য নিশ্চিত হলে অর্ডার কনফার্ম করে ধন্যবাদ জানাবে।
   এবং উত্তরের একদম শেষে অবশ্যই এই ট্যাগটি যুক্ত করবে:
   :::ORDER_CONFIRMED:::{"name": "...", "mobile": "...", "address": "...", "product": "...", "amount": "...", "note": "..."}:::END:::

২. কাস্টমার যদি মানুষের সাথে কথা বলতে চায় (যেমন: "মানুষের সাথে কথা বলতে চাই", "এডমিনের নাম্বার দিন", "কথা বলব"), জটিল কোনো অভিযোগ করে, বিশেষ ছাড় চায় বা এমন কিছু জানতে চায় যা তোমার জানা নেই:
   - তাকে আশ্বস্ত করবে যে আমাদের প্রধান প্রতিনিধি খুব দ্রুত তার সাথে ইনবক্সে সরাসরি যোগাযোগ করছেন।
   - উত্তরের শেষে অবশ্যই এই ট্যাগটি যুক্ত করবে:
   :::HANDOVER_NEEDED:::{"reason": "কাস্টমার প্রতিনিধির সাথে কথা বলতে চেয়েছেন"}:::END:::
"""

def send_telegram_alert(text: str):
    """টেলিগ্রামে অ্যালার্ট পাঠানোর ফাংশন"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Alert Error: {e}")

def send_fb_message(recipient_id: str, message_text: str):
    """ফেসবুকে রিপ্লাই পাঠানোর ফাংশন"""
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
    today_str = datetime.now().strftime("%Y-%m-%d")
    if today_str not in DAILY_CUSTOMERS:
        DAILY_CUSTOMERS[today_str] = {}

    try:
        if data.get("object") == "page":
            for entry in data.get("entry", []):
                for messaging_event in entry.get("messaging", []):
                    sender_id = messaging_event.get("sender", {}).get("id")

                    # পেজ অ্যাডমিন নিজে কথা বললে বট ১ ঘণ্টা পজ থাকবে
                    if messaging_event.get("message", {}).get("is_echo"):
                        recipient_id = messaging_event.get("recipient", {}).get("id")
                        PAUSED_USERS[recipient_id] = time.time() + 3600
                        continue

                    if "message" in messaging_event and "text" in messaging_event["message"]:
                        user_text = messaging_event["message"]["text"].strip()
                        current_time_str = datetime.now().strftime("%I:%M %p")

                        # দৈনিক কাস্টমার ট্র্যাকিং
                        if sender_id not in DAILY_CUSTOMERS[today_str]:
                            DAILY_CUSTOMERS[today_str][sender_id] = current_time_str

                        # কমান্ড ১: সারাদিনের রিপোর্ট দেখা
                        if user_text.lower() == "#report":
                            count = len(DAILY_CUSTOMERS[today_str])
                            report_text = f"📊 *Tasty Mushroom ডেইলি মেসেজ রিপোর্ট ({today_str})*\n━━━━━━━━━━━━━━━━━━━━\n"
                            report_text += f"👥 *মোট ইউনিক কাস্টমার:* {count} জন\n\n*কাস্টমার আইডি ও শুরুর সময়:*\n"
                            for idx, (cid, ctime) in enumerate(DAILY_CUSTOMERS[today_str].items(), 1):
                                report_text += f"{idx}. ID: `{cid}` — সময়: {ctime}\n"
                            
                            send_telegram_alert(report_text)
                            send_fb_message(sender_id, f"আজকের মোট কাস্টমার: {count} জন। বিস্তারিত রিপোর্ট টেলিগ্রামে পাঠানো হয়েছে।")
                            continue

                        # কমান্ড ২: ম্যানুয়াল কন্ট্রোল (#stop / #start)
                        if user_text.lower() == "#stop":
                            PAUSED_USERS[sender_id] = time.time() + (24 * 3600)
                            send_fb_message(sender_id, "অটো-অ্যাসিস্ট্যান্ট সাময়িকভাবে বন্ধ করা হয়েছে। আমাদের প্রতিনিধি যোগাযোগ করবেন।")
                            continue
                        elif user_text.lower() == "#start":
                            PAUSED_USERS.pop(sender_id, None)
                            send_fb_message(sender_id, "অটো-অ্যাসিস্ট্যান্ট পুনরায় চালু করা হয়েছে।")
                            continue

                        # পজ থাকলে বট স্কিপ করবে
                        if sender_id in PAUSED_USERS:
                            if time.time() < PAUSED_USERS[sender_id]:
                                continue
                            else:
                                del PAUSED_USERS[sender_id]

                        # হিস্ট্রি সংরক্ষণ
                        if sender_id not in CONVERSATIONS:
                            CONVERSATIONS[sender_id] = []
                        CONVERSATIONS[sender_id].append({"role": "user", "parts": [{"text": user_text}]})
                        CONVERSATIONS[sender_id] = CONVERSATIONS[sender_id][-10:]

                        # AI রেসপন্স তৈরি
                        reply_text = ""
                        if client:
                            try:
                                response = client.models.generate_content(
                                    model="gemini-3.6-flash",
                                    contents=CONVERSATIONS[sender_id],
                                    config=types.GenerateContentConfig(
                                        system_instruction=SYSTEM_INSTRUCTION,
                                        temperature=0.7
                                    )
                                )
                                reply_text = response.text
                            except Exception as ge:
                                print(f"Gemini API Error: {ge}")
                                reply_text = "আপনার মেসেজের জন্য ধন্যবাদ। আমাদের প্রতিনিধি দ্রুত যোগাযোগ করবেন।"
                        else:
                            reply_text = "Tasty Mushroom-এ স্বাগতম!"

                        # ১. হিউম্যান টেকওভার অ্যালার্ট চেক
                        if ":::HANDOVER_NEEDED:::" in reply_text:
                            try:
                                parts = reply_text.split(":::HANDOVER_NEEDED:::")
                                reply_text = parts[0].strip()
                                PAUSED_USERS[sender_id] = time.time() + (12 * 3600) # বট ১২ ঘণ্টা চুপ থাকবে
                                
                                handover_alert = (
                                    "⚠️ *হিউম্যান সাপোর্ট প্রয়োজন! (Tasty Mushroom)*\n"
                                    "━━━━━━━━━━━━━━━━━━━━\n"
                                    f"👤 *কাস্টমার আইডি:* `{sender_id}`\n"
                                    f"💬 *কাস্টমারের মেসেজ:* {user_text}\n"
                                    f"⏰ *সময়:* {current_time_str}\n"
                                    "━━━━━━━━━━━━━━━━━━━━\n"
                                    "📌 *বট সাময়িকভাবে পজ করা হয়েছে। দয়া করে পেজ ইনবক্স থেকে রিপ্লাই দিন।*"
                                )
                                send_telegram_alert(handover_alert)
                            except Exception as he:
                                print(f"Handover Parse Error: {he}")

                        # ২. অর্ডার কনফার্মেশন অ্যালার্ট চেক
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

                        CONVERSATIONS[sender_id].append({"role": "model", "parts": [{"text": reply_text}]})
                        send_fb_message(sender_id, reply_text)

        return {"status": "EVENT_RECEIVED"}
    except Exception as e:
        print(f"Webhook processing error: {e}")
        return {"status": "ERROR"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
