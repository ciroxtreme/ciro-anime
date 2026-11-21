import os
import itertools
import math
import time
import threading
import sys
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from providers import samehadaku, kusonime, otakudesu

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
WORKER_URL = os.environ.get("WORKER_URL", "https://ciro-anime-wake.captenciro.workers.dev").strip()
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

print("🤖 CiroAnime Bot is initializing (On-Demand GitHub Actions Edition)...")

# Cache memori untuk callback & hasil search per sesi
_cb_counter = itertools.count(1)
CB_CACHE = {}

# Items per page
PAGE_SIZE = 5

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
    key = f"c_{next(_cb_counter)}"
    if len(CB_CACHE) > 3000:
        for k in list(CB_CACHE.keys())[:500]:
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
    while not is_shutting_down:
        time.sleep(15)
        idle_duration = time.time() - last_activity_time
        if idle_duration >= IDLE_TIMEOUT_SECONDS:
            print(f"⏰ Idle timeout reached ({int(idle_duration)}s >= {IDLE_TIMEOUT_SECONDS}s).")
            shutdown_bot(reason="timeout")
            break

# ============================================================================
# COMMANDS
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
        "Cukup ketik judul anime yang ingin kamu tonton.\n"
        "Kamu bisa bebas pilih mau cari di sumber mana:\n"
        "• 📺 <b>Samehadaku:</b> Spesialis Episode & Ongoing Mingguan\n"
        "• 📦 <b>Kusonime:</b> Spesialis Paket Batch Tamat (GDrive / Mega)\n"
        "• 🌐 <b>Otakudesu:</b> Sumber Alternatif Lengkap\n\n"
        "<i>Semua link download bersih tanpa shortlink, iklan, atau pop-up!</i>"
    )
    bot.reply_to(message, text)

# ============================================================================
# PROVIDER SELECTION MENU
# ============================================================================

def show_provider_selection(chat_id: int, query: str, message_id: int = None):
    update_activity(chat_id)
    q = query.strip()
    if not q:
        return

    text = (
        f"🔍 <b>Pencarian Anime:</b> <i>\"{q}\"</i>\n\n"
        "Silakan pilih mau cari di sumber mana:"
    )

    markup = InlineKeyboardMarkup(row_width=1)
    
    cb_same = cb_cache_put({"action": "exec_search", "provider": "samehadaku", "query": q, "page": 1})
    cb_kuso = cb_cache_put({"action": "exec_search", "provider": "kusonime", "query": q, "page": 1})
    cb_otaku = cb_cache_put({"action": "exec_search", "provider": "otakudesu", "query": q, "page": 1})

    markup.add(
        InlineKeyboardButton("📺 Samehadaku (Episode & Ongoing)", callback_data=cb_same),
        InlineKeyboardButton("📦 Kusonime (Paket Batch Lengkap)", callback_data=cb_kuso),
        InlineKeyboardButton("🌐 Otakudesu (Episode & Batch)", callback_data=cb_otaku)
    )

    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text and not msg.text.startswith("/"))
def handle_text_query(message):
    show_provider_selection(message.chat.id, message.text)

# ============================================================================
# PAGINATED SEARCH RESULTS RENDERER
# ============================================================================

def render_search_results(chat_id: int, message_id: int, provider: str, query: str, page: int = 1, cached_results: list = None):
    update_activity(chat_id)

    # Ambil hasil dari cache atau lakukan scraping jika belum ada
    if cached_results is None:
        bot.edit_message_text(
            f"⏳ <i>Menghubungi server {provider.capitalize()} untuk \"{query}\"...</i>",
            chat_id=chat_id,
            message_id=message_id
        )
        if provider == "samehadaku":
            results = samehadaku.search(query)
        elif provider == "kusonime":
            results = kusonime.search(query)
        elif provider == "otakudesu":
            results = otakudesu.search(query)
        else:
            results = []
    else:
        results = cached_results

    if not results:
        back_cb = cb_cache_put({"action": "select_provider", "query": query})
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔄 Ganti Sumber Lain", callback_data=back_cb))
        bot.edit_message_text(
            f"❌ <b>Anime \"{query}\" tidak ditemukan di {provider.capitalize()}.</b>\n"
            "Coba cari menggunakan sumber yang lain di bawah ini:",
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=markup
        )
        return

    total_items = len(results)
    total_pages = math.ceil(total_items / PAGE_SIZE)
    current_page = max(1, min(page, total_pages))

    start_idx = (current_page - 1) * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    page_items = results[start_idx:end_idx]

    prov_icons = {"samehadaku": "📺", "kusonime": "📦", "otakudesu": "🌐"}
    icon = prov_icons.get(provider, "🎬")

    header_text = (
        f"{icon} <b>Hasil di {provider.capitalize()}:</b> <i>\"{query}\"</i>\n"
        f"Total <b>{total_items}</b> judul • Halaman <b>{current_page}/{total_pages}</b>\n\n"
        "Pilih judul di bawah untuk melihat link:"
    )

    markup = InlineKeyboardMarkup(row_width=1)

    for item in page_items:
        action_key = f"{provider}_detail"
        cb_key = cb_cache_put({"action": action_key, "url": item["url"], "query": query, "provider": provider, "page": current_page})
        type_badge = "📦" if item.get("type") == "batch" else "📺"
        btn_text = f"{type_badge} {item['title'][:45]}"
        markup.add(InlineKeyboardButton(btn_text, callback_data=cb_key))

    # Baris Tombol Navigasi Pagination
    nav_buttons = []
    results_cache_id = cb_cache_put(results)

    if current_page > 1:
        prev_cb = cb_cache_put({
            "action": "nav_page",
            "provider": provider,
            "query": query,
            "page": current_page - 1,
            "results_id": results_cache_id
        })
        nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=prev_cb))

    nav_buttons.append(InlineKeyboardButton(f"📄 {current_page}/{total_pages}", callback_data="none"))

    if current_page < total_pages:
        next_cb = cb_cache_put({
            "action": "nav_page",
            "provider": provider,
            "query": query,
            "page": current_page + 1,
            "results_id": results_cache_id
        })
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=next_cb))

    markup.row(*nav_buttons)

    # Tombol Ganti Provider
    switch_cb = cb_cache_put({"action": "select_provider", "query": query})
    markup.add(InlineKeyboardButton("🔄 Ganti Sumber Provider", callback_data=switch_cb))

    bot.edit_message_text(header_text, chat_id=chat_id, message_id=message_id, reply_markup=markup)

# ============================================================================
# CALLBACK QUERY ROUTING
# ============================================================================

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    update_activity(call.message.chat.id)
    if call.data == "none":
        bot.answer_callback_query(call.id)
        return

    data = CB_CACHE.get(call.data)
    if not data:
        bot.answer_callback_query(call.id, "⚠️ Sesi tombol telah kedaluwarsa. Silakan cari ulang ya.", show_alert=True)
        return

    action = data.get("action")

    # KEMBALI KE PILIHAN PROVIDER
    if action == "select_provider":
        bot.answer_callback_query(call.id)
        show_provider_selection(call.message.chat.id, data.get("query", ""), message_id=call.message.message_id)

    # EKSEKUSI PENCARIAN PROVIDER
    elif action == "exec_search":
        bot.answer_callback_query(call.id, f"Mencari di {data['provider']}...")
        render_search_results(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            provider=data["provider"],
            query=data["query"],
            page=1
        )

    # NAVIGASI NEXT / PREV HALAMAN
    elif action == "nav_page":
        bot.answer_callback_query(call.id)
        cached_list = CB_CACHE.get(data.get("results_id"))
        render_search_results(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            provider=data["provider"],
            query=data["query"],
            page=data["page"],
            cached_results=cached_list
        )

    # DETAIL KUSONIME BATCH
    elif action == "kusonime_detail":
        bot.answer_callback_query(call.id, "⏳ Mengambil data Batch Kusonime...")
        url = data.get("url")
        detail = kusonime.get_detail(url)
        if not detail or not detail.get("batches"):
            bot.send_message(call.message.chat.id, "⚠️ Gagal mengambil detail batch dari Kusonime.")
            return

        title = detail.get("title", "Batch Anime")
        batches = detail.get("batches", [])
        caption = f"📦 <b>{title}</b>\n\n📌 <i>Ditemukan {len(batches)} paket download. Pilih paket di bawah:</i>"

        markup = InlineKeyboardMarkup(row_width=1)
        for idx, b in enumerate(batches):
            b_key = cb_cache_put({"action": "kuso_batch_links", "url": url, "batch_idx": idx})
            markup.add(InlineKeyboardButton(f"📥 {b['batch_name'][:45]}", callback_data=b_key))

        bot.send_message(call.message.chat.id, caption, reply_markup=markup)

    # DETAIL LINK RESOLUSI KUSONIME
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

        text = f"📦 <b>{b_name}</b>\n\nPilih resolusi dan server untuk download:\n\n"
        for res_name, links in res_dict.items():
            text += f"🔹 <b>{res_name}:</b>\n"
            for link in links[:5]:
                text += f"  • <a href=\"{link['url']}\">{link['server']}</a>\n"
            text += "\n"

        text += "<i>💡 Klik server di atas untuk download (GDrive/Mega).</i>"
        bot.send_message(call.message.chat.id, text, disable_web_page_preview=True)

    # DETAIL SAMEHADAKU EPISODE
    elif action == "samehadaku_detail":
        bot.answer_callback_query(call.id, "⏳ Mengambil link Samehadaku...")
        url = data.get("url")
        detail = samehadaku.get_detail(url)
        if not detail:
            bot.send_message(call.message.chat.id, "⚠️ Gagal mengambil halaman Samehadaku.")
            return

        title = detail.get("title", "Episode Anime")
        downloads = detail.get("downloads", {})

        if not downloads:
            bot.send_message(call.message.chat.id, f"⚠️ Tidak ditemukan direct link pada halaman ini.")
            return

        text = f"📺 <b>{title}</b>\n\nLink download bersih (Bebas Iklan):\n\n"
        for res_name, links in downloads.items():
            text += f"🎬 <b>Resolusi {res_name}:</b>\n"
            for link in links:
                text += f"  • <a href=\"{link['url']}\">{link['server']}</a>\n"
            text += "\n"

        text += "<i>💡 Klik nama server untuk streaming / download.</i>"
        bot.send_message(call.message.chat.id, text, disable_web_page_preview=True)

    # DETAIL OTAKUDESU EPISODE
    elif action == "otakudesu_detail":
        bot.answer_callback_query(call.id, "⏳ Mengambil link Otakudesu...")
        url = data.get("url")
        detail = otakudesu.get_detail(url)
        if not detail:
            bot.send_message(call.message.chat.id, "⚠️ Gagal mengambil halaman Otakudesu.")
            return

        title = detail.get("title", "Otakudesu Anime")
        downloads = detail.get("downloads", {})

        if not downloads:
            bot.send_message(call.message.chat.id, f"⚠️ Tidak ditemukan direct link pada halaman ini.")
            return

        text = f"🌐 <b>{title}</b>\n\nLink download Otakudesu:\n\n"
        for res_name, links in downloads.items():
            text += f"🎬 <b>Resolusi {res_name}:</b>\n"
            for link in links:
                text += f"  • <a href=\"{link['url']}\">{link['server']}</a>\n"
            text += "\n"

        text += "<i>💡 Klik server untuk download langsung.</i>"
        bot.send_message(call.message.chat.id, text, disable_web_page_preview=True)

# ============================================================================
# MAIN LIFECYCLE
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

            # 3. Langsung tampilkan menu pilihan provider
            if wake_query not in ["/stop", "/off", "/start"]:
                show_provider_selection(cid, wake_query)
        except Exception as e:
            print(f"⚠️ Error handling initial wake: {e}")

    threading.Thread(target=handle_initial_wake, daemon=True).start()

    print("🤖 Bot is now actively listening for updates...")
    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    main()
