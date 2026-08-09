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

function parseKofiPayloadFromRawBody(rawBody, contentType) {
    if (contentType.includes("application/x-www-form-urlencoded")) {
        const params = new URLSearchParams(rawBody);
        const rawData = params.get("data");

        if (!rawData) {
            throw new Error("Missing Ko-fi data field.");
        }

        return JSON.parse(rawData);
    }

    const body = JSON.parse(rawBody);

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

async function processKofiPayment(payload, env) {
    if (
        !env.KOFI_VERIFICATION_TOKEN
        || payload?.verification_token !== env.KOFI_VERIFICATION_TOKEN
    ) {
        throw new Error("INVALID_VERIFICATION_TOKEN");
    }

    // Only the dedicated Voicely Translate Credits Ko-fi Shop product
    // is allowed to create Voicely credit.
    if (payload?.type !== "Shop Order") {
        return {
            ok: true,
            ignored: true,
            reason: "Not a Ko-fi Shop order.",
        };
    }

    const shopItems = Array.isArray(payload.shop_items)
        ? payload.shop_items
        : [];

    if (shopItems.length === 0) {
        return {
            ok: true,
            ignored: true,
            reason: "Shop order contains no shop_items.",
        };
    }

    if (!env.VOICELY_SHOP_ITEM_CODE) {
        console.error("VOICELY_SHOP_ITEM_CODE is not configured.");
        throw new Error("VOICELY_SHOP_ITEM_CODE_NOT_CONFIGURED");
    }

    const voicelyShopItemCode = String(
        env.VOICELY_SHOP_ITEM_CODE
    ).trim();

    const containsVoicelyItem = shopItems.some(
        (item) => String(item?.direct_link_code || "").trim()
            === voicelyShopItemCode
    );

    if (!containsVoicelyItem) {
        return {
            ok: true,
            ignored: true,
            reason: "Shop order is not for Voicely Translate Credits.",
        };
    }

    // Avoid treating money spent on unrelated products as Voicely credit.
    const containsOtherItems = shopItems.some(
        (item) => String(item?.direct_link_code || "").trim()
            !== voicelyShopItemCode
    );

    if (containsOtherItems) {
        console.warn(
            "Ignoring mixed Ko-fi Shop order containing Voicely credits "
            + "and other products."
        );

        return {
            ok: true,
            ignored: true,
            reason: (
                "Mixed shop orders cannot be converted into Voicely credit. "
                + "Purchase Voicely Translate Credits separately."
            ),
        };
    }

    const messageId = String(
        payload.message_id
        || payload.kofi_transaction_id
        || ""
    ).trim();

    const currency = String(payload.currency || "").toUpperCase();
    const topupCode = normalizeCode(payload.message);

    if (!messageId) {
        throw new Error("MISSING_MESSAGE_ID");
    }

    if (!topupCode) {
        console.warn(
            `Ignoring Voicely Shop order ${messageId}: `
            + "no VT-XXXXXX server code was supplied in the order message."
        );

        return {
            ok: true,
            ignored: true,
            reason: "Missing Voicely server top-up code in Ko-fi message.",
        };
    }

    if (currency !== "USD") {
        console.warn(
            `Ignoring Ko-fi payment ${messageId}: unsupported currency ${currency}`
        );

        return {
            ok: true,
            ignored: true,
            reason: "Only USD payments are currently supported.",
        };
    }

    let amountMicrousd;

    try {
        amountMicrousd = decimalUsdToMicrousd(payload.amount);
    } catch {
        throw new Error("INVALID_PAYMENT_AMOUNT");
    }

    if (amountMicrousd <= 0) {
        throw new Error("INVALID_PAYMENT_AMOUNT");
    }

    const registration = await env.DB.prepare(
        `
        SELECT guild_id
        FROM registrations
        WHERE topup_code = ?
        `
    )
        .bind(topupCode)
        .first();

    const guildId = registration?.guild_id
        ? String(registration.guild_id)
        : null;

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
        `Voicely Shop payment ${messageId}: `
        + `$${payload.amount} ${currency}, `
        + `code=${topupCode}, guild=${guildId || "unmatched"}`
    );

    return {
        ok: true,
        matched: Boolean(guildId),
        product: "Voicely Translate Credits",
    };
}

async function forwardWebhook(rawBody, contentType, env) {
    if (!env.EXISTING_WEBHOOK_URL) {
        console.warn(
            "EXISTING_WEBHOOK_URL is not configured; webhook was not forwarded."
        );

        return {
            forwarded: false,
            reason: "EXISTING_WEBHOOK_URL is not configured.",
        };
    }

    const response = await fetch(env.EXISTING_WEBHOOK_URL, {
        method: "POST",
        headers: {
            "content-type": contentType || "application/x-www-form-urlencoded",
        },
        body: rawBody,
    });

    const responseText = await response.text();

    if (!response.ok) {
        console.error(
            `Existing webhook returned HTTP ${response.status}: ${responseText}`
        );

        return {
            forwarded: false,
            status: response.status,
        };
    }

    console.log(
        `Forwarded Ko-fi webhook successfully; HTTP ${response.status}.`
    );

    return {
        forwarded: true,
        status: response.status,
    };
}

async function handleKofiWebhook(request, env) {
    const contentType = request.headers.get("content-type") || "";
    const rawBody = await request.text();

    let payload;

    try {
        payload = parseKofiPayloadFromRawBody(rawBody, contentType);
    } catch (error) {
        console.error("Could not parse Ko-fi webhook:", error);

        return jsonResponse({
            error: "Invalid webhook payload",
        }, 400);
    }

    let voicelyResult;

    try {
        voicelyResult = await processKofiPayment(payload, env);
    } catch (error) {
        if (error instanceof Error && error.message === "INVALID_VERIFICATION_TOKEN") {
            console.error(
                "Rejected Ko-fi webhook with invalid verification token."
            );

            return jsonResponse({
                error: "Invalid verification token",
            }, 401);
        }

        if (error instanceof Error && error.message === "MISSING_MESSAGE_ID") {
            return jsonResponse({
                error: "Missing payment message_id",
            }, 400);
        }

        if (error instanceof Error && error.message === "INVALID_PAYMENT_AMOUNT") {
            return jsonResponse({
                error: "Invalid payment amount",
            }, 400);
        }

        if (
            error instanceof Error
            && error.message === "VOICELY_SHOP_ITEM_CODE_NOT_CONFIGURED"
        ) {
            return jsonResponse({
                error: "Voicely Shop product code is not configured",
            }, 500);
        }

        console.error("Voicely Ko-fi processing failed:", error);

        return jsonResponse({
            error: "Voicely payment processing failed",
        }, 500);
    }

    let forwardResult;

    try {
        forwardResult = await forwardWebhook(
            rawBody,
            contentType,
            env,
        );
    } catch (error) {
        console.error("Could not forward Ko-fi webhook:", error);

        forwardResult = {
            forwarded: false,
            error: error instanceof Error ? error.message : String(error),
        };
    }

    return jsonResponse({
        ok: true,
        voicely: voicelyResult,
        forwarding: forwardResult,
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
