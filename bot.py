import os
import feedparser
import asyncio
from datetime import datetime, timezone
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes

# --- Configuration ---
# Get token from GitHub Secrets (Environment Variable)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
# Your target channel/group ID (e.g., "-1001234567890")
CHAT_ID = os.environ.get("CHAT_ID")

# RSS Feeds for Phone News (GSMArena & PhoneArena)
FEEDS = [
    "https://www.gsmarena.com/rss-news-reviews.php3",
    "https://www.phonearena.com/feed"
]

# File to track seen posts and avoid duplicates
SEEN_FILE = "seen_news.txt"

def load_seen():
    """Load previously seen article URLs."""
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(line.strip() for line in f)
    return set()

def save_seen(seen_set):
    """Save seen URLs to file (for GitHub Actions caching)."""
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
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /help command."""
    help_text = (
        "🔧 *Help*\n\n"
        "This bot monitors reputable sources (GSMArena, PhoneArena) for new phone releases and rumors.\n\n"
        "• Use /latest to manually check for updates.\n"
        "• The bot automatically posts to the channel when new content is available.\n"
        "• No spam, only real phone news."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def latest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /latest command - fetches news on demand."""
    await update.message.reply_text("🔍 Checking for the latest phone news...")
    await check_and_send(context.bot, force_send=True)

async def check_and_send(bot, force_send=False):
    """Fetch feeds and send new items to the channel."""
    seen = load_seen()
    new_items = []
    
    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:  # Check top 5 from each feed
                url = entry.link
                if url not in seen or force_send:
                    new_items.append({
                        "title": entry.title,
                        "link": url,
                        "summary": getattr(entry, "summary", "No summary available.")[:200] + "...",
                        "published": getattr(entry, "published", "")
                    })
        except Exception as e:
            print(f"Error parsing feed {feed_url}: {e}")
    
    # Send new items (limit to avoid flooding)
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
                parse_mode="Markdown",
                disable_web_page_preview=False
            )
            seen.add(item['link'])
        except Exception as e:
            print(f"Failed to send message: {e}")
    
    save_seen(seen)
    return len(new_items)

async def post_init(application: Application):
    """Set bot commands menu (visible to users)."""
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("latest", "Get latest phone news now"),
        BotCommand("help", "How to use this bot")
    ]
    await application.bot.set_my_commands(commands)

def main():
    """Main entry point for GitHub Actions."""
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set")
    
    # Build application
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("latest", latest_command))
    
    # For GitHub Actions (one-shot mode): run once and exit
    # If running locally with polling, use application.run_polling()
    if os.environ.get("GITHUB_ACTIONS"):
        # Run once to check for updates
        print("Running in GitHub Actions mode...")
        asyncio.run(check_and_send(application.bot))
        print("Check complete.")
    else:
        # Local polling mode (for testing)
        print("Running in polling mode...")
        application.run_polling()
