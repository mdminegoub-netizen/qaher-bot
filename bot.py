import os
import json
import logging
import random
from datetime import datetime, time
from threading import Thread

from flask import Flask

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

# ================= إعدادات أساسية =================

# توكن البوت من متغيّر البيئة في Render
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ملف تخزين بيانات المستخدمين
DATA_FILE = "user_data.json"

# ID الإدمن (اكتبه كرقم، بدون علامات تنصيص)
# مثال: ADMIN_ID = 931350292
ADMIN_ID = None  # عدّل هذا ووضع الـ ID الخاص بك

# وقت التذكير اليومي (بتوقيت UTC)
DAILY_REMINDER_HOUR = 20
DAILY_REMINDER_MINUTE = 0

# إعداد اللوجز
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ================= خادم ويب بسيط لـ Render =================

app = Flask(__name__)

@app.route("/")
def index():
    return "Qaher-bot is running ✅"

def run_flask():
    # Render يمرّر رقم البورت في متغيّر PORT
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

# ================= تخزين بيانات المستخدمين =================

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading data: {e}")
        return {}


def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving data: {e}")


def get_user_record(user_id):
    """إرجاع سجل المستخدم من الملف، وإنشاء سجل جديد لو غير موجود."""
    data = load_data()
    user_key = str(user_id)

    is_new = False
    if user_key not in data:
        is_new = True
        data[user_key] = {
            "created_at": datetime.utcnow().isoformat(),
            "streak_start": None,
            "relapses": [],
            "notes": "",
            "last_active": datetime.utcnow().isoformat(),
        }
        save_data(data)

    return data, data[user_key], is_new


def update_user_record(user_id, user_record, all_data):
    all_data[str(user_id)] = user_record
    save_data(all_data)


# ================= أدوات مساعدة =================

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
        [KeyboardButton("💡 نصيحة"), KeyboardButton("🆘 خطة الطوارئ")],
        [KeyboardButton("🧠 أسباب الانتكاس"), KeyboardButton("🕊 أذكار وسكينة")],
        [KeyboardButton("📓 ملاحظاتي"), KeyboardButton("♻️ إعادة ضبط العدّاد")],
        [KeyboardButton("📨 تواصل مع الدعم")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def tips_list():
    return [
        "أغلق مصادر الإثارة من جذورها: حسابات، مواقع، أوقات فراغ بلا هدف.",
        "ثواني متعة مزيفة = أيام من الندم والتشتّت، تذكّر ذلك لحظة الضعف.",
        "كل يوم تقاوم فيه، تبني نسخة أقوى وأنظف من نفسك.",
        "الراحة النفسية الحقيقية تأتي من نقاء القلب، لا من لقطات محرّمة.",
        "مارس رياضة بسيطة 20 دقيقة يوميًا، تغيّر مزاجك بشكل مذهل.",
        "اكتب هدفك من الإقلاع وضعه خلفية لهاتفك كتذكير دائم.",
        "اجعل هاتفك خارج الغرفة عند النوم لتقلّل فرص الانتكاس.",
        "استعن بالدعاء: (اللهم طهّر قلبي واحفظ فرجي واصرف عني السوء والفحشاء).",
        "غيّر روتينك قبل النوم: قراءة، أذكار، تخطيط لغدٍ أفضل.",
        "لا تعش لوحدك في المعركة، شارك شخصًا تثق به في هدفك ليستمر دعمك.",
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
        "✅ الحل: نظّف بيئتك + خطّة يومية بسيطة + نوم جيد + صحبة نافعة."
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


def is_admin(user_id: int) -> bool:
    if ADMIN_ID is None:
        return False
    return user_id == ADMIN_ID


def notify_admin_new_user(context: CallbackContext, user):
    if ADMIN_ID is None:
        return
    try:
        text = (
            "👋 مستخدم جديد دخل البوت:\n\n"
            f"الاسم: {user.first_name or ''} {user.last_name or ''}\n"
            f"اليوزر: @{user.username}\n"
            f"ID: `{user.id}`"
        )
        context.bot.send_message(
            chat_id=ADMIN_ID,
            text=text,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Error notifying admin: {e}")


# ================= أوامر البوت =================

def start_command(update: Update, context: CallbackContext):
    user = update.effective_user
    data, record, is_new = get_user_record(user.id)

    # أول مرة يستخدم فيها /start
    if record.get("streak_start") is None:
        record["streak_start"] = datetime.utcnow().isoformat()
    record["last_active"] = datetime.utcnow().isoformat()
    update_user_record(user.id, record, data)

    if is_new:
        notify_admin_new_user(context, user)

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
        "/support - إرسال رسالة إلى الدعم\n"
    )
    update.message.reply_text(text, reply_markup=main_menu_keyboard())


def streak_command(update: Update, context: CallbackContext):
    user = update.effective_user
    data, record, _ = get_user_record(user.id)
    msg = format_streak_days(record.get("streak_start"))
    update.message.reply_text(msg, reply_markup=main_menu_keyboard())


def reset_command(update: Update, context: CallbackContext):
    user = update.effective_user
    data, record, _ = get_user_record(user.id)

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
    data, record, _ = get_user_record(user.id)

    current_note = record.get("notes") or "لا توجد ملاحظة بعد."
    text = (
        "📓 ملاحظتك الشخصية عن سبب إقلاعك:\n\n"
        f"{current_note}\n\n"
        "✏️ أرسل الآن ملاحظة جديدة (جملة أو أكثر) وسأحفظها لك.\n"
        "اكتب ما تريد أن تتذكّره عند لحظة الضعف."
    )
    context.user_data["awaiting_note"] = True
    update.message.reply_text(text, reply_markup=main_menu_keyboard())


def support_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if ADMIN_ID is None:
        update.message.reply_text(
            "حاليًّا ميزة التواصل مع الدعم غير مفعّلة.",
            reply_markup=main_menu_keyboard(),
        )
        return

    context.user_data["awaiting_support"] = True
    update.message.reply_text(
        "📨 اكتب رسالتك للدعم الآن (وستصل إلى المسؤول عن البوت).",
        reply_markup=main_menu_keyboard(),
    )


# ================= الرسائل النصية =================

def handle_text_message(update: Update, context: CallbackContext):
    user = update.effective_user
    text = (update.message.text or "").strip()

    data, record, _ = get_user_record(user.id)
    record["last_active"] = datetime.utcnow().isoformat()
    update_user_record(user.id, record, data)

    # 1) حفظ ملاحظة
    if context.user_data.get("awaiting_note"):
        record["notes"] = text
        update_user_record(user.id, record, data)
        context.user_data["awaiting_note"] = False
        update.message.reply_text(
            "✅ تم حفظ ملاحظتك. يمكنك رؤيتها من زر (📓 ملاحظاتي).",
            reply_markup=main_menu_keyboard(),
        )
        return

    # 2) رسالة دعم
    if context.user_data.get("awaiting_support"):
        context.user_data["awaiting_support"] = False
        if ADMIN_ID is not None:
            try:
                msg = (
                    "📨 رسالة جديدة من مستخدم:\n\n"
                    f"الاسم: {user.first_name or ''} {user.last_name or ''}\n"
                    f"اليوزر: @{user.username}\n"
                    f"ID: `{user.id}`\n\n"
                    f"النص:\n{text}"
                )
                context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=msg,
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error(f"Error sending support message: {e}")

        update.message.reply_text(
            "✅ تم إرسال رسالتك إلى الدعم، سيتم الرد عليك إن لزم الأمر.",
            reply_markup=main_menu_keyboard(),
        )
        return

    # 3) أزرار القائمة
    if text == "🚀 بدء الرحلة":
        return start_command(update, context)

    if text == "📅 عدّاد الأيام":
        return streak_command(update, context)

    if text == "💡 نصيحة":
        tip = random.choice(tips_list())
        update.message.reply_text(
            f"💡 نصيحة:\n\n{tip}",
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

    if text == "📨 تواصل مع الدعم":
        return support_command(update, context)

    # رسالة افتراضية
    update.message.reply_text(
        "استخدم الأزرار بالأسفل أو اكتب /help لرؤية الأوامر المتاحة ✅",
        reply_markup=main_menu_keyboard(),
    )


# ================= التذكير اليومي =================

def send_daily_reminders(context: CallbackContext):
    """إرسال تذكير يومي لكل المستخدمين مرة واحدة في اليوم."""
    data = load_data()
    tips = tips_list()

    for user_id_str, record in data.items():
        user_id = int(user_id_str)
        tip = random.choice(tips)

        text = (
            "🌅 تذكير يومي من *قاهر العادة*:\n\n"
            "تذكّر لماذا بدأت هذه الرحلة، ولا تترك عادة سرية تسرق منك صفاء قلبك.\n\n"
            f"💡 {tip}"
        )
        try:
            context.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning(f"Could not send reminder to {user_id}: {e}")


# ================= نقطة تشغيل البوت =================

def main():
    if not BOT_TOKEN:
        logger.error("لم يتم العثور على BOT_TOKEN في متغيّرات البيئة.")
        return

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    job_queue = updater.job_queue

    # أوامر
    dp.add_handler(CommandHandler("start", start_command))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("streak", streak_command))
    dp.add_handler(CommandHandler("reset", reset_command))
    dp.add_handler(CommandHandler("note", note_command))
    dp.add_handler(CommandHandler("support", support_command))

    # رسائل نصية عامة
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text_message))

    # جدولة التذكير اليومي (وقت UTC)
    job_queue.run_daily(
        send_daily_reminders,
        time=time(hour=DAILY_REMINDER_HOUR, minute=DAILY_REMINDER_MINUTE),
        name="daily_reminders",
    )

    logger.info("Bot is starting...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    # نشغّل سيرفر الويب في ثريد منفصل لـ Render
    Thread(target=run_flask, daemon=True).start()
    # ثم نشغّل بوت تيليجرام
    main()
