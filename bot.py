import os
import re
import logging
import feedparser
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)
from telegram.constants import ParseMode

# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# RSS Feeds for Phone News
FEEDS = [
    "https://www.gsmarena.com/rss-news-reviews.php3",
    "https://www.phonearena.com/feed",
]

# Files (Railway persistent via volume recommended; otherwise ephemeral)
SUBSCRIBERS_FILE = "subscribers.txt"
SEEN_FILE = "seen_news.txt"

# How often to push updates to each user (in seconds)
UPDATE_INTERVAL = 3600  # 1 hour

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------- Persistence helpers ----------
def load_set(filepath):
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def save_set(filepath, data_set):
    with open(filepath, "w") as f:
        for item in data_set:
            f.write(item + "\n")


def load_subscribers():
    return load_set(SUBSCRIBERS_FILE)


def save_subscribers(subs):
    save_set(SUBSCRIBERS_FILE, subs)


def load_seen():
    return load_set(SEEN_FILE)


def save_seen(seen):
    save_set(SEEN_FILE, seen)


# ---------- News fetcher ----------
def clean_html(text):
    """Remove HTML tags and trim."""
    text = re.sub("<[^<]+?>", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:250] + "..." if len(text) > 250 else text


def fetch_new_news(seen, limit=3):
    """Fetch new phone news not yet seen."""
    new_items = []
    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:10]:
                url = entry.link
                if url in seen:
                    continue
                new_items.append(
                    {
                        "title": entry.title,
                        "link": url,
                        "summary": clean_html(getattr(entry, "summary", "")),
                    }
                )
        except Exception as e:
            logger.error(f"Error parsing feed {feed_url}: {e}")
    return new_items[:limit]


def build_message(item):
    return (
        f"📱 *{item['title']}*\n\n"
        f"{item['summary']}\n\n"
        f"🔗 [Read full article]({item['link']})"
    )


# ---------- Command handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    subscribers = load_subscribers()

    first_time = user_id not in subscribers
    if first_time:
        subscribers.add(user_id)
        save_subscribers(subscribers)

    keyboard = [
        [
            InlineKeyboardButton("📲 Latest News Now", callback_data="latest"),
            InlineKeyboardButton("❌ Stop Updates", callback_data="stop"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if first_time:
        text = (
            "👋 *Welcome to Phone Update Bot!*\n\n"
            "You're now subscribed. I'll send you the latest phone launches, "
            "leaks, and features automatically — right here in this chat.\n\n"
            "Use the buttons below anytime."
        )
    else:
        text = (
            "✅ You're already subscribed.\n\n"
            "I'll keep sending you the latest phone news automatically."
        )

    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🔧 *Help*\n\n"
        "*Commands:*\n"
        "/start – Subscribe and get the welcome message\n"
        "/latest – Fetch the latest phone news right now\n"
        "/stop – Unsubscribe from automatic updates\n"
        "/help – Show this message\n\n"
        "Once you start the bot, you'll automatically receive new phone "
        "launches, leaks, and reviews every hour."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def latest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Fetching the latest phone news...")
    seen = load_seen()
    items = fetch_new_news(seen, limit=3)
    if not items:
        await update.message.reply_text(
            "😕 No new phone news right now. Try again later."
        )
        return
    for item in items:
        await update.message.reply_text(
            build_message(item),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=False,
        )
        seen.add(item["link"])
    save_seen(seen)


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    subscribers = load_subscribers()
    if user_id in subscribers:
        subscribers.discard(user_id)
        save_subscribers(subscribers)
        await update.message.reply_text(
            "🛑 You've been unsubscribed. Send /start anytime to resubscribe."
        )
    else:
        await update.message.reply_text(
            "You're not currently subscribed. Send /start to subscribe."
        )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "latest":
        seen = load_seen()
        items = fetch_new_news(seen, limit=3)
        if not items:
            await query.message.reply_text("😕 No new phone news right now.")
            return
        for item in items:
            await query.message.reply_text(
                build_message(item),
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=False,
            )
            seen.add(item["link"])
        save_seen(seen)
    elif query.data == "stop":
        user_id = str(query.from_user.id)
        subscribers = load_subscribers()
        subscribers.discard(user_id)
        save_subscribers(subscribers)
        await query.message.reply_text(
            "🛑 You've been unsubscribed. Send /start to resubscribe."
        )


# ---------- Scheduled broadcast ----------
async def broadcast_updates(context: ContextTypes.DEFAULT_TYPE):
    """Send new phone news to every subscriber."""
    subscribers = load_subscribers()
    if not subscribers:
        logger.info("No subscribers yet.")
        return

    seen = load_seen()
    items = fetch_new_news(seen, limit=3)
    if not items:
        logger.info("No new items to broadcast.")
        return

    sent = 0
    for user_id in list(subscribers):
        for item in items:
            try:
                await context.bot.send_message(
                    chat_id=int(user_id),
                    text=build_message(item),
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=False,
                )
                sent += 1
            except Exception as e:
                logger.warning(f"Failed to send to {user_id}: {e}")
                # If user blocked the bot, remove them
                if "blocked" in str(e).lower() or "chat not found" in str(e).lower():
                    subscribers.discard(user_id)
                    save_subscribers(subscribers)
        # Mark items as seen after sending to all
    for item in items:
        seen.add(item["link"])
    save_seen(seen)
    logger.info(f"Broadcast complete. Sent {sent} messages to {len(subscribers)} users.")


# ---------- Post init: set commands + schedule ----------
async def post_init(application: Application):
    commands = [
        BotCommand("start", "Subscribe to phone updates"),
        BotCommand("latest", "Get the latest phone news now"),
        BotCommand("stop", "Unsubscribe from updates"),
        BotCommand("help", "How to use this bot"),
    ]
    await application.bot.set_my_commands(commands)

    if application.job_queue:
        application.job_queue.run_repeating(
            broadcast_updates,
            interval=UPDATE_INTERVAL,
            first=60,  # Start after 60 seconds
        )
        logger.info(f"Scheduled broadcast every {UPDATE_INTERVAL}s.")
    else:
        logger.warning("JobQueue unavailable — automatic updates disabled.")


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is not set")

    logger.info("Starting Phone Update Bot (personal mode)...")

    application = (
        Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("latest", latest_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot is running. Polling for updates...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
