// Clip bot webhook (24 Nov 2026). A free Cloudflare Worker: Telegram sends each of his messages here the
// moment he sends it, and the Worker starts telegram-inbox.yml for that one message (no more waiting on
// GitHub's */5 cron, which ran twice on 23 Nov). It also keeps his publish-time pings and sends each one
// on time (Cron Trigger every minute). Setup: docs/telegram-webhook.md in alfred-hq.
//
// Secrets, set in Cloudflare (never in this public repo): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
// GITHUB_TOKEN (fine-grained, repo clip-engine only, Actions: Read and write), HOOK_SECRET, PING_KEY.
// KV namespace bound as PINGS.

const REPO = "mapadda11/clip-engine";

async function tg(env, method, body) {
  return fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
}

async function due(env) {
  try { return JSON.parse((await env.PINGS.get("due")) || "[]"); } catch { return []; }
}

export default {
  async fetch(req, env) {
    const path = new URL(req.url).pathname;
    if (req.method === "POST" && path === "/telegram") {
      if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.HOOK_SECRET) return new Response("no", { status: 403 });
      const msg = ((await req.json()) || {}).message || {};
      if (String((msg.chat || {}).id) !== String(env.TELEGRAM_CHAT_ID) || !msg.text) return new Response("ok");
      await tg(env, "sendChatAction", { chat_id: env.TELEGRAM_CHAT_ID, action: "typing" });
      const update = JSON.stringify({ text: msg.text, reply_caption: (msg.reply_to_message || {}).caption || "" });
      const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/telegram-inbox.yml/dispatches`, {
        method: "POST",
        headers: { Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "clip-bot" },
        body: JSON.stringify({ ref: "main", inputs: { update: update.slice(0, 60000) } }),
      });
      if (!r.ok) await tg(env, "sendMessage", { chat_id: env.TELEGRAM_CHAT_ID, text: `I couldn't wake the robot (GitHub said ${r.status}).` });
      return new Response("ok"); // always 200, or Telegram keeps resending
    }
    if (req.method === "POST" && path === "/pings") { // the inbox adds pings here: [{at: unix seconds, text}]
      if (req.headers.get("Authorization") !== `Bearer ${env.PING_KEY}`) return new Response("no", { status: 403 });
      const add = await req.json();
      await env.PINGS.put("due", JSON.stringify((await due(env)).concat(add).sort((a, b) => a.at - b.at)));
      return new Response("ok");
    }
    return new Response("clip bot");
  },

  async scheduled(event, env) { // every minute: send the pings whose time has come
    const now = Date.now() / 1000, list = await due(env);
    const ready = list.filter((p) => p.at <= now);
    if (!ready.length) return;
    for (const p of ready) {
      await tg(env, "sendMessage", { chat_id: env.TELEGRAM_CHAT_ID, text: p.text, parse_mode: "HTML", disable_web_page_preview: true });
    }
    await env.PINGS.put("due", JSON.stringify(list.filter((p) => p.at > now)));
  },
};
