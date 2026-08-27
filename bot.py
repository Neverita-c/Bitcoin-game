import os
import telebot
from telebot import types

# --- НАСТРОЙКИ ---
BOT_TOKEN = "8669188850:AAEDTy2I8Z9jR11AKjbHI9t6TJ8YJbQTLWU"

# Временные заглушки для платежки, чтобы бот не выдавал ошибок
AAIO_MERCHANT = "000000"
AAIO_SECRET = "Merchant Secret"
AAIO_API_KEY = "api-key-here"
ADMIN_ID = 0

DONATE_PRICE = "50"
DONATE_CURRENCY = "RUB"
PAY_METHOD = "sbp"

# Инициализация бота
bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def start_message(message):
    markup = types.InlineKeyboardMarkup()
    # Твоя ссылка на игру с GitHub Pages
    web_app_url = f"https://github.io{message.from_user.username or 'game'}/" 
    
    # Кнопка для запуска мини-приложения
    join_button = types.InlineKeyboardButton(
        text="🚀 Играть в Биткоин", 
        web_app=types.WebAppInfo(url="https://github.iobitcoin-game/") # Если имя репозитория другое, замени его тут
    )
    markup.add(join_button)
    
    bot.send_message(
        message.chat.id, 
        f"Привет, {message.from_user.first_name}! Добро пожаловать в Биткоин Кликер. Нажми кнопку ниже, чтобы начать тапать!", 
        reply_markup=markup
    )

@bot.message_handler(content_types=['web_app_data'])
def web_app_data_receive(message):
    # Логика обработки кликов или доната из игры
    bot.send_message(message.chat.id, "Запрос из игры получен! Когда подключишь Aaio, здесь будет создаваться ссылка на Сбербанк.")

if __name__ == '__main__':
    print("[+] Бот успешно запущен и готов к работе!")
    bot.infinity_polling()

