Discord Voice Translator Bot

Environment variables:
    DISCORD_TOKEN=your Discord bot token
    OPENAI_API_KEY=your OpenAI API key

Install:
    python -m pip install -r requirements.txt

Run:
    python discord_voice_translator.py

Commands:
    /join languages:English, Japanese, Spanish
    /add languages:French, Korean
    /remove languages:Spanish
    /languages
    /leave

Required Discord bot permissions in the server/channel:
    View Channel
    Connect
    Use Voice Activity
    Send Messages
    Use Application Commands

Notes:
    - The bot posts translations directly into the voice channel's built-in text chat.
    - Incoming audio is buffered separately for every Discord member, so overlapping speakers are processed independently.
    - Language values are comma-separated so there is no fixed number of language arguments.
    - The code uses gpt-4o-transcribe for speech-to-text and gpt-4o-mini for language detection + translations.
