import os
import json
import logging
from datetime import datetime, time
from pytz import utc  # مهم لحل مشكلة التايم زون مع APScheduler

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackContext,
    MessageHandler,
    Filters,
)

# ============== الإعدادات الأساسية ==============

# نقرأ التوكن من متغيّر البيئة BOT_TOKEN في Render
BOT_TOKEN = os.getenv("BOT_TOKEN")

DATA_FILE = "user_data.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ============== تخزين بيانات المستخدمين (بسيط) ==============

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving data: {e}")


def get_user_record(user_id):
    data = load_data()
    user_key = str(user_id)
    if user_key not in data:
        data[user_key] = {
            "created_at": datetime.utcnow().isoformat(),
            "streak_start": None,
            "relapses": [],
            "notes": "",
            "chat_id": None,
            "daily_enabled": True,  # التذكير اليومي مفعّل افتراضيًا
            "name": None,
            "last_active": None,
        }
        save_data(data)
    return data, data[user_key]


def update_user_record(user_id, user_record, all_data):
    all_data[str(user_id)] = user_record
    save_data(all_data)


# ============== أدوات مساعدة ==============

def format_streak_days(streak_start):
    if not streak_start:
        return (
            "لم تبدأ العدّاد بعد.\n"
            "استخدم زر (🚀 بدء الرحلة) أو الأمر /reset للبدء من اليوم."
        )
    try:
        start_dt = datetime.fromisoformat(streak_start)
    except Exception:
        return "حدث خطأ في قراءة تاريخ البداية، جرّب إعادة ضبط العدّاد بواسطة /reset."
    delta = datetime.utcnow() - start_dt
    days = delta.days
    hours = delta.seconds // 3600
    return f"مدّتك الحالية بدون انتكاس: {days} يوم و {hours} ساعة تقريبًا ✅"


def main_menu_keyboard():
    keyboard = [
        [KeyboardButton("🚀 بدء الرحلة"), KeyboardButton("📅 عدّاد الأيام")],
        [KeyboardButton("💡 نصيحة اليوم"), KeyboardButton("🆘 خطة الطوارئ")],
        [KeyboardButton("🧠 أسباب الانتكاس"), KeyboardButton("🕊 أذكار وسكينة")],
        [KeyboardButton("📓 ملاحظاتي"), KeyboardButton("♻️ إعادة ضبط العدّاد")],
        [KeyboardButton("⏰ تفعيل التذكير اليومي"), KeyboardButton("🔕 إيقاف التذكير اليومي")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def tips_list():
    return [
        "أغلق مصادر الإثارة من جذورها: حسابات، مواقع، أوقات فراغ بلا هدف.",
        "عدّاد الأيام يذكّرك أنك تبني عادة جديدة، ليس مجرد رقم.",
        "ثواني متعة مزيفة = أيام من الندم والتشتّت، تذكّر ذلك لحظة الضعف.",
        "رياضة 20 دقيقة مشي يوميًا تغيّر حالتك النفسية بالكامل.",
        "استعن بالدعاء: (اللهم طهّر قلبي واحفظ فرجي واصرف عني السوء والفحشاء).",
        "اكتب هدفك من الإقلاع: من تريد أن تكون بعد ٣ شهور من الآن؟",
        "نم مبكرًا؛ أغلب الانتكاسات تحدث ليلًا مع السهر والتعب والوحدة.",
    ]


def emergency_plan_text():
    return (
        "🆘 خطة الطوارئ عند لحظة الضعف:\n\n"
        "1️⃣ غيّر مكانك فورًا (انهض من السرير أو اخرج من الغرفة).\n"
        "2️⃣ توضأ أو اغسل وجهك وخذ نفسًا عميقًا 10 مرات.\n"
        "3️⃣ امشِ في البيت أو الغرفة لمدة 5 دقائق.\n"
        "4️⃣ افتح هذه المحادثة واقرأ ملاحظتك عن سبب الإقلاع (من زر 📓 ملاحظاتي).\n"
        "5️⃣ اشغل يديك: تمارين بسيطة، قراءة، كتابة، تنظيف بسيط.\n\n"
        "💬 تذكّر: رغبة اليوم لو قاومتها، رغبة الغد ستكون أضعف بكثير."
    )


def reasons_text():
    return (
        "🧠 أسباب الانتكاس المتكرّر:\n\n"
        "- الفراغ الطويل بدون خطة لليوم.\n"
        "- السهر مع الهاتف بلا رقابة.\n"
        "- الوحدة والعزلة عن الناس الصالحين.\n"
        "- متابعة محتوى سيّئ وعدم حذفه.\n"
        "- قلة النوم وكثرة التوتّر.\n\n"
        "✅ العلاج: نظّف بيئتك + خطّة يومية بسيطة + نوم جيد + صحبة نافعة."
    )


def adhkar_text():
    return (
        "🕊 أذكار وسكينة:\n\n"
        "• أستغفر الله العظيم وأتوب إليه.\n"
        "• لا حول ولا قوة إلا بالله.\n"
        "• اللهم اغفر لي، وطهّر قلبي، واحفظ فرجي، واصرف عني السوء.\n"
        "• {قُل لِّلْمُؤْمِنِينَ يَغُضُّوا مِنْ أَبْصَارِهِمْ وَيَحْفَظُوا فُرُوجَهُمْ}.\n\n"
        "كرّرها بتركيز مع تنفّس هادئ، ودع قلبك يهدأ."
    )


def daily_message_for_user(user_name, streak_text, note):
    base = (
        f"مرحبًا {user_name if user_name else 'يا صديق الرحلة'} 🌿\n\n"
        "تذكيرك اليومي من *قاهر العادة*:\n\n"
        f"{streak_text}\n\n"
    )

    if note:
        base += f"🎯 تذكّر ملاحظتك الشخصية:\n«{note}»\n\n"

    base += (
        "اليوم خطوة جديدة في رحلتك، لا تستهين بصمودك حتى لو كان بسيطًا.\n"
        "ركّز على *خطوة اليوم فقط*، والباقي سيأتي مع الوقت بإذن الله 💪"
    )
    return base


# ============== أوامر البوت ==============

def start_command(update: Update, context: CallbackContext):
    user = update.effective_user
    chat_id = update.effective_chat.id
    data, record = get_user_record(user.id)

    # حفظ اسم المستخدم والشات وآخر نشاط
    record["name"] = user.first_name
    record["chat_id"] = chat_id
    record.setdefault("daily_enabled", True)
    record["last_active"] = datetime.utcnow().isoformat()

    if record.get("streak_start") is None:
        record["streak_start"] = datetime.utcnow().isoformat()

    update_user_record(user.id, record, data)

    text = (
        f"أهلًا {user.first_name} 🌿\n\n"
        "هذا بوت *قاهر العادة* لمساعدتك في رحلة الإقلاع عن العادة السرّية.\n"
        "استخدم الأزرار بالأسفل لاختيار ما تحتاجه الآن 👇"
    )

    update.message.reply_text(
        text,
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown",
    )


def help_command(update: Update, context: CallbackContext):
    text = (
        "📝 أوامر البوت:\n\n"
        "/start - فتح القائمة الرئيسية\n"
        "/help - عرض هذه المساعدة\n"
        "/streak - عرض عدد أيام الإقلاع\n"
        "/reset - إعادة ضبط العدّاد من اليوم\n"
        "/note - إضافة أو تعديل ملاحظتك الشخصية\n"
    )
    update.message.reply_text(text, reply_markup=main_menu_keyboard())


def streak_command(update: Update, context: CallbackContext):
    user = update.effective_user
    data, record = get_user_record(user.id)
    record["last_active"] = datetime.utcnow().isoformat()
    update_user_record(user.id, record, data)

    msg = format_streak_days(record.get("streak_start"))
    update.message.reply_text(msg, reply_markup=main_menu_keyboard())


def reset_command(update: Update, context: CallbackContext):
    user = update.effective_user
    data, record = get_user_record(user.id)

    record["streak_start"] = datetime.utcnow().isoformat()
    record.setdefault("relapses", []).append(datetime.utcnow().isoformat())
    record["last_active"] = datetime.utcnow().isoformat()
    update_user_record(user.id, record, data)

    text = (
        "♻️ تم إعادة ضبط العدّاد من اليوم.\n"
        "لا تعتبرها هزيمة، بل بداية بوعي أكبر وتجربة أعمق.\n\n"
        f"{format_streak_days(record['streak_start'])}"
    )
    update.message.reply_text(text, reply_markup=main_menu_keyboard())


def note_command(update: Update, context: CallbackContext):
    user = update.effective_user
    data, record = get_user_record(user.id)

    record["last_active"] = datetime.utcnow().isoformat()
    update_user_record(user.id, record, data)

    current_note = record.get("notes") or "لا توجد ملاحظة بعد."
    text = (
        "📓 ملاحظتك الشخصية عن سبب إقلاعك:\n\n"
        f"{current_note}\n\n"
        "✏️ أرسل الآن ملاحظة جديدة (جملة أو أكثر) وسأحفظها لك.\n"
        "اكتب ما تريد أن تتذكّره عند لحظة الضعف."
    )
    context.user_data["awaiting_note"] = True
    update.message.reply_text(text, reply_markup=main_menu_keyboard())


# ============== أوامر إحصائية للإدمن (اختياري) ==============

ADMIN_ID = None  # ضع هنا ID حسابك في تيليجرام إن حبيت تحمي أوامر الإحصائيات


def is_admin(user_id: int) -> bool:
    if ADMIN_ID is None:
        # لو ما عيّنا ADMIN_ID، نسمح للجميع (يمكنك تغييره لاحقًا)
        return True
    return user_id == ADMIN_ID


def users_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if not is_admin(user.id):
        return

    data = load_data()
    if not data:
        update.message.reply_text("لا يوجد أي مستخدم بدأ استخدام البوت بعد.")
        return

    text = "📋 قائمة المستخدمين الذين استخدموا البوت:\n\n"
    for user_id, record in data.items():
        name = record.get("name") or "بدون اسم"
        text += f"• {name} — ID: `{user_id}`\n"

    text += f"\nإجمالي المستخدمين: {len(data)} 👥"
    update.message.reply_text(text, parse_mode="Markdown")


def last_active_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if not is_admin(user.id):
        return

    data = load_data()
    if not data:
        update.message.reply_text("لا يوجد بيانات نشاط بعد.")
        return

    # ترتيب المستخدمين حسب آخر نشاط
    users_list = []
    for user_id, record in data.items():
        last = record.get("last_active")
        if last:
            try:
                dt = datetime.fromisoformat(last)
            except Exception:
                continue
            users_list.append((dt, user_id, record))

    if not users_list:
        update.message.reply_text("لا يوجد نشاط مسجّل بعد.")
        return

    users_list.sort(reverse=True)
    users_list = users_list[:10]

    lines = ["🕒 آخر 10 مستخدمين تفاعلوا:\n"]
    for dt, user_id, record in users_list:
        name = record.get("name") or "بدون اسم"
        lines.append(f"• {name} — ID: `{user_id}` — آخر نشاط: {dt.isoformat()}")

    update.message.reply_text("\n".join(lines), parse_mode="Markdown")


def stats_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if not is_admin(user.id):
        return

    data = load_data()
    total = len(data)
    today = datetime.utcnow().date()

    active_today = 0
    for record in data.values():
        last = record.get("last_active")
        if not last:
            continue
        try:
            dt = datetime.fromisoformat(last)
        except Exception:
            continue
        if dt.date() == today:
            active_today += 1

    text = (
        "📊 إحصائيات البوت:\n\n"
        f"- إجمالي المستخدمين: {total} 👥\n"
        f"- المستخدمون النشطون اليوم: {active_today} ✅\n"
    )
    update.message.reply_text(text)


# ============== التذكير اليومي ==============

def send_daily_reminders(context: CallbackContext):
    data = load_data()
    if not data:
        return

    for user_id, record in data.items():
        chat_id = record.get("chat_id")
        daily_enabled = record.get("daily_enabled", True)
        if not chat_id or not daily_enabled:
            continue

        try:
            user = context.bot.get_chat(chat_id)
            name = user.first_name
        except Exception:
            name = record.get("name")

        streak_text = format_streak_days(record.get("streak_start"))
        note = record.get("notes") or ""
        text = daily_message_for_user(name, streak_text, note)

        try:
            context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send daily message to {chat_id}: {e}")


# ============== التعامل مع الرسائل النصية والأزرار ==============

def handle_text_message(update: Update, context: CallbackContext):
    user = update.effective_user
    data, record = get_user_record(user.id)
    record["last_active"] = datetime.utcnow().isoformat()
    update_user_record(user.id, record, data)

    text = (update.message.text or "").strip()

    # لو المستخدم يكتب ملاحظة جديدة
    if context.user_data.get("awaiting_note"):
        record["notes"] = text
        update_user_record(user.id, record, data)
        context.user_data["awaiting_note"] = False
        update.message.reply_text(
            "✅ تم حفظ ملاحظتك. يمكنك رؤيتها من زر (📓 ملاحظاتي).",
            reply_markup=main_menu_keyboard(),
        )
        return

    # الأزرار
    if text == "🚀 بدء الرحلة":
        return start_command(update, context)

    if text == "📅 عدّاد الأيام":
        return streak_command(update, context)

    if text == "💡 نصيحة اليوم":
        tips = tips_list()
        idx = datetime.utcnow().day % len(tips)
        update.message.reply_text(
            f"💡 نصيحة اليوم:\n\n{tips[idx]}",
            reply_markup=main_menu_keyboard(),
        )
        return

    if text == "🆘 خطة الطوارئ":
        update.message.reply_text(
            emergency_plan_text(),
            reply_markup=main_menu_keyboard(),
        )
        return

    if text == "🧠 أسباب الانتكاس":
        update.message.reply_text(
            reasons_text(),
            reply_markup=main_menu_keyboard(),
        )
        return

    if text == "🕊 أذكار وسكينة":
        update.message.reply_text(
            adhkar_text(),
            reply_markup=main_menu_keyboard(),
        )
        return

    if text == "📓 ملاحظاتي":
        note = record.get("notes") or (
            "لا توجد ملاحظة مكتوبة بعد.\n"
            "استخدم الأمر /note أو زر (📓 ملاحظاتي) لإضافتها."
        )
        update.message.reply_text(
            f"📓 ملاحظتك الحالية:\n\n{note}",
            reply_markup=main_menu_keyboard(),
        )
        return

    if text == "♻️ إعادة ضبط العدّاد":
        return reset_command(update, context)

    if text == "⏰ تفعيل التذكير اليومي":
        record["daily_enabled"] = True
        update_user_record(user.id, record, data)
        update.message.reply_text(
            "✅ تم تفعيل التذكير اليومي. سأرسل لك رسالة تحفيزية كل يوم بإذن الله.",
            reply_markup=main_menu_keyboard(),
        )
        return

    if text == "🔕 إيقاف التذكير اليومي":
        record["daily_enabled"] = False
        update_user_record(user.id, record, data)
        update.message.reply_text(
            "🔕 تم إيقاف التذكير اليومي. يمكنك تفعيله مرة أخرى في أي وقت.",
            reply_markup=main_menu_keyboard(),
        )
        return

    # افتراضيًا
    update.message.reply_text(
        "استخدم الأزرار بالأسفل أو اكتب /help لرؤية الأوامر المتاحة ✅",
        reply_markup=main_menu_keyboard(),
    )


# ============== نقطة تشغيل البوت ==============

def main():
    if not BOT_TOKEN:
        logger.error("لم يتم العثور على BOT_TOKEN في متغيّرات البيئة.")
        return

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # أوامر أساسية
    dp.add_handler(CommandHandler("start", start_command))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("streak", streak_command))
    dp.add_handler(CommandHandler("reset", reset_command))
    dp.add_handler(CommandHandler("note", note_command))

    # أوامر إحصائية للإدمن
    dp.add_handler(CommandHandler("users", users_command))
    dp.add_handler(CommandHandler("last_active", last_active_command))
    dp.add_handler(CommandHandler("stats", stats_command))

    # الرسائل النصية
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text_message))

    # التذكير اليومي: كل يوم الساعة 20:00 UTC (تقدر تغيّرها)
    job_queue = updater.job_queue
    job_queue.run_daily(
        send_daily_reminders,
        time=time(hour=20, minute=0, tzinfo=utc),
        name="daily_reminders",
    )

    logger.info("Bot is starting...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
