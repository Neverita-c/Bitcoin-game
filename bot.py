# -*- coding: utf-8 -*-
"""
back_bot.py — бэкенд-бот для игры «Золотая лихорадка».
Платежи: Aaio (СБП, 50 ₽). Начисление доната: одноразовый промокод.

Установка зависимостей:
    pip install pyTelegramBotAPI requests

Запуск:
    python back_bot.py
"""

import hashlib
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs

import requests
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException

# ══════════════════════════ НАСТРОЙКИ ══════════════════════════

BOT_TOKEN       = os.getenv("BOT_TOKEN", "8669188850:AAEDTy2I8Z9jR11AKjbHI9t6TJ8YJbQTLWU")  # @BotFather
AAIO_MERCHANT   = int(os.getenv("AAIO_MERCHANT", "000000"))     # ID магазина из кабинета Aaio
AAIO_API_KEY    = os.getenv("AAIO_API_KEY", "api-key-here")     # API-ключ магазина (для проверки статусов)
ADMIN_ID        = int(os.getenv("ADMIN_ID", "0"))               # ваш Telegram ID — присылает лог покупок (0 = выкл)
DONATE_PRICE    = "50"          # строкой, целое число рублей
DONATE_CURRENCY = "RUB"
PAY_METHOD      = "sbp"         # способ оплаты: СБП
POLL_INTERVAL   = 8             # сек между опросами статуса
POLL_MAX_TIME   = 20 * 60       # сколько секунд автополлинг живёт после выставления счёта
WEBHOOK_PORT    = int(os.getenv("WEBHOOK_PORT", "0"))  # например 8080 — включит локальный приём коллбэков

AAIO_BASE       = "https://aaio.so/api/v1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("back-bot")

bot = TeleBot = telebot.TeleBot(BOT_TOKEN)

# ══════════════════════════ БАЗА ДАННЫХ ══════════════════════════
# Схема минимальна, но рассчитана на продакшен-практики:
# order_id уникален, промокод уникален, факты оплаты записываются один раз.
db_lock = threading.Lock()

def db() -> sqlite3.Connection:
    conn = sqlite3.connect("payments.db")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

with db() as _conn:
    _conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS payments (
            order_id   TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            tg_chat    INTEGER NOT NULL,
            tg_msg_id  INTEGER NOT NULL DEFAULT 0,
            amount     TEXT NOT NULL,
            currency   TEXT NOT NULL,
            method     TEXT NOT NULL DEFAULT 'sbp',
            status     TEXT NOT NULL DEFAULT 'pending',   -- pending/success/fail/expired/canceled
            promo      TEXT UNIQUE,                       -- одноразовый код доната
            created_at INTEGER NOT NULL,
            paid_at    INTEGER NOT NULL DEFAULT 0,
            credited   INTEGER NOT NULL DEFAULT 0         -- бонус выписан: защита от повторов
        );
        CREATE INDEX IF NOT EXISTS idx_pay_user ON payments(user_id);
        CREATE INDEX IF NOT EXISTS idx_pay_promo ON payments(promo);
        """
    )

# ══════════════════════════ API AAIO ══════════════════════════

class AaioError(Exception):
    """Ошибка взаимодействия с платёжным API."""

def aaio_create_payment(order_id: str) -> str:
    """Выставляет счёт на 50 ₽ через СБП, возвращает ссылку на страницу оплаты."""
    payload = {
        "merchant_id": AAIO_MERCHANT,
        "amount":      DONATE_PRICE,
        "currency":    DONATE_CURRENCY,
        "order_id":    order_id,
        "description": "Донат в игре «Золотая лихорадка»",
        "method":      PAY_METHOD,   # СБП
        "lang":        "ru",
    }
    try:
        r = requests.post(
            f"{AAIO_BASE}/create-payment",
            data=payload,
            # Мерчант-ключ передаётся именно в заголовке Sign — так требует спецификация Aaio.
            headers={"Accept": "application/json", "Sign": AAIO_SECRET},
            timeout=(6, 15),
        )
    except requests.RequestException as e:
        raise AaioError(f"Нет связи с платёжным сервисом: {e}") from e

    try:
        body = r.json()
    except ValueError:
        raise AaioError(f"Крупная проблема сервиса (HTTP {r.status_code}), попробуйте позже")

    if body.get("type") == "success" and body.get("url"):
        return body["url"]

    detail = (
        body.get("message")
        or (body.get("errors") or [{}])[0].get("message")
        or (body.get("error") or {}).get("message")
        or str(body)[:300]
    )
    raise AaioError(f"Шлюз отклонил счёт: {detail}")

def aaio_orders_info(order_ids: list[str]) -> dict[str, dict]:
    """Статусы заказов напрямую от шлюза (доверенный источник данных)."""
    ids = ",".join(order_ids)
    try:
        r = requests.get(
            f"{AAIO_BASE}/orders-info",
            params={"merchant_id": AAIO_MERCHANT, "order_ids": ids},
            headers={"Accept": "application/json", "X-API-Key": AAIO_API_KEY},
            timeout=(6, 15),
        )
        body = r.json()
    except (requests.RequestException, ValueError) as e:
        raise AaioError(f"Не удалось проверить статус: {e}")

    if body.get("type") != "success":
        raise AaioError(str(body)[:300])

    out = {}
    for it in body.get("list", []):
        oid = str(it.get("order_id"))
        out[oid] = it
    return out

def verify_webhook_sign(form: dict) -> bool:
    """SHA-256 подписи коллбэка. Без валидной подписи данные НЕ считаем платёжными."""
    raw = ":".join([
        str(form.get("amount", "")),
        str(form.get("currency", "")),
        str(form.get("payment_system", "")),
        str(form.get("payment_id", "")),
        str(form.get("order_id", "")),
        AAIO_SECRET,
    ])
    expected = hashlib.sha256(raw.encode()).hexdigest()
    got = str(form.get("sign", ""))
    return expected.lower() == got.lower()

# ══════════════════════════ ВЫДАЧА ДОНАТА ══════════════════════════
# Состав доната за 50 ₽ — правьте под свой баланс игры.
# Ключи соответствуют объекту бонуса, который ожидает активация в игре.
DONAT_PACK = {
    "title": "Майнерский набор",
    "coins": 15000,   # монеты сразу
    "items": {"gpu": 3},  # доп. постройки в инвентарь
}

def gen_promo() -> str:
    """Одноразовый код вида GR-A7F3-KX92."""
    import secrets as _s
    return f"GR-{_s.token_hex(2).upper()}-{_s.token_hex(2).upper()}"

credit_guard = threading.Lock()

def mark_paid_and_credit(order_id: str, source: str) -> bool:
    """
    Единая точка зачисления (вызывается поллингом ИЛИ вебхуком).
    Идемпотентна: второй вызов для того же заказа ничего не делает.
    Возвращает True, если бонус выдан этим вызовом.
    """
    with credit_guard:
        now = int(time.time())
        promo = gen_promo()
        with db() as conn:
            row = conn.execute(
                "SELECT status, credited FROM payments WHERE order_id=?", (order_id,)
            ).fetchone()
            if not row:
                log.warning("mark_paid: неизвестный заказ %s", order_id)
                return False
            if row[1]:                      # credited==1 — уже выдан
                return False

            cur = conn.execute(
                """UPDATE payments
                   SET status='success', paid_at=?, credited=1, promo=?
                   WHERE order_id=? AND credited=0""",
                (now, promo, order_id),
            )
            conn.commit()
            if cur.rowcount != 1:
                return False                # параллельный поток опередил нас

        user_id, chat_id, msg_id = fetch_payment_refs(order_id)
        text = (
            "🎉 <b>Оплата прошла!</b>\n\n"
            f"Ваш набор: <b>{DONAT_PACK['title']}</b>\n\n"
            "<b>Как забрать:</b>\n"
            "1️⃣ Откройте игру\n"
            "2️⃣ Нажмите кнопку <code>🎁</code> рядом с магазином\n"
            "3️⃣ Введите код:\n\n"
            f"<pre>{promo}</pre>\n"
            "⚠️ Код одноразовый. Сохрани это сообщение!"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🎮 Открыть игру", url="t.me"))  # ← замените ссылкой на ваше Mini App/Web App
        try:
            bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
        except ApiTelegramException as e:
            log.error("Не удалось доставить промокод (%s): %s", order_id, e)

        if ADMIN_ID:
            try:
                bot.send_message(
                    ADMIN_ID,
                    f"💸 Донат #{order_id}\nuser: <a href='tg://user?id={user_id}'>{user_id}</a>"
                    f"\nсумма: {DONATE_PRICE} {DONATE_CURRENCY} ({source})\nпромо: {promo}",
                    parse_mode="HTML",
                )
            except ApiTelegramException:
                pass

        log.info("Оплачен и зачислен %s (источник=%s)", order_id, source)
        return True

def fetch_payment_refs(order_id):
    with db() as conn:
        r = conn.execute(
            "SELECT user_id, tg_chat, tg_msg_id FROM payments WHERE order_id=?",
            (order_id,),
        ).fetchone()
    return r if r else (0, 0, 0)

def set_msg_ref(order_id: str, chat_id: int, msg_id: int):
    with db() as conn:
        conn.execute(
            "UPDATE payments SET tg_chat=?, tg_msg_id=? WHERE order_id=?",
            (chat_id, msg_id, order_id),
        )

def create_local_order(user_id: int, chat_id: int) -> str:
    order_id = f"{user_id}-{int(time.time())}-{'{:06x}'.format(int(time.time()*1000)%0xFFFFFF)}"
    with db() as conn:
        conn.execute(
            """INSERT INTO payments
               (order_id, user_id, tg_chat, amount, currency, method, status, created_at)
               VALUES (?,?,?,?,?,?, 'pending', ?)""",
            (order_id, user_id, chat_id, DONATE_PRICE, DONATE_CURRENCY, PAY_METHOD, int(time.time())),
        )
    return order_id

# ══════════════════════════ АВТОПОЛЛИНГ СТАТУСА ══════════════════════════

def poll_order(order_id: str):
    """Живёт в фоне, пока счёт висит неоплаченным, и ловит момент оплаты."""
    deadline = time.time() + POLL_MAX_TIME
    last_try_edit = 0.0
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        try:
            info = aaio_orders_info([order_id]).get(order_id)
        except AaioError as e:
            log.warning("poll %s: %s", order_id, e)
            continue
        if not info:
            continue
        st = str(info.get("status", "")).lower()
        if st == "success":
            mark_paid_and_credit(order_id, "polling")
            return
        if st in ("fail", "expired"):
            finish_unpaid(order_id, st)
            return

def finish_unpaid(order_id: str, status: str):
    human = "Истёк срок оплаты" if status == "expired" else "Платёж не прошёл"
    emoji = "⌛" if status == "expired" else "❌"
    with db() as conn:
        cur = conn.execute(
            "UPDATE payments SET status=?, tg_msg_id=tg_msg_id WHERE order_id=? AND status='pending'",
            (status, order_id),
        )
        refs = conn.execute(
            "SELECT tg_chat, tg_msg_id FROM payments WHERE order_id=?", (order_id,)
        ).fetchone()
        conn.commit()
    if not cur.rowcount or not refs:
        return
    chat_id, msg_id = refs
    try:
        bot.edit_message_text(
            f"{emoji} {human}. Счёт закрыт.\nЕсли деньги списались — напишите администрации.",
            chat_id, msg_id,
        )
    except ApiTelegramException:
        pass

# ══════════════════════════ WEBHOOK-SЕРВЕР (опционально) ══════════════════════════
# В кабинете Aaio укажите callback: http(s)://<ваш-домен/ip>:PORT/aaio/notify
# Запускается автоматически, если переменная окружения WEBHOOK_PORT > 0.

class HookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path.rstrip() != "/aaio/notify":
            self.send_response(404); self.end_headers(); return
        length = int(self.headers.get("Content-Length", 0))
        ctype  = self.headers.get("Content-Type", "")
        raw = self.rfile.read(length)
        form: dict = {}
        if "multipart/form-data" in ctype:
            # Минимальный разбор multipart: по границам фиксируем только пары имя-значение
            boundary = ctype.split("boundary=")[-1].strip('"').encode()
            for part in raw.split(b"--" + boundary):
                part = part.strip(b"\r\n")
                if b"\r\n\r\n" in part:
                    head, _, value = part.partition(b"\r\n\r\n")
                    name_line = head.split(b"\r\n")[0]
                    if b'name="' in name_line:
                        name = name_line.split(b'name="')[1].split(b'"')[0]
                        form[name.decode()] = value.decode(errors="replace")
        else:
            form = {k: v[0] for k, v in parse_qs(raw.decode(errors="replace")).items()}

        ok = False
        if verify_webhook_sign(form) and form.get("payment_status") == "success":
            ok = bool(mark_paid_and_credit(str(form.get("order_id")), "webhook"))

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}' if ok else b'{"ok":false}')

    def log_message(self, fmt, *args):   # тишина в консоли от мелких запросов
        log.debug(fmt, *args)

def start_webhook_server():
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", WEBHOOK_PORT), HookHandler)
        threading.Thread(target=srv.serve_forever, daemon=True, name="aaio-webhook").start()
        log.info("Webhook-приёмник слушает :%d/aaio/notify", WEBHOOK_PORT)
    except OSError as e:
        log.error("Не удалось занять порт %d: %s — работаем только поллингом", WEBHOOK_PORT, e)

# ══════════════════════════ КНОПКИ И КОМАНДЫ ══════════════════════════

def main_menu() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(f"💎 Купить донат · {DONATE_PRICE} ₽", callback_data="donate:start"),
        types.InlineKeyboardButton("📖 Что входит в донат?", callback_data="donate:info"),
    )
    return kb

@bot.message_handler(commands=["start"])
def cmd_start(m: types.Message):
    bot.send_message(
        m.chat.id,
        "👋 Привет!\n"
        "Я платёжный помощник игры <b>«Золотая лихорадка»</b>.\n\n"
        f"💵 Стоимость набора — <b>{DONATE_PRICE} ₽</b>, оплата картой по <b>СБП</b> "
        "(QR-код или приложение банка).\n"
        "🎟 После оплаты бот мгновенно выдаст вам <b>уникальный промокод</b> "
        "— введите его в игре, и бонус ляжет на ваш баланс.",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    bot.send_message(m.chat.id, "Выберите действие:", reply_markup=main_menu())

@bot.message_handler(commands=["myorders"])
def cmd_myorders(m: types.Message):
    with db() as conn:
        rows = conn.execute(
            """SELECT order_id, status, created_at, promo FROM payments
               WHERE user_id=? ORDER BY created_at DESC LIMIT 5""",
            (m.from_user.id,),
        ).fetchall()
    if not rows:
        bot.send_message(m.chat.id, "У вас пока нет счетов.")
        return
    lines = ["<b>Последние счета:</b>\n"]
    names = {"pending": "🟡 Ожидает оплаты", "success": "🟢 Оплачено",
             "fail": "🔴 Не прошёл", "expired": "⌛ Истёк", "canceled": "⚫ Отменён"}
    for oid, st, ts, promo in rows:
        dt = datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")
        line = f"— <b>{dt}</b>: {names.get(st, st)}"
        lines.append(line)
        if st == "success":
            lines.append(f"&nbsp;&nbsp;&nbsp;&nbsp;<pre>{promo}</pre>")
    bot.send_message(m.chat.id, "\n".join(lines).replace("&nbsp;", "\u00a0"),
                     parse_mode="HTML")

# ─────────── Callback-кнопки ───────────

@bot.callback_query_handler(func=lambda c: c.data.startswith(("donate:start", "donate:info")))
def on_donate(c: types.CallbackQuery):
    bot.answer_callback_query(c.id)
    if c.data == "donate:info":
        items = "\n".join(f"➕ <b>+{v}</b> × {k.upper()}" if k != "coins"
                          else f"💰 <b>{v:,}</b> монет".replace(",", " ")
                          for k, v in DONAT_PACK["items"].items())
        bot.send_message(
            c.message.chat.id,
            f"<b>📦 {DONAT_PACK['title']} · {DONATE_PRICE} ₽</b>\n\n"
            f"💰 Монеты: <b>{DONAT_PACK['coins']:,}</b>\n{items}".replace(",", " "),
            parse_mode="HTML",
        )
        return

    # donate:start → создаём счёт
    uid = c.from_user.id
    order_id = create_local_order(uid, c.message.chat.id)
    try:
        pay_url = aaio_create_payment(order_id)
    except AaioError as e:
        log.error("create-payment отказ: %s", e)
        bot.send_message(c.message.chat.id, f"😔 Сейчас не получилось создать счёт.\nДетали: {e}")
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🟢 Перейти к оплате СБП", url=pay_url))
    kb.row(
        types.InlineKeyboardButton("✅ Я оплатил — проверить", callback_data=f"check:{order_id}"),
    )

    sent = bot.send_message(
        c.message.chat.id,
        f"🧾 <b>Счёт #{order_id.split('-')[1]}</b> готов\n"
        f"Сумма: <b>{DONATE_PRICE} ₽</b> · способ: <b>СБП</b>\n\n"
        "1️⃣ Жмите зелёную кнопку выше\n"
        "2️⃣ Отсканируйте QR-код вашим банковским приложением\n"
        "3️⃣ Нажмите <b>«Я оплатил»</b>, если не хотите ждать\n\n"
        f"⏳ Бот следит за счётом сам до {POLL_MAX_TIME//60} минут.",
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=kb,
    )
    set_msg_ref(order_id, sent.chat.id, sent.message_id)
    # Отписываемся от будущих нажатий — бесполезные счёта плодить незачем
    try: bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
    except ApiTelegramException: pass
    threading.Thread(target=poll_order, args=(order_id,), daemon=True).start()

@bot.callback_query_handler(func=lambda c: c.data.startswith("check:"))
def on_check(c: types.CallbackQuery):
    bot.answer_callback_query(c.id)
    order_id = c.data.split(":", 1)[1]

    try:
        info = aaio_orders_info([order_id]).get(order_id)
    except AaioError as e:
        bot.send_message(c.message.chat.id, f"⚠️ Не удалось проверить: {e}")
        return

    st = str((info or {}).get("status", "")).lower()
    if st == "success":
        if mark_paid_and_credit(order_id, "manual-check"):
            # закрываем счётное сообщение, чтобы кнопка не давила дважды
            try: bot.edit_message_text("🎉 Отлично! Всё поступило — смотрите новое сообщение.", c.message.chat.id, c.message.message_id)
            except ApiTelegramException: pass
        return
    msgs = {
        "process": "⏳ Платёж ещё обрабатывается банком — придёт мгновение.",
        "fail":    "❌ Похоже, оплата не удалась. Попробуйте заново через /start",
        "expired": "⌛ Срок счёта истёк. Создайте новый через /start",
    }
    bot.send_message(c.message.chat.id, msgs.get(st, "🔄 Пока нет подтверждения — дайте секунд десять."))

# ─── fallback: перехват всего, что не команда ───
@bot.message_handler(content_types=["text"])
def echo_fallback(m: types.Message):
    bot.send_message(m.chat.id, "Используйте /start, чтобы увидеть меню 🙌")

# ══════════════════════════ ЗАПУСК ══════════════════════════

if __name__ == "__main__":
    missing = []
    if not BOT_TOKEN or ":" not in BOT_TOKEN:           missing.append("BOT_TOKEN")
    if not AAIO_SECRET or "Merchant Secret" in AAIO_SECRET: missing.append("AAIO_SECRET")
    if not AAIO_API_KEY or "api-key-here" in AAIO_API_KEY:  missing.append("AAIO_API_KEY")
    if missing:
        raise SystemExit(
            f"[!] Задайте переменные окружения: {', '.join(missing)}\n"
            f"    BOT_TOKEN=`1234567890:XXX`\n"
            f"    AAIO_MERCHANT=`12345`\n"
            f"    AAIO_SECRET=`merchant secret #1`\n"
            f"    AAIO_API_KEY=`api-key`\n"
            f"    ADMIN_ID=`ваш тг-id` (не обязательно)\n"
            f"    WEBHOOK_PORT=`8080` (только если поднят публичный сервер)\n"
        )
    if WEBHOOK_PORT > 0:
        start_webhook_server()
    log.info("Бот запущен ✔ метод оплаты=%s, цена=%s%s", PAY_METHOD, DONATE_PRICE, DONATE_CURRENCY)
    bot.infinity_polling(skip_pending=True, timeout=35)
