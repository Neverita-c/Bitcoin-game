import os
import http.server
import socketserver
import threading
import telebot
from telebot import types

# --- 1. ТОКЕН ТВОЕГО БОТА ---
BOT_TOKEN = "8669188850:AAEDTy2I8Z9jR11AKjbHI9t6TJ8YJbQTLWU"

# --- 2. ФАЛЬШИВЫЙ СЕРВЕР ДЛЯ ХОСТИНГА (ЧТОБЫ НЕ БЫЛО TIMED OUT) ---
def start_dummy_server():
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args): pass
    PORT = int(os.environ.get("PORT", 8080))
    with socketserver.TCPServer(("", PORT), QuietHandler) as httpd:
        httpd.serve_forever()

threading.Thread(target=start_dummy_server, daemon=True).start()

# --- 3. ЗАПУСК ТЕЛЕГРАМ БОТА ---
bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup()
    # Ссылка на твою игру с правильными большими буквами
    game_button = types.InlineKeyboardButton(
        text="🚀 Играть в Биткоин", 
        web_app=types.WebAppInfo(url="https://github.io")
    )
    markup.add(game_button)
    
    bot.send_message(
        message.chat.id, 
        f"Привет, {message.from_user.first_name}! Жми кнопку ниже и запускай свой Биткоин-кликер!", 
        reply_markup=markup
    )

# --- 4. ОБРАБОТКА СИГНАЛА ДОНАТА ИЗ ИГРЫ ---
@bot.message_handler(content_types=['web_app_data'])
def web_app_data_receive(message):
    if message.web_app_data.data == "donate_1m":
        prices = [types.LabeledPrice(label="1 000 000 Биткоинов", amount=50)] 
        
        bot.send_invoice(
            chat_id=message.chat.id,
            title="⚡ 1 000 000 Биткоинов",
            description="Моментальное зачисление одного миллиона монет на твой баланс в игре!",
            invoice_payload="donate_1m_payload",
            provider_token="", 
            currency="XTR",   
            prices=prices
        )

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    bot.send_message(
        message.chat.id, 
        "🔥 Оплата прошла успешно! 1 000 000 Биткоинов начислены! (После 31 августа на ПК мы настроем базу данных, чтобы они сохранялись на балансе)."
    )

if __name__ == '__main__':
    print("[+] Бот успешно запущен в сети!")
    bot.infinity_polling()
