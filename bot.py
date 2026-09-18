import os
import logging
import feedparser
from datetime import datetime, timezone
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes, JobQueue
from telegram.constants import ParseMode

# --- Configuration ---
# Read from Railway environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")  # Your channel ID (e.g., -1001234567890)

# RSS Feeds for Phone News
FEEDS = [
    "https://www.gsmarena.com/rss-news-reviews.php3",
    "https://www.phonearena.com/feed"
]

# File to track seen posts (persisted in Railway's ephemeral storage)
SEEN_FILE = "seen_news.txt"

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def load_seen():
    """Load previously seen article URLs."""
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(line.strip() for line in f)
    return set()


def save_seen(seen_set):
    """Save seen URLs to file."""
    with open(SEEN_FILE, "w") as f:
        for url in seen_set:
            f.write(url + "\n")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start command."""
    welcome_text = (
        "📱 *Phone Update Bot*\n\n"
        "I provide the latest phone news and leaks automatically.\n\n"
        "*Commands:*\n"
        "/start - Show this message\n"
        "/latest - Get the latest phone news immediately\n"
        "/help - How to use this bot\n\n"
        "I'm active 24/7 and push updates whenever new phone news breaks!"
    )
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /help command."""
    help_text = (
        "🔧 *Help*\n\n"
        "This bot monitors reputable sources (GSMArena, PhoneArena) for new phone releases and rumors.\n\n"
        "• Use /latest to manually check for updates.\n"
        "• The bot automatically posts to the channel when new content is available.\n"
        "• No spam, only real phone news."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def latest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /latest command - fetches news on demand."""
    await update.message.reply_text("🔍 Checking for the latest phone news...")
    await check_and_send(context.bot, force_send=True)


async def check_and_send(bot, force_send=False):
    """Fetch feeds and send new items to the channel."""
    if not CHAT_ID:
        logger.warning("CHAT_ID not set. Skipping channel post.")
        return 0

    seen = load_seen()
    new_items = []

    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:  # Check top 5 from each feed
                url = entry.link
                if url not in seen or force_send:
                    # Clean up summary
                    summary = getattr(entry, "summary", "No summary available.")
                    # Remove HTML tags roughly for Telegram
                    import re
                    summary = re.sub('<[^<]+?>', '', summary)
                    summary = summary[:200] + "..." if len(summary) > 200 else summary

                    new_items.append({
                        "title": entry.title,
                        "link": url,
                        "summary": summary,
                        "published": getattr(entry, "published", "")
                    })
        except Exception as e:
            logger.error(f"Error parsing feed {feed_url}: {e}")

    # Send new items (limit to avoid flooding)
    sent_count = 0
    for item in new_items[:3]:
        text = (
            f"📱 *{item['title']}*\n\n"
            f"{item['summary']}\n\n"
            f"🔗 [Read more]({item['link']})"
        )
        try:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=False
            )
            seen.add(item['link'])
            sent_count += 1
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    save_seen(seen)
    logger.info(f"Sent {sent_count} new items.")
    return len(new_items)


async def scheduled_check(context: ContextTypes.DEFAULT_TYPE):
    """Callback for the scheduled job."""
    logger.info("Running scheduled news check...")
    await check_and_send(context.bot)


async def post_init(application: Application):
    """Set bot commands menu and schedule the recurring job."""
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("latest", "Get latest phone news now"),
        BotCommand("help", "How to use this bot")
    ]
    await application.bot.set_my_commands(commands)

    # Schedule the news check to run every hour
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(
            scheduled_check,
            interval=3600,  # 1 hour in seconds
            first=10        # Start after 10 seconds
        )
        logger.info("Scheduled hourly news check.")
    else:
        logger.warning("JobQueue not available. Scheduled checks disabled.")


def main():
    """Main entry point for Railway."""
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set")

    logger.info("Starting Phone Update Bot...")

    # Build application with post_init to set commands and scheduler
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("latest", latest_command))

    # Run polling (Railway will keep this process alive 24/7)
    logger.info("Bot is running. Polling for updates...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
