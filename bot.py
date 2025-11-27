import os
import json
import logging
import random
from datetime import datetime, timezone, timedelta, time
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

import pytz

# =================== الإعدادات الأساسية ===================

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "user_data.json"

# عدّلي هذا إلى ID الخاص بحساب المشرفة (بدون علامات تنصيص)
ADMIN_ID = 931350292  # مثال

# تتبّع من في وضع "تواصل مع الدعم"
WAITING_FOR_SUPPORT = set()
# تتبّع من في وضع "رسالة جماعية"
WAITING_FOR_BROADCAST = set()

# =================== إعداد اللوج ===================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# =================== خادم ويب بسيط لـ Render ===================

app = Flask(__name__)


@app.route("/")
def index():
    return "Qaher-bot (girls version) is running ✅"


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


def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving data: {e}")


data = load_data()


def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID


def get_user_record(user):
    """
    ترجع سجل المستخدمة، وتنشئ واحدًا جديدًا إن لم يوجد.
    """
    user_id = str(user.id)
    now_iso = datetime.now(timezone.utc).isoformat()

    created = False
    if user_id not in data:
        created = True
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
        # تحديث آخر نشاط والاسم واسم المستخدم
        data[user_id]["last_active"] = now_iso
        data[user_id]["first_name"] = user.first_name
        data[user_id]["username"] = user.username

    save_data(data)
    return data[user_id], created


def update_user_record(user_id: int, **kwargs):
    uid = str(user_id)
    if uid not in data:
        return
    data[uid].update(kwargs)
    data[uid]["last_active"] = datetime.now(timezone.utc).isoformat()
    save_data(data)


def get_all_user_ids():
    return [int(uid) for uid in data.keys()]

# =================== حساب مدة التعافي ===================


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

BTN_START = "بدء الرحلة 🚀"
BTN_COUNTER = "عداد التعافي ⏱"
BTN_TIP = "نصيحة للبنات 💖"
BTN_EMERGENCY = "خطة الطوارئ 🆘"
BTN_RELAPSE = "أسباب الانتكاس 🧠"
BTN_DHIKR = "أذكار وسكينة 🕊"
BTN_NOTES = "ملاحظاتي 📓"
BTN_RESET = "إعادة ضبط العداد ♻️"
BTN_SUPPORT = "تواصل مع الدعم ✉️"
BTN_BROADCAST = "رسالة جماعية 📢"
BTN_STATS = "عدد المشتركات 👥"
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

SUPPORT_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_CANCEL)],
    ],
    resize_keyboard=True,
)


BROADCAST_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_CANCEL)],
    ],
    resize_keyboard=True,
)

# =================== رسائل جاهزة ===================

TIPS = [
    "حبيبتي، كل محاولة لمقاومة العادات السيئة هي خطوة عملية نحو احترامك لذاتك من جديد، فلا تستهيني بأي لحظة ثبات 💪🩷",
    "إن شعرتِ بضعف، غيّري مكانك فورًا: انهضي، افتحي النافذة، تحركي قليلًا… تغيير الجو يغيّر الفكرة 🌿",
    "قاعدة مهمّة لسلامتك: لا استخدام للهاتف وأنتِ على السرير ليلًا، فهذا من أكبر أبواب الانتكاس 🚫📱",
    "اهتمي بروتين بسيط لنفسك: عناية ببشرتك، كوب شراب دافئ، قراءة، أو كتابة… هذه الأشياء الصغيرة تصنع فارقًا كبيرًا في مزاجك يا جميلتي 🌸",
    "تخفيف متابعة الحسابات والمحتويات التي تثير الفضول أو المقارنات حماية لقلبك ونفسك قبل أن تكون قيودًا عليكِ 🙏",
]

EMERGENCY_PLAN = (
    "🆘 *خطة الطوارئ في لحظة الضعف – للفتيات:*\n\n"
    "1️⃣ غيّري وضعك فورًا يا غاليتي: إن كنتِ جالسة فقومي، وإن كنتِ على السرير فابتعدي عنه.\n"
    "2️⃣ أغلقي ما يثيركِ من تطبيقات أو مواقع، وأبعدي الهاتف عنك قدر الإمكان.\n"
    "3️⃣ خذي عشرة أنفاس عميقة بهدوء: شهيق من الأنف ببطء، وزفير من الفم ببطء أكثر 🌬️.\n"
    "4️⃣ استمعي لآيات من القرآن أو سورة تحبينها، ودعي قلبك يهدأ بكلام الله 🕊.\n"
    "5️⃣ افتحي «ملاحظاتي 📓» واكتبي ما تشعرين به الآن؛ فضفضة مكتوبة خير من صمت يؤلمك في الداخل.\n\n"
    "تذكّري يا جميلتي: كل مرة تتجاوزين فيها لحظة ضعف، أنتِ تبنين عضلة إرادتك وتقتربين أكثر من نفسك التي تحبينها 💪🩷"
)

RELAPSE_REASONS = (
    "🧠 *أسباب الانتكاس الشائعة عند الفتيات:*\n\n"
    "• السهر الطويل ليلًا مع الهاتف من غير هدف واضح.\n"
    "• متابعة محتوى أو مسلسلات تحتوي على تلميحات أو مشاهد مثيرة للفضول.\n"
    "• الشعور بالوحدة أو الفراغ العاطفي ومحاولة الهروب من الألم الداخلي.\n"
    "• الفراغ وعدم وجود أهداف يومية صغيرة تشغلك عن التفكير السلبي.\n"
    "• المقارنة المستمرة بالآخرين وما يسببه ذلك من إحباط أو حزن.\n\n"
    "حاولي يا حبيبتي أن تتعرّفي على السبب الأقرب لحالتك؛ لأن معرفة السبب نصف طريق العلاج 🌱."
)

ADHKAR = (
    "🕊 *أذكار وسكينة لقلبك يا جميلتي:*\n\n"
    "• أستغفرُ اللهَ العظيمَ الذي لا إلهَ إلا هو الحيَّ القيومَ وأتوبُ إليه.\n"
    "• لا إله إلا أنت سبحانك إني كنتُ من الظالمين.\n"
    "• حسبي الله لا إله إلا هو، عليه توكّلتُ وهو ربُّ العرش العظيم.\n\n"
    "ردّديها بقلب حاضر، وتيقّني أن ربّك يرى تعبك ومحاولتك، ولن يضيّع دموعك ولا نيتك الصادقة يا غاليتي 🤍."
)

# =================== أوامر البوت ===================


def start_command(update: Update, context: CallbackContext):
    user = update.effective_user
    record, created = get_user_record(user)

    text = (
        f"أهلاً بكِ يا جميلتي {user.first_name} 🌸\n\n"
        "هذا بوت *قهر العادة للفتيات* 🩷\n"
        "وُجد خصيصًا ليكون عونًا لكِ في رحلة التعافي من العادات التي تُتعب قلبك، "
        "وتُضعف صلتكِ بنفسك الحقيقية وربِّك.\n\n"
        "اعتبري هذا البوت صديقة رقمية تذكّرك بقيمتك، وتشجّعك، وتفرح بكل خطوة ثبات تقومين بها 🤍\n\n"
        "استخدمي الأزرار في الأسفل لاختيار ما يناسب حالتك الآن 👇\n"
        "⚠️ ملاحظة: هذا البوت مخصّص للفتيات فقط."
    )

    update.message.reply_text(text, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")

    # إشعار للمشرفة عند دخول مستخدمة جديدة لأول مرة
    if created and is_admin(ADMIN_ID):
        try:
            context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "👤 *مستخدمة جديدة دخلت إلى البوت:*\n\n"
                    f"الاسم: {user.full_name}\n"
                    f"ID: `{user.id}`\n"
                    f"اسم المستخدم: @{user.username if user.username else 'لا يوجد'}"
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Error notifying admin about new user: {e}")


def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "غاليتي 🌸\n\n"
        "استخدمي الأزرار في الأسفل للتنقّل بين مميزات البوت:\n"
        "• بدء الرحلة ومتابعة عدّاد التعافي.\n"
        "• قراءة النصائح وخطة الطوارئ وأسباب الانتكاس.\n"
        "• قراءة الأذكار وتسجيل ملاحظاتك اليومية.\n\n"
        "وإن احتجتِ دعمًا شخصيًا، اضغطي على زر «تواصل مع الدعم ✉️» "
        "واكتبي ما في قلبك، وسيتم إرسال رسالتك إلى المشرفة 🤍",
        reply_markup=MAIN_KEYBOARD,
    )

# =================== وظائف الأزرار ===================


def handle_start_journey(update: Update, context: CallbackContext):
    user = update.effective_user
    record, _ = get_user_record(user)

    if record.get("streak_start"):
        delta = get_streak_delta(record)
        if delta:
            human = format_streak_text(delta)
            update.message.reply_text(
                f"🚀 رحلتكِ في التعافي بدأت من قبل.\nمدة ثباتك الحالية: {human}.",
                reply_markup=MAIN_KEYBOARD,
            )
            return

    now_iso = datetime.now(timezone.utc).isoformat()
    update_user_record(user.id, streak_start=now_iso)

    update.message.reply_text(
        "🚀 تم بدء رحلتكِ في التعافي يا حبيبتي 🌸\n"
        "من هذه اللحظة سيبدأ العدّ لمدّة ثباتك عن العادة.",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_days_counter(update: Update, context: CallbackContext):
    user = update.effective_user
    record, _ = get_user_record(user)

    delta = get_streak_delta(record)
    if not delta:
        update.message.reply_text(
            "لم تبدئي رحلتكِ بعد 🌱\n"
            "اضغطي على زر «بدء الرحلة 🚀» لبدء عدّاد التعافي.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    human = format_streak_text(delta)
    update.message.reply_text(
        f"⏱ مدة تعافيكِ حتى الآن:\n{human}",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_tip(update: Update, context: CallbackContext):
    tip = random.choice(TIPS)
    update.message.reply_text(
        f"💖 نصيحة لقلبك اليوم:\n{tip}",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_emergency(update: Update, context: CallbackContext):
    update.message.reply_text(
        EMERGENCY_PLAN,
        reply_markup=MAIN_KEYBOARD,
        parse_mode="Markdown",
    )


def handle_relapse_reasons(update: Update, context: CallbackContext):
    update.message.reply_text(
        RELAPSE_REASONS,
        reply_markup=MAIN_KEYBOARD,
        parse_mode="Markdown",
    )


def handle_adhkar(update: Update, context: CallbackContext):
    update.message.reply_text(
        ADHKAR,
        reply_markup=MAIN_KEYBOARD,
        parse_mode="Markdown",
    )


def handle_notes(update: Update, context: CallbackContext):
    user = update.effective_user
    record, _ = get_user_record(user)
    notes = record.get("notes", [])

    if not notes:
        update.message.reply_text(
            "📓 لا توجد ملاحظات بعد.\n"
            "أرسلي أي جملة تريدين حفظها، وسأضيفها إلى ملاحظاتك يا جميلتي.",
            reply_markup=MAIN_KEYBOARD,
        )
    else:
        last_notes = notes[-20:]
        joined = "\n\n".join(f"{idx+1}. {n}" for idx, n in enumerate(last_notes))
        update.message.reply_text(
            f"📓 آخر ملاحظاتك:\n\n{joined}\n\n"
            "📝 يمكنك إرسال ملاحظة جديدة في أي وقت، وسأقوم بحفظها لكِ.",
            reply_markup=MAIN_KEYBOARD,
        )


def handle_reset_counter(update: Update, context: CallbackContext):
    user = update.effective_user
    record, _ = get_user_record(user)

    if not record.get("streak_start"):
        update.message.reply_text(
            "العداد لم يُضبط بعد.\n"
            "يمكنك البدء عبر زر «بدء الرحلة 🚀».",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    update_user_record(user.id, streak_start=now_iso)

    update.message.reply_text(
        "♻️ تم إعادة ضبط عدّاد التعافي.\n"
        "اعتبريها بداية جديدة أقوى بإذن الله يا غاليتي 🤍",
        reply_markup=MAIN_KEYBOARD,
    )


def handle_contact_support(update: Update, context: CallbackContext):
    user = update.effective_user
    WAITING_FOR_SUPPORT.add(user.id)

    update.message.reply_text(
        "✉️ غاليتي، اكتبي الآن رسالتك التي تودّين إرسالها إلى *المشرفة*.\n\n"
        "يمكنك أن تشرحي ما تشعرين به، أو موقفًا مرّ عليكِ، أو انتكاسة حدثت، "
        "أو مجرد فضفضة تحتاج إلى من يسمعها.\n\n"
        "إن أحببتِ التراجع، اضغطي على زر «إلغاء ❌».",
        reply_markup=SUPPORT_KEYBOARD,
        parse_mode="Markdown",
    )


def handle_broadcast_button(update: Update, context: CallbackContext):
    user = update.effective_user
    if not is_admin(user.id):
        update.message.reply_text(
            "هذه الميزة خاصة بالمشرفة فقط 👩‍💻",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    WAITING_FOR_BROADCAST.add(user.id)
    update.message.reply_text(
        "📢 ارسلي الآن الرسالة التي تريدين إرسالها إلى جميع المشتركات في البوت.\n\n"
        "إن أردتِ الإلغاء، اضغطي على زر «إلغاء ❌».",
        reply_markup=BROADCAST_KEYBOARD,
    )


def handle_stats_button(update: Update, context: CallbackContext):
    user = update.effective_user
    if not is_admin(user.id):
        update.message.reply_text(
            "هذه المعلومة خاصة بالمشرفة فقط 👩‍💻",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    total_users = len(get_all_user_ids())
    update.message.reply_text(
        f"👥 عدد المشتركات المسجّلات في البوت: *{total_users}*",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )

# =================== الهاندلر العام للرسائل ===================


def handle_text_message(update: Update, context: CallbackContext):
    user = update.effective_user
    user_id = user.id
    text = (update.message.text or "").strip()

    record, _ = get_user_record(user)

    # زر إلغاء
    if text == BTN_CANCEL:
        if user_id in WAITING_FOR_SUPPORT:
            WAITING_FOR_SUPPORT.discard(user_id)
            update.message.reply_text(
                "تم إلغاء رسالة الدعم.\n"
                "يمكنك العودة لاستخدام الأزرار في الأسفل يا جميلتي 🌸",
                reply_markup=MAIN_KEYBOARD,
            )
            return
        if user_id in WAITING_FOR_BROADCAST:
            WAITING_FOR_BROADCAST.discard(user_id)
            update.message.reply_text(
                "تم إلغاء وضع الرسالة الجماعية.\n"
                "يمكنك العودة لاستخدام بقية المميزات 🌿",
                reply_markup=MAIN_KEYBOARD,
            )
            return

    # 1️⃣ لو المشرفة ردّت بالـ Reply على رسالة دعم
    if is_admin(user_id) and update.message.reply_to_message:
        # نحاول استخراج ID من نص الرسالة الأصلية
        original_text = update.message.reply_to_message.text or ""
        target_id = None
        # نبحث عن سطر فيه ID: رقم
        for line in original_text.splitlines():
            line = line.strip()
            if line.startswith("ID:"):
                try:
                    parts = line.split("ID:")[1].strip()
                    # قد يكون على الشكل `12345`
                    parts = parts.replace("`", "").strip()
                    target_id = int(parts)
                except Exception:
                    target_id = None
                break

        if target_id:
            try:
                context.bot.send_message(
                    chat_id=target_id,
                    text=(
                        "💌 ردّ من المشرفة:\n\n"
                        f"{text}"
                    ),
                )
                update.message.reply_text(
                    "✅ تم إرسال ردّكِ إلى المشتركة.",
                    reply_markup=MAIN_KEYBOARD,
                )
            except Exception as e:
                logger.error(f"Error sending reply to user {target_id}: {e}")
                update.message.reply_text(
                    "حدث خطأ أثناء إرسال الرسالة للمشتركة.",
                    reply_markup=MAIN_KEYBOARD,
                )
        else:
            update.message.reply_text(
                "لم أستطع تحديد هوية المشتركة من هذه الرسالة.\n"
                "تأكدي أنكِ تردّين على رسالة دعم تحتوي على سطر ID.",
                reply_markup=MAIN_KEYBOARD,
            )
        return

    # 2️⃣ وضع "تواصل مع الدعم"
    if user_id in WAITING_FOR_SUPPORT:
        WAITING_FOR_SUPPORT.discard(user_id)

        support_msg = (
            "📩 *رسالة جديدة إلى المشرفة:*\n\n"
            f"الاسم: {user.full_name}\n"
            f"ID: `{user_id}`\n"
            f"اسم المستخدم: @{user.username if user.username else 'لا يوجد'}\n\n"
            f"✉️ محتوى الرسالة:\n{text}"
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
            "✅ تم إرسال رسالتكِ إلى المشرفة يا حبيبتي.\n"
            "سيتم الاطلاع عليها والرد عليكِ إن لزم الأمر بإذن الله 🤍",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # 3️⃣ وضع "رسالة جماعية" (للمشرفة فقط)
    if user_id in WAITING_FOR_BROADCAST:
        WAITING_FOR_BROADCAST.discard(user_id)

        if not is_admin(user_id):
            update.message.reply_text(
                "هذه الميزة خاصة بالمشرفة فقط 👩‍💻",
                reply_markup=MAIN_KEYBOARD,
            )
            return

        user_ids = get_all_user_ids()
        sent = 0
        for uid in user_ids:
            try:
                context.bot.send_message(
                    chat_id=uid,
                    text=(
                        "📢 رسالة من المشرفة:\n\n"
                        f"{text}\n\n"
                        "إن أردتِ الرد على هذه الرسالة:\n"
                        "1️⃣ اضغطي على الرسالة مطوّلًا.\n"
                        "2️⃣ اختاري Reply / الرد.\n"
                        "3️⃣ اكتبي رسالتك بعدها ليصل ردّكِ إلى المشرفة 💌."
                    ),
                )
                sent += 1
            except Exception as e:
                logger.error(f"Error sending broadcast to {uid}: {e}")

        update.message.reply_text(
            f"✅ تم إرسال الرسالة إلى {sent} مشتركة.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # 4️⃣ التعامل مع الأزرار
    if text == BTN_START:
        handle_start_journey(update, context)
        return
    if text == BTN_COUNTER:
        handle_days_counter(update, context)
        return
    if text == BTN_TIP:
        handle_tip(update, context)
        return
    if text == BTN_EMERGENCY:
        handle_emergency(update, context)
        return
    if text == BTN_RELAPSE:
        handle_relapse_reasons(update, context)
        return
    if text == BTN_DHIKR:
        handle_adhkar(update, context)
        return
    if text == BTN_NOTES:
        handle_notes(update, context)
        return
    if text == BTN_RESET:
        handle_reset_counter(update, context)
        return
    if text == BTN_SUPPORT:
        handle_contact_support(update, context)
        return
    if text == BTN_BROADCAST:
        handle_broadcast_button(update, context)
        return
    if text == BTN_STATS:
        handle_stats_button(update, context)
        return

    # 5️⃣ أي نص آخر من المشتركة → نعتبره ملاحظة + تنبيه أنه لا يصل للمشرفة
    notes = record.get("notes", [])
    notes.append(text)
    update_user_record(user_id, notes=notes)

    update.message.reply_text(
        "📝 تم حفظ رسالتكِ كملاحظة شخصية داخل البوت.\n\n"
        "⚠️ تنبيه يا غاليتي:\n"
        "هذه الرسالة لا تصل إلى *المشرفة* بشكل مباشر.\n\n"
        "إن أردتِ التواصل مع المشرفة:\n"
        "1️⃣ اضغطي على زر «تواصل مع الدعم ✉️» في الأسفل.\n"
        "2️⃣ أو اضغطي على رسالة سابقة جاءتْك من المشرفة في الخاص، "
        "ثم اختاري Reply / الرد واكتبي رسالتك بعدها.\n\n"
        "بهذه الطريقة تضمنين أن رسالتك تصل إلى المشرفة وتتم متابعتها بإذن الله 💌",
        reply_markup=MAIN_KEYBOARD,
        parse_mode="Markdown",
    )

# =================== التذكير اليومي ===================


def send_daily_reminders(context: CallbackContext):
    logger.info("Running daily reminders job...")
    user_ids = get_all_user_ids()
    for uid in user_ids:
        try:
            context.bot.send_message(
                chat_id=uid,
                text=(
                    "🤍 *تذكير لطيف لقلبك يا غاليتي:*\n\n"
                    "أنتِ لستِ وحدك في هذه الرحلة، وهناك الكثير من الفتيات يجاهدن مثلك تمامًا.\n"
                    "خذي دقيقة الآن لتستحضري سبب رغبتك في التعافي، وتذكّري أنكِ تستحقين قلبًا نقيًّا "
                    "ونفسًا مطمئنة.\n\n"
                    "اضغطي على الزر الذي تحتاجينه الآن في البوت، ولا تخجلي من طلب العون متى احتجتِ 🌸."
                ),
                parse_mode="Markdown",
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

    # جميع الرسائل النصية
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text_message))

    # جدولة تذكير يومي عن طريق JobQueue (الساعة 20:00 بتوقيت UTC)
    job_queue = updater.job_queue
    job_queue.run_daily(
        send_daily_reminders,
        time=time(hour=20, minute=0, tzinfo=pytz.utc),
        name="daily_reminders",
    )

    # تشغيل Flask في ثريد منفصل
    Thread(target=run_flask, daemon=True).start()

    logger.info("Bot is starting...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
