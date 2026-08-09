const TOPUP_CODE_PATTERN = /\bVT-[A-Z0-9]{6}\b/i;

function jsonResponse(data, status = 200) {
    return new Response(JSON.stringify(data), {
        status,
        headers: {
            "content-type": "application/json; charset=utf-8",
        },
    });
}

function isAuthorized(request, env) {
    const authorization = request.headers.get("authorization") || "";
    return authorization === `Bearer ${env.BOT_API_SECRET}`;
}

function normalizeCode(value) {
    const match = String(value || "").toUpperCase().match(TOPUP_CODE_PATTERN);
    return match ? match[0] : null;
}

function decimalUsdToMicrousd(value) {
    const text = String(value ?? "").trim();

    if (!/^\d+(?:\.\d+)?$/.test(text)) {
        throw new Error("Invalid USD amount.");
    }

    const [whole, fraction = ""] = text.split(".");
    const paddedFraction = `${fraction}000000`.slice(0, 6);

    return (
        Number.parseInt(whole, 10) * 1_000_000
        + Number.parseInt(paddedFraction, 10)
    );
}

async function parseKofiPayload(request) {
    const contentType = request.headers.get("content-type") || "";

    if (contentType.includes("application/x-www-form-urlencoded")) {
        const form = await request.formData();
        const rawData = form.get("data");

        if (!rawData) {
            throw new Error("Missing Ko-fi data field.");
        }

        return JSON.parse(String(rawData));
    }

    const body = await request.json();

    if (body && typeof body.data === "string") {
        return JSON.parse(body.data);
    }

    return body;
}

async function handleRegister(request, env) {
    if (!isAuthorized(request, env)) {
        return jsonResponse({ error: "Unauthorized" }, 401);
    }

    const body = await request.json();
    const guildId = String(body.guild_id || "").trim();
    const topupCode = normalizeCode(body.topup_code);

    if (!/^\d+$/.test(guildId) || !topupCode) {
        return jsonResponse({ error: "Invalid guild_id or topup_code" }, 400);
    }

    await env.DB.prepare(
        `
        INSERT INTO registrations (
            topup_code,
            guild_id,
            updated_at
        )
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(topup_code) DO UPDATE SET
            guild_id = excluded.guild_id,
            updated_at = CURRENT_TIMESTAMP
        `
    )
        .bind(topupCode, guildId)
        .run();

    await env.DB.prepare(
        `
        UPDATE topups
        SET guild_id = ?
        WHERE topup_code = ?
          AND guild_id IS NULL
        `
    )
        .bind(guildId, topupCode)
        .run();

    return jsonResponse({
        ok: true,
        guild_id: guildId,
        topup_code: topupCode,
    });
}

async function handlePending(request, env) {
    if (!isAuthorized(request, env)) {
        return jsonResponse({ error: "Unauthorized" }, 401);
    }

    const url = new URL(request.url);
    const guildId = String(url.searchParams.get("guild_id") || "").trim();

    if (!/^\d+$/.test(guildId)) {
        return jsonResponse({ error: "Invalid guild_id" }, 400);
    }

    const result = await env.DB.prepare(
        `
        SELECT
            message_id,
            amount_microusd,
            currency,
            topup_code,
            received_at
        FROM topups
        WHERE guild_id = ?
          AND claimed = 0
        ORDER BY received_at ASC
        LIMIT 100
        `
    )
        .bind(guildId)
        .all();

    return jsonResponse({
        topups: result.results || [],
    });
}

async function handleClaim(request, env) {
    if (!isAuthorized(request, env)) {
        return jsonResponse({ error: "Unauthorized" }, 401);
    }

    const body = await request.json();
    const guildId = String(body.guild_id || "").trim();
    const messageIds = Array.isArray(body.message_ids)
        ? body.message_ids.map((value) => String(value)).filter(Boolean)
        : [];

    if (!/^\d+$/.test(guildId) || messageIds.length === 0) {
        return jsonResponse({ error: "Invalid claim request" }, 400);
    }

    if (messageIds.length > 100) {
        return jsonResponse({ error: "Too many message_ids" }, 400);
    }

    const statements = messageIds.map((messageId) =>
        env.DB.prepare(
            `
            UPDATE topups
            SET claimed = 1
            WHERE guild_id = ?
              AND message_id = ?
            `
        ).bind(guildId, messageId)
    );

    await env.DB.batch(statements);

    return jsonResponse({
        ok: true,
        claimed: messageIds.length,
    });
}

async function handleKofiWebhook(request, env) {
    let payload;

    try {
        payload = await parseKofiPayload(request);
    } catch (error) {
        console.error("Could not parse Ko-fi webhook:", error);
        return jsonResponse({ error: "Invalid webhook payload" }, 400);
    }

    if (
        !env.KOFI_VERIFICATION_TOKEN
        || payload?.verification_token !== env.KOFI_VERIFICATION_TOKEN
    ) {
        console.error("Rejected Ko-fi webhook with invalid verification token.");
        return jsonResponse({ error: "Invalid verification token" }, 401);
    }

    const messageId = String(
        payload.message_id
        || payload.kofi_transaction_id
        || ""
    ).trim();

    const currency = String(payload.currency || "").toUpperCase();
    const topupCode = normalizeCode(payload.message);

    if (!messageId) {
        return jsonResponse({ error: "Missing payment message_id" }, 400);
    }

    if (currency !== "USD") {
        console.warn(
            `Ignoring Ko-fi payment ${messageId}: unsupported currency ${currency}`
        );

        return jsonResponse({
            ok: true,
            ignored: true,
            reason: "Only USD payments are currently supported.",
        });
    }

    let amountMicrousd;

    try {
        amountMicrousd = decimalUsdToMicrousd(payload.amount);
    } catch (error) {
        return jsonResponse({ error: "Invalid payment amount" }, 400);
    }

    if (amountMicrousd <= 0) {
        return jsonResponse({ error: "Payment amount must be positive" }, 400);
    }

    let guildId = null;

    if (topupCode) {
        const registration = await env.DB.prepare(
            `
            SELECT guild_id
            FROM registrations
            WHERE topup_code = ?
            `
        )
            .bind(topupCode)
            .first();

        if (registration?.guild_id) {
            guildId = String(registration.guild_id);
        }
    }

    await env.DB.prepare(
        `
        INSERT OR IGNORE INTO topups (
            message_id,
            guild_id,
            topup_code,
            amount_microusd,
            currency,
            claimed,
            received_at
        )
        VALUES (?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
        `
    )
        .bind(
            messageId,
            guildId,
            topupCode,
            amountMicrousd,
            currency,
        )
        .run();

    console.log(
        `Ko-fi payment ${messageId}: $${payload.amount} ${currency}, `
        + `code=${topupCode || "none"}, guild=${guildId || "unmatched"}`
    );

    // Ko-fi expects a 200 response for successfully received webhooks.
    return jsonResponse({
        ok: true,
        matched: Boolean(guildId),
    });
}

export default {
    async fetch(request, env) {
        const url = new URL(request.url);

        if (request.method === "GET" && url.pathname === "/health") {
            return jsonResponse({ ok: true });
        }

        if (request.method === "POST" && url.pathname === "/register") {
            return handleRegister(request, env);
        }

        if (request.method === "GET" && url.pathname === "/pending") {
            return handlePending(request, env);
        }

        if (request.method === "POST" && url.pathname === "/claim") {
            return handleClaim(request, env);
        }

        if (request.method === "POST" && url.pathname === "/kofi") {
            return handleKofiWebhook(request, env);
        }

        return jsonResponse({ error: "Not found" }, 404);
    },
};
