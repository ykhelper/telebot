import os

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Bot credentials
bot_token = os.getenv(
    "TELEGRAM_BOT_TOKEN", "here goes your access token from BotFather"
)
bot_user_name = os.getenv("TELEGRAM_BOT_USERNAME", "the username you entered")
url = os.getenv("WEBHOOK_URL", "https://localhost")

# Dify API credentials
dify_api_key = os.getenv("DIFY_API_KEY", "your_dify_api_key_here")

# Webhook configuration
webhook_port = int(os.getenv("PORT", "8000"))

base_url = os.getenv("BASE_URL", "http://contabo.duksosleepy.dev/v1")
