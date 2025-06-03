import os
from threading import Thread
from flask import Flask
import asyncio

# Assuming your main bot logic and the 'bot' object are defined in main.py
# Make sure main.py does NOT call bot.run(TOKEN) itself, but defines the bot object.
# We will pass the bot object or its token directly here.
from main import bot, TOKEN # Import the bot object and the TOKEN variable from main.py

# Initialize Flask app
app = Flask(__name__)

# Define a simple health check route
@app.route('/')
def home():
    """A simple endpoint to confirm the server is running."""
    return "Bot is alive!"

def run_discord_bot():
    """Function to run the Discord bot in a separate thread."""
    try:
        # The TOKEN is now imported from main.py, which gets it from .env or system env.
        if TOKEN is None:
            print("ERROR: Discord bot token is not set. Cannot run bot.")
            return

        # discord.py's bot.run() method handles its own event loop, making it
        # suitable for running directly in a new thread.
        print("Starting Discord bot...")
        bot.run(TOKEN)
    except Exception as e:
        print(f"FATAL ERROR: Discord bot crashed: {e}")
        # In a production environment, you might want more robust error handling
        # or graceful shutdown here.

def start_web_server():
    """Starts the Flask web server."""
    # Render provides the PORT environment variable to web services
    port = int(os.getenv("PORT", 5000)) # Default to 5000 if PORT is not set (e.g., local testing)
    print(f"Flask web server starting on port {port}...")
    # host="0.0.0.0" makes the server accessible from outside the container
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # Start the Discord bot in a separate thread
    # This ensures the Flask server doesn't block the bot, and vice-versa.
    discord_bot_thread = Thread(target=run_discord_bot)
    discord_bot_thread.start()

    # Start the Flask web server in the main thread.
    # This thread will be the primary process that Render monitors.
    start_web_server()
