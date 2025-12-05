import asyncio
import logging
import logging.config
from uuid import uuid4

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route
from telegram import InlineQueryResultArticle, InputTextMessageContent, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

from dify_client import ChatClient
from telebot import bot_token, dify_api_key, url, webhook_port

# Configure logging
LOGGING_CONFIG = {
    "version": 1,
    "handlers": {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "http",
            "stream": "ext://sys.stderr",
        }
    },
    "formatters": {
        "http": {
            "format": "%(levelname)s [%(asctime)s] %(name)s - %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
    },
    "loggers": {
        "httpx": {
            "handlers": ["default"],
            "level": "INFO",
        },
        "httpcore": {
            "handlers": ["default"],
            "level": "INFO",
        },
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)

# Initialize Dify Client
dify_client = ChatClient(dify_api_key)

# Define configuration constants for the webhook
PORT = webhook_port
WEBHOOK_PATH = "/"
WEBHOOK_URL = f"{url}{WEBHOOK_PATH}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    await update.message.reply_text(
        f"Hello {update.effective_user.first_name}! I'm your Telegram Bot. Type /help for available commands."
    )


async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the /help command."""
    await update.message.reply_text(
        "Available commands:\n"
        "/start - Start the bot\n"
        "/help - Display available commands\n"
        "/cat - Get a random cat picture\n"
        "/hello - Get a personal greeting\n"
        "/resetconversation - Reset your AI conversation\n\n"
        "You can also chat with me directly and I'll respond using AI!"
    )


async def cat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /cat command - send a random cat picture."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                "https://api.thecatapi.com/v1/images/search"
            )
            response.raise_for_status()
            data = response.json()
            cat_url = data[0]["url"]
            await update.message.reply_photo(cat_url)
        except (httpx.RequestError, KeyError) as e:
            logger.error(f"Error fetching cat image: {e}")
            await update.message.reply_text(
                "Sorry, I couldn't fetch a cat picture right now."
            )


async def hello(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /hello command - kept from original codebase."""
    await update.message.reply_text(f"Hello {update.effective_user.first_name}")


async def reset_conversation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Reset the user's conversation with Dify."""
    if "dify_conversation_id" in context.user_data:
        del context.user_data["dify_conversation_id"]
        await update.message.reply_text(
            "Your conversation has been reset. Let's start fresh!"
        )
    else:
        await update.message.reply_text("No active conversation to reset.")


async def handle_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle non-command messages by sending to Dify API."""
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name
    message_text = update.message.text

    # Send typing action to show the bot is processing
    await update.message.chat.send_action(action="typing")

    # Prepare inputs with user name
    inputs = {"name": user_name}

    # Initialize response to user
    response_text = ""

    try:
        # Get or create conversation ID for this user
        if "dify_conversation_id" not in context.user_data:
            # No existing conversation, create a new one by sending first message
            chat_response = dify_client.create_chat_message(
                user=user_id,
                inputs=inputs,  # Using the inputs with name
                query=message_text,
                response_mode="blocking",
            )

            chat_response.raise_for_status()
            chat_data = chat_response.json()
            context.user_data["dify_conversation_id"] = chat_data.get(
                "conversation_id"
            )
            response_text = chat_data.get("answer", "No response from AI")
        else:
            # Use existing conversation
            conversation_id = context.user_data["dify_conversation_id"]

            chat_response = dify_client.create_chat_message(
                user=user_id,
                inputs=inputs,  # Using the inputs with name
                query=message_text,
                conversation_id=conversation_id,
                response_mode="blocking",
            )

            chat_response.raise_for_status()
            chat_data = chat_response.json()
            response_text = chat_data.get("answer", "No response from AI")

    except Exception as e:
        logger.error(f"Error processing message with Dify API: {e}")
        response_text = "I encountered an error while processing your message."

    # Send response back to the user
    await update.message.reply_text(response_text)


async def inline_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle inline queries."""
    query = update.inline_query.query
    results = [
        InlineQueryResultArticle(
            id=str(uuid4()),
            title="Echo",
            input_message_content=InputTextMessageContent(
                query or "Empty query"
            ),
        )
    ]
    await update.inline_query.answer(results)


async def main() -> None:
    """Set up the application with webhook and Starlette web server."""
    # Create the Application with no updater
    application = Application.builder().token(bot_token).updater(None).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cat", cat))
    application.add_handler(CommandHandler("hello", hello))
    application.add_handler(
        CommandHandler("resetconversation", reset_conversation)
    )

    # Add inline query handler
    application.add_handler(InlineQueryHandler(inline_query))

    # Add message handler for non-command messages
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    # Set webhook for the Telegram bot
    await application.bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"Webhook set up at {WEBHOOK_URL}")

    # Set up Starlette routes
    async def telegram_webhook(request: Request) -> Response:
        """Handle incoming Telegram updates."""
        try:
            update_data = await request.json()
            await application.update_queue.put(
                Update.de_json(data=update_data, bot=application.bot)
            )
        except Exception as e:
            logger.error(f"Error processing Telegram update: {e}")
        return Response()

    async def health_check(request: Request) -> PlainTextResponse:
        """Provide a health check endpoint."""
        return PlainTextResponse(content="Bot is running")

    # Create Starlette application with routes
    starlette_app = Starlette(
        routes=[
            Route(WEBHOOK_PATH, telegram_webhook, methods=["POST"]),
            Route("/health", health_check, methods=["GET"]),
        ]
    )

    # Configure and run the web server
    webserver = uvicorn.Server(
        config=uvicorn.Config(
            app=starlette_app,
            port=PORT,
            host="172.17.0.1",  # Listen on all interfaces
            log_level="info",
            # ssl_certfile=r"C:\work\localhost+2.pem",
            # ssl_keyfile=r"C:\work\localhost+2-key.pem",
            forwarded_allow_ips="*",
            proxy_headers=True,
        )
    )

    logger.info(f"Starting webhook server on port {PORT}")

    # Start the application and webserver
    async with application:
        await application.start()
        await webserver.serve()
        await application.stop()


if __name__ == "__main__":
    asyncio.run(main())
