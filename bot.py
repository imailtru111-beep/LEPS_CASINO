import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from telegram.constants import ParseMode
import sqlite3
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
    c.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS games (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, bet REAL, mines_count INTEGER, result TEXT, winnings REAL)')
    conn.commit()
    conn.close()

def get_user_or_create(user_id: int, username: str = None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    if not c.fetchone():
        c.execute('INSERT INTO users (user_id, username, balance) VALUES (?, ?, ?)', (user_id, username, 100))
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    get_user_or_create(user_id, username)
    
    keyboard = [
        [InlineKeyboardButton("🎮 Играть", callback_data="play")],
        [InlineKeyboardButton("💰 Баланс", callback_data="balance")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🎰 Добро пожаловать!\n\nБаланс: ${get_user_balance(user_id):.2f}",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def play_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text="💰 Введите ставку (напр: 1)\n\nНапишите сообщением:")
    context.user_data['waiting_for_bet'] = True
    return BET_AMOUNT

async def handle_bet_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        bet = float(update.message.text)
        if bet < MIN_BET:
            await update.message.reply_text(f"❌ Минимум ${MIN_BET}")
            return BET_AMOUNT
        balance = get_user_balance(user_id)
        if bet > balance:
            await update.message.reply_text(f"❌ Недостаточно средств: ${balance:.2f}")
            return BET_AMOUNT
        context.user_data['bet'] = bet
        keyboard = [
            [InlineKeyboardButton("2 мины", callback_data="mines_2"), InlineKeyboardButton("5 мин", callback_data="mines_5")],
            [InlineKeyboardButton("10 мин", callback_data="mines_10"), InlineKeyboardButton("15 мин", callback_data="mines_15")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"⛏️ Выберите мины:\nСтавка: ${bet:.2f}", reply_markup=reply_markup)
        return MINES_COUNT
    except:
        await update.message.reply_text("❌ Ошибка. Введите число")
        return BET_AMOUNT

async def select_mines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    mines_count = int(query.data.split('_')[1])
    bet = context.user_data.get('bet', 0)
    
    update_balance(user_id, -bet)
    
    mine_positions = set(random.sample(range(25), mines_count))
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
    keyboard.append([InlineKeyboardButton("💸 Забрать", callback_data="cash_out")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text=f"⛏️ ИГРА!\n💰 Ставка: ${bet:.2f}\n⛏️ Мин: {mines_count}", reply_markup=reply_markup)
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
        keyboard = [[InlineKeyboardButton("Играть снова", callback_data="play")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=f"💣 ВИБУХ!\n❌ Проиграли ${bet:.2f}", reply_markup=reply_markup)
        return ConversationHandler.END
    else:
        context.user_data['current_winnings'] = context.user_data.get('bet', 0) * (1 + len(revealed) * 0.15)
        keyboard = []
        for i in range(5):
            row = []
            for j in range(5):
                cell_num = i * 5 + j
                if cell_num in revealed:
                    row.append(InlineKeyboardButton("✅", callback_data="none"))
                else:
                    row.append(InlineKeyboardButton("⬜", callback_data=f"cell_{cell_num}"))
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("💸 Забрать", callback_data="cash_out")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=f"✅ БЕЗОПАСНО!\n💰 Выигрыш: ${context.user_data['current_winnings']:.2f}\nОткрыто: {len(revealed)}", reply_markup=reply_markup)
        return MINING

async def cash_out(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    winnings = context.user_data.get('current_winnings', 0)
    update_balance(user_id, winnings)
    
    keyboard = [[InlineKeyboardButton("Играть снова", callback_data="play")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=f"💰 ВЫИГРЫШ!\n💵 ${winnings:.2f}", reply_markup=reply_markup)
    return ConversationHandler.END

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    balance = get_user_balance(user_id)
    keyboard = [[InlineKeyboardButton("Назад", callback_data="play")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=f"💰 Баланс: ${balance:.2f}", reply_markup=reply_markup)

async def back_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    keyboard = [[InlineKeyboardButton("🎮 Играть", callback_data="play")], [InlineKeyboardButton("💰 Баланс", callback_data="balance")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=f"🎰 Меню\n💵 Баланс: ${get_user_balance(user_id):.2f}", reply_markup=reply_markup)

def main():
    init_db()
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN не найден!")
        return
    
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(play_game, pattern="^play$")],
        states={
            BET_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bet_input)],
            MINES_COUNT: [CallbackQueryHandler(select_mines, pattern="^mines_")],
            MINING: [CallbackQueryHandler(reveal_cell, pattern="^cell_\\d+$"), CallbackQueryHandler(cash_out, pattern="^cash_out$")],
        },
        fallbacks=[CallbackQueryHandler(back_menu, pattern="^back_menu$")],
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(show_balance, pattern="^balance$"))
    app.add_handler(CallbackQueryHandler(back_menu, pattern="^back_menu$"))
    
    print("✅ Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
