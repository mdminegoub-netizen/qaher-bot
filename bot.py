import os
import json
import logging
import random
from datetime import datetime, timezone, timedelta, time
from threading import Thread

from flask import Flask

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
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
ADMIN_ID = 931350292  # عدّل هذا للـ ID تبعك لو حاب

# حالات خاصة بالمستخدمين
WAITING_FOR_SUPPORT = set()          # يكتب رسالة دعم
WAITING_FOR_BROADCAST = set()       # الأدمن يكتب رسالة جماعية
WAITING_FOR_SET_START = set()       # يكتب عدد الأيام لبداية التعافي
WAITING_FOR_RATING = set()          # يكتب تقييم اليوم

# ربط رسالة الدعم عند الأدمن بالمستخدم الأصلي (للرد بالـ Reply)
ADMIN_INBOX = {}  # key: admin_message_id -> user_id

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
    now_iso = datetime.now(timezone.utc).isoformat()

    if user_id not in data:
        data[user_id] = {
            "user_id": user.id,
            "first_name": user.first_name,
            "username": user.username,
            "created_at": now_iso,
            "last_active": now_iso,
            "streak_start": None,
            "notes": [],
            "ratings": [],  # [{date: 'YYYY-MM-DD', score: int}]
        }
        save_data(data)
    else:
        record = data[user_id]
        record["last_active"] = now_iso
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
    """
    يحدد هل المستخدم أدمن أم لا:
    1) لو ADMIN_ID مضبوط ويطابق user_id → أدمن.
    2) لو ما فيه ADMIN_ID صحيح → أول مستخدم دخل البوت يُعتبر الأدمن.
    """
    try:
        if ADMIN_ID is not None and user_id == ADMIN_ID:
            return True

        # fallback: أول مستخدم في الداتا
        if data:
            owner = sorted(
                data.values(),
                key=lambda r: r.get("created_at", "")
            )[0]
            owner_id = owner.get("user_id")
            if owner_id and user_id == owner_id:
                return True
    except Exception as e:
        logger.error(f"Error checking admin: {e}")

    return False

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
    # نحسب دائماً (شهر، يوم، ساعة، دقيقة) حتى لو صفر
    total_minutes = int(delta.total_seconds() // 60)

    minutes_in_hour = 60
    minutes_in_day = 24 * minutes_in_hour
    minutes_in_month = 30 * minutes_in_day  # تقريباً

    months = total_minutes // minutes_in_month
    rem = total_minutes % minutes_in_month

    days = rem // minutes_in_day
    rem = rem % minutes_in_day

    hours = rem // minutes_in_hour
    minutes = rem % minutes_in_hour

    return f"{months} شهر، {days} يوم، {hours} ساعة، {minutes} دقيقة"

# =================== الأزرار الرئيسية ===================

BTN_START = "بدء الرحلة 🚀"
BTN_COUNTER = "عداد الأيام 🗓"
BTN_TIP = "نصيحة 💡"
BTN_EMERGENCY = "خطة الطوارئ 🆘"
BTN_RELAPSE = "أسباب الانتكاس 🧠"
BTN_DHIKR = "أذكار وسكينة 🕊"
BTN_NOTES = "ملاحظاتي 📓"
BTN_RESET = "إعادة ضبط العداد ♻️"
BTN_RATING = "تقييم اليوم ⭐️"
BTN_LEVEL = "مستواي 💎"
BTN_ACCOUNT = "معرفة حسابي 👤"
BTN_SUPPORT = "تواصل مع الدعم ✉️"
BTN_SET_START = "تعيين بداية التعافي ⏰"
BTN_HELP = "مساعدة ℹ️"
BTN_BROADCAST = "رسالة جماعية 📢"
BTN_STATS = "عدد المستخدمين 👥"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_START), KeyboardButton(BTN_COUNTER)],
        [KeyboardButton(BTN_TIP), KeyboardButton(BTN_EMERGENCY)],
        [KeyboardButton(BTN_RELAPSE), KeyboardButton(BTN_DHIKR)],
        [KeyboardButton(BTN_NOTES), KeyboardButton(BTN_RESET)],
        [KeyboardButton(BTN_RATING), KeyboardButton(BTN_LEVEL)],
        [KeyboardButton(BTN_ACCOUNT), KeyboardButton(BTN_SUPPORT)],
        [KeyboardButton(BTN_SET_START), KeyboardButton(BTN_HELP)],
        [KeyboardButton(BTN_BROADCAST), KeyboardButton(BTN_STATS)],
    ],
    resize_keyboard=True,
)

# =================== رسائل جاهزة ===================

TIPS = [
    "💡 جرّب تبدأ يومك بدون هاتف أول 30 دقيقة… هذا يعطيك قوة تحكم في نفسك طول اليوم.",
    "💡 كل مرة تقول (لا) للعادة، أنت تبني احترامك لنفسك وتقرّب من النسخة اللي تحلم تكونها.",
    "💡 غيّر مكانك فور ما تحس بضعف: قم، تحرك، اغسل وجهك… الحركة تكسر الموجة.",
    "💡 راقب أفكارك قبل الانتكاس… غالباً تبدأ بفكرة صغيرة؛ أوقفها من أول لحظة.",
    "💡 أحط نفسك بأهداف يومية بسيطة: قراءة، رياضة خفيفة، تعلم شيء جديد.",
    "💡 لو تعبت لا تكره نفسك… اعتبر التعب إشارة للراحة وليس مبررًا للانتكاس.",
    "💡 التقدم الحقيقي هو أن تكون اليوم أفضل من أمس ولو بنسبة 1٪ فقط.",
    "💡 دوّن إنجازاتك الصغيرة في ملاحظاتك… سترى أنك أقوى مما تتخيل.",
]

ADHKAR_LIST = [
    "🕊 *لحظة سكينة:*\n\n«أستغفر الله العظيم وأتوب إليه» ١٠ مرات… قلها بتركيز واستشعار، وليس بسرعة فقط.",
    "🕊 *راحة قلب:*\n\n«لا إله إلا أنت سبحانك إني كنت من الظالمين» ٣ مرات… هذه دعوة يونس عليه السلام في الكرب.",
    "🕊 *طمأنينة:*\n\n«حسبي الله لا إله إلا هو عليه توكلت وهو رب العرش العظيم» ٧ مرات.",
    "🕊 *هدوء قبل النوم:*\n\nاقرأ آية الكرسي وسورة الإخلاص والمعوذتين بنية الحفظ والستر.",
]

RELAPSE_LIST = [
    "🧠 *سبب شائع للانتكاس:* استخدام الهاتف في السرير مع إضاءة خافتة.\nالحل: اجعل الشحن بعيدًا عن السرير واغلق الإنترنت قبل النوم.",
    "🧠 *سبب شائع:* الفراغ الطويل بدون خطة لليوم.\nالحل: اكتب ٣ مهام فقط لليوم ونفذها مهما كان مزاجك.",
    "🧠 *سبب شائع:* الإحباط والشعور أن (ما في أمل).\nالحل: تذكّر أن كل بطل مرّ بفترات سقوط، لكن الفارق أنه استمر بالقيام.",
    "🧠 *سبب شائع:* متابعة محتوى (خفيف) لكنه يلمّح للإثارة.\nالحل: كن حازمًا؛ احذف المصادر المريبة ولو كانت مشهورة.",
]

EMERGENCY_PLAN = (
    "🆘 *خطة الطوارئ عند لحظة الضعف:*\n"
    "1️⃣ غيّر وضع جسمك فورًا (انهض/اجلس/تحرك).\n"
    "2️⃣ اخرج من المكان الذي يثيرك ولو لخمس دقائق في الهواء.\n"
    "3️⃣ خذ 10 أنفاس عميقة ببطء… شهيق 4 ثوانٍ، حبس 4، زفير 4.\n"
    "4️⃣ افتح زر «أذكار وسكينة 🕊» أو «نصيحة 💡» وخذ دفعة معنوية.\n"
    "5️⃣ اكتب شعورك الآن في «ملاحظاتي 📓» بدل ما تكتمه بداخلك.\n"
)

HELP_TEXT = (
    "ℹ️ *مساعدة سريعة:*\n\n"
    "• ابدأ من زر «بدء الرحلة 🚀» ليبدأ العداد.\n"
    "• زر «عداد الأيام 🗓» يعرض لك مدة ثباتك (شهر/يوم/ساعة/دقيقة).\n"
    "• لو كنت ثابتًا من قبل، استخدم «تعيين بداية التعافي ⏰» لتحديد الأيام السابقة.\n"
    "• «تقييم اليوم ⭐️» يساعدك تراجع نفسك في نهاية اليوم.\n"
    "• لو احتجت شخص يسمعك، استخدم «تواصل مع الدعم ✉️» واكتب ما تشاء.\n\n"
    "أنا هنا لأمشي معك خطوة خطوة يا بطل 🤍"
)

# =================== أوامر البوت ===================


def start_command(update: Update, context: CallbackContext):
    user = update.effective_user
    get_user_record(user)

    text = (
        f"أهلاً {user.first_name} 🌱\n\n"
        "هذا بوت *قاهر العادة* يساعدك في رحلة التعافي من العادة السرّية.\n"
        "اختر من الأزرار بالأسفل ما تحتاجه الآن 👇"
    )

    update.message.reply_text(text, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")


def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(HELP_TEXT, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")

# =================== وظائف الأزرار ===================


def handle_start_journey(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    delta = get_streak_delta(record)
    if delta:
        human = format_streak_text(delta)
        update.message.reply_text(
            f"🚀 رحلتك بدأت من قبل.\nمدة ثباتك الحالية:\n{human}",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    now = datetime.now(timezone.utc).isoformat()
    update_user_record(user.id, streak_start=now)

    update.message.reply_text(
        "🚀 انطلاقة جديدة!\nتم بدء رحلتك، ومن الآن سيبدأ حساب مدة ثباتك 🤍",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_days_counter(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    delta = get_streak_delta(record)
    if not delta:
        update.message.reply_text(
            "لم تبدأ رحلتك بعد.\n"
            "اضغط على زر «بدء الرحلة 🚀» أو استخدم «تعيين بداية التعافي ⏰».",
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
    update.message.reply_text(tip, reply_markup=MAIN_KEYBOARD)


def handle_emergency(update: Update, context: CallbackContext):
    update.message.reply_text(
        EMERGENCY_PLAN, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown"
    )


def handle_relapse_reasons(update: Update, context: CallbackContext):
    msg = random.choice(RELAPSE_LIST)
    update.message.reply_text(msg, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")


def handle_adhkar(update: Update, context: CallbackContext):
    msg = random.choice(ADHKAR_LIST)
    update.message.reply_text(msg, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")


def handle_notes(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)
    notes = record.get("notes", [])

    if not notes:
        update.message.reply_text(
            "📓 لا توجد ملاحظات بعد.\n"
            "أرسل أي جملة تشعر بها الآن وسأحفظها لك كملاحظة.",
            reply_markup=MAIN_KEYBOARD,
        )
    else:
        joined = "\n\n".join(f"• {n}" for n in notes[-20:])
        update.message.reply_text(
            f"📓 آخر ملاحظاتك:\n\n{joined}\n\n"
            "أرسل رسالة جديدة لإضافة ملاحظة أخرى.",
            reply_markup=MAIN_KEYBOARD,
        )


def handle_reset_counter(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    if not record.get("streak_start"):
        update.message.reply_text(
            "العداد لم يُضبط بعد.\n"
            "ابدأ من زر «بدء الرحلة 🚀» أو «تعيين بداية التعافي ⏰».",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    now = datetime.now(timezone.utc).isoformat()
    update_user_record(user.id, streak_start=now)

    update.message.reply_text(
        "♻️ تم إعادة ضبط العداد.\n"
        "ابدأ من هذه اللحظة بقلب أقوى وعزيمة أنضج 💪",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_rating_button(update: Update, context: CallbackContext):
    user = update.effective_user
    get_user_record(user)

    WAITING_FOR_RATING.add(user.id)
    update.message.reply_text(
        "⭐️ قيّم يومك من 1 إلى 10 (1 سيء جدًا، 10 ممتاز).\n"
        "أرسل رقمًا واحدًا فقط.",
        reply_markup=ReplyKeyboardRemove(),
    )


def handle_level(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    delta = get_streak_delta(record)
    if not delta:
        update.message.reply_text(
            "لم تبدأ رحلتك بعد، لذلك لا يوجد مستوى حاليًا.\n"
            "ابدأ من زر «بدء الرحلة 🚀».",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    days = int(delta.total_seconds() // 86400)
    if days < 7:
        level = "مبتدئ 🔰"
    elif days < 30:
        level = "مقاتل 💪"
    elif days < 90:
        level = "صامد 🛡"
    else:
        level = "أسطورة التعافي 🏆"

    human = format_streak_text(delta)
    update.message.reply_text(
        f"💎 مستواك الحالي: *{level}*\n"
        f"⏱ مدة ثباتك: {human}",
        reply_markup=MAIN_KEYBOARD,
        parse_mode="Markdown",
    )


def handle_account_info(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    created = record.get("created_at")
    try:
        created_dt = datetime.fromisoformat(created).astimezone(timezone.utc)
        created_text = created_dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        created_text = created

    text = (
        "👤 *بيانات حسابك في البوت:*\n\n"
        f"• الاسم: {user.full_name}\n"
        f"• ID: `{user.id}`\n"
        f"• اسم المستخدم: @{user.username if user.username else 'لا يوجد'}\n"
        f"• تاريخ أول استخدام للبوت: {created_text}"
    )

    update.message.reply_text(text, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")


def handle_set_start_button(update: Update, context: CallbackContext):
    user = update.effective_user
    get_user_record(user)

    WAITING_FOR_SET_START.add(user.id)
    update.message.reply_text(
        "⏰ اكتب عدد الأيام التي أنت ثابت فيها بدون انتكاس حتى الآن.\n"
        "مثال: لو لك أسبوع نظيف ارسل: 7",
        reply_markup=ReplyKeyboardRemove(),
    )


def handle_help_button(update: Update, context: CallbackContext):
    update.message.reply_text(HELP_TEXT, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")

# ====== تواصل مع الدعم / رسالة جماعية / إحصائيات ======


def handle_contact_support(update: Update, context: CallbackContext):
    user = update.effective_user
    get_user_record(user)

    WAITING_FOR_SUPPORT.add(user.id)

    update.message.reply_text(
        "✉️ اكتب الآن رسالتك التي تريد إرسالها للدعم.\n"
        "سأرسلها للأدمن مع معلومات حسابك.\n\n"
        "اكتب ما تشعر به بحرية يا بطل 🤍",
        reply_markup=ReplyKeyboardRemove(),
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
        reply_markup=ReplyKeyboardRemove(),
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
                    "أنت أقوى من العادة… خطوة صغيرة اليوم أفضل من لا شيء.\n"
                    "لو احتجت دفعة، استخدم أحد الأزرار بالأسفل ✨"
                ),
            )
        except Exception as e:
            logger.error(f"Error sending daily reminder to {uid}: {e}")

# =================== هاندلر الرسائل العامة ===================


def handle_text_message(update: Update, context: CallbackContext):
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id
    text = update.message.text.strip()
    message = update.message

    record = get_user_record(user)

    # 0️⃣ لو الأدمن يرد بالـ Reply على رسالة دعم
    if is_admin(user_id) and message.reply_to_message:
        original_msg_id = message.reply_to_message.message_id
        target_user_id = ADMIN_INBOX.get(original_msg_id)
        if target_user_id:
            try:
                context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"💬 رد من الدعم:\n\n{text}",
                )
                message.reply_text("✅ تم إرسال ردّك للمستخدم.", reply_markup=MAIN_KEYBOARD)
            except Exception as e:
                logger.error(f"Error sending admin reply to {target_user_id}: {e}")
                message.reply_text("حدث خطأ أثناء إرسال الرد للمستخدم.", reply_markup=MAIN_KEYBOARD)
            return

    # 1️⃣ وضع تواصل مع الدعم
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
                ADMIN_INBOX[sent.message_id] = user_id
            except Exception as e:
                logger.error(f"Error sending support message to admin: {e}")

        message.reply_text(
            "✅ تم إرسال رسالتك للدعم.\n"
            "سيتم التواصل معك إن لزم الأمر 🤍",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # 2️⃣ وضع رسالة جماعية (للأدمن)
    if user_id in WAITING_FOR_BROADCAST:
        WAITING_FOR_BROADCAST.remove(user_id)

        if not is_admin(user_id):
            message.reply_text(
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

        message.reply_text(
            f"✅ تم إرسال الرسالة إلى {sent} مستخدم.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # 3️⃣ وضع تعيين بداية التعافي
    if user_id in WAITING_FOR_SET_START:
        WAITING_FOR_SET_START.remove(user_id)
        try:
            days_clean = int(text)
            if days_clean < 0:
                raise ValueError
        except ValueError:
            message.reply_text(
                "من فضلك أرسل رقمًا صحيحًا يمثل عدد الأيام (مثل: 7).",
                reply_markup=MAIN_KEYBOARD,
            )
            return

        now = datetime.now(timezone.utc)
        start_dt = now - timedelta(days=days_clean)
        update_user_record(user_id, streak_start=start_dt.isoformat())

        delta = get_streak_delta(get_user_record(user))
        human = format_streak_text(delta)

        message.reply_text(
            f"⏰ تم تعيين بداية التعافي منذ {days_clean} يوم.\n"
            f"⏱ مدة ثباتك الآن:\n{human}",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # 4️⃣ وضع تقييم اليوم
    if user_id in WAITING_FOR_RATING:
        WAITING_FOR_RATING.remove(user_id)
        try:
            score = int(text)
            if not 1 <= score <= 10:
                raise ValueError
        except ValueError:
            message.reply_text(
                "أرسل رقمًا من 1 إلى 10 فقط لتقييم يومك ⭐️.",
                reply_markup=MAIN_KEYBOARD,
            )
            return

        today = datetime.now(timezone.utc).date().isoformat()
        ratings = record.get("ratings", [])
        ratings.append({"date": today, "score": score})
        update_user_record(user_id, ratings=ratings)

        message.reply_text(
            f"✅ تم حفظ تقييمك لليوم ({score}/10).\n"
            "غدًا نحاول نكون أفضل ولو 1٪ 🙌",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # 5️⃣ الأزرار
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
    elif text == BTN_RATING:
        handle_rating_button(update, context)
    elif text == BTN_LEVEL:
        handle_level(update, context)
    elif text == BTN_ACCOUNT:
        handle_account_info(update, context)
    elif text == BTN_SUPPORT:
        handle_contact_support(update, context)
    elif text == BTN_SET_START:
        handle_set_start_button(update, context)
    elif text == BTN_HELP:
        handle_help_button(update, context)
    elif text == BTN_BROADCAST:
        handle_broadcast_button(update, context)
    elif text == BTN_STATS:
        handle_stats_button(update, context)
    else:
        # 6️⃣ أي نص آخر → نعتبره ملاحظة شخصية
        notes = record.get("notes", [])
        notes.append(text)
        update_user_record(user_id, notes=notes)

        message.reply_text(
            "📝 تم حفظ ملاحظتك.\n"
            "استخدم زر «ملاحظاتي 📓» لعرض آخر ما كتبت.",
            reply_markup=MAIN_KEYBOARD,
        )

# =================== تشغيل البوت ===================


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN غير موجود في متغيرات البيئة!")

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # أوامر
    dp.add_handler(CommandHandler("start", start_command))
    dp.add_handler(CommandHandler("help", help_command))

    # جميع الرسائل النصية
    dp.add_handler(
        MessageHandler(Filters.text & ~Filters.command, handle_text_message)
    )

    # تذكير يومي عبر JobQueue (الساعة 20:00 بتوقيت السيرفر)
    job_queue = updater.job_queue
    job_queue.run_daily(
        send_daily_reminders,
        time=time(hour=20, minute=0),
        name="daily_reminders",
    )

    # تشغيل Flask في ثريد منفصل
    Thread(target=run_flask, daemon=True).start()

    logger.info("Bot is starting...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
