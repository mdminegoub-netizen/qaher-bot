import os
import json
import logging
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    CallbackContext,
    MessageHandler,
    Filters,
)

# ============== الإعدادات الأساسية ==============

# يفضّل وضع التوكن في متغيّر بيئة BOT_TOKEN في الاستضافة
BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")

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
            "relapses": [],  # قائمة تواريخ الانتكاسات
            "notes": "",
        }
        save_data(data)
    return data, data[user_key]


def update_user_record(user_id, user_record, all_data):
    all_data[str(user_id)] = user_record
    save_data(all_data)


# ============== أدوات مساعدة ==============

def format_streak_days(streak_start):
    if not streak_start:
        return "لم تبدأ العدّاد بعد. استخدم زر (بدء العدّاد) أو أرسل /reset للبدء من اليوم."
    try:
        start_dt = datetime.fromisoformat(streak_start)
    except Exception:
        return "حدث خطأ في قراءة تاريخ البداية، جرّب إعادة ضبط العدّاد."
    delta = datetime.utcnow() - start_dt
    days = delta.days
    hours = delta.seconds // 3600
    return f"مدّتك الحالية بدون انتكاس: {days} يوم و {hours} ساعة تقريبًا ✅"


def main_menu_keyboard():
    # لوحة أزرار رئيسية (تظهر أسفل الشاشة)
    keyboard = [
        [KeyboardButton("🚀 بدء الرحلة"), KeyboardButton("📅 عدّاد الأيام")],
        [KeyboardButton("💡 نصيحة اليوم"), KeyboardButton("🆘 خطة الطوارئ")],
        [KeyboardButton("🧠 أسباب الانتكاس"), KeyboardButton("🕊 أذكار وسكينة")],
        [KeyboardButton("📓 ملاحظاتي"), KeyboardButton("♻️ إعادة ضبط العدّاد")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def tips_list():
    return [
        "اغلق مصادر الإثارة من جذورها: حسابات، مواقع، أشخاص، أوقات فراغ قاتلة.",
        "عدّك للأيام ليس للزينة، بل لتذكير نفسك أنك قادر على بناء عادة جديدة.",
        "كلما ضعفت، تذكّر: ثواني متعة مزيفة = أيام من الندم والتشتّت.",
        "مارس رياضة يومية بسيطة: مشي 20 دقيقة يغيّر حالتك النفسية بالكامل.",
        "استعن بالدعاء: (اللهم طهّر قلبي، واحفظ فرجي، واصرف عني السوء والفحشاء).",
        "اكتب هدفك من الإقلاع: ماذا تريد أن تصبح بعد ٣ شهور من الآن؟",
        "نم مبكرًا، أغلب الانتكاسات تحدث ليلًا مع التعب والوحدة.",
    ]


def emergency_plan_text():
    return (
        "🆘 خطة الطوارئ عند لحظة الضعف:

"
        "1️⃣ غيّر مكانك فورًا (انهض من السرير / الغرفة).
"
        "2️⃣ اغسل وجهك أو توضأ، خذ نفس عميق 10 مرات.
"
        "3️⃣ امشِ في الغرفة أو البيت لمدة 5 دقائق.
"
        "4️⃣ افتح هذه المحادثة واقرأ الأسباب التي جعلتك تقرر الإقلاع.
"
        "5️⃣ اشغل يديك: تمرين ضغط، قراءة، كتابة، تنظيف بسيط.

"
        "💬 تذكّر: رغبة اليوم لو قاومتها، غدًا تكون أضعف بكثير."
    )


def reasons_text():
    return (
        "🧠 أسباب الانتكاس المتكرّر:

"
        "- الفراغ الطويل بدون هدف واضح.
"
        "- السهر مع الهاتف بدون مراقبة.
"
        "- وحدة وعزلة، وعدم مشاركة الرحلة مع أحد.
"
        "- محتوى سيء في مواقع التواصل لا يتم حذفه.
"
        "- عدم النوم الكافي، والتوتر والضغط.

"
        "✅ الحل: نظّف بيئتك + خطّة يومية بسيطة + نوم جيد + صحبة نافعة."
    )


def adhkar_text():
    return (
        "🕊 أذكار وسكينة:

"
        "• أستغفر الله العظيم وأتوب إليه.
"
        "• لا حول ولا قوة إلا بالله.
"
        "• اللهم اغفر لي، وطهّر قلبي، واحفظ فرجي، واصرف عني السوء.
"
        "• {قُل لِّلْمُؤْمِنِينَ يَغُضُّوا مِنْ أَبْصَارِهِمْ وَيَحْفَظُوا فُرُوجَهُمْ}.

"
        "كرّرها بتركيز وعمق، وخذ نفسًا هادئًا بين كل ذكر والآخر."
    )


# ============== أوامر البوت ==============

def start_command(update: Update, context: CallbackContext):
    user = update.effective_user
    data, record = get_user_record(user.id)

    text = (
        f"أهلًا {user.first_name} 🌿

"
        "هذا بوت *قاهر العادة* لمساعدتك في رحلة الإقلاع عن العادة السرّية.
"
        "اختر من الأزرار بالأسفل ما تحتاجه الآن 👇"
    )

    # لو أول مرة، اجعل اليوم بداية العدّاد إذا لم يكن مضبوطًا
    if record.get("streak_start") is None:
        record["streak_start"] = datetime.utcnow().isoformat()
        update_user_record(user.id, record, data)

    update.message.reply_text(
        text,
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown",
    )


def help_command(update: Update, context: CallbackContext):
    text = (
        "📝 أوامر البوت:

"
        "/start - فتح القائمة الرئيسية
"
        "/help - مساعدة
"
        "/streak - عرض عدد أيام الإقلاع
"
        "/reset - إعادة ضبط العدّاد من اليوم
"
        "/note - إضافة/تعديل ملاحظتك الشخصية
"
    )
    update.message.reply_text(text, reply_markup=main_menu_keyboard())


def streak_command(update: Update, context: CallbackContext):
    user = update.effective_user
    data, record = get_user_record(user.id)
    msg = format_streak_days(record.get("streak_start"))
    update.message.reply_text(msg, reply_markup=main_menu_keyboard())


def reset_command(update: Update, context: CallbackContext):
    user = update.effective_user
    data, record = get_user_record(user.id)

    record["streak_start"] = datetime.utcnow().isoformat()
    record.setdefault("relapses", []).append(datetime.utcnow().isoformat())
    update_user_record(user.id, record, data)

    text = (
        "♻️ تم إعادة ضبط العدّاد من اليوم.
"
        "لا تعتبرها هزيمة، بل بداية جديدة بوعي أكبر.

"
        + format_streak_days(record["streak_start"])
    )
    update.message.reply_text(text, reply_markup=main_menu_keyboard())


def note_command(update: Update, context: CallbackContext):
    user = update.effective_user
    data, record = get_user_record(user.id)

    current_note = record.get("notes") or "لا توجد ملاحظة بعد."
    text = (
        "📓 ملاحظتك الشخصية عن سبب إقلاعك:

"
        f"{current_note}

"
        "أرسل الآن ملاحظة جديدة (جملة أو أكثر) وسأحفظها لك.
"
        "اكتب ما تريد أن تتذكّره عند لحظة الضعف."
    )
    context.user_data["awaiting_note"] = True
    update.message.reply_text(text, reply_markup=main_menu_keyboard())


def handle_text_message(update: Update, context: CallbackContext):
    user = update.effective_user
    text = (update.message.text or "").strip()

    # أولوية: لو ينتظر ملاحظة جديدة
    if context.user_data.get("awaiting_note"):
        data, record = get_user_record(user.id)
        record["notes"] = text
        update_user_record(user.id, record, data)
        context.user_data["awaiting_note"] = False
        update.message.reply_text(
            "✅ تم حفظ ملاحظتك. ارجع لها في أي وقت من خلال زر (ملاحظاتي).",
            reply_markup=main_menu_keyboard(),
        )
        return

    # التعامل مع الأزرار النصية في الكيبورد
    if text == "🚀 بدء الرحلة":
        return start_command(update, context)
    if text == "📅 عدّاد الأيام":
        return streak_command(update, context)
    if text == "💡 نصيحة اليوم":
        tips = tips_list()
        # اختيار نصيحة حسب اليوم (بشكل بسيط)
        idx = datetime.utcnow().day % len(tips)
        update.message.reply_text(f"💡 نصيحة اليوم:

{tips[idx]}", reply_markup=main_menu_keyboard())
        return
    if text == "🆘 خطة الطوارئ":
        update.message.reply_text(emergency_plan_text(), reply_markup=main_menu_keyboard())
        return
    if text == "🧠 أسباب الانتكاس":
        update.message.reply_text(reasons_text(), reply_markup=main_menu_keyboard())
        return
    if text == "🕊 أذكار وسكينة":
        update.message.reply_text(adhkar_text(), reply_markup=main_menu_keyboard())
        return
    if text == "📓 ملاحظاتي":
        data, record = get_user_record(user.id)
        note = record.get("notes") or "لا توجد ملاحظة مكتوبة بعد. استخدم الأمر /note أو زر (ملاحظاتي) لإضافتها."
        update.message.reply_text(f"📓 ملاحظتك الحالية:

{note}", reply_markup=main_menu_keyboard())
        return
    if text == "♻️ إعادة ضبط العدّاد":
        return reset_command(update, context)

    # أي نص آخر
    update.message.reply_text(
        "استخدم الأزرار بالأسفل أو اكتب /help لرؤية الأوامر المتاحة ✅",
        reply_markup=main_menu_keyboard(),
    )


# ============== نقطة تشغيل البوت ==============

def main():
    if not BOT_TOKEN or BOT_TOKEN == "PUT_YOUR_TOKEN_HERE":
        logger.error("رجاءً عيّن BOT_TOKEN كمتغير بيئة في الاستضافة أو داخل الكود.")
        return

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # أوامر
    dp.add_handler(CommandHandler("start", start_command))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("streak", streak_command))
    dp.add_handler(CommandHandler("reset", reset_command))
    dp.add_handler(CommandHandler("note", note_command))

    # استقبال الرسائل النصية (للأزرار / الملاحظات)
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text_message))

    logger.info("Bot is starting...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
