Voicely Translate - Node voice bridge setup

Files that must stay together in the same folder:
    voicely-translate-bridge.py
    voice-worker.mjs
    package.json
    requirements.txt
    .env

Your .env should contain:
    DISCORD_TOKEN=...
    OPENAI_API_KEY=...
    GUILD_ID=...

Python setup:
    python -m pip install -r requirements.txt

Node setup (Node.js 22.12.0 or newer):
    npm install

Run the bot:
    python voicely-translate-bridge.py

You do NOT run voice-worker.mjs yourself. The Python bot launches it automatically.

The Node worker only handles Discord voice receive and Opus -> PCM decoding.
The Python process still handles slash commands, per-user utterance buffering, OpenAI transcription/translation, and posting to the voice channel side chat.

If you later run this on Raspberry Pi and want lower CPU use for Opus decoding, you can try installing @discordjs/opus and removing opusscript, but opusscript is included here because it is easier to install across Windows and Linux.
