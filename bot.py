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
        def log_message(self, format, *args):
            pass  # Отключаем лишний спам в логах Render

    PORT = int(os.environ.get("PORT", 8080))
    with socketserver.TCPServer(("", PORT), QuietHandler) as httpd:
        httpd.serve_forever()

# Запуск «сайта» в фоновом потоке для обмана Render
threading.Thread(target=start_dummy_server, daemon=True).start()

# --- 3. ЗАПУСК ТЕЛЕГРАМ БОТА ---
bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup()
    # Твоя ссылка на игру, которую ты сделал через GitHub Pages
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

if __name__ == '__main__':
    print("[+] Бот успешно запущен в сети!")
    bot.infinity_polling()
