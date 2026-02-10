import os
import time
import telebot
from flask import Flask
from threading import Thread
from telebot import types
from pymongo import MongoClient
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# --- ၁။ Configuration ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
admin_env = os.getenv('ADMIN_IDS', '')
ADMIN_IDS = [int(i) for i in admin_env.split(',') if i.strip()]

# Connection Error မတက်အောင် Threaded false ထားပြီး Exception handle လုပ်ပါမယ်
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)

# MongoDB Setup
try:
    client = MongoClient(MONGO_URI)
    db = client['MyBotDB']
    config_col = db['settings']
    print("✅ MongoDB Connected Successfully!")
except Exception as e:
    print(f"❌ MongoDB Connection Error: {e}")

# --- ၂။ Flask Server (Keep Alive) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running 24/7!"

def run():
    # Errors တွေကို Suppress လုပ်ပြီး Port ကို Environment ကနေယူပါမယ်
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

def keep_alive():
    t = Thread(target=run)
    t.daemon = True # Main thread ပိတ်ရင် ဒါပါပိတ်အောင်
    t.start()

# --- ၃။ Helper Functions ---
def get_config():
    try:
        data = config_col.find_one({"_id": "bot_settings"})
        return data if data else {}
    except: return {}

def update_config(key, value):
    try:
        config_col.update_one({"_id": "bot_settings"}, {"$set": {key: value}}, upsert=True)
    except Exception as e:
        print(f"DB Error: {e}")

def is_admin(user_id):
    return user_id in ADMIN_IDS

def is_joined(user_id):
    config = get_config()
    force_id = config.get('force_channel_id')
    if not force_id or is_admin(user_id): return True
    try:
        member = bot.get_chat_member(force_id, user_id)
        if member.status in ['member', 'administrator', 'creator']: return True
    except: return True
    return False

# --- ၄။ Admin Setup Commands ---
@bot.message_handler(commands=['setforce'], func=lambda m: is_admin(m.from_user.id))
def set_force(message):
    try:
        args = message.text.split()
        if len(args) < 3: return bot.reply_to(message, "Usage: `/setforce ID Link`", parse_mode="Markdown")
        update_config("force_channel_id", int(args[1]))
        update_config("force_channel_link", args[2])
        bot.reply_to(message, "✅ Force Subscribe Channel Set!")
    except: bot.reply_to(message, "❌ Error")

@bot.message_handler(commands=['setdb'], func=lambda m: is_admin(m.from_user.id))
def set_db(message):
    try:
        db_id = int(message.text.split()[1])
        update_config("db_channel_id", db_id)
        bot.reply_to(message, f"✅ DB Channel Set: `{db_id}`", parse_mode="Markdown")
    except: bot.reply_to(message, "❌ Error")

@bot.message_handler(commands=['status'], func=lambda m: is_admin(m.from_user.id))
def status(message):
    conf = get_config()
    bot.reply_to(message, f"⚙️ Config:\nForce: `{conf.get('force_channel_id')}`\nDB: `{conf.get('db_channel_id')}`", parse_mode="Markdown")

# --- ၅။ Backup Command ---
def backup_task(admin_id, target_ch, start_id, end_id, source_db):
    bot.send_message(admin_id, f"🚀 **Backup Started!**\nFrom ID: {start_id} to {end_id}\nTarget: `{target_ch}`")
    success = 0
    failed = 0
    
    for msg_id in range(start_id, end_id + 1):
        try:
            bot.copy_message(chat_id=target_ch, from_chat_id=source_db, message_id=msg_id)
            success += 1
            time.sleep(3) 
        except Exception as e:
            failed += 1
            print(f"Backup Error at ID {msg_id}: {e}")
            continue
            
    bot.send_message(admin_id, f"✅ **Backup Completed!**\n\nTotal: {success + failed}\nSuccess: {success}\nSkipped/Failed: {failed}")

@bot.message_handler(commands=['backup'], func=lambda m: is_admin(m.from_user.id))
def backup_command(message):
    config = get_config()
    source_db = config.get('db_channel_id')
    
    if not source_db:
        return bot.reply_to(message, "❌ DB Channel မသတ်မှတ်ရသေးပါ။")
        
    try:
        args = message.text.split()
        if len(args) < 4:
            return bot.reply_to(message, "⚠️ Usage: `/backup [Target_Ch_ID] [Start_ID] [End_ID]`", parse_mode="Markdown")
        
        target_ch = int(args[1])
        start_id = int(args[2])
        end_id = int(args[3])
        
        Thread(target=backup_task, args=(message.chat.id, target_ch, start_id, end_id, source_db)).start()
        
    except ValueError:
        bot.reply_to(message, "❌ ID များသည် ဂဏန်းဖြစ်ရပါမည်။")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# --- ၆။ Strict File Handler ---
@bot.message_handler(content_types=['video', 'document', 'audio'], func=lambda m: is_admin(m.from_user.id))
def handle_admin_file(message):
    config = get_config()
    db_id = config.get('db_channel_id')

    if not db_id: return bot.reply_to(message, "❌ DB Channel Not Set.")
    
    if not message.forward_from_chat or message.forward_from_chat.id != int(db_id):
        return bot.reply_to(message, "⚠️ **Action Denied!** Only Forwarded files from DB Channel.")

    try:
        original_id = message.forward_from_message_id
        bot_username = bot.get_me().username
        share_link = f"https://t.me/{bot_username}?start={original_id}"
        bot.reply_to(message, f"✅ **Link Created!**\nID: `{original_id}`\nLink: `{share_link}`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# --- ၇။ User Logic ---
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    config = get_config()
    args = message.text.split()
    payload = args[1] if len(args) > 1 else "only"

    if not is_joined(user_id):
        link = config.get('force_channel_link', '')
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📢 Join Channel", url=link if link else "https://t.me/"))
        markup.add(types.InlineKeyboardButton("♻️ Join ပြီးပါပြီ", callback_data=f"check_{payload}"))
        return bot.send_message(user_id, "⚠️ **Channel Join ပေးပါ**", reply_markup=markup, parse_mode="Markdown")

    if payload != "only": send_file(user_id, payload)
    else: bot.send_message(user_id, "✅ **Bot is Online!**")

def send_file(user_id, msg_id):
    config = get_config()
    try:
        bot.copy_message(user_id, config.get('db_channel_id'), int(msg_id))
    except:
        bot.send_message(user_id, "❌ File Not Found or Deleted.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('check_'))
def check(call):
    if is_joined(call.from_user.id):
        bot.delete_message(call.message.chat.id, call.message.message_id)
        data = call.data.split('_')[1]
        if data != "only": send_file(call.from_user.id, data)
        else: bot.send_message(call.message.chat.id, "✅ Success")
    else: bot.answer_callback_query(call.id, "❌ Not Joined", show_alert=True)

# --- ၈။ Execution (Modified for 24/7) ---
if __name__ == "__main__":
    keep_alive() # Flask Server run မည်
    print("🤖 Bot is starting...")
    
    # Auto-Restart Loop
    while True:
        try:
            # timeout နှင့် long_polling_timeout ထည့်ခြင်းက connection ငြိမ်စေသည်
            bot.infinity_polling(timeout=10, long_polling_timeout=5, skip_pending=True)
        except Exception as e:
            print(f"⚠️ Bot Crashed: {e}")
            time.sleep(5) # Error တက်ရင် 5 စက္ကန့်နားပြီး ပြန် run မည်
            print("♻️ Restarting Bot...")
