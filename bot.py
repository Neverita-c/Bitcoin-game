import os
import threading
import logging
from http.server import HTTPServer, SimpleHTTPRequestHandler
import telebot
from telebot import types

# Включаем подробные логи
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "8669188850:AAEDTy2I8Z9jR11AKjbHI9t6TJ8YJbQTLWU"
PROVIDER_TOKEN = "1744374395:TEST:d120a3e7495fe4dbc7c5"
WEBAPP_URL = "https://neverita-c.github.io/Bitcoin-game/"

bot = telebot.TeleBot(BOT_TOKEN)


@bot.message_handler(commands=['start'])
def start_command(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
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


# Ловим любые данные из Web App
@bot.message_handler(content_types=['web_app_data'])
def handle_web_app_data(message):
    data = message.web_app_data.data
    print(f"--> Получены данные из Web App: {data}")

    # 1. Сразу отправляем текстовое подтверждение
    bot.send_message(message.chat.id, f"Получен сигнал на покупку: {data}. Формирую счет...")

    if data == "donate_1m":
        prices = [types.LabeledPrice(label="1 000 000 BTC", amount=4900)] # 49.00 RUB
        
        try:
            bot.send_invoice(
                chat_id=message.chat.id,
                title="Покупка 1 000 000 Биткоинов",
                description="Пакет ускорения для Биткоин-кликера.",
                invoice_payload="payload_donate_1m",
                provider_token=PROVIDER_TOKEN,
                currency="RUB",
                prices=prices,
                start_parameter="donate-1m"
            )
            print("--> Счет успешно выставлен в чат!")
        except Exception as e:
            print(f"--> Ошибка при выставлении счета: {e}")
            # Выводим точную причину ошибки прямо в чат Telegram
            bot.send_message(
                message.chat.id, 
                f"❌ Ошибка выставления счета от Telegram:\n`{e}`", 
                parse_mode="Markdown"
            )


@bot.pre_checkout_query_handler(func=lambda query: True)
def process_pre_checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@bot.message_handler(content_types=['successful_payment'])
def process_successful_payment(message):
    if message.successful_payment.invoice_payload == "payload_donate_1m":
        bot.send_message(
            message.chat.id,
            "🎉 **Оплата прошла успешно!**\n\n1 000 000 BTC зачислены на ваш аккаунт.",
            parse_mode="Markdown"
        )


def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()


if __name__ == '__main__':
    threading.Thread(target=run_dummy_server, daemon=True).start()
    print("Бот запущен и ожидает сообщений...")
    bot.infinity_polling(skip_pending=True)
