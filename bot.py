import os
import json
import logging
import random
from datetime import datetime, timezone, timedelta
from threading import Thread

from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)

# =================== إعدادات أساسية ===================

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "user_data.json"

# ضع هنا ID الأدمن (بدون علامات تنصيص)
# مثال: ADMIN_ID = 931350292
ADMIN_ID = 931350292  # عدّل هذا للـ ID تبعك

# مستخدمون في وضع "تواصل مع الدعم"
WAITING_FOR_SUPPORT = set()

# الأدمن في وضع "رسالة جماعية"
WAITING_FOR_BROADCAST = set()

# ملف اللوج
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# =================== خادم ويب بسيط لـ Render ===================

app = Flask(__name__)


@app.route("/")
def index():
    return "Qaher-bot is running ✅"


def run_flask():
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

# =================== تخزين بيانات المستخدمين ===================


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
        logger.error(f"Error saving data: {e})


data = load_data()


def get_user_record(user: "telegram.User"):
    user_id = str(user.id)
    if user_id not in data:
        now = datetime.now(timezone.utc).isoformat()
        data[user_id] = {
            "user_id": user.id,
            "first_name": user.first_name,
            "username": user.username,
            "created_at": now,
            "last_active": now,
            "streak_start": None,
            "notes": [],
        }
        save_data(data)
    else:
        # تحديث آخر نشاط + اسم المستخدم لو تغيّر
        record = data[user_id]
        record["last_active"] = datetime.now(timezone.utc).isoformat()
        record["first_name"] = user.first_name
        record["username"] = user.username
        save_data(data)
    return data[user_id]


def update_user_record(user_id: int, **kwargs):
    uid = str(user_id)
    if uid not in data:
        return
    data[uid].update(kwargs)
    data[uid]["last_active"] = datetime.now(timezone.utc).isoformat()
    save_data(data)


def get_all_user_ids():
    return [int(uid) for uid in data.keys()]


def is_admin(user_id: int) -> bool:
    if ADMIN_ID is None:
        return False
    return user_id == ADMIN_ID

# =================== حساب مدة الثبات ===================


def get_streak_delta(record) -> timedelta | None:
    start_iso = record.get("streak_start")
    if not start_iso:
        return None
    try:
        start_dt = datetime.fromisoformat(start_iso)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return now - start_dt
    except Exception as e:
        logger.error(f"Error parsing streak_start: {e}")
        return None


def format_streak_text(delta: timedelta) -> str:
    total_minutes = int(delta.total_seconds() // 60)
    total_hours = int(delta.total_seconds() // 3600)
    total_days = int(delta.total_seconds() // 86400)
    # تقريب الأشهر على أساس 30 يوماً
    months = total_days // 30
    days = total_days % 30
    hours = total_hours % 24
    minutes = total_minutes % 60

    parts = []
    if months:
        parts.append(f"{months} شهر")
    if days:
        parts.append(f"{days} يوم")
    if hours:
        parts.append(f"{hours} ساعة")
    if minutes or not parts:
        parts.append(f"{minutes} دقيقة")

    return "، ".join(parts)

# =================== الأزرار الرئيسية ===================

BTN_START = "بدء الرحلة 🚀"
BTN_COUNTER = "عداد الأيام 🗓"
BTN_TIP = "نصيحة 💡"
BTN_EMERGENCY = "خطة الطوارئ 🆘"
BTN_RELAPSE = "أسباب الانتكاس 🧠"
BTN_DHIKR = "أذكار وسكينة 🕊"
BTN_NOTES = "ملاحظاتي 📓"
BTN_RESET = "إعادة ضبط العداد ♻️"
BTN_SUPPORT = "تواصل مع الدعم ✉️"
BTN_BROADCAST = "رسالة جماعية 📢"
BTN_STATS = "عدد المستخدمين 👥"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_START), KeyboardButton(BTN_COUNTER)],
        [KeyboardButton(BTN_TIP), KeyboardButton(BTN_EMERGENCY)],
        [KeyboardButton(BTN_RELAPSE), KeyboardButton(BTN_DHIKR)],
        [KeyboardButton(BTN_NOTES), KeyboardButton(BTN_RESET)],
        [KeyboardButton(BTN_SUPPORT)],
        [KeyboardButton(BTN_BROADCAST), KeyboardButton(BTN_STATS)],
    ],
    resize_keyboard=True,
)

# =================== رسائل جاهزة ===================

TIPS = [
    "غيّر مكانك فوراً عندما تشعر بالضعف، الحركة تكسر موجة العادة.",
    "تذكّر أن كل دقيقة ثبات هي انتصار صغير يبني شخصية جديدة.",
    "اهتم بالنوم الجيد، التعب يُضعف قدرتك على المقاومة.",
    "اشغل يديك بشيء نافع: كتابة، رسم، قراءة، أو تمرين بسيط.",
]

EMERGENCY_PLAN = (
    "🆘 *خطة الطوارئ عند لحظة الضعف:*\n"
    "1️⃣ غيّر وضع جسمك فوراً (انهض/اجلس/تحرك).\n"
    "2️⃣ اخرج من المكان الذي يثيرك ولو لخمس دقائق.\n"
    "3️⃣ خذ نفسًا عميقًا 10 مرات ببطء.\n"
    "4️⃣ اقرأ ما تحفظ من القرآن أو استمع لسورة تحبها.\n"
    "5️⃣ ذكّر نفسك بسبب إقلاعك عن العادة واكتب شعورك في ملاحظاتك."
)

RELAPSE_REASONS = (
    "🧠 *أسباب الانتكاس الشائعة:*\n"
    "• الفراغ وعدم وجود أهداف واضحة.\n"
    "• استخدام الهاتف في السرير ووقت متأخر.\n"
    "• متابعة محتوى مُثير ولو كان \"بريئًا\" ظاهريًا.\n"
    "• العزلة والابتعاد عن الناس لفترات طويلة.\n"
    "حاول تلاحظ السبب الأقرب لك وتعالجه مباشرة."
)

ADHKAR = (
    "🕊 *أذكار وسكينة:*\n"
    "• أستغفر الله العظيم وأتوب إليه.\n"
    "• لا إله إلا أنت سبحانك إني كنت من الظالمين.\n"
    "• حسبي الله لا إله إلا هو عليه توكلت وهو رب العرش العظيم.\n"
    "ردّد ما يرتاح له قلبك بتركيز وهدوء."
)

# =================== أوامر البوت ===================


def start_command(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    text = (
        f"أهلاً {user.first_name} 🌱\n\n"
        "هذا بوت *قاهر العادة* لمساعدتك في رحلة الإقلاع عن العادة السرّية.\n"
        "استخدم الأزرار بالأسفل لاختيار ما تحتاجه الآن 👇"
    )

    update.message.reply_text(text, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")

    # لو ما عنده بداية رحلة نتركها None حتى يضغط بدء الرحلة
    # (لا نعدّل شيء هنا)


def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "استخدم الأزرار بالأسفل للتحكم في البوت.\n"
        "لو احتجت مساعدة إضافية اضغط على زر «تواصل مع الدعم ✉️».",
        reply_markup=MAIN_KEYBOARD,
    )

# =================== وظائف الأزرار ===================


def handle_start_journey(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    # لو كان عنده بداية من قبل، نذكّره فقط
    if record.get("streak_start"):
        delta = get_streak_delta(record)
        if delta:
            human = format_streak_text(delta)
            update.message.reply_text(
                f"🚀 رحلتك بدأت من قبل.\nمدة ثباتك الحالية: {human}."
            )
            return

    # بداية جديدة
    now = datetime.now(timezone.utc).isoformat()
    update_user_record(user.id, streak_start=now)

    update.message.reply_text(
        "🚀 تم بدء رحلتك بنجاح!\n"
        "من الآن سيتم حساب مدة ثباتك عن آخر انتكاسة.",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_days_counter(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    delta = get_streak_delta(record)
    if not delta:
        update.message.reply_text(
            "لم تبدأ رحلتك بعد.\n"
            "اضغط على زر «بدء الرحلة 🚀» لبدء العداد.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    human = format_streak_text(delta)
    update.message.reply_text(
        f"⏱ مدة ثباتك حتى الآن:\n{human}",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_tip(update: Update, context: CallbackContext):
    tip = random.choice(TIPS)
    update.message.reply_text(f"💡 نصيحة اليوم:\n{tip}", reply_markup=MAIN_KEYBOARD)


def handle_emergency(update: Update, context: CallbackContext):
    update.message.reply_text(
        EMERGENCY_PLAN, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown"
    )


def handle_relapse_reasons(update: Update, context: CallbackContext):
    update.message.reply_text(
        RELAPSE_REASONS, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown"
    )


def handle_adhkar(update: Update, context: CallbackContext):
    update.message.reply_text(
        ADHKAR, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown"
    )


def handle_notes(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)
    notes = record.get("notes", [])

    if not notes:
        update.message.reply_text(
            "📓 لا توجد ملاحظات بعد.\n"
            "أرسل لي أي جملة تريد حفظها، وأنا سأضيفها إلى ملاحظاتك.",
            reply_markup=MAIN_KEYBOARD,
        )
    else:
        joined = "\n\n".join(f"• {n}" for n in notes[-20:])  # آخر 20 ملاحظة
        update.message.reply_text(
            f"📓 آخر ملاحظاتك:\n\n{joined}\n\n"
            "أرسل ملاحظة جديدة لأي فكرة أو شعور تريد حفظه.",
            reply_markup=MAIN_KEYBOARD,
        )


def handle_reset_counter(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    # لو أصلاً ما عنده بداية
    if not record.get("streak_start"):
        update.message.reply_text(
            "العداد لم يُضبط بعد.\n"
            "يمكنك البدء من جديد عبر زر «بدء الرحلة 🚀».",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    now = datetime.now(timezone.utc).isoformat()
    update_user_record(user.id, streak_start=now)

    update.message.reply_text(
        "♻️ تم إعادة ضبط العداد.\n"
        "اعتبرها بداية جديدة أقوى بإذن الله.",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_contact_support(update: Update, context: CallbackContext):
    user = update.effective_user
    WAITING_FOR_SUPPORT.add(user.id)

    update.message.reply_text(
        "✉️ اكتب الآن رسالتك التي تريد إرسالها للدعم.\n"
        "سيتم إرسالها للأدمن مع معلومات حسابك.",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_broadcast_button(update: Update, context: CallbackContext):
    user = update.effective_user
    if not is_admin(user.id):
        update.message.reply_text(
            "هذه الميزة خاصة بالمشرف فقط 👨‍💻", reply_markup=MAIN_KEYBOARD
        )
        return

    WAITING_FOR_BROADCAST.add(user.id)
    update.message.reply_text(
        "📢 اكتب الآن الرسالة التي تريد إرسالها لجميع مستخدمي البوت.",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_stats_button(update: Update, context: CallbackContext):
    user = update.effective_user
    if not is_admin(user.id):
        update.message.reply_text(
            "هذه المعلومة خاصة بالمشرف فقط 👨‍💻", reply_markup=MAIN_KEYBOARD
        )
        return

    total_users = len(get_all_user_ids())
    update.message.reply_text(
        f"👥 عدد المستخدمين المسجلين في البوت: *{total_users}*",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )

# =================== هاندلر الرسائل العامة ===================


def handle_text_message(update: Update, context: CallbackContext):
    user = update.effective_user
    user_id = user.id
    text = update.message.text.strip()

    record = get_user_record(user)  # يتأكد أنه مسجّل ويحدّث آخر نشاط

    # 1️⃣ أولوية: وضع "تواصل مع الدعم"
    if user_id in WAITING_FOR_SUPPORT:
        WAITING_FOR_SUPPORT.remove(user_id)

        support_msg = (
            "📩 *رسالة جديدة للدعم:*\n\n"
            f"👤 الاسم: {user.full_name}\n"
            f"🆔 ID: `{user_id}`\n"
            f"🔹 اسم المستخدم: @{user.username if user.username else 'لا يوجد'}\n\n"
            f"✉️ محتوى الرسالة:\n{text}"
        )

        if ADMIN_ID is not None:
            try:
                context.bot.send_message(
                    chat_id=ADMIN_ID, text=support_msg, parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Error sending support message to admin: {e}")

        update.message.reply_text(
            "✅ تم إرسال رسالتك للدعم.\n"
            "سيتم التواصل معك إن لزم الأمر 🤍",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # 2️⃣ أولوية: وضع "رسالة جماعية" (للأدمن فقط)
    if user_id in WAITING_FOR_BROADCAST:
        WAITING_FOR_BROADCAST.remove(user_id)

        if not is_admin(user_id):
            update.message.reply_text(
                "هذه الميزة خاصة بالمشرف فقط 👨‍💻", reply_markup=MAIN_KEYBOARD
            )
            return

        user_ids = get_all_user_ids()
        sent = 0
        for uid in user_ids:
            try:
                context.bot.send_message(chat_id=uid, text=f"📢 رسالة من الدعم:\n\n{text}")
                sent += 1
            except Exception as e:
                logger.error(f"Error sending broadcast to {uid}: {e}")

        update.message.reply_text(
            f"✅ تم إرسال الرسالة إلى {sent} مستخدم.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # 3️⃣ التعامل مع الأزرار
    if text == BTN_START:
        handle_start_journey(update, context)
    elif text == BTN_COUNTER:
        handle_days_counter(update, context)
    elif text == BTN_TIP:
        handle_tip(update, context)
    elif text == BTN_EMERGENCY:
        handle_emergency(update, context)
    elif text == BTN_RELAPSE:
        handle_relapse_reasons(update, context)
    elif text == BTN_DHIKR:
        handle_adhkar(update, context)
    elif text == BTN_NOTES:
        handle_notes(update, context)
    elif text == BTN_RESET:
        handle_reset_counter(update, context)
    elif text == BTN_SUPPORT:
        handle_contact_support(update, context)
    elif text == BTN_BROADCAST:
        handle_broadcast_button(update, context)
    elif text == BTN_STATS:
        handle_stats_button(update, context)
    else:
        # أي نص آخر → نعتبره ملاحظة شخصية
        notes = record.get("notes", [])
        notes.append(text)
        update_user_record(user_id, notes=notes)

        update.message.reply_text(
            "📝 تم حفظ ملاحظتك.\n"
            "استخدم زر «ملاحظاتي 📓» لعرض آخر ما كتبت.",
            reply_markup=MAIN_KEYBOARD,
        )

# =================== تذكير يومي ===================


def send_daily_reminders(context: CallbackContext):
    logger.info("Running daily reminders job...")
    user_ids = get_all_user_ids()
    for uid in user_ids:
        try:
            context.bot.send_message(
                chat_id=uid,
                text=(
                    "🤍 تذكير لطيف:\n"
                    "أنت لست وحدك في هذه الرحلة.\n"
                    "خذ دقيقة لتتذكر سبب إقلاعك، واضغط على أي زر تحتاجه الآن."
                ),
            )
        except Exception as e:
            logger.error(f"Error sending daily reminder to {uid}: {e}")

# =================== تشغيل البوت ===================


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN غير موجود في متغيرات البيئة!")

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # أوامر
    dp.add_handler(CommandHandler("start", start_command))
    dp.add_handler(CommandHandler("help", help_command))

    # جميع الرسائل النصية (بعد الأوامر)
    dp.add_handler(
        MessageHandler(Filters.text & ~Filters.command, handle_text_message)
    )

    # جدولة التذكير اليومي (مثال: 20:00 بتوقيت UTC)
    scheduler = BackgroundScheduler(timezone=timezone.utc)
    scheduler.add_job(
        lambda: send_daily_reminders(updater.job_queue),
        "cron",
        hour=20,
        minute=0,
        id="daily_reminders",
        replace_existing=True,
    )
    scheduler.start()

    # تشغيل Flask في ثريد منفصل
    Thread(target=run_flask, daemon=True).start()

    logger.info("Bot is starting...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
