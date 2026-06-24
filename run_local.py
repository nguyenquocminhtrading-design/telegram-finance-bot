"""
Run bot and web dashboard locally (polling mode).
"""
import os
import sys
import threading
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Set polling mode
os.environ["BOT_MODE"] = "polling"

def start_bot():
    from bot import bot
    logger.info("Starting bot in polling mode...")
    try:
        bot.remove_webhook()
        bot.polling(none_stop=True, interval=1, timeout=30)
    except Exception as e:
        logger.error(f"Bot polling error: {e}")

def start_web():
    from app import app
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting web dashboard at http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════╗
║   TELEGRAM FINANCE BOT - LOCAL MODE             ║
╠══════════════════════════════════════════════════╣
║  Web Dashboard: http://localhost:5000            ║
║  Bot: polling (không cần webhook)               ║
║                                                  ║
║  LẦN ĐẦU CHẠY: gõ /sync để import từ Sheets     ║
╚══════════════════════════════════════════════════╝
""")
    threading.Thread(target=start_bot, daemon=True).start()
    start_web()
