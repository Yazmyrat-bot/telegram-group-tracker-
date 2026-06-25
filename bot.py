# bot.py
import os
import sqlite3
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

# === AYARLAR ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "8258465223:AAF5zQpgZIRRU4hnEv2snMWyxSdg-nryw5E")
OWNER_ID = int(os.getenv("OWNER_ID", "7339222202"))
DB_PATH = "bot_data.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# === VERİTABANI ===
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS members (
            user_id INTEGER,
            group_id INTEGER,
            name TEXT,
            username TEXT,
            added_by INTEGER,
            joined_at TEXT,
            left_at TEXT,
            status TEXT DEFAULT 'active',
            PRIMARY KEY (user_id, group_id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            group_id INTEGER,
            event TEXT,
            event_at TEXT,
            by_user INTEGER
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS adders (
            adder_id INTEGER,
            group_id INTEGER,
            total_added INTEGER DEFAULT 0,
            still_active INTEGER DEFAULT 0,
            left_count INTEGER DEFAULT 0,
            PRIMARY KEY (adder_id, group_id)
        )
    ''')
    
    conn.commit()
    conn.close()


def add_member(user_id, group_id, name, username, added_by, joined_at):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        INSERT OR REPLACE INTO members 
        (user_id, group_id, name, username, added_by, joined_at, status, left_at)
        VALUES (?, ?, ?, ?, ?, ?, 'active', NULL)
    ''', (user_id, group_id, name, username, added_by, joined_at))
    
    c.execute('''
        INSERT INTO history (user_id, group_id, event, event_at, by_user)
        VALUES (?, ?, 'joined', ?, ?)
    ''', (user_id, group_id, joined_at, added_by))
    
    # Adder summary güncelle
    c.execute('''
        INSERT INTO adders (adder_id, group_id, total_added, still_active, left_count)
        VALUES (?, ?, 1, 1, 0)
        ON CONFLICT(adder_id, group_id) DO UPDATE SET
        total_added = total_added + 1,
        still_active = still_active + 1
    ''', (added_by, group_id))
    
    conn.commit()
    conn.close()


def remove_member(user_id, group_id, left_at):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        UPDATE members SET status = 'left', left_at = ?
        WHERE user_id = ? AND group_id = ?
    ''', (left_at, user_id, group_id))
    
    c.execute('''
        INSERT INTO history (user_id, group_id, event, event_at, by_user)
        VALUES (?, ?, 'left', ?, ?)
    ''', (user_id, group_id, left_at, user_id))
    
    # Adder summary güncelle: added_by kim ise onun still_active azalt
    c.execute('SELECT added_by FROM members WHERE user_id = ? AND group_id = ?', 
              (user_id, group_id))
    row = c.fetchone()
    if row and row[0]:
        added_by = row[0]
        c.execute('''
            UPDATE adders SET still_active = still_active - 1, left_count = left_count + 1
            WHERE adder_id = ? AND group_id = ?
        ''', (added_by, group_id))
    
    conn.commit()
    conn.close()


def get_stats(group_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('SELECT COUNT(*) FROM members WHERE group_id = ? AND status = "active"', (group_id,))
    active = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM members WHERE group_id = ? AND status = "left"', (group_id,))
    left = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM members WHERE group_id = ?', (group_id,))
    total = c.fetchone()[0]
    
    conn.close()
    return total, active, left


def get_my_added(owner_id, group_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        SELECT user_id, name, username, joined_at, left_at, status
        FROM members WHERE added_by = ? AND group_id = ?
        ORDER BY joined_at DESC
    ''', (owner_id, group_id))
    
    rows = c.fetchall()
    
    active_list = []
    left_list = []
    
    for row in rows:
        user_id, name, username, joined, left, status = row
        display = f"@{username}" if username else name
        if status == 'active':
            active_list.append(f"• {display} — {joined}")
        else:
            left_list.append(f"• {display} — {joined} → Ayrıldı: {left}")
    
    conn.close()
    return active_list, left_list, len(active_list), len(left_list)


def get_adders_summary(group_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        SELECT a.adder_id, a.total_added, a.still_active, a.left_count,
               m.name, m.username
        FROM adders a
        LEFT JOIN members m ON a.adder_id = m.user_id AND a.group_id = m.group_id
        WHERE a.group_id = ?
        ORDER BY a.total_added DESC
    ''', (group_id,))
    
    rows = c.fetchall()
    result = []
    
    for row in rows:
        adder_id, total, active, left, name, username = row
        display = f"@{username}" if username else f"ID:{adder_id}"
        result.append({
            'name': display,
            'total': total,
            'active': active,
            'left': left
        })
    
    conn.close()
    return result


def get_blacklist(owner_id, group_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        SELECT user_id, name, username, left_at
        FROM members 
        WHERE added_by = ? AND group_id = ? AND status = 'left'
        ORDER BY left_at DESC
    ''', (owner_id, group_id))
    
    rows = c.fetchall()
    result = []
    for row in rows:
        user_id, name, username, left = row
        display = f"@{username}" if username else name
        result.append(f"• {display} — {left}")
    
    conn.close()
    return result


# === HANDLERLAR ===

async def track_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Katılma ve ayrılma olaylarını yakala"""
    if not update.chat_member:
        return
    
    chat_member = update.chat_member
    chat = chat_member.chat
    old = chat_member.old_chat_member
    new = chat_member.new_chat_member
    from_user = chat_member.from_user
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Yeni katılan
    if old.status in ['left', 'kicked'] and new.status == 'member':
        user = new.user
        adder_id = from_user.id if from_user else user.id
        
        add_member(
            user_id=user.id,
            group_id=chat.id,
            name=user.first_name or "İsimsiz",
            username=user.username,
            added_by=adder_id,
            joined_at=now
        )
        logger.info(f"✅ Yeni üye: {user.id} ({user.username}) - Ekleyen: {adder_id}")
    
    # Ayrılan
    elif old.status == 'member' and new.status in ['left', 'kicked']:
        user = new.user
        
        remove_member(
            user_id=user.id,
            group_id=chat.id,
            left_at=now
        )
        logger.info(f"❌ Ayrılan: {user.id} ({user.username})")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Merhaba! Ben grup üye takip botuyum.\n\n"
        "Komutlar:\n"
        "/grup — Grup istatistiği\n"
        "/benim — Senin eklediklerin\n"
        "/ekleyenler — Herkesin ekledikleri\n"
        "/kara_liste — Ayrılanlar (senin eklediklerin)\n"
        "/yardim — Yardım"
    )


async def cmd_grup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    total, active, left = get_stats(chat_id)
    
    text = (
        f"📊 <b>Grup İstatistiği</b>\n\n"
        f"👥 Toplam kayıtlı: {total}\n"
        f"✅ Aktif üye: {active}\n"
        f"❌ Ayrılan: {left}\n"
    )
    await update.message.reply_text(text, parse_mode='HTML')


async def cmd_benim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Sadece sahip kullanabilir (isteğe bağlı, herkes kullanabilir de)
    # Ama senin ID'n ile filtreleme yapacağız
    
    active, left_list, active_count, left_count = get_my_added(user_id, chat_id)
    
    text = f"👤 <b>Senin Eklediklerin</b>\n\n"
    text += f"✅ Grupta kalan: {active_count}\n"
    text += f"❌ Ayrılan: {left_count}\n"
    
    if left_count > 0:
        text += f"\n<b>⚠️ Ayrılanlar:</b>\n"
        text += "\n".join(left_list[:20])  # İlk 20
        if left_count > 20:
            text += f"\n... ve {left_count - 20} kişi daha"
    
    if active_count > 0:
        text += f"\n\n<b>Grupta kalanlar:</b>\n"
        text += "\n".join(active[:10])
    
    await update.message.reply_text(text, parse_mode='HTML')


async def cmd_ekleyenler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    adders = get_adders_summary(chat_id)
    
    text = "👥 <b>Ekleyenler Özeti</b>\n\n"
    
    for adder in adders:
        text += (
            f"• {adder['name']}\n"
            f"  ├ Toplam eklemiş: {adder['total']}\n"
            f"  ├ Grupta kalan: {adder['active']}\n"
            f"  └ Ayrılan: {adder['left']}\n\n"
        )
    
    if not adders:
        text += "Henüz veri yok."
    
    await update.message.reply_text(text, parse_mode='HTML')


async def cmd_kara_liste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    blacklist = get_blacklist(user_id, chat_id)
    
    text = "🚫 <b>Kara Liste</b> (Senin eklediklerinden ayrılanlar)\n\n"
    
    if blacklist:
        text += "\n".join(blacklist)
    else:
        text += "Kara liste boş."
    
    await update.message.reply_text(text, parse_mode='HTML')


async def cmd_yardim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>Komutlar</b>\n\n"
        "/grup — Toplam üye, aktif, ayrılan sayısı\n"
        "/benim — Senin eklediklerin ve ayrılanların isimleri\n"
        "/ekleyenler — Herkes kaç kişi eklemiş, kaçı ayrılmış\n"
        "/kara_liste — Senin eklediklerinden ayrılanlar\n\n"
        "⚠️ <b>Önemli:</b>\n"
        "• Bot grupta admin olmalı\n"
        "• Privacy Mode kapalı olmalı\n"
        "• Sadece bot eklendikten sonraki olaylar takip edilir"
    )
    await update.message.reply_text(text, parse_mode='HTML')


# === UYARI: Kara listedekini eklemeye çalışınca ===

async def warn_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yeni katılan kara listedeyse sahibi uyar"""
    if not update.chat_member:
        return
    
    chat_member = update.chat_member
    new = chat_member.new_chat_member
    
    if new.status != 'member':
        return
    
    user_id = new.user.id
    chat_id = chat_member.chat.id
    from_user = chat_member.from_user
    
    # Sadece sahip eklediyse kontrol et
    if from_user and from_user.id == OWNER_ID:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            SELECT name, username, left_at 
            FROM members 
            WHERE user_id = ? AND group_id = ? AND status = 'left' AND added_by = ?
        ''', (user_id, chat_id, OWNER_ID))
        
        row = c.fetchone()
        conn.close()
        
        if row:
            name, username, left_at = row
            display = f"@{username}" if username else name
            
            try:
                await context.bot.send_message(
                    chat_id=OWNER_ID,
                    text=(
                        f"⚠️ <b>Uyarı!</b>\n\n"
                        f"{display} daha önce gruptan ayrıldı.\n"
                        f"Ayrılma tarihi: {left_at}\n\n"
                        f"Bu kişi kara listede. Tekrar ekledin."
                    ),
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Uyarı mesajı gönderilemedi: {e}")


# === MAIN ===

def main():
    init_db()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Chat member olaylarını yakala
    app.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(warn_blacklist, ChatMemberHandler.CHAT_MEMBER))
    
    # Komutlar
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("grup", cmd_grup))
    app.add_handler(CommandHandler("benim", cmd_benim))
    app.add_handler(CommandHandler("ekleyenler", cmd_ekleyenler))
    app.add_handler(CommandHandler("kara_liste", cmd_kara_liste))
    app.add_handler(CommandHandler("yardim", cmd_yardim))
    
    logger.info("Bot başlatıldı...")
    app.run_polling(allowed_updates=["chat_member", "message"])


if __name__ == "__main__":
    main()
