import os
import telebot
from flask import Flask
from threading import Thread
from telebot import types
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# --- ၁။ Configuration & MongoDB Connection ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')

# Admin ID များကို Env မှ ယူပါ (ဥပမာ: 111111,222222)
admin_env = os.getenv('ADMIN_IDS', '')
ADMIN_IDS = [int(i) for i in admin_env.split(',') if i.strip()]

bot = telebot.TeleBot(BOT_TOKEN)

# MongoDB Setup
try:
    client = MongoClient(MONGO_URI)
    db = client['MyBotDB']      # Database Name
    config_col = db['settings'] # Collection Name
    print("✅ MongoDB Connected Successfully!")
except Exception as e:
    print(f"❌ MongoDB Connection Error: {e}")

# --- ၂။ Flask Server (Render Keep-Alive) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running with MongoDB!"

def run():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- ၃။ Helper Functions (Database) ---
def get_config():
    """Database မှ Setting များကို ယူသည်"""
    data = config_col.find_one({"_id": "bot_settings"})
    if not data:
        # Default တန်ဖိုးများ ထည့်ပေးထားခြင်း
        return {"force_channel_id": None, "force_channel_link": None, "db_channel_id": None}
    return data

def update_config(key, value):
    """Database တွင် Setting အသစ်ပြင်သည်"""
    config_col.update_one(
        {"_id": "bot_settings"},
        {"$set": {key: value}},
        upsert=True
    )

def is_admin(user_id):
    return user_id in ADMIN_IDS

def is_joined(user_id):
    """User သည် Force Sub Channel ကို Join ထားမထား စစ်ဆေးသည်"""
    config = get_config()
    force_id = config.get('force_channel_id')
    
    # Channel မသတ်မှတ်ရသေးရင် (သို့) Admin ဆိုရင် Pass
    if not force_id or is_admin(user_id):
        return True
            
    try:
        member = bot.get_chat_member(force_id, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
    except Exception as e:
        # Bot က Admin မဟုတ်ရင် Error တက်နိုင်သည်
        print(f"Force Sub Error: {e}")
        return True 
    return False

# --- ၄။ Admin Commands (Setup) ---

@bot.message_handler(commands=['setforce'], func=lambda m: is_admin(m.from_user.id))
def set_force_channel(message):
    # အသုံးပြုပုံ: /setforce -100xxxxxx https://t.me/xxxx
    try:
        args = message.text.split()
        if len(args) < 3:
            return bot.reply_to(message, "❌ မှားယွင်းနေပါသည်။\nပုံစံ: `/setforce <Channel_ID> <Link>`", parse_mode="Markdown")
        
        ch_id = int(args[1])
        ch_link = args[2]
        
        # Test if bot is admin there (Optional check)
        try:
            bot.get_chat_member(ch_id, message.from_user.id)
        except:
            return bot.reply_to(message, "⚠️ သတိပေးချက်: Bot သည် ထို Channel တွင် Admin ဖြစ်မနေပါ။")
        
        # Save to MongoDB
        update_config("force_channel_id", ch_id)
        update_config("force_channel_link", ch_link)
        
        bot.reply_to(message, f"✅ Force Channel သိမ်းဆည်းပြီးပါပြီ!\nID: `{ch_id}`\nLink: {ch_link}", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['setdb'], func=lambda m: is_admin(m.from_user.id))
def set_db_channel(message):
    # အသုံးပြုပုံ: /setdb -100xxxxxx
    try:
        args = message.text.split()
        if len(args) < 2:
            return bot.reply_to(message, "❌ မှားယွင်းနေပါသည်။\nပုံစံ: `/setdb <Channel_ID>`", parse_mode="Markdown")
        
        ch_id = int(args[1])
        
        # Save to MongoDB
        update_config("db_channel_id", ch_id)
        
        bot.reply_to(message, f"✅ Database Channel သိမ်းဆည်းပြီးပါပြီ!\nID: `{ch_id}`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['status', 'admin'], func=lambda m: is_admin(m.from_user.id))
def check_status(message):
    config = get_config()
    force_id = config.get('force_channel_id', 'Not Set')
    force_link = config.get('force_channel_link', 'Not Set')
    db_id = config.get('db_channel_id', 'Not Set')
    
    text = (
        f"⚙️ **Current Bot Settings**\n(Saved in MongoDB)\n\n"
        f"📢 **Force Channel:** `{force_id}`\n"
        f"🔗 **Link:** {force_link}\n\n"
        f"📂 **DB Channel:** `{db_id}`"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

# --- ၅။ User Handling Logic ---

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    config = get_config()
    
    # Payload (ဥပမာ: /start 123) ကို ယူခြင်း
    args = message.text.split()
    payload = args[1] if len(args) > 1 else "only"

    # ၁။ Force Subscribe စစ်ဆေးခြင်း
    if not is_joined(user_id):
        link = config.get('force_channel_link', '')
        
        # Link မရှိသေးရင် အလွတ်ပေးလိုက်မည်
        if not link:
            if payload != "only": send_file(user_id, payload)
            else: bot.send_message(user_id, "✅ Bot is active but no channel set.")
            return

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📢 Join Channel", url=link))
        markup.add(types.InlineKeyboardButton("♻️ Join ပြီးပါပြီ", callback_data=f"check_{payload}"))
        
        return bot.send_message(user_id, "⚠️ **ဇာတ်ကားကြည့်ရှုရန် အောက်ပါ Channel ကို အရင် Join ပေးပါ။**", reply_markup=markup, parse_mode="Markdown")

    # ၂။ Join ပြီးသားဆိုရင် ရှေ့ဆက်မည်
    if payload != "only":
        send_file(user_id, payload)
    else:
        bot.send_message(user_id, "✅ မင်္ဂလာပါ! ဇာတ်ကား Link ကို နှိပ်၍ ကြည့်ရှုနိုင်ပါသည်။")

def send_file(user_id, msg_id):
    config = get_config()
    db_id = config.get('db_channel_id')
    
    if not db_id:
        return bot.send_message(user_id, "❌ Admin မှ DB Channel မသတ်မှတ်ရသေးပါ။")
        
    try:
        # copy_message သည် forward tag မပါဘဲ ကူးပေးသည်
        bot.copy_message(user_id, db_id, int(msg_id))
    except Exception as e:
        bot.send_message(user_id, "❌ ဖိုင်ရှာမတွေ့ပါ။ Link မှားနေခြင်း (သို့) ဖျက်လိုက်ခြင်း ဖြစ်နိုင်ပါသည်။")
        print(f"File Send Error: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('check_'))
def callback_check(call):
    user_id = call.from_user.id
    data = call.data.split('_')[1] # payload ကို ပြန်ယူသည်
    
    if is_joined(user_id):
        bot.delete_message(call.message.chat.id, call.message.message_id)
        if data != "only":
            send_file(user_id, data)
        else:
            bot.send_message(user_id, "✅ Join ထားခြင်း အောင်မြင်ပါသည်။")
    else:
        bot.answer_callback_query(call.id, "❌ Channel မ Join ရသေးပါ။", show_alert=True)

# --- Main Execution ---
if __name__ == "__main__":
    keep_alive() # Flask Server Run
    bot.infinity_polling() # Bot Run
