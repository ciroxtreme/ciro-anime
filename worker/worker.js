export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // 1-Click setWebhook endpoint
    if (url.pathname === "/setWebhook") {
      const botToken = env.BOT_TOKEN;
      const webhookUrl = `${url.origin}/`;
      const res = await fetch(`https://api.telegram.org/bot${botToken}/setWebhook?url=${encodeURIComponent(webhookUrl)}&drop_pending_updates=true`);
      const data = await res.json();
      return new Response(JSON.stringify(data, null, 2), {
        headers: { "Content-Type": "application/json" }
      });
    }

    if (request.method !== "POST") {
      return new Response("CiroAnime Wake-up Bridge OK", { status: 200 });
    }

    try {
      const update = await request.json();
      const message = update.message;
      const chatId = message?.chat?.id;
      const text = message?.text?.trim();

      if (!chatId || !text) {
        return new Response("OK", { status: 200 });
      }

      const botToken = env.BOT_TOKEN;
      const ghToken = env.GH_TOKEN;
      const repo = "ciroxtreme/ciro-anime";

      // 1. Cek apakah ada run yang sedang in_progress atau queued
      const runsRes = await fetch(`https://api.github.com/repos/${repo}/actions/runs?status=in_progress`, {
        headers: {
          "Authorization": `Bearer ${ghToken}`,
          "User-Agent": "CiroAnime-WakeWorker",
          "Accept": "application/vnd.github+json"
        }
      });
      const runsData = await runsRes.json();
      const inProgressRuns = runsData?.workflow_runs || [];
      const hasActiveRun = inProgressRuns.length > 0;

      // KASUS 1: Perintah /stop saat mesin LAGI TIDUR atau ON
      if (text === "/stop" || text === "/off") {
        if (!hasActiveRun) {
          await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              chat_id: chatId,
              text: "💤 <b>Mesin CiroAnime memang sedang OFF (Tidur).</b>\nKetik judul anime apa saja untuk menyalakan!",
              parse_mode: "HTML"
            })
          });
          return new Response("OK", { status: 200 });
        } else {
          for (const run of inProgressRuns) {
            await fetch(`https://api.github.com/repos/${repo}/actions/runs/${run.id}/cancel`, {
              method: "POST",
              headers: {
                "Authorization": `Bearer ${ghToken}`,
                "User-Agent": "CiroAnime-WakeWorker",
                "Accept": "application/vnd.github+json"
              }
            });
          }
          await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              chat_id: chatId,
              text: "🛑 <b>Mesin CiroAnime berhasil dimatikan (OFF).</b>",
              parse_mode: "HTML"
            })
          });
          return new Response("OK", { status: 200 });
        }
      }

      // KASUS 2: Jika mesin sedang booting / running dan user chat lagi
      if (hasActiveRun) {
        await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chat_id: chatId,
            text: `⏳ <b>Mesin CiroAnime sedang proses aktif...</b>\nSedang menyiapkan pencarian <i>"${text}"</i>. Mohon tunggu beberapa detik ya!`,
            parse_mode: "HTML"
          })
        });
        return new Response("OK", { status: 200 });
      }

      // KASUS 3: Bangunkan mesin dari keadaan tidur
      const initialText = "🚀 <b>Membangunkan mesin CiroAnime...</b> <i>(Est. ~30-45 detik)</i>\n" +
                          "▓░░░░░░░░░ [10%] Menghubungi GitHub Runner...";
      const sendRes = await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: chatId,
          text: initialText,
          parse_mode: "HTML"
        })
      });
      const sendData = await sendRes.json();
      const wakeMsgId = sendData?.result?.message_id || 0;

      // Pemicu GitHub Actions via repository_dispatch
      await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${ghToken}`,
          "User-Agent": "CiroAnime-WakeWorker",
          "Accept": "application/vnd.github+json",
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          event_type: "wake_bot",
          client_payload: {
            chat_id: chatId,
            query: text,
            wake_msg_id: wakeMsgId
          }
        })
      });

      return new Response("OK", { status: 200 });
    } catch (e) {
      console.error("Worker Wake Error:", e);
      return new Response("Error", { status: 500 });
    }
  }
};
