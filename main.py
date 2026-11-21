import os
import itertools
import time
import threading
import sys
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from concurrent.futures import ThreadPoolExecutor

from providers import samehadaku, kusonime

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
WORKER_URL = os.environ.get("WORKER_URL", "https://ciro-anime-wake.captenciro.workers.dev").strip()
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

print("🤖 CiroAnime Bot is initializing (On-Demand GitHub Actions Edition)...")

_cb_counter = itertools.count(1)
CB_CACHE = {}

IDLE_TIMEOUT_SECONDS = 3600
last_activity_time = time.time()
is_shutting_down = False
last_user_chat_id = None

def update_activity(chat_id=None):
    global last_activity_time, last_user_chat_id
    last_activity_time = time.time()
    if chat_id:
        last_user_chat_id = chat_id

def cb_cache_put(data):
    key = f"a_{next(_cb_counter)}"
    if len(CB_CACHE) > 2000:
        for k in list(CB_CACHE.keys())[:400]:
            CB_CACHE.pop(k, None)
    CB_CACHE[key] = data
    return key

def restore_webhook():
    if not WORKER_URL:
        return
    try:
        print(f"🔄 Restoring webhook to Cloudflare Worker: {WORKER_URL}")
        bot.set_webhook(url=WORKER_URL, drop_pending_updates=True)
        print("✅ Webhook restored successfully!")
    except Exception as e:
        print(f"⚠️ Failed to restore webhook: {e}")

def shutdown_bot(reason="timeout"):
    global is_shutting_down
    if is_shutting_down:
        return
    is_shutting_down = True
    print(f"🛑 Shutting down CiroAnime Bot (Reason: {reason})...")

    if last_user_chat_id:
        try:
            if reason == "manual":
                bot.send_message(
                    last_user_chat_id,
                    "💤 <b>CiroAnime Bot telah dinonaktifkan (Manual Stop).</b>\n"
                    "Server GitHub Actions dimatikan untuk menghemat kuota.\n\n"
                    "<i>Ketik judul anime apa saja kapan pun untuk membangunkan kembali!</i>"
                )
            else:
                bot.send_message(
                    last_user_chat_id,
                    "💤 <b>CiroAnime Bot otomatis tidur</b> karena tidak ada aktivitas selama 1 jam.\n"
                    "Server dimatikan dengan aman. Ketik judul anime apa pun jika ingin nonton lagi!"
                )
        except Exception as e:
            print(f"⚠️ Failed to send shutdown message: {e}")

    try:
        bot.stop_polling()
    except Exception:
        pass

    restore_webhook()
    print("👋 Bye! Process exiting cleanly.")
    os._exit(0)

def idle_checker_thread():
    while not is_shutting_down:
        time.sleep(15)
        idle_duration = time.time() - last_activity_time
        if idle_duration >= IDLE_TIMEOUT_SECONDS:
            print(f"⏰ Idle timeout reached ({int(idle_duration)}s >= {IDLE_TIMEOUT_SECONDS}s).")
            shutdown_bot(reason="timeout")
            break

@bot.message_handler(commands=["stop", "off"])
def handle_stop(message):
    update_activity(message.chat.id)
    bot.reply_to(message, "🛑 <i>Menerima perintah /stop. Menyiapkan proses tidur...</i>")
    threading.Thread(target=shutdown_bot, kwargs={"reason": "manual"}).start()

@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    update_activity(message.chat.id)
    text = (
        "🍿 <b>Selamat Datang di CiroAnime Bot!</b>\n\n"
        "Bot streaming & download <b>Anime Sub Indo</b> tercepat tanpa iklan, pop-up, atau shortlink receh.\n\n"
        "📌 <b>Fitur Utama:</b>\n"
        "• 📺 <b>Samehadaku Engine:</b> Episode terbaru & anime ongoing mingguan.\n"
        "• 📦 <b>Kusonime Engine:</b> Paket Batch lengkap (Google Drive, Mega, Acefile, Pixeldrain).\n\n"
        "🔍 <b>Cara Pakai:</b>\n"
        "Cukup ketik judul anime apa saja yang ingin kamu tonton.\n"
        "Contoh:\n"
        "• <code>Solo Leveling</code>\n"
        "• <code>Frieren</code>\n"
        "• <code>Naruto Batch</code>\n\n"
        "<i>Server on-demand otomatis aktif dan tidur jika tidak ada aktivitas.</i>"
    )
    bot.reply_to(message, text)

def process_search_query(chat_id: int, query: str):
    update_activity(chat_id)
    q = query.strip()
    if not q:
        return

    wait_msg = bot.send_message(chat_id, f"🔍 <b>Mencari anime:</b> <i>\"{q}\"</i>...\n<i>Sedang menghubungkan ke Samehadaku & Kusonime...</i>")

    with ThreadPoolExecutor(max_workers=2) as executor:
        fut_same = executor.submit(samehadaku.search, q)
        fut_kuso = executor.submit(kusonime.search, q)
        same_res = fut_same.result() or []
        kuso_res = fut_kuso.result() or []

    total_results = len(same_res) + len(kuso_res)
    if total_results == 0:
        bot.edit_message_text(
            f"❌ <b>Anime tidak ditemukan untuk pencarian:</b> <i>\"{q}\"</i>\n"
            "Coba ketik kata kunci yang lebih singkat atau judul bahasa Inggrisnya.",
            chat_id=chat_id,
            message_id=wait_msg.message_id
        )
        return

    markup = InlineKeyboardMarkup(row_width=1)

    if kuso_res:
        markup.add(InlineKeyboardButton("📦 ═══ HASIL BATCH (KUSONIME) ═══", callback_data="none"))
        for item in kuso_res[:5]:
            cb_id = cb_cache_put({"action": "kuso_detail", "url": item["url"]})
            btn_title = f"📦 {item['title'][:45]}"
            markup.add(InlineKeyboardButton(btn_title, callback_data=cb_id))

    if same_res:
        markup.add(InlineKeyboardButton("📺 ═══ HASIL EPISODE (SAMEHADAKU) ═══", callback_data="none"))
        for item in same_res[:8]:
            cb_id = cb_cache_put({"action": "same_detail", "url": item["url"]})
            icon = "📦" if item.get("type") == "batch" else "📺"
            btn_title = f"{icon} {item['title'][:45]}"
            markup.add(InlineKeyboardButton(btn_title, callback_data=cb_id))

    res_text = (
        f"🎯 <b>Hasil Pencarian:</b> <i>\"{q}\"</i>\n"
        f"Ditemukan <b>{len(kuso_res)}</b> paket Batch & <b>{len(same_res)}</b> Episode.\n\n"
        "Silakan pilih anime di bawah ini untuk melihat link download:"
    )

    bot.edit_message_text(res_text, chat_id=chat_id, message_id=wait_msg.message_id, reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text and not msg.text.startswith("/"))
def handle_text_search(message):
    process_search_query(message.chat.id, message.text)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    update_activity(call.message.chat.id)
    if call.data == "none":
        bot.answer_callback_query(call.id)
        return

    data = CB_CACHE.get(call.data)
    if not data:
        bot.answer_callback_query(call.id, "⚠️ Sesi tombol telah kedaluwarsa. Silakan cari ulang.", show_alert=True)
        return

    action = data.get("action")

    if action == "kuso_detail":
        bot.answer_callback_query(call.id, "⏳ Mengambil data Batch Kusonime...")
        url = data.get("url")
        detail = kusonime.get_detail(url)
        if not detail or not detail.get("batches"):
            bot.send_message(call.message.chat.id, "⚠️ Gagal mengambil detail batch dari Kusonime.")
            return

        title = detail.get("title", "Batch Anime")
        batches = detail.get("batches", [])
        
        caption = f"📦 <b>{title}</b>\n\n"
        caption += f"📌 <i>Ditemukan {len(batches)} paket download. Pilih paket di bawah:</i>"

        markup = InlineKeyboardMarkup(row_width=1)
        for idx, b in enumerate(batches):
            b_key = cb_cache_put({"action": "kuso_batch_links", "url": url, "batch_idx": idx})
            markup.add(InlineKeyboardButton(f"📥 {b['batch_name'][:45]}", callback_data=b_key))

        bot.send_message(call.message.chat.id, caption, reply_markup=markup)

    elif action == "kuso_batch_links":
        bot.answer_callback_query(call.id)
        url = data.get("url")
        idx = data.get("batch_idx", 0)
        detail = kusonime.get_detail(url)
        batches = detail.get("batches", [])
        if idx >= len(batches):
            return

        target_batch = batches[idx]
        b_name = target_batch["batch_name"]
        res_dict = target_batch["resolutions"]

        text = f"📦 <b>{b_name}</b>\n\n"
        text += "Pilih resolusi dan server untuk mendownload langsung:\n\n"

        for res_name, links in res_dict.items():
            text += f"🔹 <b>{res_name}:</b>\n"
            for link in links[:5]:
                text += f"  • <a href=\"{link['url']}\">{link['server']}</a>\n"
            text += "\n"

        text += "<i>💡 Klik nama server di atas untuk membuka link download.</i>"
        bot.send_message(call.message.chat.id, text, disable_web_page_preview=True)

    elif action == "same_detail":
        bot.answer_callback_query(call.id, "⏳ Mengambil link download Samehadaku...")
        url = data.get("url")
        detail = samehadaku.get_detail(url)
        if not detail:
            bot.send_message(call.message.chat.id, "⚠️ Gagal mengambil halaman Samehadaku.")
            return

        title = detail.get("title", "Episode Anime")
        downloads = detail.get("downloads", {})

        if not downloads:
            bot.send_message(call.message.chat.id, f"⚠️ Tidak ditemukan link download langsung pada halaman:\n{url}")
            return

        text = f"📺 <b>{title}</b>\n\n"
        text += "Daftar link download bersih (Bebas Iklan):\n\n"

        for res_name, links in downloads.items():
            text += f"🎬 <b>Resolusi {res_name}:</b>\n"
            for link in links:
                text += f"  • <a href=\"{link['url']}\">{link['server']}</a>\n"
            text += "\n"

        text += "<i>💡 Klik nama server di atas untuk streaming / download langsung.</i>"
        bot.send_message(call.message.chat.id, text, disable_web_page_preview=True)

def main():
    if not BOT_TOKEN:
        print("❌ Error: BOT_TOKEN is required!")
        sys.exit(1)

    print("🚀 Initializing Telegram polling & Webhook cleanup...")
    try:
        bot.remove_webhook()
        print("✅ Telegram webhook removed successfully for local polling.")
    except Exception as e:
        print(f"⚠️ Webhook removal error: {e}")

    t = threading.Thread(target=idle_checker_thread, daemon=True)
    t.start()

    wake_chat_id = os.environ.get("WAKE_CHAT_ID", "").strip()
    wake_query = os.environ.get("WAKE_QUERY", "").strip()
    wake_msg_id = os.environ.get("WAKE_MSG_ID", "").strip()

    def handle_initial_wake():
        if not wake_chat_id or not wake_query:
            return
        try:
            cid = int(wake_chat_id)
            print(f"⚡ Handling initial wake query: '{wake_query}' for chat {cid} (Wake Msg ID: {wake_msg_id})")

            # 1. Hapus pesan 10%
            if wake_msg_id and wake_msg_id != "0":
                try:
                    bot.delete_message(cid, int(wake_msg_id))
                    print("🗑️ Deleted wake message")
                except Exception as e:
                    print(f"⚠️ Failed to delete wake message: {e}")

            # 2. Notifikasi cepat bot aktif
            on_msg = bot.send_message(cid, "🟢 <b>Bot CiroAnime ON</b>", parse_mode="HTML")
            time.sleep(1.2)
            try:
                bot.delete_message(cid, on_msg.message_id)
            except Exception:
                pass

            # 3. Jalankan pencarian jika bukan perintah stop/start
            if wake_query not in ["/stop", "/off", "/start"]:
                process_search_query(cid, wake_query)
        except Exception as e:
            print(f"⚠️ Error handling initial wake: {e}")

    threading.Thread(target=handle_initial_wake, daemon=True).start()

    print("🤖 Bot is now actively listening for updates...")
    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    main()
