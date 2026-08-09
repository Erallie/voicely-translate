import net from 'node:net';
import process from 'node:process';
import { Client, GatewayIntentBits } from 'discord.js';
import {
    EndBehaviorType,
    VoiceConnectionStatus,
    entersState,
    joinVoiceChannel,
} from '@discordjs/voice';
import prism from 'prism-media';

const token = process.env.DISCORD_TOKEN;
const host = process.env.VOICE_WORKER_HOST || '127.0.0.1';
const port = Number(process.env.VOICE_WORKER_PORT || '8765');

if (!token) {
    throw new Error('DISCORD_TOKEN is not set.');
}

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildVoiceStates,
    ],
});

const connections = new Map();
let socket;
let incomingBuffer = '';
let shuttingDown = false;

function send(payload) {
    if (!socket || socket.destroyed) {
        return;
    }

    socket.write(`${JSON.stringify(payload)}\n`);
}

function log(message) {
    send({
        type: 'log',
        message,
    });
}

function cleanupGuild(guildId) {
    const state = connections.get(guildId);

    if (!state) {
        return;
    }

    for (const streamState of state.streams.values()) {
        try {
            streamState.opusStream.destroy();
        } catch {
            // Ignore cleanup errors.
        }

        try {
            streamState.decoder.destroy();
        } catch {
            // Ignore cleanup errors.
        }
    }

    state.streams.clear();

    try {
        state.connection.destroy();
    } catch {
        // Ignore cleanup errors.
    }

    connections.delete(guildId);
}

function subscribeToSpeaker(guildId, userId) {
    const state = connections.get(guildId);

    if (!state || userId === client.user?.id || state.streams.has(userId)) {
        return;
    }

    const opusStream = state.connection.receiver.subscribe(userId, {
        end: {
            behavior: EndBehaviorType.AfterSilence,
            duration: 250,
        },
    });

    const decoder = new prism.opus.Decoder({
        rate: 48000,
        channels: 2,
        frameSize: 960,
    });

    state.streams.set(userId, {
        opusStream,
        decoder,
    });

    opusStream.on('error', (error) => {
        send({
            type: 'voice_error',
            guild_id: guildId,
            message: `Opus receive stream error for user ${userId}: ${error.message}`,
        });
    });

    decoder.on('error', (error) => {
        send({
            type: 'voice_error',
            guild_id: guildId,
            message: `Opus decoder error for user ${userId}: ${error.message}`,
        });
    });

    decoder.on('data', (pcm) => {
        send({
            type: 'audio',
            guild_id: guildId,
            user_id: userId,
            pcm: pcm.toString('base64'),
        });
    });

    const cleanupStream = () => {
        const current = state.streams.get(userId);

        if (current?.opusStream === opusStream) {
            state.streams.delete(userId);
        }

        try {
            decoder.destroy();
        } catch {
            // Ignore cleanup errors.
        }
    };

    opusStream.once('end', cleanupStream);
    opusStream.once('close', cleanupStream);

    opusStream.pipe(decoder);
}

async function joinGuild(guildId, channelId) {
    cleanupGuild(guildId);

    try {
        const guild = await client.guilds.fetch(guildId);
        const channel = await client.channels.fetch(channelId);

        if (!channel || !channel.isVoiceBased() || channel.guildId !== guildId) {
            throw new Error('The requested channel is not a voice channel in that guild.');
        }

        const connection = joinVoiceChannel({
            channelId,
            guildId,
            adapterCreator: guild.voiceAdapterCreator,
            selfDeaf: false,
            selfMute: true,
            daveEncryption: true,
            decryptionFailureTolerance: 24,
        });

        const state = {
            connection,
            streams: new Map(),
        };
        connections.set(guildId, state);

        connection.on('error', (error) => {
            send({
                type: 'voice_error',
                guild_id: guildId,
                message: error.message,
            });
        });

        connection.on(VoiceConnectionStatus.Disconnected, () => {
            log(`Voice connection disconnected in guild ${guildId}.`);
        });

        connection.receiver.speaking.on('start', (userId) => {
            subscribeToSpeaker(guildId, userId);
        });

        await entersState(connection, VoiceConnectionStatus.Ready, 20_000);

        send({
            type: 'joined',
            guild_id: guildId,
            channel_id: channelId,
        });
    } catch (error) {
        cleanupGuild(guildId);
        send({
            type: 'join_error',
            guild_id: guildId,
            message: error instanceof Error ? error.message : String(error),
        });
    }
}

async function handleMessage(message) {
    switch (message.type) {
        case 'join':
            await joinGuild(String(message.guild_id), String(message.channel_id));
            break;

        case 'leave':
            cleanupGuild(String(message.guild_id));
            send({
                type: 'left',
                guild_id: String(message.guild_id),
            });
            break;

        case 'shutdown':
            shuttingDown = true;

            for (const guildId of [...connections.keys()]) {
                cleanupGuild(guildId);
            }

            await client.destroy();
            socket?.end();
            process.exit(0);
            break;

        default:
            log(`Unknown bridge command: ${message.type}`);
            break;
    }
}

function connectToPython() {
    socket = net.createConnection({ host, port });

    socket.setNoDelay(true);

    socket.on('connect', () => {
        console.log(`Connected to Python voice bridge at ${host}:${port}`);

        if (client.isReady()) {
            send({ type: 'ready' });
        }
    });

    socket.on('data', (chunk) => {
        incomingBuffer += chunk.toString('utf8');

        while (true) {
            const newlineIndex = incomingBuffer.indexOf('\n');

            if (newlineIndex === -1) {
                break;
            }

            const line = incomingBuffer.slice(0, newlineIndex);
            incomingBuffer = incomingBuffer.slice(newlineIndex + 1);

            if (!line.trim()) {
                continue;
            }

            let message;

            try {
                message = JSON.parse(line);
            } catch (error) {
                console.error('Invalid JSON from Python:', error);
                continue;
            }

            void handleMessage(message);
        }
    });

    socket.on('error', (error) => {
        console.error('Python bridge socket error:', error.message);
    });

    socket.on('close', () => {
        if (shuttingDown) {
            return;
        }

        console.error('Python bridge socket closed. Reconnecting...');

        socket = undefined;
        incomingBuffer = '';

        setTimeout(() => {
            connectToPython();
        }, 1000);
    });
}

client.once('ready', () => {
    console.log(`Voice worker logged in as ${client.user.tag}`);

    if (socket?.readyState === 'open') {
        send({ type: 'ready' });
    }
});

client.on('error', (error) => {
    console.error('Discord client error:', error);
});

connectToPython();
await client.login(token);
