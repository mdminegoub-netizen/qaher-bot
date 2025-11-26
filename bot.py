import os
import json
import logging
import random
import re
from datetime import datetime, timezone, timedelta, time
from threading import Thread

from flask import Flask

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
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

# حالات خاصة للمستخدمين
WAITING_FOR_SUPPORT = set()      # مستخدم يكتب رسالة للدعم
WAITING_FOR_BROADCAST = set()    # الأدمن يكتب رسالة جماعية
WAITING_FOR_DATE = set()         # مستخدم يضبط بداية التعافي يدوياً

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
    """إرجاع سجل المستخدم، وإن لم يكن موجوداً يتم إنشاؤه."""
    user_id = str(user.id)
    now = datetime.now(timezone.utc).isoformat()

    if user_id not in data:
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
        record["last_active"] = now
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

# =================== الأزرار ===================

BTN_START = "بدء الرحلة 🚀"
BTN_COUNTER = "عداد الأيام 🗓"
BTN_TIP = "نصيحة 💡"
BTN_EMERGENCY = "خطة الطوارئ 🆘"
BTN_RELAPSE = "أسباب الانتكاس 🧠"
BTN_DHIKR = "أذكار وسكينة 🕊"
BTN_NOTES = "ملاحظاتي 📓"
BTN_RESET = "إعادة ضبط العداد ♻️"
BTN_RATE = "تقييم اليوم ⭐️"
BTN_LEVEL = "مستواي 💎"
BTN_ACCOUNT = "معرفة حسابي 👤"
BTN_SUPPORT = "تواصل مع الدعم ✉️"
BTN_SET_DATE = "تعيين بداية التعافي ⏱"
BTN_HELP = "مساعدة ℹ️"
BTN_BROADCAST = "رسالة جماعية 📢"
BTN_STATS = "عدد المستخدمين 👥"
BTN_CANCEL = "إلغاء ❌"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_START), KeyboardButton(BTN_COUNTER)],
        [KeyboardButton(BTN_TIP), KeyboardButton(BTN_EMERGENCY)],
        [KeyboardButton(BTN_RELAPSE), KeyboardButton(BTN_DHIKR)],
        [KeyboardButton(BTN_NOTES), KeyboardButton(BTN_RESET)],
        [KeyboardButton(BTN_RATE), KeyboardButton(BTN_LEVEL)],
        [KeyboardButton(BTN_ACCOUNT), KeyboardButton(BTN_SUPPORT)],
        [KeyboardButton(BTN_SET_DATE), KeyboardButton(BTN_HELP)],
        [KeyboardButton(BTN_BROADCAST), KeyboardButton(BTN_STATS)],
    ],
    resize_keyboard=True,
)

SMALL_CANCEL_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton(BTN_CANCEL)]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

# =================== رسائل جاهزة ===================

TIPS = [
    "💡 غيّر مكانك فوراً عندما تشعر بالضعف، الحركة تكسر موجة العادة.",
    "💡 تذكّر أن كل دقيقة ثبات هي انتصار صغير يبني نسخة أقوى منك.",
    "💡 اهتم بالنوم الجيد، التعب يُضعف قدرتك على المقاومة.",
    "💡 اشغل يديك بشيء نافع: كتابة، رسم، قراءة، أو تمرين بسيط.",
    "💡 قلّل الجلوس مع الهاتف لوحدك، واستبدله بالناس أو بالكتاب.",
]

EMERGENCY_PLAN = (
    "🆘 *خطة الطوارئ عند لحظة الضعف:*\n"
    "1️⃣ غيّر وضع جسمك فوراً (انهض/اجلس/تحرك).\n"
    "2️⃣ اخرج من المكان الذي يثيرك ولو لخمس دقائق.\n"
    "3️⃣ خذ نفسًا عميقًا 10 مرات ببطء.\n"
    "4️⃣ استمع لشيء يهدّئك: قرآن، أنشودة هادئة، أو بودكاست نافع.\n"
    "5️⃣ اكتب شعورك في «ملاحظاتي 📓» بدل ما تكتمه.\n"
    "6️⃣ تذكّر: موجة الشهوة قصيرة، لكن أثر قرارك طويل جداً 💪."
)

RELAPSE_REASONS = (
    "🧠 *أسباب الانتكاس الشائعة:*\n"
    "• الفراغ وعدم وجود أهداف واضحة لليوم.\n"
    "• استخدام الهاتف في السرير ووقت متأخر.\n"
    "• متابعة محتوى مُثير ولو كان \"بريئًا\" ظاهريًا.\n"
    "• العزلة والابتعاد عن الناس لفترات طويلة.\n"
    "• الملل وعدم وجود بدائل ممتعة.\n"
    "حاول تلاحظ السبب الأقرب لك وتعالجه مباشرة، خطوة صغيرة تصنع فرقًا كبيرًا ✨."
)

ADHKAR_LIST = [
    "🕊 *جرعة سكينة سريعة:*\n\n"
    "﴿ أَلَا بِذِكْرِ اللَّهِ تَطْمَئِنُّ الْقُلُوبُ ﴾\n\n"
    "ردّد بهدوء: *أستغفر الله العظيم وأتوب إليه* ٣٣ مرة 🤍",
    "🕊 *دعاء جميل وقت التعب:*\n\n"
    "« اللهم إني أعوذ بك من منكرات الأخلاق والأعمال والأهواء »\n\n"
    "قلها من قلبك، واسمح لنفسك أن تبدأ صفحة أنظف 💫",
    "🕊 *ذكر قصير وأجره عظيم:*\n\n"
    "« لا إله إلا الله وحده لا شريك له، له الملك وله الحمد وهو على كل شيء قدير »\n\n"
    "قلها 10 مرات الآن، واهدِ أجرها لنفسك المستقبلية القوية 🔥",
]

HELP_TEXT = (
    "ℹ️ *طريقة استخدام البوت:*\n\n"
    "• استخدم «بدء الرحلة 🚀» لبدء عداد التعافي.\n"
    "• «عداد الأيام 🗓» يعرض لك مدة ثباتك بالدقائق والساعات والأيام والشهور.\n"
    "• عند الانتكاس استخدم «إعادة ضبط العداد ♻️» وابدأ من جديد بدون جلد ذات.\n"
    "• «ملاحظاتي 📓» لحفظ أفكارك ومشاعرك.\n"
    "• «تقييم اليوم ⭐️» لمراجعة يومك سريعًا.\n"
    "• لو احتجت شخص يسمعك استخدم «تواصل مع الدعم ✉️».\n\n"
    "استمر، أنت تبني عادة جديدة وهوية جديدة خطوة خطوة 💪✨."
)

# =================== أوامر البوت ===================


def start_command(update: Update, context: CallbackContext):
    user = update.effective_user
    user_id_str = str(user.id)
    is_new_user = user_id_str not in data

    record = get_user_record(user)

    # إشعار للأدمن عند دخول مستخدم جديد
    if is_new_user and ADMIN_ID is not None:
        try:
            username = f"@{user.username}" if user.username else "لا يوجد"
            context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "🆕 مستخدم جديد دخل البوت!\n\n"
                    f"👤 الاسم: {user.full_name}\n"
                    f"🆔 ID: `{user.id}`\n"
                    f"🔹 يوزر: {username}"
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Error sending new user notification: {e}")

    text = (
        f"أهلاً {user.first_name} 🌱\n\n"
        "هذا بوت *قاهر العادة* لمساعدتك في رحلة الإقلاع عن العادة السرّية.\n"
        "استخدم الأزرار بالأسفل لاختيار ما تحتاجه الآن 👇"
    )

    update.message.reply_text(text, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")


def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(HELP_TEXT, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")

# =================== وظائف الأزرار ===================


def handle_start_journey(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    if record.get("streak_start"):
        delta = get_streak_delta(record)
        if delta:
            human = format_streak_text(delta)
            update.message.reply_text(
                f"🚀 رحلتك بدأت من قبل.\nمدة ثباتك الحالية: {human} 🔥",
                reply_markup=MAIN_KEYBOARD,
            )
            return

    now = datetime.now(timezone.utc).isoformat()
    update_user_record(user.id, streak_start=now)

    update.message.reply_text(
        "🚀✨ تم بدء رحلتك بنجاح!\n"
        "من الآن سيتم حساب مدة ثباتك عن آخر انتكاسة.\n"
        "أنا معك خطوة بخطوة 💪",
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
        f"⏱ مدة ثباتك حتى الآن:\n{human} 🙌",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_tip(update: Update, context: CallbackContext):
    tip = random.choice(TIPS)
    update.message.reply_text(tip, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")


def handle_emergency(update: Update, context: CallbackContext):
    update.message.reply_text(
        EMERGENCY_PLAN, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown"
    )


def handle_relapse_reasons(update: Update, context: CallbackContext):
    update.message.reply_text(
        RELAPSE_REASONS, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown"
    )


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
            "اكتب أي فكرة أو شعور الآن وسأحفظه لك كملاحظة.",
            reply_markup=MAIN_KEYBOARD,
        )
    else:
        joined = "\n\n".join(f"• {n}" for n in notes[-20:])
        update.message.reply_text(
            f"📓 آخر ملاحظاتك:\n\n{joined}\n\n"
            "اكتب ملاحظة جديدة متى ما احتجت تفضفض أو ترتّب أفكارك 📝",
            reply_markup=MAIN_KEYBOARD,
        )


def handle_reset_counter(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    if not record.get("streak_start"):
        update.message.reply_text(
            "العداد لم يُضبط بعد.\n"
            "يمكنك البدء عبر زر «بدء الرحلة 🚀».",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    now = datetime.now(timezone.utc).isoformat()
    update_user_record(user.id, streak_start=now)

    update.message.reply_text(
        "♻️ تم إعادة ضبط العداد.\n"
        "لا جلد ذات، اعتبرها بداية أنضج وأقوى بإذن الله 💪",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_rate_day(update: Update, context: CallbackContext):
    update.message.reply_text(
        "⭐️ قيّم يومك من 1 إلى 5 في رأسك الآن.\n"
        "لو كان أقل من 3، اختر زر «خطة الطوارئ 🆘» أو «نصيحة 💡» وخذ خطوة صغيرة تحسّن بها غدك ✨",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_level(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)
    delta = get_streak_delta(record)

    if not delta:
        update.message.reply_text(
            "مستواك الحالي: *مستكشف مبتدئ* 🌱\n"
            "ابدأ الرحلة أولاً عبر زر «بدء الرحلة 🚀».",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    days = (delta.days) + (delta.seconds // 86400)
    if days < 7:
        level = "مستكشف مبتدئ 🌱"
    elif days < 30:
        level = "مقاتل صاعد ⚔️"
    elif days < 90:
        level = "محارب ثابت 🛡"
    else:
        level = "أسطورة التعافي 🏆"

    human = format_streak_text(delta)
    update.message.reply_text(
        f"💎 مستواك الحالي: *{level}*\nمدة ثباتك: {human} 🙌",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_account_info(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)
    username = f"@{user.username}" if user.username else "لا يوجد"

    created_at = record.get("created_at")
    if created_at:
        try:
            created_dt = datetime.fromisoformat(created_at)
            created_str = created_dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            created_str = created_at
    else:
        created_str = "غير متوفر"

    delta = get_streak_delta(record)
    human = format_streak_text(delta) if delta else "لم تبدأ رحلتك بعد"

    text = (
        "👤 *معلومات حسابك:*\n\n"
        f"الاسم: {user.full_name}\n"
        f"اليوزر: {username}\n"
        f"ID: `{user.id}`\n"
        f"تاريخ دخولك للبوت: {created_str}\n"
        f"مدة الثبات الحالية: {human}"
    )

    update.message.reply_text(text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)


def handle_help_button(update: Update, context: CallbackContext):
    help_command(update, context)


def handle_contact_support(update: Update, context: CallbackContext):
    user = update.effective_user
    WAITING_FOR_SUPPORT.add(user.id)

    update.message.reply_text(
        "✉️ اكتب الآن رسالتك التي تريد إرسالها للدعم.\n"
        "سيتم إرسالها للأدمن مع معلومات حسابك.\n\n"
        "لو حبيت الإلغاء اضغط زر «إلغاء ❌».",
        reply_markup=SMALL_CANCEL_KEYBOARD,
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
        "أو اضغط «إلغاء ❌» للعودة.",
        reply_markup=SMALL_CANCEL_KEYBOARD,
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


def handle_set_date_button(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    WAITING_FOR_DATE.add(user_id)

    update.message.reply_text(
        "⏱✨ جميل! خلينا نثبت بداية تعافيك.\n\n"
        "يمكنك اختيار واحدة من طريقتين:\n"
        "1️⃣ تكتب *تاريخ ووقت بداية التعافي* بالشكل التالي:\n"
        "`2025-11-20 15:30`\n"
        "2️⃣ أو تكتب فقط *عدد الأيام* التي مضت منذ بداية تعافيك، مثلاً:\n"
        "`7`\n\n"
        "اكتب الآن ما يناسبك 🤍",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )

# =================== هاندلر الرسائل العامة ===================


def extract_user_id_from_text(text: str):
    """استخراج الـ ID من رسالة الدعم التي يستقبلها الأدمن."""
    match = re.search(r"ID:\s*`(\d+)`", text)
    if match:
        return int(match.group(1))
    return None


def handle_text_message(update: Update, context: CallbackContext):
    user = update.effective_user
    user_id = user.id
    text = update.message.text.strip()

    record = get_user_record(user)

    # ===== زر الإلغاء =====
    if text == BTN_CANCEL:
        if user_id in WAITING_FOR_SUPPORT:
            WAITING_FOR_SUPPORT.discard(user_id)
            update.message.reply_text(
                "تم إلغاء إرسال الرسالة للدعم ✅\n"
                "رجعناك للواجهة الرئيسية 🙌",
                reply_markup=MAIN_KEYBOARD,
            )
            return
        if user_id in WAITING_FOR_BROADCAST:
            WAITING_FOR_BROADCAST.discard(user_id)
            update.message.reply_text(
                "تم إلغاء الرسالة الجماعية ✅\n"
                "رجعناك للواجهة الرئيسية 🙌",
                reply_markup=MAIN_KEYBOARD,
            )
            return
        if user_id in WAITING_FOR_DATE:
            WAITING_FOR_DATE.discard(user_id)
            update.message.reply_text(
                "تم إلغاء تعيين بداية التعافي ✅",
                reply_markup=MAIN_KEYBOARD,
            )
            return

    # ===== رد الأدمن على رسالة دعم (Reply) =====
    if is_admin(user_id) and update.message.reply_to_message:
        original_text = update.message.reply_to_message.text or ""
        target_id = extract_user_id_from_text(original_text)

        if target_id:
            try:
                context.bot.send_message(
                    chat_id=target_id,
                    text=f"📬 رد من الدعم:\n\n{update.message.text}",
                )
                update.message.reply_text(
                    "✅ تم إرسال ردك للمستخدم.",
                    reply_markup=MAIN_KEYBOARD,
                )
            except Exception as e:
                logger.error(f"Error sending reply to user {target_id}: {e}")
                update.message.reply_text(
                    "❌ حدث خطأ أثناء إرسال الرد للمستخدم.",
                    reply_markup=MAIN_KEYBOARD,
                )
            return

    # ===== تعيين بداية التعافي يدوياً =====
    if user_id in WAITING_FOR_DATE:
        WAITING_FOR_DATE.remove(user_id)

        # أولاً: لو كتب عدد أيام
        try:
            days = int(text)
            now = datetime.now(timezone.utc)
            new_dt = now - timedelta(days=days)
            update_user_record(user_id, streak_start=new_dt.isoformat())

            update.message.reply_text(
                f"⏱ تم ضبط بداية التعافي منذ {days} يومًا.\n"
                "الآن عداد الأيام سيحسب من هذا التاريخ 💪🔥",
                reply_markup=MAIN_KEYBOARD,
            )
            return
        except ValueError:
            pass

        # ثانياً: نحاول نقرأه كتاريخ ووقت
        try:
            new_dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
            new_dt = new_dt.replace(tzinfo=timezone.utc)
            update_user_record(user_id, streak_start=new_dt.isoformat())

            update.message.reply_text(
                "⏱✨ تم ضبط بداية التعافي بالتاريخ الذي أدخلته.\n"
                "الآن عداد الأيام سيحسب من هذا الوقت 🙌",
                reply_markup=MAIN_KEYBOARD,
            )
        except ValueError:
            update.message.reply_text(
                "⚠️ لم أفهم التاريخ.\n"
                "اكتب التاريخ بهذا الشكل مثلًا:\n"
                "`2025-11-20 15:30`\n"
                "أو اكتب عدد الأيام منذ بداية تعافيك مثل:\n"
                "`7`",
                parse_mode="Markdown",
                reply_markup=MAIN_KEYBOARD,
            )
        return

    # ===== إرسال رسالة دعم من المستخدم =====
    if user_id in WAITING_FOR_SUPPORT:
        WAITING_FOR_SUPPORT.remove(user_id)

        support_msg = (
            "📩 *رسالة جديدة للدعم:*\n\n"
            f"👤 الاسم: {user.full_name}\n"
            f"🆔 ID: `{user_id}`\n"
            f"🔹 اسم المستخدم: @{user.username if user.username else 'لا يوجد'}\n\n"
            f"✉️ محتوى الرسالة:\n{text}\n\n"
            "للرد على هذا المستخدم، اضغط *Reply* على هذه الرسالة واكتب ردك."
        )

        if ADMIN_ID is not None:
            try:
                context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=support_msg,
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error(f"Error sending support message to admin: {e}")

        update.message.reply_text(
            "✅ تم إرسال رسالتك للدعم.\n"
            "سيتم التواصل معك إن لزم الأمر 🤍",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # ===== رسالة جماعية من الأدمن =====
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
                    chat_id=uid,
                    text=f"📢 رسالة من الدعم:\n\n{text}",
                )
                sent += 1
            except Exception as e:
                logger.error(f"Error sending broadcast to {uid}: {e}")

        update.message.reply_text(
            f"✅ تم إرسال الرسالة إلى {sent} مستخدم.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # ===== التعامل مع الأزرار =====
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
    elif text == BTN_RATE:
        handle_rate_day(update, context)
    elif text == BTN_LEVEL:
        handle_level(update, context)
    elif text == BTN_ACCOUNT:
        handle_account_info(update, context)
    elif text == BTN_SUPPORT:
        handle_contact_support(update, context)
    elif text == BTN_BROADCAST:
        handle_broadcast_button(update, context)
    elif text == BTN_STATS:
        handle_stats_button(update, context)
    elif text == BTN_SET_DATE:
        handle_set_date_button(update, context)
    elif text == BTN_HELP:
        handle_help_button(update, context)
    else:
        # أي نص عادي → نحفظه كملاحظة
        notes = record.get("notes", [])
        notes.append(text)
        update_user_record(user_id, notes=notes)

        update.message.reply_text(
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
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text_message))

    # تشغيل Flask في ثريد منفصل
    Thread(target=run_flask, daemon=True).start()

    logger.info("Bot is starting...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
