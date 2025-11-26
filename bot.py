import os
import json
import logging
import random
from datetime import datetime, timezone, timedelta, time
from threading import Thread

import pytz
from flask import Flask

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
ADMIN_ID = 931350292  # عدّل هذا للـ ID تبعك

# حالات خاصة للمستخدمين
WAITING_FOR_SUPPORT = set()
WAITING_FOR_BROADCAST = set()

# خريطة لربط رسالة الدعم عند الأدمن بالمستخدم الأصلي (للرد عبر Reply)
ADMIN_REPLY_MAP = {}

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
        logger.error(f"Error saving data: {e}")


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

    months = total_days // 30
    days = total_days % 30
    hours = total_hours % 24
    minutes = total_minutes % 60

    # ✅ دايمًا نعرض كل الوحدات حتى لو صفر
    return f"{months} شهر، {days} يوم، {hours} ساعة، {minutes} دقيقة"

# =================== الأزرار ===================

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
BTN_CANCEL = "إلغاء ❌"

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

CANCEL_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton(BTN_CANCEL)]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

# =================== رسائل جاهزة ===================

TIPS = [
    "💡 تذكّر: كل دقيقة تصبر فيها تبني نسخة أقوى من نفسك.",
    "💡 غيّر مكانك فوراً لما تحس بالضعف، الحركة تكسر موجة العادة.",
    "💡 اشغل يدك بشيء نافع: كتابة، قراءة، تمارين بسيطة، أو ترتيب غرفتك.",
    "💡 قل لنفسك: «هذه الرغبة مؤقتة، لكن فخري بنفسي لو صبرت رح يبقى طويل» 💪.",
    "💡 قلّل العزلة، وجود الناس حولك يقلل فرص السقوط بشكل كبير.",
]

EMERGENCY_PLAN = (
    "🆘 *خطة الطوارئ لحظة الضعف:*\n"
    "1️⃣ غيّر وضع جسمك فورًا (انهض من السرير، اجلس، تحرك).\n"
    "2️⃣ اترك الجهاز أو المكان المثير ولو لخمس دقائق.\n"
    "3️⃣ خذ نفسًا عميقًا 10 مرات ببطء وركّز على الشهيق والزفير.\n"
    "4️⃣ افتح قسم «أذكار وسكينة 🕊» أو استمع لسورة تحبها.\n"
    "5️⃣ اكتب شعورك الآن في «ملاحظاتي 📓» بدل ما تكبته.\n"
    "أهم شيء: *لا تبقى وحدك مع الفكرة* 🔥."
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
    "ردّد ما يرتاح له قلبك بتركيز وهدوء 🌿."
)

HELP_TEXT = (
    "ℹ️ *طريقة استخدام البوت:*\n\n"
    "• «بدء الرحلة 🚀»: يبدأ عدّاد ثباتك من الآن.\n"
    "• «عداد الأيام 🗓»: يريك الشهور والأيام والساعات والدقائق.\n"
    "• «إعادة ضبط العداد ♻️»: لو حصلت انتكاسة وتريد بداية جديدة.\n"
    "• «تواصل مع الدعم ✉️»: تتواصل مع الأدمن مباشرة.\n\n"
    "استخدم الأزرار اللي تناسب حالتك، خطوة خطوة 💪."
)

# =================== أوامر البوت ===================


def start_command(update: Update, context: CallbackContext):
    user = update.effective_user

    # هل المستخدم جديد فعلاً؟
    is_new = str(user.id) not in data
    record = get_user_record(user)

    # إشعار للأدمن لو دخل مستخدم جديد لأول مرة
    if is_new and ADMIN_ID is not None:
        try:
            context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "🆕 مستخدم جديد دخل البوت!\n\n"
                    f"👤 الاسم: {user.full_name}\n"
                    f"🆔 ID: `{user.id}`\n"
                    f"🔹 اسم المستخدم: @{user.username if user.username else 'لا يوجد'}\n"
                    f"📅 وقت التسجيل (UTC): {record.get('created_at')}"
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Error notifying admin about new user: {e}")

    text = (
        f"أهلاً {user.first_name} 🌱\n\n"
        "هذا بوت *قاهر العادة* يساعدك في رحلة التعافي من العادة السرّية.\n"
        "اختر من الأزرار بالأسفل ما تحتاجه الآن 👇"
    )

    update.message.reply_text(text, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")


def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        HELP_TEXT,
        reply_markup=MAIN_KEYBOARD,
        parse_mode="Markdown",
    )

# =================== وظائف الأزرار ===================


def handle_start_journey(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    if record.get("streak_start"):
        delta = get_streak_delta(record)
        if delta:
            human = format_streak_text(delta)
            update.message.reply_text(
                f"🚀 رحلتك بدأت من قبل.\nمدة ثباتك الحالية: {human}.",
                reply_markup=MAIN_KEYBOARD,
            )
            return

    now = datetime.now(timezone.utc).isoformat()
    update_user_record(user.id, streak_start=now)

    update.message.reply_text(
        "🚀 تم بدء رحلتك بنجاح!\n"
        "من الآن سيتم حساب مدة ثباتك عن آخر انتكاسة.\n"
        "شد حيلك، كل لحظة صبر ترفع مستواك 💪",
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
    update.message.reply_text(
        f"💡 نصيحة تحفيزية:\n{tip}", reply_markup=MAIN_KEYBOARD
    )


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
        joined = "\n\n".join(f"• {n}" for n in notes[-20:])
        update.message.reply_text(
            f"📓 آخر ملاحظاتك:\n\n{joined}\n\n"
            "أرسل ملاحظة جديدة لأي فكرة أو شعور تريد حفظه.",
            reply_markup=MAIN_KEYBOARD,
        )


def handle_reset_counter(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

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
        "اعتبرها بداية جديدة أقوى بإذن الله، ولا تيأس أبدًا 🤍.",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_contact_support(update: Update, context: CallbackContext):
    user = update.effective_user
    WAITING_FOR_SUPPORT.add(user.id)

    update.message.reply_text(
        "✉️ اكتب الآن رسالتك التي تريد إرسالها للدعم.\n"
        "اكتب بارتياح، لن يرى رسالتك أحد غير الأدمن.\n\n"
        "لو حبيت تتراجع اضغط «إلغاء ❌».",
        reply_markup=CANCEL_KEYBOARD,
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
        "📢 اكتب الآن الرسالة التي تريد إرسالها لجميع مستخدمي البوت.\n"
        "أو اضغط «إلغاء ❌» للرجوع بدون إرسال.",
        reply_markup=CANCEL_KEYBOARD,
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

    record = get_user_record(user)

    # 0️⃣ زر الإلغاء
    if text == BTN_CANCEL:
        WAITING_FOR_SUPPORT.discard(user_id)
        WAITING_FOR_BROADCAST.discard(user_id)
        update.message.reply_text(
            "تم الإلغاء ✅ رجعناك للوضع العادي.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # 1️⃣ رد الأدمن عبر Reply
    if is_admin(user_id) and update.message.reply_to_message:
        original_msg_id = update.message.reply_to_message.message_id
        target_user_id = ADMIN_REPLY_MAP.get(original_msg_id)
        if target_user_id:
            try:
                context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"📬 رد من الدعم:\n\n{text}",
                )
                update.message.reply_text(
                    "✅ تم إرسال ردك للمستخدم.", reply_markup=MAIN_KEYBOARD
                )
            except Exception as e:
                logger.error(f"Error sending admin reply to user {target_user_id}: {e}")
                update.message.reply_text(
                    "حدث خطأ أثناء إرسال الرد للمستخدم.", reply_markup=MAIN_KEYBOARD
                )
            return

    # 2️⃣ وضع "تواصل مع الدعم"
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
                sent = context.bot.send_message(
                    chat_id=ADMIN_ID, text=support_msg, parse_mode="Markdown"
                )
                ADMIN_REPLY_MAP[sent.message_id] = user_id
            except Exception as e:
                logger.error(f"Error sending support message to admin: {e}")

        update.message.reply_text(
            "✅ تم إرسال رسالتك للدعم.\n"
            "سيتم التواصل معك إن لزم الأمر 🤍",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # 3️⃣ وضع "رسالة جماعية"
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
                context.bot.send_message(
                    chat_id=uid, text=f"📢 رسالة من الدعم:\n\n{text}"
                )
                sent += 1
            except Exception as e:
                logger.error(f"Error sending broadcast to {uid}: {e}")

        update.message.reply_text(
            f"✅ تم إرسال الرسالة إلى {sent} مستخدم.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # 4️⃣ الأزرار
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
                    "خذ دقيقة تتنفس بعمق، وتذكر ليش قررت تتعافى، "
                    "واضغط على الزر اللي تحسه أنسب لك الآن ✨."
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
    job_queue = updater.job_queue

    dp.add_handler(CommandHandler("start", start_command))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text_message))

    # تذكير يومي 20:00 UTC باستخدام pytz.UTC
    job_queue.run_daily(
        send_daily_reminders,
        time=time(hour=20, minute=0, tzinfo=pytz.UTC),
        name="daily_reminders",
    )

    # تشغيل Flask في ثريد منفصل
    Thread(target=run_flask, daemon=True).start()

    logger.info("Bot is starting...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
