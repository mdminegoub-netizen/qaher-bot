import os
import json
import logging
import random
from datetime import datetime, time
from threading import Thread

from flask import Flask
from pytz import utc

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    ConversationHandler,
)

# ========================= إعدادات أساسية =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")  # توكن البوت من متغير البيئة في Render

# ملف تخزين بيانات المستخدمين
DATA_FILE = "user_data.json"

# ID الأدمن (اكتبه كرقم فقط بدون علامات تنصيص)
# مثال: ADMIN_ID = 931350292
ADMIN_ID = 931350292

# ========================= إعداد اللوج =========================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ========================= خادم Flask بسيط لـ Render =========================

app = Flask(__name__)


@app.route("/")
def index():
    return "Qaher-bot is running ✅"


def run_flask():
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)


# ========================= التعامل مع ملف البيانات =========================

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading data file: {e}")
        return {}


def save_data(data: dict):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving data file: {e}")


def get_user_record(user_id: int, update: Update = None) -> dict:
    data = load_data()
    key = str(user_id)

    if key not in data:
        now = datetime.utcnow().isoformat()
        user = update.effective_user if update else None
        data[key] = {
            "id": user_id,
            "name": user.full_name if user else "",
            "username": user.username if user else None,
            "created_at": now,
            "last_active": now,
            "streak_start": None,  # يبدأ عندما يضغط "بدء الرحلة"
            "notes": [],
            "relapses": [],  # تواريخ الانتكاسات
            "daily_ratings": [],  # قائمة من {date, rating}
            "motivation_note": None,
            "level": 1,
        }
        save_data(data)

    return data[key]


def update_user_record(user_id: int, record: dict):
    data = load_data()
    data[str(user_id)] = record
    save_data(data)


def update_last_active(user_id: int):
    record = get_user_record(user_id)
    record["last_active"] = datetime.utcnow().isoformat()
    update_user_record(user_id, record)


# ========================= دوال مساعدة =========================

def get_streak_delta(record: dict):
    """يرجع فرق الوقت بين الآن وبداية السلسلة (أو 0 لو ما بدأ)."""
    start = record.get("streak_start")
    if not start:
        return None
    try:
        start_dt = datetime.fromisoformat(start)
        now = datetime.utcnow()
        return now - start_dt
    except Exception:
        return None


def format_streak_text(record: dict) -> str:
    delta = get_streak_delta(record)
    if not delta:
        return "لم تبدأ رحلتك بعد.\nاضغط على زر «بدء الرحلة 🚀» لبدء العدّاد."

    total_minutes = int(delta.total_seconds() // 60)
    days = total_minutes // (24 * 60)
    hours = (total_minutes % (24 * 60)) // 60
    minutes = total_minutes % 60

    parts = []
    if days:
        parts.append(f"{days} يوم")
    if hours:
        parts.append(f"{hours} ساعة")
    if minutes or not parts:
        parts.append(f"{minutes} دقيقة")

    text = "⏱️ مدة ثباتك حتى الآن:\n" + "، ".join(parts)
    return text


def calc_level(record: dict) -> int:
    """حساب مستوى بسيط بناءً على عدد الأيام النظيفة."""
    delta = get_streak_delta(record)
    if not delta:
        return 1
    days = delta.days
    if days >= 90:
        return 5
    elif days >= 60:
        return 4
    elif days >= 30:
        return 3
    elif days >= 7:
        return 2
    else:
        return 1


def level_title(level: int) -> str:
    return {
        1: "مبتدئ واعٍ 🌱",
        2: "مقاوم جاد 💪",
        3: "مقاتل ثابت 🛡️",
        4: "منتصر قوي 🏆",
        5: "قدوة مُلهمة 🌟",
    }.get(level, "مبتدئ واعٍ 🌱")


TIPS = [
    "اغلق الهاتف قبل النوم بساعة، وجرب أن تنام على طهارة وذكر.",
    "املأ يومك بمهام صغيرة نافعة؛ الفراغ هو أكبر باب للانتكاس.",
    "اجعل هناك صديقًا صالحًا تخبره بتقدمك؛ المشاركة تقلل العزلة.",
    "اكتب أسباب إقلاعك في ورقة، وضعها في مكان تراه كثيرًا.",
    "كل مرة تقاوم فيها، أنت تعيد برمجة دماغك على العفة.",
]

ADHKAR = [
    "«اللهم اغفر لي، وطهر قلبي، واحفظ فرجي، واصرف عني السوء والفحشاء»",
    "«اللهم إني أعوذ بك من منكرات الأخلاق والأعمال والأهواء»",
    "«اللهم حبِّب إليّ العفة، وكرِّه إليّ الفاحشة، واصرف عني وساوس الشيطان»",
    "استغفر الله العظيم الذي لا إله إلا هو الحي القيوم وأتوب إليه.",
]

EMERGENCY_PLAN = (
    "🆘 *خطة الطوارئ عند لحظة الضعف:*\n\n"
    "1️⃣ غيّر مكانك فورًا (انهض من السرير / اخرج من الحمام).\n"
    "2️⃣ اغسل وجهك وتوضأ وصلِّ ركعتين خفيفتين.\n"
    "3️⃣ امسك الهاتف واكتب ملاحظة عن شعورك الآن بدل أن تبحث عن الحرام.\n"
    "4️⃣ تواصل مع شخص تثق به أو مع الدعم في البوت.\n"
    "5️⃣ اخرج من الغرفة أو البيت لو استطعت، وتحرّك."
)

RELAPSE_CAUSES = (
    "🧠 *أسباب شائعة للانتكاس:*\n\n"
    "• الفراغ الطويل بدون هدف واضح.\n"
    "• استخدام الهاتف ليلًا في السرير.\n"
    "• العزلة، وعدم وجود علاقات صحية.\n"
    "• متابعة حسابات أو محتوى مُثير.\n"
    "• الإنهاك النفسي دون تفريغ صحي (رياضة، مشي، كتابة...).\n\n"
    "حاول أن تعالج السبب قبل أن يظهر أثره."
)

HELP_TEXT = (
    "ℹ️ *دليل استخدام البوت:*\n\n"
    "• «بدء الرحلة 🚀» لبدء العدّاد من الآن.\n"
    "• «عداد الأيام 📅» لعرض مدة ثباتك (أيام + ساعات + دقائق).\n"
    "• «نصيحة 💡» يعطيك نصيحة عشوائية.\n"
    "• «خطة الطوارئ 🆘» لما تحس بلحظة ضعف قوية.\n"
    "• «أسباب الانتكاس 🧠» لتتعرف على أكثر الأسباب شيوعًا.\n"
    "• «أذكار وسكينة 🕊️» لجرعة إيمانية سريعة.\n"
    "• «ملاحظاتي 🗃️» لكتابة ملاحظتك التحفيزية الخاصة.\n"
    "• «إعادة ضبط العداد ♻️» عند حدوث انتكاس (يُسجل التاريخ ويُعاد العدّاد).\n"
    "• «تقييم اليوم ⭐» لتقييم يومك من 1 إلى 5.\n"
    "• «مستواي 💎» يعرض مستواك التقريبي حسب عدد الأيام.\n"
    "• «معرفة حسابي 👤» يعرض ID واسمك وبياناتك الأساسية.\n"
    "• «تواصل مع الدعم ✉️» لإرسال رسالة خاصة للأدمن (إن كان مفعّلًا)."
)

# ========================= لوحات الأزرار =========================

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["بدء الرحلة 🚀", "عداد الأيام 📅"],
        ["نصيحة 💡", "خطة الطوارئ 🆘"],
        ["أسباب الانتكاس 🧠", "أذكار وسكينة 🕊️"],
        ["ملاحظاتي 🗃️", "إعادة ضبط العداد ♻️"],
        ["تقييم اليوم ⭐", "مستواي 💎"],
        ["معرفة حسابي 👤", "تواصل مع الدعم ✉️"],
        ["مساعدة ℹ️"],
    ],
    resize_keyboard=True,
)

# ========================= حالات المحادثات =========================

NOTES_WAITING, SUPPORT_WAITING, RATING_WAITING = range(3)

# ========================= أوامر /start وغيرها =========================

def start(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user.id, update)
    update_last_active(user.id)

    text = (
        f"🍃 أهلاً {user.first_name}!\n\n"
        "هذا بوت *قاهر العادة* لمساعدتك في رحلة الإقلاع عن العادة السرّية.\n"
        "استخدم الأزرار بالأسفل لاختيار ما تحتاجه الآن 👇"
    )
    update.message.reply_text(text, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")


def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(HELP_TEXT, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")


# ========================= معالجات الأزرار الرئيسية =========================

def handle_text(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    user = update.effective_user
    record = get_user_record(user.id, update)
    update_last_active(user.id)

    if text == "بدء الرحلة 🚀":
        now = datetime.utcnow().isoformat()
        if record.get("streak_start"):
            msg = "✅ رحلتك بدأت من قبل، لكن يمكننا الاستمرار من آخر تاريخ مسجل."
        else:
            record["streak_start"] = now
            msg = (
                "🚀 تم بدء رحلتك الآن!\n"
                "من هذه اللحظة سيبدأ العدّاد بحساب مدة ثباتك."
            )
        update_user_record(user.id, record)
        update.message.reply_text(msg, reply_markup=MAIN_KEYBOARD)

    elif text == "عداد الأيام 📅":
        counter_text = format_streak_text(record)
        update.message.reply_text(counter_text, reply_markup=MAIN_KEYBOARD)

    elif text == "إعادة ضبط العداد ♻️":
        now_iso = datetime.utcnow().isoformat()
        # تسجيل انتكاس
        relapses = record.get("relapses", [])
        relapses.append(now_iso)
        record["relapses"] = relapses
        # إعادة ضبط العدّاد من الآن
        record["streak_start"] = now_iso
        update_user_record(user.id, record)

        update.message.reply_text(
            "♻️ تم تسجيل الانتكاس وإعادة ضبط العدّاد من الآن.\n"
            "لا تيأس، المهم أنك ما زلت تحاول 🙏",
            reply_markup=MAIN_KEYBOARD,
        )

    elif text == "نصيحة 💡":
        tip = random.choice(TIPS)
        update.message.reply_text(f"💡 *نصيحة اليوم:*\n\n{tip}", parse_mode="Markdown")

    elif text == "أذكار وسكينة 🕊️":
        dhikr = random.choice(ADHKAR)
        update.message.reply_text(f"🕊️ {dhikr}")

    elif text == "خطة الطوارئ 🆘":
        update.message.reply_text(EMERGENCY_PLAN, parse_mode="Markdown")

    elif text == "أسباب الانتكاس 🧠":
        update.message.reply_text(RELAPSE_CAUSES, parse_mode="Markdown")

    elif text == "ملاحظاتي 🗃️":
        return start_notes(update, context)

    elif text == "تقييم اليوم ⭐":
        return start_rating(update, context)

    elif text == "مستواي 💎":
        lvl = calc_level(record)
        title = level_title(lvl)
        delta = get_streak_delta(record)
        days = delta.days if delta else 0
        update.message.reply_text(
            f"💎 *مستواك الحالي:* {title}\n"
            f"عدد الأيام النظيفة (تقريبًا): {days} يوم.",
            parse_mode="Markdown",
        )

    elif text == "معرفة حسابي 👤":
        username = f"@{user.username}" if user.username else "لا يوجد"
        created_at = record.get("created_at")
        joined_text = ""
        if created_at:
            try:
                dt = datetime.fromisoformat(created_at)
                joined_text = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                joined_text = created_at

        msg = (
            "👤 *معلومات حسابك في البوت:*\n\n"
            f"• ID: `{user.id}`\n"
            f"• الاسم: {user.full_name}\n"
            f"• اسم المستخدم: {username}\n"
            f"• تاريخ أول دخول للبوت: {joined_text}\n"
        )
        update.message.reply_text(msg, parse_mode="Markdown")

    elif text == "تواصل مع الدعم ✉️":
        return start_support(update, context)

    elif text == "مساعدة ℹ️":
        help_command(update, context)

    else:
        # رد افتراضي
        update.message.reply_text(
            "لم أفهم طلبك بالضبط 🤔\n"
            "استخدم الأزرار بالأسفل لاختيار ما تريده.",
            reply_markup=MAIN_KEYBOARD,
        )

    return ConversationHandler.END


# ========================= ملاحظاتي =========================

def start_notes(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🗃️ أرسل الآن ملاحظتك أو جملة تحفيزية تريد أن تتذكّرها عند لحظات الضعف.\n"
        "اكتب ما تشاء في رسالة واحدة.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return NOTES_WAITING


def save_note(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user.id, update)

    note = update.message.text.strip()
    notes = record.get("notes", [])
    notes.append(
        {
            "text": note,
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    record["notes"] = notes
    update_user_record(user.id, record)

    update.message.reply_text(
        "✅ تم حفظ ملاحظتك.\n"
        "ستكون هذه الملاحظة مرجعًا لك عند الحاجة.\n"
        "يمكنك دائمًا كتابة ملاحظات جديدة.",
        reply_markup=MAIN_KEYBOARD,
    )
    return ConversationHandler.END


# ========================= تواصل مع الدعم =========================

def start_support(update: Update, context: CallbackContext):
    if ADMIN_ID is None:
        update.message.reply_text(
            "هذه الميزة غير مفعّلة حاليًا لأن ID الأدمن غير مضبوط في الكود.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    update.message.reply_text(
        "✉️ اكتب الآن رسالتك التي تريد إرسالها للدعم.\n"
        "سيتم إرسالها للأدمن مع معلومات حسابك.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return SUPPORT_WAITING


def send_support_message(update: Update, context: CallbackContext):
    user = update.effective_user
    text = update.message.text.strip()

    # إرسال للأدمن
    try:
        context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "📩 *رسالة دعم جديدة:*\n\n"
                f"من: {user.full_name} (@{user.username})\n"
                f"ID: `{user.id}`\n\n"
                f"المحتوى:\n{text}"
            ),
            parse_mode="Markdown",
        )
        update.message.reply_text(
            "✅ تم إرسال رسالتك للدعم.\n"
            "سيتم التواصل معك إن لزم الأمر.",
            reply_markup=MAIN_KEYBOARD,
        )
    except Exception as e:
        logger.error(f"Error sending support message: {e}")
        update.message.reply_text(
            "حصل خطأ أثناء إرسال الرسالة للدعم.\n"
            "حاول لاحقًا إن استمرّ الخطأ.",
            reply_markup=MAIN_KEYBOARD,
        )

    return ConversationHandler.END


# ========================= تقييم اليوم =========================

def start_rating(update: Update, context: CallbackContext):
    update.message.reply_text(
        "⭐ قيّم يومك من 1 إلى 5 (1 = سيء جدًا، 5 = ممتاز).\n"
        "أرسل رقمًا واحدًا فقط.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return RATING_WAITING


def save_rating(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user.id, update)

    try:
        rating = int(update.message.text.strip())
    except ValueError:
        update.message.reply_text(
            "الرجاء إرسال رقم من 1 إلى 5 فقط.",
        )
        return RATING_WAITING

    if rating < 1 or rating > 5:
        update.message.reply_text(
            "الرجاء إرسال رقم بين 1 و 5 فقط.",
        )
        return RATING_WAITING

    ratings = record.get("daily_ratings", [])
    ratings.append(
        {
            "rating": rating,
            "date": datetime.utcnow().isoformat(),
        }
    )
    record["daily_ratings"] = ratings
    update_user_record(user.id, record)

    comment = {
        1: "اليوم كان صعبًا، لا بأس.. المهم أنك ما زلت هنا 💔",
        2: "ليس أفضل يوم، لكن كل محاولة تُحسب لك 💪",
        3: "يوم متوسط، حاول غدًا أن تجعله أفضل 😊",
        4: "عمل رائع اليوم! استمر على هذا النسق 🔥",
        5: "ممتاز! يوم قوي ومشرّف 👑",
    }.get(rating, "")

    update.message.reply_text(
        f"تم تسجيل تقييمك: {rating}/5\n{comment}",
        reply_markup=MAIN_KEYBOARD,
    )
    return ConversationHandler.END


# ========================= تذكير يومي =========================

def send_daily_reminders(context: CallbackContext):
    data = load_data()
    if not data:
        return

    messages = [
        "تذكّر أن نقاء اليوم هو هدية لنسخة المستقبل منك 🤍",
        "قاوم لدقائق، وستشكر نفسك لساعات.",
        "كل يوم نظيف هو صفعة للعادة السيئة وصفحة بيضاء لك.",
        "لا تنس الدعاء: «اللهم طهّر قلبي وحصّن فرجي».",
    ]

    for key, record in data.items():
        user_id = int(key)
        # نرسل فقط لمن بدأوا الرحلة
        if not record.get("streak_start"):
            continue
        try:
            context.bot.send_message(
                chat_id=user_id,
                text=f"📩 *تذكير يومي:*\n\n{random.choice(messages)}",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Error sending reminder to {user_id}: {e}")


# ========================= دالة main =========================

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set in environment variables.")
        return

    # تشغيل Flask في ثريد منفصل ليبقى Render يعتبر الخدمة حية
    Thread(target=run_flask, daemon=True).start()

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # أوامر بسيطة
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))

    # محادثة الملاحظات
    notes_conv = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex("^ملاحظاتي 🗃️$"), start_notes)],
        states={
            NOTES_WAITING: [
                MessageHandler(Filters.text & ~Filters.command, save_note)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", lambda u, c: u.message.reply_text("تم الإلغاء.", reply_markup=MAIN_KEYBOARD))
        ],
    )
    dp.add_handler(notes_conv)

    # محادثة الدعم
    support_conv = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex("^تواصل مع الدعم ✉️$"), start_support)],
        states={
            SUPPORT_WAITING: [
                MessageHandler(Filters.text & ~Filters.command, send_support_message)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", lambda u, c: u.message.reply_text("تم الإلغاء.", reply_markup=MAIN_KEYBOARD))
        ],
    )
    dp.add_handler(support_conv)

    # محادثة تقييم اليوم
    rating_conv = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex("^تقييم اليوم ⭐$"), start_rating)],
        states={
            RATING_WAITING: [
                MessageHandler(Filters.text & ~Filters.command, save_rating)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", lambda u, c: u.message.reply_text("تم الإلغاء.", reply_markup=MAIN_KEYBOARD))
        ],
    )
    dp.add_handler(rating_conv)

    # هاندلر عام لكل النصوص (الأزرار)
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))

    # تذكير يومي الساعة 20:00 بتوقيت UTC (تقدر تعدلها)
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
