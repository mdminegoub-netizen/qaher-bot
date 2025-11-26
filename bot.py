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
ADMIN_ID = 931350292  # عدّل هذا للـ ID تبعك

# مستخدمون في وضع "تواصل مع الدعم"
WAITING_FOR_SUPPORT = set()

# الأدمن في وضع "رسالة جماعية"
WAITING_FOR_BROADCAST = set()

# مستخدمون في وضع "تعيين بداية التعافي"
WAITING_FOR_CUSTOM_START = set()

# خريطة لربط رسالة الدعم عند الأدمن بالمستخدم الأصلي (للرد عبر Reply)
ADMIN_REPLY_MAP: dict[int, int] = {}

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
            "ratings": [],  # تقييم اليوم
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
BTN_RATE_DAY = "تقييم اليوم ⭐"
BTN_LEVEL = "مستواي 💎"
BTN_ACCOUNT = "معرفة حسابي 👤"
BTN_SUPPORT = "تواصل مع الدعم ✉️"
BTN_SET_RECOVERY_START = "تعيين بداية التعافي ⏰"
BTN_HELP = "مساعدة ℹ️"
BTN_BROADCAST = "رسالة جماعية 📢"
BTN_STATS = "عدد المستخدمين 👥"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_START), KeyboardButton(BTN_COUNTER)],
        [KeyboardButton(BTN_TIP), KeyboardButton(BTN_EMERGENCY)],
        [KeyboardButton(BTN_RELAPSE), KeyboardButton(BTN_DHIKR)],
        [KeyboardButton(BTN_NOTES), KeyboardButton(BTN_RESET)],
        [KeyboardButton(BTN_RATE_DAY), KeyboardButton(BTN_LEVEL)],
        [KeyboardButton(BTN_ACCOUNT), KeyboardButton(BTN_SUPPORT)],
        [KeyboardButton(BTN_SET_RECOVERY_START), KeyboardButton(BTN_HELP)],
        [KeyboardButton(BTN_STATS), KeyboardButton(BTN_BROADCAST)],
    ],
    resize_keyboard=True,
)

# =================== رسائل جاهزة ===================

TIPS = [
    "💡 تذكّر: كل دقيقة تصبر فيها تبني نسخة أقوى من نفسك.",
    "💡 غيّر مكانك فوراً لما تحس بالضعف، الحركة تكسر موجة العادة.",
    "💡 اشغل يدك بشي نافع: كتابة، قراءة، تمارين بسيطة، أو ترتيب غرفتك.",
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

RELAPSE_TEXTS = [
    "🧠 *سبب شائع للانتكاس: الفراغ.*\nحاول تملأ يومك بشيء واضح: دراسة، عمل، رياضة، قراءة، أو مشروع صغير.",
    "🧠 *سبب شائع للانتكاس: استخدام الهاتف في السرير.*\nحاول تخلي السرير للنوم فقط، والهاتف بعيد عنك قبل النوم.",
    "🧠 *سبب شائع للانتكاس: المحتوى المثير (حتى لو كان عادي ظاهريًا).*\nنظّف حساباتك وتتبع من تشوف، خلك شجاع في الحظر والإلغاء.",
    "🧠 *سبب شائع للانتكاس: العزلة.*\nقابل ناس، كل مع أهلك، اطلع تمشى، لا تبقى لحالك وقت طويل.",
]

ADHKAR_TEXTS = [
    "🕊 *جرعة سكينة سريعة:*\n\n"
    "• أستغفر الله العظيم وأتوب إليه.\n"
    "• لا إله إلا أنت سبحانك إني كنت من الظالمين.\n"
    "• حسبي الله لا إله إلا هو عليه توكلت وهو رب العرش العظيم.\n\n"
    "ردّدها بهدوء مع تنفس عميق 🌿.",
    "🕊 *اذكر الله الآن:* \n\n"
    "سبحان الله ✨\n"
    "الحمد لله 🤍\n"
    "لا إله إلا الله 🌙\n"
    "الله أكبر 💫\n\n"
    "20 مرة من كل ذكر تغيّر مزاجك بالكامل إن شاء الله.",
]

HELP_TEXT = (
    "ℹ️ *مساعدة سريعة:*\n\n"
    "• «بدء الرحلة 🚀»: يبدأ عدّاد ثباتك من الآن.\n"
    "• «عداد الأيام 🗓»: يريك كم مضى من وقت ثباتك (أشهر، أيام، ساعات، دقائق).\n"
    "• «تعيين بداية التعافي ⏰»: لو كنت ثابت من قبل اليوم وتريد ضبط البداية يدويًا.\n"
    "• «إعادة ضبط العداد ♻️»: لو حصلت انتكاسة وتريد بداية جديدة.\n"
    "• «تواصل مع الدعم ✉️»: تتواصل معي مباشرة وتقدر أحيانًا أجاوبك على موقفك الخاص.\n\n"
    "أي وقت تضيع، ارجع للأزرار واختَر اللي يناسب حالتك الآن 💪."
)

# =================== أوامر البوت ===================


def start_command(update: Update, context: CallbackContext):
    user = update.effective_user

    # نتحقق: هل هذا أول دخول للمستخدم؟
    is_new_user = str(user.id) not in data

    # نسجّل/نحدّث بياناته كالمعتاد
    record = get_user_record(user)

    # لو مستخدم جديد → نرسل إشعار للأدمن
    if is_new_user and ADMIN_ID is not None:
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

    # لو كان عنده بداية من قبل، نذكّره فقط
    if record.get("streak_start"):
        delta = get_streak_delta(record)
        if delta:
            human = format_streak_text(delta)
            update.message.reply_text(
                f"🚀 رحلتك بدأت من قبل.\nمدة ثباتك الحالية: {human}.",
                reply_markup=MAIN_KEYBOARD,
            )
            return

    # بداية جديدة
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
    text = random.choice(RELAPSE_TEXTS)
    update.message.reply_text(
        text, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown"
    )


def handle_adhkar(update: Update, context: CallbackContext):
    text = random.choice(ADHKAR_TEXTS)
    update.message.reply_text(
        text, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown"
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
        "اعتبرها بداية جديدة أقوى بإذن الله، ولا تيأس أبدًا 🤍.",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_rate_day(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)
    update.message.reply_text(
        "⭐ قيّم يومك من 1 إلى 5 في رسالة واحدة.\n"
        "1 = يوم صعب جدًا\n"
        "5 = يوم ممتاز مليان إنجاز ✨",
        reply_markup=MAIN_KEYBOARD,
    )
    # نخزن أنه ينتظر تقييم (نستخدم نفس حقل ratings للتخزين فقط)
    record.setdefault("waiting_for_rating", True)
    save_data(data)


def handle_level(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)
    delta = get_streak_delta(record)

    if not delta:
        update.message.reply_text(
            "لسه ما عندك مستوى لأنك ما بدأت الرحلة.\n"
            "ابدأ عبر زر «بدء الرحلة 🚀».",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    days = delta.days
    if days < 3:
        level = "مبتدئ 🌱"
        msg = "بداية بطلة! ركّز على أول أسبوع ولا تستعجل النتائج."
    elif days < 7:
        level = "صامد 💪"
        msg = "أسبوعك هذا مهم جدًا، حاول تقلل محفزاتك لأقصى درجة."
    elif days < 30:
        level = "مقاتل 🔥"
        msg = "دخلت مرحلة التغيير الحقيقي، لا تسمح لانتكاسة واحدة تهدم كل شيء."
    else:
        level = "أسطورة التعافي 🏆"
        msg = "ما شاء الله! خلي نيتك ثابتة، وساعد غيرك إذا قدرت."

    update.message.reply_text(
        f"💎 مستواك الحالي: *{level}*\n"
        f"مرّ من ثباتك تقريبًا: {days} يوم.\n\n"
        f"{msg}",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_account_info(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    created_at = record.get("created_at")
    streak_start = record.get("streak_start") or "لم تبدأ بعد"
    username = f"@{user.username}" if user.username else "لا يوجد"

    text = (
        "👤 *معلومات حسابك في البوت:*\n\n"
        f"• الاسم: {user.full_name}\n"
        f"• اسم المستخدم: {username}\n"
        f"• ID: `{user.id}`\n"
        f"• تاريخ أول دخول (UTC): {created_at}\n"
        f"• بداية آخر رحلة تعافي (UTC): {streak_start}\n"
    )

    if is_admin(user.id):
        total_users = len(get_all_user_ids())
        text += f"\n📊 *أنت الأدمن.* عدد المستخدمين الحاليين: *{total_users}*"

    update.message.reply_text(
        text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD
    )


def handle_contact_support(update: Update, context: CallbackContext):
    user = update.effective_user
    WAITING_FOR_SUPPORT.add(user.id)

    # نخفي الكيبورد حتى يكتب رسالته براحة
    update.message.reply_text(
        "✉️ اكتب الآن رسالتك التي تريد إرسالها للدعم.\n"
        "اكتب بارتياح، لن يرى رسالتك أحد غير الأدمن.\n\n"
        "بعد الإرسال ستصلك رسالة تأكيد ✅",
        reply_markup=ReplyKeyboardRemove(),
    )


def handle_set_recovery_start_button(update: Update, context: CallbackContext):
    user = update.effective_user
    WAITING_FOR_CUSTOM_START.add(user.id)
    update.message.reply_text(
        "⏰ جميل إن عندك ثبات من قبل!\n"
        "أرسل الآن عدد *الأيام* التي كنت فيها ثابتًا قبل اليوم.\n\n"
        "مثال:\n"
        "لو أنت ثابت من أسبوع → أرسل: 7\n"
        "لو ثابت من 30 يوم → أرسل: 30",
        reply_markup=MAIN_KEYBOARD,
        parse_mode="Markdown",
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

    # 0️⃣ أولًا: لو الأدمن ردّ بـ Reply على رسالة دعم
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
                sent = context.bot.send_message(
                    chat_id=ADMIN_ID, text=support_msg, parse_mode="Markdown"
                )
                # نربط رسالة الأدمن بالمستخدم الأصلي للرد لاحقًا
                ADMIN_REPLY_MAP[sent.message_id] = user_id
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

    # 3️⃣ أولوية: وضع "تعيين بداية التعافي"
    if user_id in WAITING_FOR_CUSTOM_START:
        # نحاول نقرأ عدد الأيام
        try:
            # نستخرج أول رقم في النص
            days_str = "".join(ch for ch in text if ch.isdigit())
            days = int(days_str)
            now = datetime.now(timezone.utc)
            start_dt = now - timedelta(days=days)
            update_user_record(user_id, streak_start=start_dt.isoformat())
            WAITING_FOR_CUSTOM_START.remove(user_id)

            update.message.reply_text(
                f"⏰ تم تعيين بداية التعافي قبل {days} يوم.\n"
                "من الآن عدّادك يحسب من هذا التاريخ 💪",
                reply_markup=MAIN_KEYBOARD,
            )
        except Exception:
            update.message.reply_text(
                "لم أفهم الرقم 😅\n"
                "أرسل فقط عدد الأيام مثل: 7 أو 30.",
                reply_markup=MAIN_KEYBOARD,
            )
        return

    # 4️⃣ تقييم اليوم (لو كان ينتظر تقييم)
    if record.get("waiting_for_rating"):
        try:
            rating = int(text)
            if rating < 1 or rating > 5:
                raise ValueError("out of range")
            ratings = record.get("ratings", [])
            ratings.append({"value": rating, "at": datetime.now(timezone.utc).isoformat()})
            record["ratings"] = ratings
            record["waiting_for_rating"] = False
            save_data(data)

            msg = "شكراً لتقييمك 🤍\n"
            if rating <= 2:
                msg += "يوم صعب، لكن مجرد تقييمك له خطوة وعي قوية، بكرة يكون أفضل بإذن الله 🌤."
            elif rating == 3:
                msg += "يوم متوسط، حاول تضيف له حاجة حلوة قبل ما يخلص ✨."
            else:
                msg += "يوم ممتاز! ثبت هذا الشعور في ملاحظاتك حتى ترجع له وقت ما تضعف 💎."

            update.message.reply_text(msg, reply_markup=MAIN_KEYBOARD)
        except Exception:
            update.message.reply_text(
                "رجاءً أرسل رقم من 1 إلى 5 فقط لتقييم يومك ⭐.",
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
    elif text == BTN_RATE_DAY:
        handle_rate_day(update, context)
    elif text == BTN_LEVEL:
        handle_level(update, context)
    elif text == BTN_ACCOUNT:
        handle_account_info(update, context)
    elif text == BTN_SUPPORT:
        handle_contact_support(update, context)
    elif text == BTN_SET_RECOVERY_START:
        handle_set_recovery_start_button(update, context)
    elif text == BTN_HELP:
        help_command(update, context)
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

    # أوامر
    dp.add_handler(CommandHandler("start", start_command))
    dp.add_handler(CommandHandler("help", help_command))

    # جميع الرسائل النصية (بعد الأوامر)
    dp.add_handler(
        MessageHandler(Filters.text & ~Filters.command, handle_text_message)
    )

    # جدولة التذكير اليومي (20:00 بتوقيت UTC)
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
