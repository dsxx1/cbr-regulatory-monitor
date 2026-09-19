const encoder = new TextEncoder();

async function hmacHex(secret, body) {
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(body));
  return [...new Uint8Array(signature)].map(x => x.toString(16).padStart(2, "0")).join("");
}

function safeMessage(alert) {
  return `[${String(alert.level || "important").toUpperCase()}] ${String(alert.title || "").slice(0, 300)}\n\nИсточник: ${String(alert.source || "").slice(0, 200)}\nСсылка: ${String(alert.url || "").slice(0, 1000)}\nКлюч: ${String(alert.idempotency_key || "").slice(0, 80)}`;
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST" || new URL(request.url).pathname !== "/alert") return new Response("Not found", { status: 404 });
    const body = await request.text();
    const supplied = request.headers.get("X-Monitor-Signature") || "";
    if (!env.MONITOR_SHARED_SECRET || supplied !== await hmacHex(env.MONITOR_SHARED_SECRET, body)) return new Response("Unauthorized", { status: 401 });
    let alert;
    try { alert = JSON.parse(body); } catch { return new Response("Invalid JSON", { status: 400 }); }
    if (!alert.idempotency_key || !alert.title || !alert.url) return new Response("Invalid alert", { status: 400 });
    if (env.ALERTS) {
      const delivered = await env.ALERTS.get(alert.idempotency_key);
      if (delivered) return new Response(delivered, { status: 208, headers: { "content-type": "application/json" } });
    }
    const endpoint = `${env.B24_REST_URL}/imbot.v2.Chat.Message.send.json`;
    const reply = await fetch(endpoint, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ botId: Number(env.B24_BOT_ID), botToken: env.B24_BOT_TOKEN, dialogId: env.B24_DIALOG_ID, message: safeMessage(alert) }) });
    if (!reply.ok) return new Response("Bitrix24 unavailable", { status: 502 });
    let result;
    try { result = await reply.json(); } catch { return new Response("Invalid Bitrix24 response", { status: 502 }); }
    if (result.error) return new Response("Bitrix24 rejected message", { status: 502 });
    const delivered = JSON.stringify({ accepted: true, external_id: String(result.result?.id || result.result || alert.idempotency_key) });
    if (env.ALERTS) await env.ALERTS.put(alert.idempotency_key, delivered, { expirationTtl: 60 * 60 * 24 * 180 });
    return new Response(delivered, { status: 202, headers: { "content-type": "application/json" } });
  },
};
