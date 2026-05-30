import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from telegram.constants import ParseMode
import sqlite3
from datetime import datetime
import random
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_NAME = "casino.db"
ADMIN_ID = 6621823601
MIN_BET = 0.1

BET_AMOUNT, MINES_COUNT, MINING = range(3)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0,
            total_played REAL DEFAULT 0,
            total_won REAL DEFAULT 0,
            referral_code TEXT UNIQUE,
            referred_by INTEGER,
            referral_earnings REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            bet REAL,
            mines_count INTEGER,
            result TEXT,
            winnings REAL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    ''')
    
    conn.commit()
    conn.close()

def get_user_or_create(user_id: int, username: str = None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = c.fetchone()
    
    if not user:
        referral_code = f"LEPS_{user_id}"
        c.execute('''
            INSERT INTO users (user_id, username, referral_code)
            VALUES (?, ?, ?)
        ''', (user_id, username, referral_code))
        conn.commit()
    
    conn.close()

def get_user_balance(user_id: int) -> float:
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def update_balance(user_id: int, amount: float):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    current = get_user_balance(user_id)
    c.execute('UPDATE users SET balance = ? WHERE user_id = ?', (current + amount, user_id))
    conn.commit()
    conn.close()

def get_referral_code(user_id: int) -> str:
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT referral_code FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def get_user_by_referral_code(code: str) -> int:
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT user_id FROM users WHERE referral_code = ?', (code,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    get_user_or_create(user_id, username)
    
    if context.args:
        ref_code = context.args[0]
        referred_by = get_user_by_referral_code(ref_code)
        if referred_by and referred_by != user_id:
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute('UPDATE users SET referred_by = ? WHERE user_id = ?', (referred_by, user_id))
            conn.commit()
            conn.close()
    
    keyboard = [
        [InlineKeyboardButton("🎮 Играть в Мины", callback_data="play")],
        [InlineKeyboardButton("💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton("👥 Рефералы", callback_data="referrals")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
    ]
    
    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("⚙️ /admin", callback_data="admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🎰 Добро пожаловать в LEPS_CASINO!\n\n"
        f"💵 Ваш баланс: ${get_user_balance(user_id):.2f}\n\n"
        f"Играйте в мины и выигрывайте! 🎯",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def play_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("Ввести ставку", callback_data="enter_bet")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text="💰 Введите сумму ставки (минимум $0.1):\n\n"
             "Напишите сумму сообщением (например: 1)",
        reply_markup=reply_markup
    )
    
    context.user_data['waiting_for_bet'] = True
    return BET_AMOUNT

async def handle_bet_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        bet = float(update.message.text)
        
        if bet < MIN_BET:
            await update.message.reply_text(f"❌ Минимальная ставка ${MIN_BET}")
            return BET_AMOUNT
        
        balance = get_user_balance(user_id)
        if bet > balance:
            await update.message.reply_text(f"❌ Недостаточно средств. Ваш баланс: ${balance:.2f}")
            return BET_AMOUNT
        
        context.user_data['bet'] = bet
        
        keyboard = [
            [InlineKeyboardButton("2 мины", callback_data="mines_2"),
             InlineKeyboardButton("3 мины", callback_data="mines_3"),
             InlineKeyboardButton("4 мины", callback_data="mines_4")],
            [InlineKeyboardButton("5 мин", callback_data="mines_5"),
             InlineKeyboardButton("6 мин", callback_data="mines_6"),
             InlineKeyboardButton("7 мин", callback_data="mines_7")],
            [InlineKeyboardButton("8 мин", callback_data="mines_8"),
             InlineKeyboardButton("10 мин", callback_data="mines_10"),
             InlineKeyboardButton("12 мин", callback_data="mines_12")],
            [InlineKeyboardButton("15 мин", callback_data="mines_15")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"⛏️ Выберите количество мин (2-15):\n"
            f"Ставка: ${bet:.2f}",
            reply_markup=reply_markup
        )
        
        return MINES_COUNT
    
    except ValueError:
        await update.message.reply_text("❌ Введите корректное число")
        return BET_AMOUNT

async def select_mines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    await query.answer()
    
    mines_count = int(query.data.split('_')[1])
    bet = context.user_data.get('bet', 0)
    
    balance = get_user_balance(user_id)
    if bet > balance:
        await query.edit_message_text("❌ Ошибка: недостаточно средств")
        return ConversationHandler.END
    
    update_balance(user_id, -bet)
    
    total_cells = 25
    mine_positions = set(random.sample(range(total_cells), mines_count))
    
    context.user_data['mines_count'] = mines_count
    context.user_data['mine_positions'] = mine_positions
    context.user_data['revealed'] = set()
    context.user_data['current_winnings'] = bet
    
    keyboard = []
    for i in range(5):
        row = []
        for j in range(5):
            cell = i * 5 + j
            row.append(InlineKeyboardButton("⬜", callback_data=f"cell_{cell}"))
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("💸 Забрать выигрыш", callback_data="cash_out")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=f"⛏️ ИГРА НАЧАЛАСЬ!\n\n"
             f"💰 Ставка: ${bet:.2f}\n"
             f"💵 Текущий выигрыш: ${bet:.2f}\n"
             f"⛏️ Мин: {mines_count}\n\n"
             f"Нажимайте на ячейки! Найдите безопасные клетки.",
        reply_markup=reply_markup
    )
    
    return MINING

async def reveal_cell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    await query.answer()
    
    cell = int(query.data.split('_')[1])
    mine_positions = context.user_data.get('mine_positions', set())
    revealed = context.user_data.get('revealed', set())
    
    if cell in revealed:
        await query.answer("Уже открыта!", show_alert=True)
        return MINING
    
    revealed.add(cell)
    context.user_data['revealed'] = revealed
    
    if cell in mine_positions:
        bet = context.user_data.get('bet', 0)
        mines_count = context.user_data.get('mines_count', 0)
        
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('''
            INSERT INTO games (user_id, bet, mines_count, result, winnings)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, bet, mines_count, 'LOST', 0))
        conn.commit()
        conn.close()
        
        keyboard = [[InlineKeyboardButton("🔄 Играть снова", callback_data="play")],
                   [InlineKeyboardButton("⬅️ Главное меню", callback_data="back_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=f"💣 ВИБУХ! Вы наехали на мину!\n\n"
                 f"❌ Вы проиграли ${bet:.2f}\n"
                 f"📊 Открыли ячеек: {len(revealed)}",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
    
    else:
        context.user_data['current_winnings'] = context.user_data.get('bet', 0) * (1 + len(revealed) * 0.2)
        
        keyboard = []
        for i in range(5):
            row = []
            for j in range(5):
                cell_num = i * 5 + j
                if cell_num in revealed:
                    if cell_num in mine_positions:
                        row.append(InlineKeyboardButton("💣", callback_data=f"cell_revealed"))
                    else:
                        row.append(InlineKeyboardButton("✅", callback_data=f"cell_revealed"))
                else:
                    row.append(InlineKeyboardButton("⬜", callback_data=f"cell_{cell_num}"))
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("💸 Забрать выигрыш", callback_data="cash_out")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=f"✅ БЕЗОПАСНО!\n\n"
                 f"💰 Текущий выигрыш: ${context.user_data['current_winnings']:.2f}\n"
                 f"📊 Открыто ячеек: {len(revealed)}\n\n"
                 f"Продолжайте или заберите выигрыш!",
            reply_markup=reply_markup
        )
        
        return MINING

async def cash_out(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    await query.answer()
    
    winnings = context.user_data.get('current_winnings', 0)
    bet = context.user_data.get('bet', 0)
    mines_count = context.user_data.get('mines_count', 0)
    
    update_balance(user_id, winnings)
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        INSERT INTO games (user_id, bet, mines_count, result, winnings)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, bet, mines_count, 'WON', winnings - bet))
    conn.commit()
    conn.close()
    
    keyboard = [[InlineKeyboardButton("🔄 Играть снова", callback_data="play")],
               [InlineKeyboardButton("⬅️ Главное меню", callback_data="back_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=f"💰 ВЫ ВЫИГРАЛИ!\n\n"
             f"💵 Выигрыш: ${winnings:.2f}\n"
             f"💸 Прибыль: ${winnings - bet:.2f}\n"
             f"⛏️ Открыли ячеек: {len(context.user_data.get('revealed', set()))}",
        reply_markup=reply_markup
    )
    
    return ConversationHandler.END

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    await query.answer()
    
    balance = get_user_balance(user_id)
    
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="back_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=f"💰 ВАШ БАЛАНС\n\n"
             f"💵 ${balance:.2f}\n\n"
             f"Ваш баланс:",
        reply_markup=reply_markup
    )

async def show_referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    await query.answer()
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    ref_code = get_referral_code(user_id)
    c.execute('SELECT referral_earnings FROM users WHERE user_id = ?', (user_id,))
    earnings = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM users WHERE referred_by = ?', (user_id,))
    ref_count = c.fetchone()[0]
    
    conn.close()
    
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="back_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    ref_link = f"https://t.me/LEPS_CASINO_bot?start={ref_code}"
    
    await query.edit_message_text(
        text=f"👥 ВАШИ РЕФЕРАЛЫ\n\n"
             f"🔗 Ваша ссылка:\n<code>{ref_link}</code>\n\n"
             f"👤 Рефералов: {ref_count}\n"
             f"💵 Заработано: ${earnings:.2f} (10% от проигрышей)\n\n"
             f"Приглашайте друзей и зарабатывайте!",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    await query.answer()
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('SELECT COUNT(*), SUM(bet), SUM(winnings) FROM games WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    games_count = result[0] or 0
    total_bet = result[1] or 0
    total_winnings = result[2] or 0
    
    conn.close()
    
    win_rate = (total_winnings / total_bet * 100) if total_bet > 0 else 0
    
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="back_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=f"📊 ВАША СТАТИСТИКА\n\n"
             f"🎮 Игр сыграно: {games_count}\n"
             f"💰 Всего поставлено: ${total_bet:.2f}\n"
             f"💵 Всего выигрыш: ${total_winnings:.2f}\n"
             f"📈 Процент выигрыша: {win_rate:.1f}%",
        reply_markup=reply_markup
    )

async def back_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🎮 Играть в Мины", callback_data="play")],
        [InlineKeyboardButton("💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton("👥 Рефералы", callback_data="referrals")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
    ]
    
    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("⚙️ Админ", callback_data="admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=f"🎰 LEPS_CASINO\n\n"
             f"💵 Ваш баланс: ${get_user_balance(user_id):.2f}\n\n"
             f"Выберите действие:",
        reply_markup=reply_markup
    )

def main():
    init_db()
    
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not TOKEN:
        print("❌ ОШИБКА: TELEGRAM_BOT_TOKEN не найден!")
        return
    
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(play_game, pattern="^play$")],
        states={
            BET_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bet_input)],
            MINES_COUNT: [CallbackQueryHandler(select_mines, pattern="^mines_")],
            MINING: [
                CallbackQueryHandler(reveal_cell, pattern="^cell_\\d+$"),
                CallbackQueryHandler(cash_out, pattern="^cash_out$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(back_menu, pattern="^back_menu$"),
        ],
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(show_balance, pattern="^balance$"))
    app.add_handler(CallbackQueryHandler(show_referrals, pattern="^referrals$"))
    app.add_handler(CallbackQueryHandler(show_stats, pattern="^stats$"))
    app.add_handler(CallbackQueryHandler(back_menu, pattern="^back_menu$"))
    
    print("✅ Бот запущен! Ждет сообщений...")
    app.run_polling()

if __name__ == "__main__":
    main()
