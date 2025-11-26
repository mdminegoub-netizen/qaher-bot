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

# حالات خاصة لكل مستخدم
WAITING_FOR_SUPPORT = set()
WAITING_FOR_BROADCAST = set()
WAITING_FOR_CUSTOM_START = set()
WAITING_FOR_DAY_RATING = set()

# ربط رسالة الأدمن بالمستخدم للرد عن طريق Reply
SUPPORT_THREADS = {}

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


def get_user_record(user):
    """إرجاع سجل المستخدم أو إنشاؤه لو أول مرة"""
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
            "ratings": [],  # تقييم اليوم
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
    record = data[uid]
    record.update(kwargs)
    record["last_active"] = datetime.now(timezone.utc).isoformat()
    save_data(data)


def get_all_user_ids():
    return [int(uid) for uid in data.keys()]


def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID

# =================== حساب مدة الثبات ===================


def get_streak_delta(record):
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
    total_seconds = int(delta.total_seconds())
    total_minutes = total_seconds // 60
    total_hours = total_seconds // 3600
    total_days = total_seconds // 86400
    # تقريب الأشهر على 30 يوماً
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


def get_level_info(record):
    """حساب مستوى المستخدم حسب عدد أيام الثبات"""
    delta = get_streak_delta(record)
    if not delta:
        return 0, "ابدأ رحلتك لتظهر مستوياتك 💪"

    total_days = int(delta.total_seconds() // 86400)

    if total_days < 1:
        level = 1
        title = "شرارة البداية ✨"
    elif total_days < 7:
        level = 2
        title = "مقاتل اليوم الواحد 💥"
    elif total_days < 30:
        level = 3
        title = "صامد الأسابيع 🛡"
    elif total_days < 90:
        level = 4
        title = "بطل الشهَر 🏅"
    else:
        level = 5
        title = "أسطورة الثبات 👑"

    return level, title

# =================== الأزرار ===================

BTN_START = "بدء الرحلة 🚀"
BTN_COUNTER = "عداد الأيام 🗓"
BTN_TIP = "نصيحة 💡"
BTN_EMERGENCY = "خطة الطوارئ 🆘"
BTN_RELAPSE = "أسباب الانتكاس 🧠"
BTN_DHIKR = "أذكار وسكينة 🕊"
BTN_NOTES = "ملاحظاتي 📓"
BTN_RESET = "إعادة ضبط العداد ♻️"
BTN_RATE_DAY = "تقييم اليوم ⭐"
BTN_LEVEL = "مستواي 💎"
BTN_ACCOUNT = "معرفة حسابي 👤"
BTN_SUPPORT = "تواصل مع الدعم ✉️"
BTN_HELP = "مساعدة ℹ️"
BTN_CUSTOM_START = "تعيين بداية التعافي ⏰"
BTN_CANCEL = "إلغاء ❌"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_START), KeyboardButton(BTN_COUNTER)],
        [KeyboardButton(BTN_TIP), KeyboardButton(BTN_EMERGENCY)],
        [KeyboardButton(BTN_RELAPSE), KeyboardButton(BTN_DHIKR)],
        [KeyboardButton(BTN_NOTES), KeyboardButton(BTN_RESET)],
        [KeyboardButton(BTN_RATE_DAY), KeyboardButton(BTN_LEVEL)],
        [KeyboardButton(BTN_ACCOUNT), KeyboardButton(BTN_SUPPORT)],
        [KeyboardButton(BTN_CUSTOM_START), KeyboardButton(BTN_HELP)],
    ],
    resize_keyboard=True,
)

CANCEL_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton(BTN_CANCEL)]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

# =================== رسائل جاهزة (بعدة نصوص) ===================

TIPS = [
    "كل مرة تنتصر فيها على نفسك، تبني نسخة أقوى منك 🤍",
    "غيّر مكانك فور ما تحس بالضعف، الحركة تكسر موجة العادة 💨",
    "قوّة إرادتك عضلة، ومع كل مقاومة تصير أقوى 💪",
    "أطفئ الشاشة قبل النوم بنصف ساعة، واهدأ مع كتاب أو ذكَر 📖",
    "مو لازم تكون مثالي، أهم شيء لا تتوقف عن المحاولة ✨",
    "بدّل وقت الفراغ بهواية بسيطة: مشي، قراءة، تعلّم مهارة جديدة 🚶‍♂️",
]

EMERGENCY_PLAN = (
    "🆘 *خطة الطوارئ وقت اللحظة الحرِجة:*\n"
    "1️⃣ غيّر وضع جسمك فورًا (انهض، امشِ، غيّر الغرفة).\n"
    "2️⃣ ابعد الجوال عن يدك ولو 10 دقائق.\n"
    "3️⃣ خذ 10 أنفاس عميقة ببطء... ركّز على الشهيق والزفير.\n"
    "4️⃣ اقرأ شيئًا يهدّئ قلبك: قرآن، أذكار، أو دعاء تحبه.\n"
    "5️⃣ اكتب شعورك الآن في «ملاحظاتي 📓» بدل ما تكتمه داخلك.\n"
    "انت أقوى من اللحظة هذه، صدّقني 🤍"
)

RELAPSE_LIST = [
    "أحد أشهر أسباب الانتكاس هو *الفراغ الطويل* بدون هدف واضح.\n"
    "املأ يومك بأهداف صغيرة: قراءة، رياضة، تعلّم مهارة جديدة 🎯",
    "كثير من الانتكاسات تبدأ من *تصفح عشوائي* لمواقع أو منصات.\n"
    "ضع لنفسك قواعد واضحة لاستخدام الجوال قبل النوم 📵",
    "العزلة الطويلة تغذّي العادة.\n"
    "حاول تتواصل مع ناس إيجابيين ولو عبر الإنترنت 🤝",
    "التوتر والكبت بدون تفريغ صحي سبب قوي للانتكاس.\n"
    "اكتب مشاعرك، مارس رياضة خفيفة، أو تحدّث مع شخص تثق به 🧠",
]

ADHKAR_LIST = [
    "🕊 *لحظة سكينة:*\n"
    "استغفر الآن 33 مرة من قلبك:\n"
    "«أستغفر الله العظيم وأتوب إليه» 🤍",
    "🕊 *راحة للقلب:*\n"
    "ردّد:\n«لا إله إلا أنت سبحانك إني كنت من الظالمين» 10 مرات.\n"
    "كل مرة تقولها كأنك ترسل نداء استغاثة لرب رحيم 💜",
    "🕊 *طمأنينة:*\n"
    "قل:\n«حسبي الله لا إله إلا هو عليه توكلت وهو رب العرش العظيم» 7 مرات.\n"
    "وكّل أمرك لله، ولن يخيّبك أبدًا 🤍",
]

HELP_TEXT = (
    "ℹ️ *مساعدة سريعة:*\n\n"
    f"{BTN_START} لبدء رحلة التعافي أو التأكيد أنها مستمرة.\n"
    f"{BTN_COUNTER} لعرض مدة ثباتك بالدقائق والساعات والأيام والشهور ⏱\n"
    f"{BTN_TIP} نصائح عشوائية تعينك على الطريق 💡\n"
    f"{BTN_EMERGENCY} خطة إنقاذ وقت الضعف الشديد 🆘\n"
    f"{BTN_RELAPSE} لمعرفة أسباب الانتكاس وكيف تتجنبها 🧠\n"
    f"{BTN_DHIKR} جرعة أذكار تهدّي القلب 🕊\n"
    f"{BTN_NOTES} لكتابة مشاعرك وأفكارك كملاحظات خاصة 📓\n"
    f"{BTN_RESET} لإعادة ضبط العداد كبداية جديدة ♻️\n"
    f"{BTN_RATE_DAY} قيّم يومك وراقب تحسّن حالتك يومًا بعد يوم ⭐\n"
    f"{BTN_LEVEL} عرض مستواك حسب عدد أيام الثبات 💎\n"
    f"{BTN_ACCOUNT} لمعرفة معلومات حسابك وتاريخ انضمامك 👤\n"
    f"{BTN_SUPPORT} للتواصل مع الدعم وطرح أي استفسار ✉️\n"
    f"{BTN_CUSTOM_START} لتعيين بداية التعافي يدويًا (مثلاً لديك أسبوع مسبقًا) ⏰\n\n"
    "لو تحس أنك تائه، ابدأ من زر *بدء الرحلة 🚀* والباقي بيجي خطوة خطوة 🤍"
)

# =================== أوامر البوت ===================


def start_command(update: Update, context: CallbackContext):
    user = update.effective_user
    get_user_record(user)

    text = (
        f"أهلاً يا {user.first_name} 🌱\n\n"
        "هذا بوت *قاهر العادة* يساعدك تمسك زمام حياتك من جديد ✨\n"
        "استخدم الأزرار بالأسفل واختَر الشيء اللي تحتاجه الآن 👇"
    )
    update.message.reply_text(text, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")


def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        HELP_TEXT, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown"
    )

# =================== وظائف الأزرار الأساسية ===================


def handle_start_journey(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    if record.get("streak_start"):
        delta = get_streak_delta(record)
        if delta:
            human = format_streak_text(delta)
            update.message.reply_text(
                f"رحلتك شغّالة أصلاً يا بطل 💪\nمدة ثباتك الحالية: {human} ⏱",
                reply_markup=MAIN_KEYBOARD,
            )
            return

    now = datetime.now(timezone.utc).isoformat()
    update_user_record(user.id, streak_start=now)

    update.message.reply_text(
        "🚀 تم تشغيل عدّاد رحلتك!\n"
        "كل دقيقة ثبات من الآن فصاعدًا تُحتسب انتصار لك 🤍",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_days_counter(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    delta = get_streak_delta(record)
    if not delta:
        update.message.reply_text(
            "لسّه ما حدّدنا بداية رحلتك 🙈\n"
            "اضغط على «بدء الرحلة 🚀» أو استخدم «تعيين بداية التعافي ⏰».",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    human = format_streak_text(delta)
    update.message.reply_text(
        f"⏱ مدة ثباتك حتى الآن:\n{human}\n"
        "استمر، المستقبل الجميل ينتظر صبرك 🤍",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_tip(update: Update, context: CallbackContext):
    tip = random.choice(TIPS)
    update.message.reply_text(
        f"💡 *دفعة تحفيز اليوم:*\n{tip}",
        reply_markup=MAIN_KEYBOARD,
        parse_mode="Markdown",
    )


def handle_emergency(update: Update, context: CallbackContext):
    update.message.reply_text(
        EMERGENCY_PLAN, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown"
    )


def handle_relapse_reasons(update: Update, context: CallbackContext):
    msg = random.choice(RELAPSE_LIST)
    update.message.reply_text(
        f"🧠 *نقطة وعي عن الانتكاس:*\n{msg}",
        reply_markup=MAIN_KEYBOARD,
        parse_mode="Markdown",
    )


def handle_adhkar(update: Update, context: CallbackContext):
    msg = random.choice(ADHKAR_LIST)
    update.message.reply_text(
        msg, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown"
    )


def handle_notes(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)
    notes = record.get("notes", [])

    if not notes:
        update.message.reply_text(
            "📓 دفتر ملاحظاتك جاهز!\n"
            "أرسل أي فكرة أو شعور يخطر في بالك وسأحفظه لك كمساحة آمنة 🤍",
            reply_markup=MAIN_KEYBOARD,
        )
    else:
        joined = "\n\n".join(f"• {n}" for n in notes[-20:])
        update.message.reply_text(
            f"📓 *آخر ملاحظاتك:*\n\n{joined}\n\n"
            "أرسل ملاحظة جديدة متى ما احتجت تفضفض أو تكتب فكرة ✍️",
            reply_markup=MAIN_KEYBOARD,
            parse_mode="Markdown",
        )


def handle_reset_counter(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    if not record.get("streak_start"):
        update.message.reply_text(
            "ما عندنا عدّاد شغّال أساسًا 😅\n"
            "ابدأ من زر «بدء الرحلة 🚀» أو حدّد البداية يدويًا من «تعيين بداية التعافي ⏰».",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    now = datetime.now(timezone.utc).isoformat()
    update_user_record(user.id, streak_start=now)

    update.message.reply_text(
        "♻️ تم تصفير العداد.\n"
        "لا تنظر لها كخسارة، بل كدرس جديد وبداية أذكى 🙏",
        reply_markup=MAIN_KEYBOARD,
    )

# =================== تواصل مع الدعم ===================


def handle_contact_support(update: Update, context: CallbackContext):
    user = update.effective_user
    WAITING_FOR_SUPPORT.add(user.id)

    # كيبورد صغيرة فقط فيها إلغاء
    update.message.reply_text(
        "✉️ اكتب الآن رسالتك للدعم.\n"
        "حاول تشرح وضعك أو سؤالك براحتك، وكل شيء يبقى سري 🤍",
        reply_markup=CANCEL_KEYBOARD,
    )

# =================== معلومات الحساب / المستوى / التقييم / بداية التعافي ===================


def handle_account_info(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    created_at = record.get("created_at")
    try:
        created_dt = datetime.fromisoformat(created_at)
        created_str = created_dt.strftime("%Y-%m-%d")
    except Exception:
        created_str = created_at

    delta = get_streak_delta(record)
    if delta:
        streak_text = format_streak_text(delta)
    else:
        streak_text = "لم تُحدد بداية رحلتك بعد."

    text = (
        "👤 *معلومات حسابك:*\n\n"
        f"• الاسم: {user.full_name}\n"
        f"• المعرف (ID): `{user.id}`\n"
        f"• اسم المستخدم: @{user.username if user.username else 'لا يوجد'}\n"
        f"• تاريخ الانضمام للبوت: {created_str}\n"
        f"• حالة التعافي الحالية: {streak_text}\n"
    )
    update.message.reply_text(
        text, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown"
    )


def handle_level(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    level, title = get_level_info(record)
    if level == 0:
        update.message.reply_text(
            f"{title}\n\n"
            "ابدأ من زر «بدء الرحلة 🚀» أو استخدم «تعيين بداية التعافي ⏰».",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    delta = get_streak_delta(record)
    days = int(delta.total_seconds() // 86400)
    update.message.reply_text(
        f"💎 *مستواك الحالي: المستوى {level}*\n"
        f"{title}\n\n"
        f"عدد أيام ثباتك التقريبية: {days} يوم.\n"
        "استمر في رفع مستواك، كل يوم جديد نقطة خبرة إضافية ✨",
        reply_markup=MAIN_KEYBOARD,
        parse_mode="Markdown",
    )


def handle_rate_day_button(update: Update, context: CallbackContext):
    user = update.effective_user
    WAITING_FOR_DAY_RATING.add(user.id)

    update.message.reply_text(
        "⭐ قيّم يومك اليوم من 1 إلى 5:\n"
        "1 😞 يوم صعب\n"
        "5 🔥 يوم ممتاز\n"
        "اكتب رقم واحد فقط.\n",
        reply_markup=CANCEL_KEYBOARD,
    )


def handle_custom_start_button(update: Update, context: CallbackContext):
    user = update.effective_user
    WAITING_FOR_CUSTOM_START.add(user.id)

    update.message.reply_text(
        "⏰ جميل إن عندك ثبات من قبل! 🙌\n"
        "اكتب الآن عدد *الأيام* التي مرّت منذ آخر انتكاسة.\n"
        "مثال: لو عندك أسبوع تعافي، اكتب: 7",
        reply_markup=CANCEL_KEYBOARD,
    )

# =================== تذكير يومي (عن طريق JobQueue) ===================


def send_daily_reminders(context: CallbackContext):
    logger.info("Running daily reminders job...")
    for uid in get_all_user_ids():
        try:
            context.bot.send_message(
                chat_id=uid,
                text=(
                    "🤍 تذكير لطيف:\n"
                    "مهما كان ما مرّ عليك اليوم، رجع تحكمك لنفسك الآن.\n"
                    "زر واحد من الأزرار تحت ممكن يغيّر مزاجك لليوم كله ✨"
                ),
            )
        except Exception as e:
            logger.error(f"Error sending daily reminder to {uid}: {e}")

# =================== أوامر للأدمن: بث و إحصائيات ===================


def broadcast_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if not is_admin(user.id):
        update.message.reply_text("هذه الميزة خاصة بالمشرف فقط 👨‍💻")
        return

    WAITING_FOR_BROADCAST.add(user.id)
    update.message.reply_text(
        "📢 اكتب الآن الرسالة التي تريد إرسالها لجميع مستخدمي البوت.",
        reply_markup=CANCEL_KEYBOARD,
    )


def stats_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if not is_admin(user.id):
        update.message.reply_text("هذه المعلومة خاصة بالمشرف فقط 👨‍💻")
        return

    total = len(get_all_user_ids())
    update.message.reply_text(
        f"👥 عدد المستخدمين المسجلين في البوت: *{total}*",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )

# =================== هاندلر الرسائل العامة ===================


def handle_text_message(update: Update, context: CallbackContext):
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id
    text = (update.message.text or "").strip()

    record = get_user_record(user)  # يتأكد أنه مسجّل ويحدّث آخر نشاط

    # 0️⃣ لو الأدمن يرد بـ Reply على رسالة دعم
    if chat_id == ADMIN_ID and update.message.reply_to_message:
        orig_id = update.message.reply_to_message.message_id
        target_user_id = SUPPORT_THREADS.get(orig_id)
        if target_user_id:
            try:
                context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"📨 *ردّ من الدعم:*\n\n{text}",
                    parse_mode="Markdown",
                )
                update.message.reply_text(
                    "✅ تم إرسال ردّك للمستخدم 💌",
                    quote=True,
                )
            except Exception as e:
                logger.error(f"Error sending admin reply to {target_user_id}: {e}")
                update.message.reply_text(
                    "حدث خطأ أثناء إرسال الرد للمستخدم ❗️"
                )
            return

    # زر إلغاء عام
    if text == BTN_CANCEL:
        WAITING_FOR_SUPPORT.discard(user_id)
        WAITING_FOR_BROADCAST.discard(user_id)
        WAITING_FOR_CUSTOM_START.discard(user_id)
        WAITING_FOR_DAY_RATING.discard(user_id)

        update.message.reply_text(
            "تم الإلغاء والعودة للقائمة الرئيسية ✅",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # 1️⃣ وضع "تواصل مع الدعم"
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
                SUPPORT_THREADS[sent.message_id] = user_id
            except Exception as e:
                logger.error(f"Error sending support message to admin: {e}")

        update.message.reply_text(
            "✅ تم إرسال رسالتك للدعم.\n"
            "لو احتجنا تفاصيل إضافية، راح نرجع نتواصل معك بإذن الله 🤍",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # 2️⃣ وضع "رسالة جماعية" للأدمن
    if user_id in WAITING_FOR_BROADCAST:
        WAITING_FOR_BROADCAST.remove(user_id)

        if not is_admin(user_id):
            update.message.reply_text(
                "هذه الميزة خاصة بالمشرف فقط 👨‍💻", reply_markup=MAIN_KEYBOARD
            )
            return

        sent_count = 0
        for uid in get_all_user_ids():
            try:
                context.bot.send_message(
                    chat_id=uid,
                    text=f"📢 *رسالة من الدعم:*\n\n{text}",
                    parse_mode="Markdown",
                )
                sent_count += 1
            except Exception as e:
                logger.error(f"Error sending broadcast to {uid}: {e}")

        update.message.reply_text(
            f"✅ تم إرسال الرسالة إلى {sent_count} مستخدم 🎯",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # 3️⃣ وضع "تعيين بداية التعافي"
    if user_id in WAITING_FOR_CUSTOM_START:
        try:
            days = int(text)
            if days < 0:
                raise ValueError
        except ValueError:
            update.message.reply_text(
                "أرسل رقم أيام صحيح فقط (مثال: 7) 😊",
                reply_markup=CANCEL_KEYBOARD,
            )
            return

        WAITING_FOR_CUSTOM_START.remove(user_id)

        start_dt = datetime.now(timezone.utc) - timedelta(days=days)
        update_user_record(user_id, streak_start=start_dt.isoformat())

        delta = get_streak_delta(get_user_record(user))
        human = format_streak_text(delta)

        update.message.reply_text(
            f"✅ تم تعيين بداية التعافي قبل {days} يوم.\n"
            f"مدة ثباتك الآن تقريبًا: {human} ⏱\n"
            "استمر يا بطل، عدّادك يمشي من اليوم اللي اخترته 🙌",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # 4️⃣ وضع "تقييم اليوم"
    if user_id in WAITING_FOR_DAY_RATING:
        try:
            rating = int(text)
            if rating < 1 or rating > 5:
                raise ValueError
        except ValueError:
            update.message.reply_text(
                "اكتب رقم من 1 إلى 5 فقط يا صديقي ⭐",
                reply_markup=CANCEL_KEYBOARD,
            )
            return

        WAITING_FOR_DAY_RATING.remove(user_id)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ratings = record.get("ratings", [])
        ratings = [r for r in ratings if r.get("date") != today]
        ratings.append({"date": today, "rating": rating})
        update_user_record(user_id, ratings=ratings)

        msg_map = {
            1: "يوم صعب… لكن مجرد تقييمك له خطوة وعي قوية جدًا 🤍",
            2: "يوم متوسط، بكرة نقدر نخليه أحسن إن شاء الله 🌱",
            3: "يوم مقبول، حافظ على خطواتك الجيدة وطورها شوي 💪",
            4: "يوم جميل، استمر على نفس النسق الرائع ✨",
            5: "يوم أسطوري! استغل طاقتك لبناء عادة ثابتة 🔥",
        }

        update.message.reply_text(
            f"تم حفظ تقييمك لليوم: {rating}/5 ⭐\n{msg_map.get(rating, '')}",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # 5️⃣ التعامل مع الأزرار
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
    elif text == BTN_ACCOUNT:
        handle_account_info(update, context)
    elif text == BTN_LEVEL:
        handle_level(update, context)
    elif text == BTN_RATE_DAY:
        handle_rate_day_button(update, context)
    elif text == BTN_CUSTOM_START:
        handle_custom_start_button(update, context)
    elif text == BTN_HELP:
        help_command(update, context)
    else:
        # أي نص آخر → نحفظه كملاحظة
        notes = record.get("notes", [])
        notes.append(text)
        update_user_record(user_id, notes=notes)

        update.message.reply_text(
            "📝 تم حفظ رسالتك كملاحظة شخصية.\n"
            "تقدر ترجع لها من زر «ملاحظاتي 📓» متى ما حبيت 🤍",
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
    dp.add_handler(CommandHandler("broadcast", broadcast_command))
    dp.add_handler(CommandHandler("stats", stats_command))

    # جميع الرسائل النصية (بعد الأوامر)
    dp.add_handler(
        MessageHandler(Filters.text & ~Filters.command, handle_text_message)
    )

    # تذكير يومي عن طريق JobQueue (الساعة 20:00 بتوقيت السيرفر)
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
