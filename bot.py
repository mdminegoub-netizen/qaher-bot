import os
import json
import logging
import random
from datetime import datetime, timezone, timedelta, time as dt_time
from threading import Thread

import pytz
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

# ضع هنا ID المشرفة (بدون علامات تنصيص لو رقم فقط)
# مثال: ADMIN_ID = 931350292
ADMIN_ID = 931350292  # عدّليه للـ ID تبعك

# حالات/أوضاع خاصة لكل مستخدمة
WAITING_FOR_SUPPORT = set()        # صارحي مدربتك
WAITING_FOR_VENT = set()           # الفضفضة
WAITING_FOR_BROADCAST = set()      # رسالة جماعية (للمشرفة)
WAITING_FOR_NOTE_EDIT = set()      # تعديل ملاحظة
WAITING_FOR_NOTE_DELETE = set()    # حذف ملاحظة
WAITING_FOR_RATING = set()         # تقييم اليوم
WAITING_FOR_START_DATE = set()     # تعيين بداية التعافي

# ملف اللوج
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# =================== خادم ويب لـ Render ===================

app = Flask(__name__)


@app.route("/")
def index():
    return "Qaher-bot for girls is running ✅"


def run_flask():
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

# =================== تخزين بيانات المستخدمات ===================


def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading data: {e}")
        return {}


def save_data(data_obj):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data_obj, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving data: {e}")


data = load_data()


def get_user_record(user):
    """يرجع سجل المستخدمة ويحدّث آخر نشاط."""
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
        }
    else:
        record = data[user_id]
        record["first_name"] = user.first_name
        record["username"] = user.username
        record["last_active"] = now_iso

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
    total_minutes = int(delta.total_seconds() // 60)
    total_hours = int(delta.total_seconds() // 3600)
    total_days = int(delta.total_seconds() // 86400)
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

BTN_START = "🚀 بدء رحلة التعافي"
BTN_COUNTER = "🗓 عداد التعافي"
BTN_TIPS = "💌 نصائح لك"
BTN_DHIKR = "🕊 أذكار وسكينة"
BTN_MENTAL = "💞 دعم نفسي"
BTN_EXERCISE = "🧘‍♀️ تمرين سريع"
BTN_AFTER_RELAPSE = "😔 بعد الانتكاسة"
BTN_WEAKNESS = "🧠 أسباب الضعف"
BTN_NOTES = "📝 ملاحظاتي"
BTN_RESET = "♻️ إعادة ضبط العداد"
BTN_RATE = "⭐️ تقييم اليوم"
BTN_SET_START = "⏱ تعيين بداية التعافي"

BTN_SUPPORT = "🤍 صارحي مُدرِّبتك"
BTN_VENT = "📩 الفضفضة"

BTN_CANCEL = "❌ إلغاء"

# أزرار خاصة بالمشرفة
BTN_BROADCAST = "📢 رسالة جماعية"
BTN_STATS = "👥 عدد المشتركات"


def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(BTN_START), KeyboardButton(BTN_COUNTER)],
        [KeyboardButton(BTN_TIPS), KeyboardButton(BTN_DHIKR)],
        [KeyboardButton(BTN_MENTAL), KeyboardButton(BTN_EXERCISE)],
        [KeyboardButton(BTN_WEAKNESS), KeyboardButton(BTN_EMERGENCY)],
        [KeyboardButton(BTN_NOTES), KeyboardButton(BTN_SET_START)],
        [KeyboardButton(BTN_RATE), KeyboardButton(BTN_SUPPORT)],
        [KeyboardButton(BTN_VENT)],
    ]
    if is_admin(user_id):
        rows.append([KeyboardButton(BTN_BROADCAST), KeyboardButton(BTN_STATS)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(BTN_CANCEL)]], resize_keyboard=True)

# =================== رسائل جاهزة ===================

TIPS = [
    "💌 غاليتي، لا تقللي من إنجازك… مجرد رغبتك في التعافي خطوة عظيمة نحو حياة أنقى وأهدأ.",
    "💌 حبيبتي، كل مرة تقاومين فيها الرغبة… أنتِ تُعيدين بناء احترامك لنفسك لبنة لبنة.",
    "💌 جميلة قلبي، لا أحد يعرف صراعك الداخلي مثل ربّك… كوني صادقة في دعائك وسيهديكِ طريق الثبات.",
    "💌 تذكّري: شعور الراحة المؤقتة بعد العادة لا يساوي ثقل الندم بعدها… لكن راحة التعافي تبقى في قلبك طويلًا.",
    "💌 لا تقسي على نفسك عند السقوط، تعلّمي، انهضي، وارجعي للطريق بقلب ألطف مع نفسك.",
    "💌 قلّلي العزلة، واختاري صحبة صالحة… القرب من البنات الإيجابيات يحمي قلبك وعينك وفكرك.",
    "💌 سجّلي في ملاحظاتك سبب رغبتك في التعافي، وارجعي له في لحظات الضعف… هذا السبب هو سلاحك الخفي.",
    "💌 املئي يومك بما تحبين: قراءة، تعلّم، هوايات… الفراغ بيئة خصبة للأفكار المزعجة.",
    "💌 لا تجلسي مع الهاتف في السرير… غيّري هذا العادة الصغيرة وستتفاجئين كم يخفّ الضغط عليك.",
    "💌 تعافي قلبك وجسدك نعمة تستحق الصبر… ثباتك اليوم هدية لنسختك المستقبلية القوية.",
]

DHIKR_LIST = [
    "🕊 غاليتي، ردّدي من قلبك:\n\n«أستغفرُ اللهَ العظيمَ الذي لا إلهَ إلا هو الحيَّ القيومَ وأتوبُ إليه»",
    "🕊 حبيبتي، اجعلي لسانك رطبًا:\n\n«لا إله إلا الله وحده لا شريك له، له الملك وله الحمد وهو على كل شيء قدير»",
    "🕊 جميلة قلبي، وقت الاضطراب قولي:\n\n«حسبي الله لا إله إلا هو عليه توكلت وهو رب العرش العظيم»",
    "🕊 قد تهدئين جدًّا لو داومتِ على:\n\n«سبحان الله وبحمده، سبحان الله العظيم»",
    "🕊 قولي من قلبك:\n\n«اللهم طهّر قلبي وغضّ بصري واحفظ سري وعلانيتي»",
    "🕊 في لحظة الضعف ردّدي:\n\n«لا حول ولا قوة إلا بالله»… فهي تُطفئ نارًا لا يراها إلا الله.",
]

MENTAL_SUPPORT = [
    "💞 غاليتي، مشاعرك مفهومة ومسموعة، حتى لو لم تعبّري عنها… وجودك هنا دليل قوتك لا ضعفك.",
    "💞 حبيبتي، التعافي ليس خطًا مستقيمًا، بل طريق فيه صعود وهبوط… المهم أنك لا تستسلمين.",
    "💞 يا جميلة، لا تربطي قيمتك بأخطائك… أنتِ أكرم عند الله من ذنبٍ عانيتِ منه وتحاولين تركه.",
    "💞 لا بأس أن تتعبي… خذي استراحة، تنفّسي بعمق، وعودي للطريق بخطوة صغيرة واحدة.",
    "💞 أذكّرك: أنتِ لا تسيرين وحدك… هناك من يدعو لك بظهر الغيب دون أن تعرفي.",
]

QUICK_EXERCISES = [
    "🧘‍♀️ *تمرين تنفس سريع:*\n\nخذي شهيقًا عميقًا من أنفك 4 ثوانٍ… احبسي النفس 4 ثوانٍ… ثم أخرجيه بهدوء من فمك 6 ثوانٍ. كرري هذا لـ 10 مرات.",
    "🧘‍♀️ *تمرين إلهاء ذهني:*\n\nانظري حولك وحددي:\n5 أشياء ترينها 👀\n4 أشياء تلمسينها ✋\n3 أصوات تسمعينها 👂\n2 روائح تشمينها 👃\n1 شيء تشكرين الله عليه 🤍",
    "🧘‍♀️ *تمرين جسدي بسيط:*\n\nقومي بـ 15 سكوات خفيفة + 10 ضغط حائط + مشي في المكان دقيقة واحدة… الحركة تُغيّر حالتك النفسية بسرعة.",
]

AFTER_RELAPSE = [
    "😔 حبيبتي، الانتكاسة لا تعني أنك سيئة… بل تعني أنك إنسانة تحاول وتتعلّم. المهم: لا تستسلمي ولا تجعلي الشيطان يقنعك أن كل شيء ضاع.",
    "😔 غاليتي، بدل جلد الذات… اكتبي في ملاحظاتك: ما الذي حدث قبل الانتكاسة؟ تعلّمي منه وضعي خطة صغيرة لتفادي السبب.",
    "😔 جميلة قلبي، قولي: «اللهم لا تكلني إلى نفسي طرفة عين»… ثم بدّلي شعور الذنب بعمل صالح بسيط: ركعتين، صدقة، أو مساعدة أحد.",
]

EMERGENCY_PLAN = (
    "🆘 *خطة طوارئ عند لحظة الضعف:*\n\n"
    "1️⃣ غيّري وضعية جسمك فورًا: قفي إن كنتِ جالسة، أو تحركي من سريرك.\n"
    "2️⃣ اخرجي من الغرفة أو من المكان الذي يزيد من ضعفك ولو لخمس دقائق.\n"
    "3️⃣ خذي 10 أنفاس عميقة ببطء، وركّزي على خروج الشعور المزعج مع الزفير.\n"
    "4️⃣ افتحي أذكارك أو سورة تحبينها واسمعيها حتى يهدأ قلبك.\n"
    "5️⃣ اكتبي في ملاحظاتك ما تشعرين به الآن ولماذا تريدين التعافي… هذا يقوّيك كثيرًا."
)

WEAKNESS_REASONS = (
    "🧠 *أسباب شائعة للضعف والانتكاسة:*\n\n"
    "• الجلوس وحيدة مع الهاتف لفترات طويلة خاصة في الليل.\n"
    "• متابعة محتوى يلمّح للإثارة ولو بشكل غير مباشر.\n"
    "• الفراغ وعدم وجود أهداف واضحة لليوم.\n"
    "• الكتمان الشديد وعدم مشاركة مشاعرك مع من تثقين بها.\n\n"
    "حاولي تلاحظين أكثر سبب قريب منك… ثم عالجيه بخطوات صغيرة وواضحة."
)

# =================== أوامر البوت ===================


def start_command(update: Update, context: CallbackContext):
    user = update.effective_user
    user_id_str = str(user.id)
    is_new = user_id_str not in data

    record = get_user_record(user)

    text = (
        f"أهلًا يا جميلة {user.first_name} 🌸\n\n"
        "هذا بوت *قاهر العادة*، مخصص لمساعدتك في رحلة التعافي من العادة السرية "
        "بأسلوب لطيف، آمن، وسري جدًّا 🤍\n\n"
        "استخدمي الأزرار بالأسفل لاختيار ما تحتاجينه الآن 👇"
    )

    update.message.reply_text(
        text,
        reply_markup=get_main_keyboard(user.id),
        parse_mode="Markdown",
    )

    # إشعار للمشرفة عند دخول مستخدمة جديدة
    if is_new and ADMIN_ID is not None:
        try:
            context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "🌸 *مستخدمة جديدة دخلت البوت:*\n\n"
                    f"👤 الاسم: {user.full_name}\n"
                    f"🆔 ID: `{user.id}`\n"
                    f"🔹 اسم المستخدم: @{user.username if user.username else 'لا يوجد'}"
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Error notifying admin about new user: {e}")


def help_command(update: Update, context: CallbackContext):
    user = update.effective_user
    update.message.reply_text(
        "غاليتي، استخدمي الأزرار بالأسفل للتنقل بين مميزات البوت 🌸\n"
        "ولو أحببتِ التواصل مع المشرفة، استخدمي زر «صارحي مُدرِّبتك 🤍» "
        "أو زر «الفضفضة 📩».",
        reply_markup=get_main_keyboard(user.id),
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
                f"🚀 رحلتك في التعافي بدأت من قبل يا جميلة.\n"
                f"مدة التعافي الحالية: {human} 👍",
                reply_markup=get_main_keyboard(user.id),
            )
            return

    now_iso = datetime.now(timezone.utc).isoformat()
    update_user_record(user.id, streak_start=now_iso)

    update.message.reply_text(
        "🚀 تم بدء رحلة التعافي يا جميلة 🤍\n"
        "من هذه اللحظة يبدأ احتساب مدة تعافيك.",
        reply_markup=get_main_keyboard(user.id),
    )


def handle_days_counter(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    delta = get_streak_delta(record)
    if not delta:
        update.message.reply_text(
            "لم يتم تعيين بداية رحلتك بعد يا جميلة 🌱\n"
            "استخدمي زر «🚀 بدء رحلة التعافي» للبدء، أو «⏱ تعيين بداية التعافي».",
            reply_markup=get_main_keyboard(user.id),
        )
        return

    human = format_streak_text(delta)
    update.message.reply_text(
        f"⏱ مدة تعافيك حتى الآن:\n{human} 💪",
        reply_markup=get_main_keyboard(user.id),
    )


def handle_tip(update: Update, context: CallbackContext):
    user = update.effective_user
    tip = random.choice(TIPS)
    update.message.reply_text(
        tip,
        reply_markup=get_main_keyboard(user.id),
    )


def handle_adhkar(update: Update, context: CallbackContext):
    user = update.effective_user
    dhikr = random.choice(DHIKR_LIST)
    update.message.reply_text(
        dhikr,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user.id),
    )


def handle_mental_support(update: Update, context: CallbackContext):
    user = update.effective_user
    msg = random.choice(MENTAL_SUPPORT)
    update.message.reply_text(
        msg,
        reply_markup=get_main_keyboard(user.id),
    )


def handle_quick_exercise(update: Update, context: CallbackContext):
    user = update.effective_user
    msg = random.choice(QUICK_EXERCISES)
    update.message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user.id),
    )


def handle_after_relapse(update: Update, context: CallbackContext):
    user = update.effective_user
    msg = random.choice(AFTER_RELAPSE)
    update.message.reply_text(
        msg,
        reply_markup=get_main_keyboard(user.id),
    )


def handle_weakness_reasons(update: Update, context: CallbackContext):
    user = update.effective_user
    update.message.reply_text(
        WEAKNESS_REASONS,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user.id),
    )


def handle_emergency(update: Update, context: CallbackContext):
    user = update.effective_user
    update.message.reply_text(
        EMERGENCY_PLAN,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user.id),
    )

# =================== الملاحظات ===================


def show_notes_menu(update: Update, context: CallbackContext):
    """عرض قائمة الملاحظات مع قائمة فرعية (تعديل/حذف/إلغاء)."""
    user = update.effective_user
    record = get_user_record(user)
    notes = record.get("notes", [])

    if not notes:
        text = (
            "📝 لا توجد ملاحظات بعد يا جميلة.\n"
            "أرسلي أي فكرة أو شعور يخطر في بالك وسأحفظه كملاحظة لك 🤍"
        )
    else:
        lines = []
        for idx, note in enumerate(notes, start=1):
            lines.append(f"{idx}. {note}")
        joined = "\n\n".join(lines[-30:])  # آخر 30 ملاحظة
        text = (
            "📝 آخر ملاحظاتك:\n\n"
            f"{joined}\n\n"
            "يمكنك:\n"
            "✏️ اختيار «تعديل ملاحظة» لتعديل واحدة منها.\n"
            "🗑️ اختيار «حذف ملاحظة» لحذف واحدة منها.\n"
            "أو أرسلي ملاحظة جديدة وسأحفظها لك 🤍"
        )

    notes_keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("➕ إضافة ملاحظة جديدة")],
            [KeyboardButton("✏️ تعديل ملاحظة"), KeyboardButton("🗑️ حذف ملاحظة")],
            [KeyboardButton(BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )

    update.message.reply_text(text, reply_markup=notes_keyboard)


def handle_notes_flow(update: Update, context: CallbackContext, text: str):
    user = update.effective_user
    user_id = user.id
    record = get_user_record(user)
    notes = record.get("notes", [])

    # إلغاء
    if text == BTN_CANCEL:
        # مسح كل أوضاع الملاحظات
        WAITING_FOR_NOTE_EDIT.discard(user_id)
        WAITING_FOR_NOTE_DELETE.discard(user_id)
        update.message.reply_text(
            "تم الإلغاء يا جميلة 🤍",
            reply_markup=get_main_keyboard(user.id),
        )
        return

    # الدخول لوضع تعديل/حذف
    if text == "✏️ تعديل ملاحظة":
        WAITING_FOR_NOTE_DELETE.discard(user_id)
        WAITING_FOR_NOTE_EDIT.add(user_id)
        update.message.reply_text(
            "أرسلي رقم الملاحظة التي تريدين تعديلها متبوعًا بالنص الجديد.\n"
            "مثال: `2 هذا هو النص الجديد للملاحظة`",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton(BTN_CANCEL)]], resize_keyboard=True),
        )
        return

    if text == "🗑️ حذف ملاحظة":
        WAITING_FOR_NOTE_EDIT.discard(user_id)
        WAITING_FOR_NOTE_DELETE.add(user_id)
        update.message.reply_text(
            "أرسلي رقم الملاحظة التي تريدين حذفها.\nمثال: `3`",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton(BTN_CANCEL)]], resize_keyboard=True),
        )
        return

    if text == "➕ إضافة ملاحظة جديدة":
        # يرجع للوضع العادي، وأي نص يُعتبر ملاحظة جديدة
        WAITING_FOR_NOTE_EDIT.discard(user_id)
        WAITING_FOR_NOTE_DELETE.discard(user_id)
        update.message.reply_text(
            "اكتبي ملاحظتك يا جميلة، وسأحفظها لك 🤍\n"
            "يمكنك دائمًا العودة لقائمة الملاحظات من زر «📝 ملاحظاتي».",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton(BTN_CANCEL)]], resize_keyboard=True),
        )
        return

    # معالجة وضع تعديل
    if user_id in WAITING_FOR_NOTE_EDIT:
        parts = text.split(" ", 1)
        if len(parts) < 2 or not parts[0].isdigit():
            update.message.reply_text(
                "❗️رجاءً اكتبي رقم الملاحظة ثم مسافة ثم النص الجديد.\n"
                "مثال: `2 هذا هو النص الجديد`",
                parse_mode="Markdown",
            )
            return
        idx = int(parts[0]) - 1
        new_text = parts[1].strip()
        if idx < 0 or idx >= len(notes):
            update.message.reply_text("❗️رقم الملاحظة غير صحيح يا جميلة.")
            return
        notes[idx] = new_text
        update_user_record(user_id, notes=notes)
        WAITING_FOR_NOTE_EDIT.discard(user_id)
        update.message.reply_text(
            "✅ تم تعديل الملاحظة بنجاح 🤍",
            reply_markup=get_main_keyboard(user.id),
        )
        return

    # معالجة وضع حذف
    if user_id in WAITING_FOR_NOTE_DELETE:
        if not text.isdigit():
            update.message.reply_text(
                "❗️أرسلي رقم الملاحظة فقط.\nمثال: `3`",
            )
            return
        idx = int(text) - 1
        if idx < 0 or idx >= len(notes):
            update.message.reply_text("❗️رقم الملاحظة غير صحيح يا جميلة.")
            return
        deleted = notes.pop(idx)
        update_user_record(user_id, notes=notes)
        WAITING_FOR_NOTE_DELETE.discard(user_id)
        update.message.reply_text(
            "🗑️ تم حذف الملاحظة بنجاح.\n"
            "لو حبيتي اكتبي ملاحظة أجمل بدلها 🤍",
            reply_markup=get_main_keyboard(user.id),
        )
        return

    # أي نص آخر في وضع الملاحظات → نحفظه كملاحظة جديدة
    notes.append(text)
    update_user_record(user_id, notes=notes)
    update.message.reply_text(
        "📝 تم حفظ ملاحظتك يا جميلة.\n"
        "يمكنك رؤيتها لاحقًا من زر «📝 ملاحظاتي».",
        reply_markup=get_main_keyboard(user.id),
    )

# =================== إعادة ضبط العداد ===================


def handle_reset_counter(update: Update, context: CallbackContext):
    user = update.effective_user
    record = get_user_record(user)

    if not record.get("streak_start"):
        update.message.reply_text(
            "العداد لم يُضبط بعد يا جميلة 🌱\n"
            "يمكنك البدء من زر «🚀 بدء رحلة التعافي» أو «⏱ تعيين بداية التعافي».",
            reply_markup=get_main_keyboard(user.id),
        )
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    update_user_record(user.id, streak_start=now_iso)

    update.message.reply_text(
        "♻️ تم إعادة ضبط العداد.\n"
        "اعتبريها بداية أنضج وأقوى من قبل بإذن الله 🤍",
        reply_markup=get_main_keyboard(user.id),
    )

# =================== تقييم اليوم ===================


def handle_rate_day_button(update: Update, context: CallbackContext):
    user = update.effective_user
    WAITING_FOR_RATING.add(user.id)

    rating_kb = ReplyKeyboardMarkup(
        [
            [KeyboardButton("1 😞"), KeyboardButton("2 😔")],
            [KeyboardButton("3 😐"), KeyboardButton("4 🙂")],
            [KeyboardButton("5 🤩")],
            [KeyboardButton(BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )

    update.message.reply_text(
        "⭐️ كيف تصفين يومك اليوم من 1 إلى 5؟\n"
        "1 = سيّئ جدًا\n5 = رائع جدًّا\n\n"
        "اختاري رقمًا يناسب شعورك يا جميلة 🌸",
        reply_markup=rating_kb,
    )


def handle_rating_flow(update: Update, context: CallbackContext, text: str):
    user = update.effective_user
    user_id = user.id

    # إلغاء
    if text == BTN_CANCEL:
        WAITING_FOR_RATING.discard(user_id)
        update.message.reply_text(
            "تم إلغاء تقييم اليوم 🤍",
            reply_markup=get_main_keyboard(user.id),
        )
        return

    # توقّع قيمة من 1 إلى 5 في بداية النص
    if not text or not text[0].isdigit():
        update.message.reply_text(
            "❗️رجاءً اختاري رقمًا من 1 إلى 5 من الأزرار.",
        )
        return

    rating = int(text[0])
    if rating < 1 or rating > 5:
        update.message.reply_text("❗️الرقم يجب أن يكون بين 1 و 5.")
        return

    record = get_user_record(user)
    notes = record.get("notes", [])
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    notes.append(f"تقييم يوم {today_str}: {rating}/5")
    update_user_record(user_id, notes=notes)

    WAITING_FOR_RATING.discard(user_id)
    update.message.reply_text(
        "✅ تم حفظ تقييم يومك يا جميلة.\n"
        "شكرًا على صدقك مع نفسك 🤍",
        reply_markup=get_main_keyboard(user.id),
    )

# =================== تعيين بداية التعافي ===================


def handle_set_start_button(update: Update, context: CallbackContext):
    user = update.effective_user
    WAITING_FOR_START_DATE.add(user.id)

    update.message.reply_text(
        "⏱ غاليتي، أخبريني متى بدأ تعافيك تقريبًا:\n\n"
        "يمكنك:\n"
        "• إرسال التاريخ مباشرة بصيغة: `2025-11-01`\n"
        "• أو إرسال عدد الأيام السابقة، مثل: `7` (يعني بدأتِ قبل 7 أيام)\n\n"
        "أو اضغطي «❌ إلغاء» للعودة.",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(),
    )


def handle_start_date_flow(update: Update, context: CallbackContext, text: str):
    user = update.effective_user
    user_id = user.id

    if text == BTN_CANCEL:
        WAITING_FOR_START_DATE.discard(user_id)
        update.message.reply_text(
            "تم إلغاء تعيين بداية التعافي 🤍",
            reply_markup=get_main_keyboard(user.id),
        )
        return

    text = text.strip()

    # محاولة فهم YYYY-MM-DD
    try:
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            y, m, d = text.split("-")
            dt = datetime(int(y), int(m), int(d), tzinfo=timezone.utc)
            update_user_record(user_id, streak_start=dt.isoformat())
            WAITING_FOR_START_DATE.discard(user_id)
            update.message.reply_text(
                f"✅ تم تعيين بداية التعافي بتاريخ {text}.\n"
                "سيتم احتساب العداد بناءً على هذا التاريخ 🌸",
                reply_markup=get_main_keyboard(user.id),
            )
            return
    except Exception:
        pass

    # محاولة فهم عدد الأيام
    if text.isdigit():
        days_ago = int(text)
        dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
        update_user_record(user_id, streak_start=dt.isoformat())
        WAITING_FOR_START_DATE.discard(user_id)
        update.message.reply_text(
            f"✅ تم ضبط بداية التعافي على قبل {days_ago} يومًا.\n"
            "سيتم احتساب العداد من هذا التاريخ 🤍",
            reply_markup=get_main_keyboard(user.id),
        )
        return

    update.message.reply_text(
        "❗️لم أفهم التنسيق.\n"
        "أرسلي التاريخ بهذا الشكل: `2025-11-01` أو عدد الأيام مثل: `7`",
        parse_mode="Markdown",
    )

# =================== تواصل مع المشرفة / الفضفضة ===================


def handle_support_button(update: Update, context: CallbackContext):
    """صارحي مدربتك 🤍"""
    user = update.effective_user
    WAITING_FOR_SUPPORT.add(user.id)
    WAITING_FOR_VENT.discard(user.id)

    update.message.reply_text(
        "🤍 غاليتي، اكتبي الآن ما تريدين مصارحة مشرفتك به.\n"
        "سيصل كلامك للمشرفة مباشرة وبسرية تامة.\n\n"
        "لو غيرتِ رأيك، اضغطي «❌ إلغاء».",
        reply_markup=get_cancel_keyboard(),
    )


def handle_vent_button(update: Update, context: CallbackContext):
    """الفضفضة 📩"""
    user = update.effective_user
    WAITING_FOR_VENT.add(user.id)
    WAITING_FOR_SUPPORT.discard(user.id)

    update.message.reply_text(
        "📩 تفضّلي بالفضفضة يا جميلة… اكتبي كل ما في قلبك دون ترتيب.\n"
        " رسالتك ستصل للمشرفة لتسمعك وتحتويك 🤍\n\n"
        "لو أردتِ التراجع، اضغطي «❌ إلغاء».",
        reply_markup=get_cancel_keyboard(),
    )


def process_support_or_vent(
    update: Update,
    context: CallbackContext,
    text: str,
    kind: str,
):
    """إرسال رسالة للمشرفة من صارحي مدربتك أو الفضفضة."""
    user = update.effective_user
    user_id = user.id

    if text == BTN_CANCEL:
        WAITING_FOR_SUPPORT.discard(user_id)
        WAITING_FOR_VENT.discard(user_id)
        update.message.reply_text(
            "تم الإلغاء يا جميلة 🤍",
            reply_markup=get_main_keyboard(user.id),
        )
        return

    label = "مصارحة" if kind == "support" else "فضفضة"

    msg = (
        f"📩 *رسالة {label} جديدة من إحدى المشتركات:*\n\n"
        f"👤 الاسم: {user.full_name}\n"
        f"🆔 ID: `{user.id}`\n"
        f"🔹 اسم المستخدم: @{user.username if user.username else 'لا يوجد'}\n\n"
        f"✉️ محتوى الرسالة:\n{text}"
    )

    if ADMIN_ID is not None:
        try:
            context.bot.send_message(
                chat_id=ADMIN_ID,
                text=msg,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Error sending {kind} message to admin: {e}")

    if kind == "support":
        WAITING_FOR_SUPPORT.discard(user_id)
    else:
        WAITING_FOR_VENT.discard(user_id)

    update.message.reply_text(
        "✅ تم إرسال رسالتك للمشرفة يا جميلة.\n"
        "سيتم الرد عليكِ إن لزم الأمر بإذن الله 🤍",
        reply_markup=get_main_keyboard(user.id),
    )

# =================== رسالة جماعية + عدد المشتركات ===================


def handle_broadcast_button(update: Update, context: CallbackContext):
    user = update.effective_user
    if not is_admin(user.id):
        update.message.reply_text(
            "هذه الميزة خاصة بالمشرفة فقط 👩‍💻",
            reply_markup=get_main_keyboard(user.id),
        )
        return

    WAITING_FOR_BROADCAST.add(user.id)
    update.message.reply_text(
        "📢 اكتبي الآن الرسالة التي تريدين إرسالها لكل المشتركات.\n"
        "أو اضغطي «❌ إلغاء».",
        reply_markup=get_cancel_keyboard(),
    )


def handle_stats_button(update: Update, context: CallbackContext):
    user = update.effective_user
    if not is_admin(user.id):
        update.message.reply_text(
            "هذه المعلومة خاصة بالمشرفة فقط 👩‍💻",
            reply_markup=get_main_keyboard(user.id),
        )
        return

    total = len(get_all_user_ids())
    update.message.reply_text(
        f"👥 عدد المشتركات المسجلات في البوت: *{total}*",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user.id),
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
                    "🤍 تذكير لطيف يا جميلة:\n"
                    "كل دقيقة تصمدين فيها، تبنين نسخة أنقى وأقوى من نفسك.\n"
                    "لا تستصغري خطواتك الصغيرة… فالتعافي يبدأ من هنا 🌸"
                ),
            )
        except Exception as e:
            logger.error(f"Error sending daily reminder to {uid}: {e}")

# =================== هاندلر الرسائل العامة ===================


def handle_text_message(update: Update, context: CallbackContext):
    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    record = get_user_record(user)

    # 0️⃣ لو المشرفة ردّت على رسالة إحدى المشتركات (reply)
    if is_admin(user_id) and update.message.reply_to_message:
        original = update.message.reply_to_message.text or ""
        target_id = None

        # نحاول استخراج ID من نص الرسالة التي تم الرد عليها
        for line in original.splitlines():
            if "🆔 ID:" in line:
                # مثال: "🆔 ID: `123456789`"
                digits = "".join(ch for ch in line if ch.isdigit())
                if digits:
                    target_id = int(digits)
                break

        if target_id:
            try:
                context.bot.send_message(
                    chat_id=target_id,
                    text=f"💌 رد من مشرفتك:\n\n{text}",
                )
                update.message.reply_text("✅ تم إرسال الرد للمشتركة 🤍")
            except Exception as e:
                logger.error(f"Error sending reply to user {target_id}: {e}")
                update.message.reply_text("حدث خطأ أثناء إرسال الرد للمشتركة ❗️")
        else:
            update.message.reply_text("لم أتمكّن من معرفة المشتركة التي تريدين الرد عليها ❗️")
        return

    # 1️⃣ وضع صارحي مدربتك
    if user_id in WAITING_FOR_SUPPORT:
        process_support_or_vent(update, context, text, kind="support")
        return

    # 2️⃣ وضع الفضفضة
    if user_id in WAITING_FOR_VENT:
        process_support_or_vent(update, context, text, kind="vent")
        return

    # 3️⃣ وضع رسالة جماعية (للمشرفة)
    if user_id in WAITING_FOR_BROADCAST:
        if text == BTN_CANCEL:
            WAITING_FOR_BROADCAST.discard(user_id)
            update.message.reply_text(
                "تم إلغاء الرسالة الجماعية 🤍",
                reply_markup=get_main_keyboard(user.id),
            )
            return

        if not is_admin(user_id):
            update.message.reply_text(
                "هذه الميزة خاصة بالمشرفة فقط 👩‍💻",
                reply_markup=get_main_keyboard(user.id),
            )
            WAITING_FOR_BROADCAST.discard(user_id)
            return

        user_ids = get_all_user_ids()
        sent = 0
        for uid in user_ids:
            try:
                context.bot.send_message(
                    chat_id=uid,
                    text=f"📢 رسالة من مشرفتك:\n\n{text}",
                )
                sent += 1
            except Exception as e:
                logger.error(f"Error sending broadcast to {uid}: {e}")

        WAITING_FOR_BROADCAST.discard(user_id)
        update.message.reply_text(
            f"✅ تم إرسال الرسالة إلى {sent} مشتركة 🤍",
            reply_markup=get_main_keyboard(user.id),
        )
        return

    # 4️⃣ وضع الملاحظات (تعديل/حذف/إضافة)
    if text == BTN_NOTES or user_id in WAITING_FOR_NOTE_EDIT or user_id in WAITING_FOR_NOTE_DELETE:
        handle_notes_flow(update, context, text)
        return

    # 5️⃣ وضع تقييم اليوم
    if user_id in WAITING_FOR_RATING:
        handle_rating_flow(update, context, text)
        return

    # 6️⃣ وضع تعيين بداية التعافي
    if user_id in WAITING_FOR_START_DATE:
        handle_start_date_flow(update, context, text)
        return

    # 7️⃣ التعامل مع الأزرار
    if text == BTN_START:
        handle_start_journey(update, context)
    elif text == BTN_COUNTER:
        handle_days_counter(update, context)
    elif text == BTN_TIPS:
        handle_tip(update, context)
    elif text == BTN_DHIKR:
        handle_adhkar(update, context)
    elif text == BTN_MENTAL:
        handle_mental_support(update, context)
    elif text == BTN_EXERCISE:
        handle_quick_exercise(update, context)
    elif text == BTN_AFTER_RELAPSE:
        handle_after_relapse(update, context)
    elif text == BTN_WEAKNESS:
        handle_weakness_reasons(update, context)
    elif text == BTN_EMERGENCY:
        handle_emergency(update, context)
    elif text == BTN_NOTES:
        show_notes_menu(update, context)
    elif text == BTN_RESET:
        handle_reset_counter(update, context)
    elif text == BTN_RATE:
        handle_rate_day_button(update, context)
    elif text == BTN_SET_START:
        handle_set_start_button(update, context)
    elif text == BTN_SUPPORT:
        handle_support_button(update, context)
    elif text == BTN_VENT:
        handle_vent_button(update, context)
    elif text == BTN_BROADCAST:
        handle_broadcast_button(update, context)
    elif text == BTN_STATS:
        handle_stats_button(update, context)
    else:
        # 8️⃣ أي نص عادي → نحفظه كملاحظة + تنبيه أنه لا يصل للمشرفة
        notes = record.get("notes", [])
        notes.append(text)
        update_user_record(user_id, notes=notes)

        update.message.reply_text(
            "📝 تم حفظ رسالتك كملاحظة خاصة لك يا جميلة.\n\n"
            "⚠️ تنبيه: هذه الرسالة *لا تصل للمشرفة* مباشرة.\n"
            "لو أحببتِ التواصل مع المشرفة:\n"
            "1️⃣ اضغطي زر «🤍 صارحي مُدرِّبتك» أو «📩 الفضفضة»\n"
            "2️⃣ أو استخدمي الرد *Reply / الرد* على رسالة سابقة من المشرفة.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(user.id),
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

    # تذكير يومي عبر JobQueue (الساعة 20:00 بتوقيت UTC)
    job_queue = updater.job_queue
    job_queue.run_daily(
        send_daily_reminders,
        time=dt_time(hour=20, minute=0, tzinfo=pytz.utc),
        name="daily_reminders",
    )

    # تشغيل Flask في ثريد منفصل
    Thread(target=run_flask, daemon=True).start()

    logger.info("Bot is starting...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
