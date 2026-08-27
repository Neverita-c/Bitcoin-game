import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
import telebot
from telebot import types

# === НАСТРОЙКИ ТОКЕНОВ И ССЫЛОК ===
BOT_TOKEN = "8669188850:AAEDTy2I8Z9jR11AKjbHI9t6TJ8YJbQTLWU"
PROVIDER_TOKEN = "1744374395:TEST:d120a3e7495fe4dbc7c5"
WEBAPP_URL = "https://neverita-c.github.io/Bitcoin-game/"

bot = telebot.TeleBot(BOT_TOKEN)


# === 1. КОМАНДА /start И КЛАВИАТУРА ===
@bot.message_handler(commands=['start'])
def start_command(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    # Кнопка для запуска Mini App (sendData работает только через Reply-клавиатуру)
    web_app_btn = types.KeyboardButton(
        text="🎮 Играть в Биткоин-кликер",
        web_app=types.WebAppInfo(url=WEBAPP_URL)
    )
    markup.add(web_app_btn)
    
    bot.send_message(
        message.chat.id,
        "Привет! Нажми на кнопку ниже, чтобы запустить игру 👇",
        reply_markup=markup
    )


# === 2. ОБРАБОТКА ДАННЫХ ИЗ WEB APP (sendData) ===
@bot.message_handler(content_types=['web_app_data'])
def handle_web_app_data(message):
    data = message.web_app_data.data
    
    if data == "donate_1m":
        # Сумма в копейках: 4900 = 49.00 RUB
        prices = [types.LabeledPrice(label="1 000 000 BTC", amount=4900)]
        
        bot.send_invoice(
            chat_id=message.chat.id,
            title="Покупка 1 000 000 Биткоинов",
            description="Пакет ускорения для Биткоин-кликера.",
            invoice_payload="payload_donate_1m",
            provider_token=PROVIDER_TOKEN,  # Вставлен токен PayMaster
            currency="RUB",
            prices=prices,
            start_parameter="donate-1m"
        )


# === 3. ПОДТВЕРЖДЕНИЕ ПЛАТЕЖА (PRE-CHECKOUT) ===
@bot.pre_checkout_query_handler(func=lambda query: True)
def process_pre_checkout(pre_checkout_query):
    # Telegram требует подтверждения в течение 10 секунд
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


# === 4. УСПЕШНАЯ ОПЛАТА ===
@bot.message_handler(content_types=['successful_payment'])
def process_successful_payment(message):
    payment_info = message.successful_payment
    payload = payment_info.invoice_payload
    
    if payload == "payload_donate_1m":
        bot.send_message(
            message.chat.id,
            "🎉 **Оплата успешно завершена!**\n\nВам начислено 1 000 000 BTC. Перезайдите в игру!",
            parse_mode="Markdown"
        )


# === ФОНОВЫЙ HTTP-СЕРВЕР ДЛЯ ХОСТИНГА (RENDER.COM) ===
def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()


if __name__ == '__main__':
    # Запуск заглушки сервера в отдельном потоке
    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    # Запуск поллинга сообщений бота
    print("Бот успешно запущен...")
    bot.infinity_polling(skip_pending=True)
