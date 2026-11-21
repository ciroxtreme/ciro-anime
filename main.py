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

# Cache memori untuk callback dengan atomic counter (anti-collision)
_cb_counter = itertools.count(1)
CB_CACHE = {}

# Idle timer management (1 jam = 3600 detik)
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
    """Mengembalikan Telegram Webhook ke Cloudflare Worker saat bot mau tidur"""
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
                    "<i>Ketik judul anime kapan pun untuk membangunkan kembali!</i>"
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
    """Background monitor untuk auto-shutdown jika nganggur 1 jam"""
    while not is_shutting_down:
        time.sleep(15)
        idle_duration = time.time() - last_activity_time
        if idle_duration >= IDLE_TIMEOUT_SECONDS:
            print(f"⏰ Idle timeout reached ({int(idle_duration)}s >= {IDLE_TIMEOUT_SECONDS}s).")
            shutdown_bot(reason="timeout")
            break

# ============================================================================
# BOT COMMAND HANDLERS
# ============================================================================

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
        "Bot download & streaming <b>Anime Sub Indo</b> tercepat tanpa iklan, pop-up, atau shortlink receh.\n\n"
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

# ============================================================================
# SEARCH & PROCESSOR
# ============================================================================

def process_search_query(chat_id, query, edit_msg_id=None):
    update_activity(chat_id)
    q = query.strip()
    if not q:
        return

    status_text = f"🔍 <b>Mencari anime:</b> <i>\"{q}\"</i>...\nMohon tunggu sebentar..."
    if edit_msg_id:
        try:
            bot.edit_message_text(status_text, chat_id=chat_id, message_id=edit_msg_id)
            wait_msg_id = edit_msg_id
        except Exception:
            wait_msg = bot.send_message(chat_id, status_text)
            wait_msg_id = wait_msg.message_id
    else:
        wait_msg = bot.send_message(chat_id, status_text)
        wait_msg_id = wait_msg.message_id

    # Jalankan pencarian Samehadaku & Kusonime secara paralel
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
            message_id=wait_msg_id
        )
        return

    markup = InlineKeyboardMarkup(row_width=1)

    # 1. Tampilkan Kusonime (Batch Tamat)
    if kuso_res:
        markup.add(InlineKeyboardButton("📦 --- HASIL BATCH (KUSONIME) ---", callback_data="none"))
        for item in kuso_res[:5]:
            cb_id = cb_cache_put({"action": "kuso_detail", "url": item["url"]})
            btn_title = f"📦 {item['title'][:45]}"
            markup.add(InlineKeyboardButton(btn_title, callback_data=cb_id))

    # 2. Tampilkan Samehadaku (Episode & Ongoing)
    if same_res:
        markup.add(InlineKeyboardButton("📺 --- HASIL EPISODE (SAMEHADAKU) ---", callback_data="none"))
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

    bot.edit_message_text(res_text, chat_id=chat_id, message_id=wait_msg_id, reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text and not msg.text.startswith("/"))
def handle_text_search(message):
    process_search_query(message.chat.id, message.text)

# ============================================================================
# CALLBACK QUERY HANDLER
# ============================================================================

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

    # DETAIL KUSONIME BATCH
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

    # LINK RESOLUSI KUSONIME
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

    # DETAIL SAMEHADAKU EPISODE
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

# ============================================================================
# MAIN ENTRYPOINT
# ============================================================================

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

    # Start idle timeout monitor thread
    t = threading.Thread(target=idle_checker_thread, daemon=True)
    t.start()

    # Cek payload pemicu bangun (wake up)
    wake_chat_id = os.environ.get("WAKE_CHAT_ID")
    wake_query = os.environ.get("WAKE_QUERY")
    wake_msg_id = os.environ.get("WAKE_MSG_ID")

    if wake_chat_id and wake_query:
        print(f"⚡ Handling wake-up query: '{wake_query}' for chat {wake_chat_id}...")
        try:
            threading.Thread(
                target=process_search_query,
                args=(int(wake_chat_id), wake_query, int(wake_msg_id) if wake_msg_id else None),
                daemon=True
            ).start()
        except Exception as e:
            print(f"⚠️ Failed to process wake query: {e}")

    print("🤖 Bot is now actively listening for updates...")
    bot.infinity_polling(timeout=20, long_polling_timeout=20)

if __name__ == "__main__":
    main()
