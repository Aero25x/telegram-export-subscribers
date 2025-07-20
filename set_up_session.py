
# generate_string_session.py - Generate a string session
import asyncio
from telethon import TelegramClient

API_ID = ''
API_HASH = ''

async def generate_string_session():
    """Generate a string session that you can store as an environment variable"""
    client = TelegramClient('campaign_tracker', API_ID, API_HASH)

    await client.start()

    # Get the string session
    session_string = client.session.save()
    print("Your string session:")
    print(session_string)
    print("\nSave this string securely - you can use it instead of a session file!")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(generate_string_session())

# Usage in your main bot with string session:
"""
from telethon.sessions import StringSession

SESSION_STRING = "your_generated_session_string_here"
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
"""
