import os
import telebot
from flask import Flask
from threading import Thread
from telebot import types
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# --- ၁။ Configuration ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
admin_env = os.getenv('ADMIN_IDS', '')
ADMIN_IDS = [int(i) for i in admin_env.split(',') if i.strip()]

bot = telebot.TeleBot(BOT_TOKEN)

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
def home(): return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

def keep_alive():
    Thread(target=run).start()

# --- ၃။ Helper Functions ---
def get_config():
    data = config_col.find_one({"_id": "bot_settings"})
    return data if data else {}

def update_config(key, value):
    config_col.update_one({"_id": "bot_settings"}, {"$set": {key: value}}, upsert=True)

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
        bot.reply_to(message, "✅ Force Channel Set!")
    except: bot.reply_to(message, "❌ Error")

@bot.message_handler(commands=['setdb'], func=lambda m: is_admin(m.from_user.id))
def set_db(message):
    try:
        # DB Channel ID ကို သိမ်းမည်
        db_id = int(message.text.split()[1])
        update_config("db_channel_id", db_id)
        bot.reply_to(message, f"✅ Database Channel သတ်မှတ်ပြီးပါပြီ!\nTarget ID: `{db_id}`\n\n(ယခုမှစ၍ ဤ Channel မှ Forward လုပ်မှသာ Link ထုတ်ပေးပါမည်)", parse_mode="Markdown")
    except: bot.reply_to(message, "❌ Error")

@bot.message_handler(commands=['status'], func=lambda m: is_admin(m.from_user.id))
def status(message):
    conf = get_config()
    bot.reply_to(message, f"⚙️ Config:\nForce: `{conf.get('force_channel_id')}`\nDB: `{conf.get('db_channel_id')}`", parse_mode="Markdown")

# --- ၅။ Strict File Handler (အဓိက ပြင်ဆင်ထားသောအပိုင်း) ---
@bot.message_handler(content_types=['video', 'document', 'audio'], func=lambda m: is_admin(m.from_user.id))
def handle_admin_file(message):
    config = get_config()
    db_id = config.get('db_channel_id')

    # ၁။ DB Channel မသတ်မှတ်ရသေးရင် ဘာမှမလုပ်
    if not db_id:
        return bot.reply_to(message, "❌ DB Channel မသတ်မှတ်ရသေးပါ။ `/setdb` အရင်လုပ်ပါ။")

    # ၂။ Forward ဟုတ်မဟုတ် နှင့် DB Channel က ဟုတ်မဟုတ် စစ်ဆေးခြင်း
    if not message.forward_from_chat or message.forward_from_chat.id != int(db_id):
        # DB Channel မဟုတ်ရင် ငြင်းပယ်မည်
        return bot.reply_to(message, "⚠️ **Action Denied!**\n\nBot သည် သတ်မှတ်ထားသော **Database Channel** ထဲမှ Forward လုပ်လာသည့် ဖိုင်များကိုသာ လက်ခံပါသည်။\n(အသစ် Upload တင်ခြင်း/အခြား Channel မှ ကူးခြင်းများကို လက်မခံပါ)")

    # ၃။ DB Channel က Forward လုပ်တာသေချာပြီ (Link ထုတ်ပေးမည်)
    try:
        # မူရင်း Message ID ကို ယူသည် (Copy မကူးပါ)
        original_id = message.forward_from_message_id
        
        bot_username = bot.get_me().username
        share_link = f"https://t.me/{bot_username}?start={original_id}"
        
        bot.reply_to(message, f"✅ **File Linked!**\n\nID: `{original_id}`\nLink: `{share_link}`", parse_mode="Markdown")

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# --- ၆။ User Logic ---
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
    else: bot.send_message(user_id, "✅ Bot Ready!")

def send_file(user_id, msg_id):
    config = get_config()
    try:
        # DB Channel ထဲက ID အတိုင်း လှမ်းယူပြီး Copy ပို့ပေးသည်
        bot.copy_message(user_id, config.get('db_channel_id'), int(msg_id))
    except:
        bot.send_message(user_id, "❌ File Not Found (Source Message might be deleted)")

@bot.callback_query_handler(func=lambda call: call.data.startswith('check_'))
def check(call):
    if is_joined(call.from_user.id):
        bot.delete_message(call.message.chat.id, call.message.message_id)
        data = call.data.split('_')[1]
        if data != "only": send_file(call.from_user.id, data)
        else: bot.send_message(call.message.chat.id, "✅ Success")
    else: bot.answer_callback_query(call.id, "❌ Not Joined", show_alert=True)

if __name__ == "__main__":
    keep_alive()
    bot.infinity_polling()
