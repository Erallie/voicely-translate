# Voicely Translate

[![Invite Me](https://img.shields.io/badge/Invite%20Me-7965c7?style=for-the-badge)](https://discord.com/oauth2/authorize?client_id=1535789654974930964)
[![App Directory](https://img.shields.io/badge/App%20Directory-615ccc?style=for-the-badge)](https://discord.com/application-directory/1535789654974930964)
[![Privacy Policy](https://img.shields.io/badge/Privacy%20Policy-cc7a7c?style=for-the-badge)](https://github.com/Erallie/voicely-translate/blob/main/legal/privacy-policy.md)
<br>
[![Our Discord](https://img.shields.io/discord/1102582171207741480?style=for-the-badge&logo=discord&logoColor=ffffff&label=Our%20Discord&color=5865F2)](https://discord.gozarproductions.com)
[![Our Other Projects](https://img.shields.io/badge/Our%20Other%20Projects-%E2%9D%A4-563294?style=for-the-badge&logo=data%3Aimage%2Fwebp%3Bbase64%2CUklGRu4DAABXRUJQVlA4WAoAAAAQAAAAHwAAHwAAQUxQSGABAAABgFtbm5volyZTA%2BtibzK2H0w5sDkmhe3GmxrwxGg0839r%2FvkkOogIBW7bKB0c4%2BARYihzIqfd6dfO%2B%2B3XtHsq4jJhlIvcDRcgNB%2FeieQETorBHgghRtUYqwDs%2B4U4IpcvUB%2BVUPSK54uEnTwsUJoar2DeMpzLxQpeG5DH8lxyyfLivVYAwPBbkWdOBg3qFlqiLy679iHy9UDKMZRXmYxpCcusayTHG01K%2FEtatYWuj7oI9hL4BxsxVwhoP2mlAJJ%2BuuAflc6%2BEUCQTCX9EV87xBR2H75NxLZSpWiwzqdIm7ZO7uB3oEgZKbD9Nt3EmHweEPH1t1GNsZUbKeisiwjyTm5fA3SO1yCrADZXrV2PZQJPL1tjN4%2BxUL9ie1mJobzOnDwSx6ILiF%2FW%2BTUR4tcHx0UaV75JXC1a4g6Ky5dLcTSuy9q4HhTieF64Hy1A3GHB8gLLK2e92feuqnbfPK8IVlA4IGgCAACwDQCdASogACAAPk0cjEQioaEb%2BqwAKATEtgBOl7v9V3sHcA2wG4A3gD0APLP9jX9n%2F2jmqv5AZRh7J%2BN2fOx22iE%2F4TUsecFmY%2BSf1r%2BAP%2BTfzT%2FXdIB7KX7MtdIGr1A8H0jmrrfZvqButwOaYcLWYNRq5QgAAP7%2F%2FmIMpiVNn67QXpM1rrDmRS8Nr%2F6dhD%2Bq5e%2BM%2BAtUP1%2FxOj85Ol5y3ebjz%2BpHoOf%2FWW8a%2F2ojUaKVDkVqof%2Bv4f0f6ud8i58wusz%2Fyrj%2F%2BwnM3q0769dvK%2F%2BQe04xL49tkb9t6ylCqqezZtZGuGLJ%2F5iUrPqdYc%2F8VbYZfP%2FOpZP%2F4X4q%2BqS4gPOxzdINOe5PGv%2F0TS%2FJRf4LlFrFkrWtxlS8n40grV%2BKUu%2FiwzdQzImvwH81FxL1bZyTSsrYwMku1Pk9StTtWNjSR8ZWEYBH9eTn%2FvBERii5XaWOPJ%2FFVXtVQGbv%2BFRW5jbo9tfFDu%2BDHHf8LbgUd%2F8W8Id1AehBtRNsLQWbADmvF1QJU8x5tw%2FtTUwIoSaa%2F2jkcvyVHkAsb2qoIh1KF1pPdae%2BZaqjydy6nUa9agjrDk1G4pMhEUhH%2BV%2FIUe49MjhR%2FuxyFmwQ8dDogMyQ%2BdcSBa56Lwt1wyJ%2F22%2F5O98r6q6wiM63HyaYONd36W7br%2F0%2F6y2DZ3irAddj%2FRxntvr%2FbbChSYXAfEbO%2FD0G%2FFbMFqTHypodt9T6dAx%2BUjJYfHzFf%2FM3Ec%2FAtwbjc2gka6urN1MlSLb2VTS9Q5r8fkDzxZz6vu1OYUPUB1UFMIhYGvMATbxxoTmVhvpovzAc%2F8nbOjw3wAAA)](https://github.com/Erallie)
[![Donate](https://img.shields.io/badge/Donate-%24-563294?style=for-the-badge&logo=ko-fi&logoColor=FFFFFF&color=FF6433)](https://www.ko-fi.com/GozarProductions)

---

[English](README.md) | [Español](README.es.md) | [Português](README.pt-BR.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [简体中文](README.zh-CN.md) | [Русский](README.ru.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md)

Voicely Translate is a Discord bot that automatically transcribes and translates conversations happening in voice channels.

When the bot is active in a voice channel, it listens to each speaker individually, transcribes what they say, and posts the original transcription alongside translations in the voice channel's side chat.

Multiple translation languages can be enabled at once, and languages can be added or removed while the bot is already translating.

## Features

* Automatically transcribes speech from Discord voice channels.
* Translates conversations into multiple languages at the same time.
* Posts transcriptions and translations directly in the voice channel's side chat.
* Supports multiple people speaking, including overlapping speakers.
* Lets you add or remove translation languages without restarting the session.
* Uses BCP 47 language tags, allowing you to request languages beyond a fixed built-in list.
* Automatically leaves an empty voice channel after a configurable timeout.
* Can optionally be paired with [**Voicely Text**](https://discord.com/application-directory/1290741552158609419) to read translated messages aloud.

## Adding Voicely Translate to Your Server

Add Voicely Translate to your Discord server using the [this invite link](https://discord.com/oauth2/authorize?client_id=1535789654974930964).

Once installed, its commands are available as Discord slash commands.

To start translating, join a normal Discord voice channel and use:

`/join`

You must already be inside the voice channel that you want Voicely Translate to join.

## Starting a Translation Session

Use:

`/join`

The `languages` option is optional. If you specify languages, those languages will be used for the translation session:

`/join languages:<language tags>`

Separate multiple languages with commas.

For example:

`/join languages:en,ja`

This starts a translation session with English and Japanese enabled.

You can enable as many languages as you need:

`/join languages:en,ja,es,fr,de,ko`

If you use `/join` without specifying any languages, Voicely Translate will use the server's default translation languages.

If the server does not have any default languages configured, the bot will ask you to specify languages or ask a server administrator to configure the defaults.

Once connected, Voicely Translate will post its transcriptions and translations in the **side chat belonging to that voice channel**.

## Default Translation Languages

Server administrators can set the languages that Voicely Translate uses when someone runs `/join` without specifying the `languages` option.

Use:

`/defaultlanguages languages:<language tags>`

For example:

`/defaultlanguages languages:en,ja`

sets English and Japanese as the server's default translation languages.

Separate multiple languages with commas:

`/defaultlanguages languages:en,ja,es,fr`

These defaults are stored for the Discord server and remain in effect until a server administrator changes them.

Specifying languages directly with `/join` overrides the server defaults for that translation session. It does not change the saved defaults.

This command requires the **Administrator** permission.

## Language Tags

Voicely Translate uses language tags rather than language names.

For example:

* `en` — English
* `ja` — Japanese
* `es` — Spanish
* `fr` — French
* `de` — German
* `ko` — Korean
* `zh` — Chinese
* `haw` — Hawaiian

Regional and script-specific BCP 47 tags can also be used, such as `pt-BR` or `zh-TW`.

Use:

`/languages`

to see a reference list of common language tags.

The bot is **not limited to the languages shown by `/languages`**. You can also try other valid BCP 47 language tags.

## Changing Languages While Translating

You don't have to make the bot leave and rejoin just to change languages.

### Add languages

Use:

`/add languages:<language tags>`

For example:

`/add languages:fr,ko`

adds French and Korean to the current translation session.

### Remove languages

Use:

`/remove languages:<language tags>`

For example:

`/remove languages:en,fr`

removes English and French from the current translation session.

Removing a language only affects future translations. The bot can continue translating into any languages that remain enabled.

### See active languages

Use:

`/active`

to see which translation languages are currently enabled.

## Stopping Translation

Use:

`/leave`

to stop the current translation session and make Voicely Translate leave the voice channel.

The bot can also automatically leave when nobody remains in the voice channel.

## Empty Voice Channel Timeout

Server administrators can control how long Voicely Translate waits in an empty voice channel before automatically leaving.

Use:

`/timeout seconds:<seconds>`

For example:

`/timeout seconds:60`

makes the bot wait 60 seconds after the voice channel becomes empty.

The default timeout is **30 seconds**.

This command requires the **Administrator** permission.

## Voicely Credits

Voicely Translate uses a credit system to pay for the transcription and translation services required to process voice conversations.

**100 Voicely Credits = $1.00 USD.**

New servers currently receive **50 free trial credits**. That is enough for approximately **500 typical voice messages**, although actual usage varies.

Credits are consumed as speech is transcribed and translated. The amount used can vary depending on how much people speak and how many translations are requested.

Enabling more translation languages can increase usage because each transcription needs to be translated into the requested languages.

### Check your balance

Use:

`/balance`

to see:

* Available credits
* Remaining free trial credits
* Purchased credits

### Check usage

Use:

`/usage`

to see the server's accumulated usage, including:

* Total API usage
* Transcription usage
* Translation usage
* Total purchased credits

Credit balances and usage belong to the **Discord server**, not to an individual Discord user.

## Adding More Credits

Server administrators can use:

`/topup`

Voicely Translate will provide a unique top-up code for the server and instructions for purchasing additional credit through Ko-fi.

When making the payment, include the provided top-up code in the Ko-fi payment message.

Every **$1.00 USD adds 100 Voicely Credits**.

After making a payment, use:

`/balance`

or simply start the bot with `/join`.

Voicely Translate will automatically check for newly purchased credit.

The `/topup` command requires the **Administrator** permission.

## How Translation Works

When someone speaks in the voice channel, Voicely Translate processes that person's speech independently.

The basic process is:

1. Voicely Translate receives the speaker's voice audio.
2. The audio is transcribed into the language actually being spoken.
3. The transcription is translated into the currently enabled languages.
4. The original transcription and translations are posted in the voice channel's side chat.

Because speakers are processed independently, the bot is designed to handle conversations where multiple people may speak at or near the same time.

Short pauses are used to determine when an utterance has finished before it is sent for transcription.

Nonverbal sounds and standalone hesitation noises may be ignored rather than posted as messages.

## Example

Imagine three people are in a voice channel and English, Japanese, and Spanish are enabled.

Someone says:

> Are we ready to go?

Voicely Translate can post the original transcription along with translations such as:

**Original — English**
Are we ready to go?

**Japanese**
もう行く準備はできた？

**Spanish**
¿Estamos listos para irnos?

The exact formatting and translations may vary.

## Command Reference

| Command      | Description                                                           |
| ------------ | --------------------------------------------------------------------- |
| `/join`      | Join your current voice channel and begin translating.                |
| `/add`       | Add one or more translation languages to the active session.          |
| `/remove`    | Remove one or more translation languages from the active session.     |
| `/active`    | Show the currently enabled translation languages.                     |
| `/languages` | Show common language tags that can be used with the bot.              |
| `/leave`     | Stop translating and leave the voice channel.                         |
| `/balance`   | Show the server's remaining Voicely Credits.                          |
| `/usage`     | Show the server's transcription and translation usage.                |
| `/topup`     | Get instructions for adding more Voicely Credits. Administrator only. |
| `/timeout`   | Change the empty-channel timeout. Administrator only.                 |

## Using Voicely Text

Voicely Translate is designed to display translations as text.

If you also want translated messages to be **read aloud in the voice channel**, you can use Voicely Translate alongside [**Voicely Text**](https://discord.com/application-directory/1290741552158609419).

When Voicely Translate joins a server that does not have Voicely Text installed, it may provide a link for adding it.

## Tips for Better Results

For the best transcription and translation quality:

* Speak clearly and at a normal volume.
* Avoid extremely loud background music or noise.
* Use the most appropriate language tags for the conversation.
* Remember that automated transcription and translation can make mistakes, especially with names, slang, very short utterances, heavy background noise, or ambiguous speech.
* Use regional language tags when the distinction is important.

## Privacy and Voice Processing

Voicely Translate must process voice audio in order to provide transcription and translation.

Server owners should make sure that people using a voice channel understand that the bot is transcribing the conversation while it is present.

The bot only begins a translation session after someone explicitly uses `/join`, and `/leave` can be used to stop the session.

## About Voicely Translate

Voicely Translate is designed to make multilingual Discord voice conversations easier by putting the original speech and translations together in the same place where the conversation is happening.

Instead of requiring everyone in a call to speak the same language, participants can speak naturally while using the voice channel's side chat to follow the conversation in the languages they understand.

## Support
If you have any problems with the bot or want to request a feature, please create an [issue](https://github.com/Erallie/voicely-translate/issues), and I will address it to the best of my ability!
