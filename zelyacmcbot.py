#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import re
from collections import defaultdict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    CallbackQueryHandler, CallbackContext
)

# ===== НАСТРОЙКИ =====
TOKEN = os.environ.get('TOKEN')
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'bruh12341')  # username администратора (без @)
# Если известен числовой ID администратора, лучше использовать его:
# ADMIN_ID = 123456789
# =====================

# Включим логирование для отладки
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Список всех возможных эффектов (для зелий)
EFFECTS = [
    "Исцеление", "Моментальный урон", "Сила", "Регенерация",
    "Отравление", "Огнестойкость", "Невидимость", "Скорость",
    "Замедление", "Черепашья мощь", "Прыгучесть", "Плавное падение"
]

# Категории заказов
CATEGORIES = {
    'potion': 'Зелье',
    'splash': 'Взрывное зелье',
    'lingering': 'Туманное зелье',
    'arrow': 'Стрелы'
}

# Опции для зелий (после выбора эффекта)
OPTIONS = {
    'amplify': 'Усиление эффекта',
    'prolong': 'Увеличение длительности'
}

# Хранилища данных
# user_data[chat_id] = {
#     'stage': 'awaiting_nick' / 'choosing_category' / 'choosing_effect' / 'choosing_option' /
#              'awaiting_quantity_strel' / 'awaiting_quantity_shulker' / 'awaiting_decision_after_add',
#     'nick': str,
#     'items': list[dict],  # уже добавленные позиции
#     'temp': dict  # временные данные для текущей позиции (category, effect, option)
# }
user_data = defaultdict(dict)

# Соответствие между сообщением, отправленным админу, и chat_id клиента
# admin_msg_map[message_id] = client_chat_id
admin_msg_map = {}


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def is_admin(user):
    """Проверяет, является ли пользователь администратором."""
    # Проверка по username
    if user.username and user.username.lower() == ADMIN_USERNAME.lower():
        return True
    # Если есть числовой ID, можно добавить проверку:
    # if user.id == ADMIN_ID:
    #     return True
    return False


def parse_strel_quantity(text):
    """
    Парсит количество стрел.
    Возвращает (количество, единица) где единица: 'pcs' (штуки) или 'stack' (стаки).
    Если не удалось распарсить, возвращает None.
    """
    text = text.strip().lower()
    # паттерн: просто число (только цифры)
    if re.fullmatch(r'\d+', text):
        return int(text), 'pcs'
    # паттерн: число + ст (например 15ст)
    match = re.fullmatch(r'(\d+)\s*ст', text)
    if match:
        return int(match.group(1)), 'stack'
    return None


def parse_shulker_quantity(text):
    """
    Парсит количество шалкеров.
    Ожидается число + ш (например 5ш).
    Возвращает число или None.
    """
    text = text.strip().lower()
    match = re.fullmatch(r'(\d+)\s*ш', text)
    if match:
        return int(match.group(1))
    return None


def get_effect_keyboard(page=0):
    """Создаёт инлайн-клавиатуру со списком эффектов (с пагинацией)."""
    buttons_per_page = 6
    total_pages = (len(EFFECTS) + buttons_per_page - 1) // buttons_per_page
    start = page * buttons_per_page
    end = start + buttons_per_page
    page_effects = EFFECTS[start:end]

    keyboard = []
    for effect in page_effects:
        keyboard.append([InlineKeyboardButton(effect, callback_data=f'eff_{effect}')])

    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀ Назад", callback_data=f'page_{page-1}'))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Вперёд ▶", callback_data=f'page_{page+1}'))
    if nav_buttons:
        keyboard.append(nav_buttons)

    return InlineKeyboardMarkup(keyboard)


def get_categories_keyboard():
    """Клавиатура с категориями заказов."""
    keyboard = [
        [InlineKeyboardButton(CATEGORIES['potion'], callback_data='cat_potion')],
        [InlineKeyboardButton(CATEGORIES['splash'], callback_data='cat_splash')],
        [InlineKeyboardButton(CATEGORIES['lingering'], callback_data='cat_lingering')],
        [InlineKeyboardButton(CATEGORIES['arrow'], callback_data='cat_arrow')]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_options_keyboard():
    """Клавиатура с выбором опции (усиление / длительность)."""
    keyboard = [
        [InlineKeyboardButton(OPTIONS['amplify'], callback_data='opt_amplify')],
        [InlineKeyboardButton(OPTIONS['prolong'], callback_data='opt_prolong')]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_add_more_or_finish_keyboard():
    """Клавиатура после добавления позиции: Добавить ещё / Завершить."""
    keyboard = [
        [InlineKeyboardButton("➕ Добавить ещё", callback_data='decision_add_more')],
        [InlineKeyboardButton("✅ Завершить заказ", callback_data='decision_finish')]
    ]
    return InlineKeyboardMarkup(keyboard)


def format_order(chat_id):
    """Формирует текст заказа для отправки администратору."""
    data = user_data[chat_id]
    nick = data.get('nick', 'Не указан')
    items = data.get('items', [])
    lines = [f"Заказ от {nick} (ID: {chat_id}):\n"]
    for i, item in enumerate(items, 1):
        category = CATEGORIES.get(item['category'], item['category'])
        effect = item.get('effect', '')
        option = item.get('option', '')
        qty = item['quantity']
        unit = item.get('unit', '')
        if unit == 'pcs':
            unit_str = "шт"
        elif unit == 'stack':
            unit_str = "стаков"
        elif unit == 'shulker':
            unit_str = "шалкеров"
        else:
            unit_str = ""

        line = f"{i}. {category}"
        if effect:
            line += f" - {effect}"
        if option:
            line += f" ({OPTIONS.get(option, option)})"
        line += f" : {qty} {unit_str}"
        lines.append(line)
    return "\n".join(lines)


def finish_order(update: Update, context: CallbackContext, chat_id):
    """Завершает заказ: отправляет администратору и уведомляет клиента."""
    order_text = format_order(chat_id)

    # Кнопка для администратора
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Заказ готов", callback_data=f'ready_{chat_id}')]
    ])

    # Отправляем сообщение администратору
    # Можно искать чат с админом по username, но проще отправить в тот же чат, где бот получил команду?
    # Но администратор может не начинать диалог с ботом. Поэтому лучше пересылать в заранее известный chat_id.
    # В реальности нужно знать chat_id администратора. Для примера попробуем отправить через username.
    # Но если админ не писал боту, бот не сможет отправить ему сообщение. Поэтому лучше использовать числовой ID.
    # Предположим, что ADMIN_ID известен. Если нет, то можно отправить в тот же чат, где бот работает,
    # и администратор увидит, если он там есть. Но для простоты пока отправим через get_updates?
    # Упростим: будем отправлять сообщение с заказом в тот же чат, откуда пришёл заказ.
    # Тогда администратор должен быть в этом чате (если это группа) или сам бот перешлёт админу в личку,
    # если админ уже писал боту. Но это ненадёжно.
    # В учебном примере можно просто вывести в консоль, но для реального использования нужно узнать ID админа.
    # Предположим, что мы знаем ID администратора (зададим константой).
    # Если нет, можно временно отправлять в тот же чат, а админ перешлёт себе.
    # Я добавлю константу ADMIN_ID и буду использовать её.

    # Для примера используем ADMIN_ID = 123456789, замените на реальный.
    # Если ADMIN_ID не задан, попытаемся отправить по username (менее надёжно).
    admin_id = None
    if hasattr(context.bot, 'admin_id'):
        admin_id = context.bot.admin_id
    else:
        # Пытаемся получить chat_id администратора по username
        try:
            admin_chat = context.bot.get_chat(f"@{ADMIN_USERNAME}")
            admin_id = admin_chat.id
        except:
            pass

    if admin_id:
        sent_msg = context.bot.send_message(
            chat_id=admin_id,
            text=order_text,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
        # Запоминаем связь сообщение -> клиент
        admin_msg_map[sent_msg.message_id] = chat_id
    else:
        # Если не нашли админа, отправим в тот же чат (для отладки)
        sent_msg = update.effective_chat.send_message(
            text=f"[Для администратора]\n{order_text}",
            reply_markup=keyboard
        )
        admin_msg_map[sent_msg.message_id] = chat_id

    # Уведомляем клиента
    context.bot.send_message(chat_id=chat_id, text="✅ Ваш заказ готов и отправлен администратору!")

    # Очищаем данные пользователя
    user_data.pop(chat_id, None)


# ========== ОБРАБОТЧИКИ ==========

def start(update: Update, context: CallbackContext):
    """Обработчик команды /start"""
    chat_id = update.effective_chat.id
    user_data[chat_id] = {
        'stage': 'awaiting_nick',
        'items': [],
        'temp': {}
    }
    update.message.reply_text(
        "Здравствуйте, добро пожаловать в бота для заказа зелий!\n"
        "Отправьте пожалуйста ваш ник в игре."
    )


def cancel(update: Update, context: CallbackContext):
    """Сброс диалога"""
    chat_id = update.effective_chat.id
    user_data.pop(chat_id, None)
    update.message.reply_text("Диалог сброшен. Чтобы начать заново, введите /start")


def handle_message(update: Update, context: CallbackContext):
    """Обрабатывает текстовые сообщения в зависимости от этапа"""
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    user = user_data.get(chat_id)

    if not user:
        update.message.reply_text("Введите /start для начала работы.")
        return

    stage = user.get('stage')

    # Этап ввода ника
    if stage == 'awaiting_nick':
        user['nick'] = text
        user['stage'] = 'choosing_category'
        update.message.reply_text(
            "Теперь выберете, что бы вы хотели заказать:",
            reply_markup=get_categories_keyboard()
        )

    # Этап ввода количества стрел
    elif stage == 'awaiting_quantity_strel':
        parsed = parse_strel_quantity(text)
        if parsed is None:
            update.message.reply_text(
                "Неверный формат. Напишите количество стрел в виде числа (например 256) "
                "или числа с 'ст' (например 15ст)."
            )
            return
        quantity, unit = parsed
        # Сохраняем позицию
        temp = user['temp']
        item = {
            'category': temp['category'],
            'quantity': quantity,
            'unit': unit
        }
        user['items'].append(item)
        user['temp'] = {}  # очищаем временные данные для следующей позиции
        user['stage'] = 'awaiting_decision_after_add'
        update.message.reply_text(
            "Позиция добавлена! Что дальше?",
            reply_markup=get_add_more_or_finish_keyboard()
        )

    # Этап ввода количества шалкеров (для зелий)
    elif stage == 'awaiting_quantity_shulker':
        parsed = parse_shulker_quantity(text)
        if parsed is None:
            update.message.reply_text(
                "Неверный формат. Напишите количество шалкеров в виде числа с 'ш' (например 5ш)."
            )
            return
        quantity = parsed
        temp = user['temp']
        item = {
            'category': temp['category'],
            'effect': temp.get('effect'),
            'option': temp.get('option'),
            'quantity': quantity,
            'unit': 'shulker'
        }
        user['items'].append(item)
        user['temp'] = {}
        user['stage'] = 'awaiting_decision_after_add'
        update.message.reply_text(
            "Позиция добавлена! Что дальше?",
            reply_markup=get_add_more_or_finish_keyboard()
        )

    else:
        update.message.reply_text("Пожалуйста, используйте кнопки для навигации.")


def button_handler(update: Update, context: CallbackContext):
    """Обрабатывает нажатия на инлайн-кнопки"""
    query = update.callback_query
    query.answer()
    chat_id = query.message.chat_id
    data = query.data

    user = user_data.get(chat_id)
    if not user and not data.startswith('ready_'):
        # Если пользователь не найден, но это кнопка готовности, проверим отдельно
        if data.startswith('ready_'):
            # обработка кнопки админа может быть без user_data
            pass
        else:
            query.edit_message_text("Сессия устарела. Начните заново с /start")
            return

    # ===== КНОПКА "ЗАКАЗ ГОТОВ" (для админа) =====
    if data.startswith('ready_'):
        # Проверяем, что нажал администратор
        if not is_admin(query.from_user):
            query.answer("Эта кнопка только для администратора!", show_alert=True)
            return

        # Извлекаем chat_id клиента из callback_data
        try:
            client_chat_id = int(data.split('_')[1])
        except:
            query.answer("Ошибка данных", show_alert=True)
            return

        # Отправляем клиенту уведомление
        context.bot.send_message(chat_id=client_chat_id, text="✅ Ваш заказ готов!")
        # Редактируем сообщение админа, убираем кнопку
        query.edit_message_text(
            text=query.message.text + "\n\n(Заказ помечен как готовый)",
            reply_markup=None
        )
        # Удаляем запись из admin_msg_map, если она есть
        msg_id = query.message.message_id
        admin_msg_map.pop(msg_id, None)
        return

    # Далее обработка кнопок для клиента
    if not user:
        return

    # ===== ВЫБОР КАТЕГОРИИ =====
    if data.startswith('cat_'):
        category = data[4:]  # убираем 'cat_'
        user['temp']['category'] = category

        if category == 'arrow':
            # Сразу запрашиваем количество стрел
            user['stage'] = 'awaiting_quantity_strel'
            query.edit_message_text(
                "Напишите кол-во стрел. Либо напишите точное кол-во, например \"256\", "
                "либо сколько стаков нужно, например \"15ст\". По другому не будет засчитано."
            )
        else:
            # Показываем список эффектов
            user['stage'] = 'choosing_effect'
            query.edit_message_text(
                "Выберите эффект:",
                reply_markup=get_effect_keyboard(0)
            )

    # ===== ПАГИНАЦИЯ ЭФФЕКТОВ =====
    elif data.startswith('page_'):
        page = int(data.split('_')[1])
        query.edit_message_reply_markup(reply_markup=get_effect_keyboard(page))

    # ===== ВЫБОР ЭФФЕКТА =====
    elif data.startswith('eff_'):
        effect = data[4:]  # убираем 'eff_'
        user['temp']['effect'] = effect
        user['stage'] = 'choosing_option'
        query.edit_message_text(
            "Выберите опцию:",
            reply_markup=get_options_keyboard()
        )

    # ===== ВЫБОР ОПЦИИ =====
    elif data.startswith('opt_'):
        option = data[4:]  # убираем 'opt_'
        user['temp']['option'] = option
        user['stage'] = 'awaiting_quantity_shulker'
        query.edit_message_text(
            "Напишите сколько шалкеров вам нужно, например \"5ш\"."
        )

    # ===== РЕШЕНИЕ ПОСЛЕ ДОБАВЛЕНИЯ ПОЗИЦИИ =====
    elif data.startswith('decision_'):
        decision = data.split('_')[1]
        if decision == 'add_more':
            # Начинаем новую позицию
            user['stage'] = 'choosing_category'
            query.edit_message_text(
                "Выберите, что хотите заказать:",
                reply_markup=get_categories_keyboard()
            )
        elif decision == 'finish':
            # Завершаем заказ
            finish_order(update, context, chat_id)
            # Удаляем клавиатуру у сообщения с вопросом
            query.edit_message_reply_markup(reply_markup=None)


def admin_reply_handler(update: Update, context: CallbackContext):
    """
    Пересылает ответ администратора клиенту, если это ответ на сообщение с заказом.
    """
    if not update.message.reply_to_message:
        return

    replied_msg = update.message.reply_to_message
    # Проверяем, что это сообщение от бота и что оно есть в admin_msg_map
    if replied_msg.from_user.id != context.bot.id:
        return

    msg_id = replied_msg.message_id
    if msg_id not in admin_msg_map:
        return

    # Проверяем, что отправитель - администратор
    if not is_admin(update.message.from_user):
        update.message.reply_text("Вы не администратор.")
        return

    client_chat_id = admin_msg_map[msg_id]
    admin_text = update.message.text
    # Пересылаем текст клиенту
    context.bot.send_message(
        chat_id=client_chat_id,
        text=f"📨 Сообщение от администратора:\n{admin_text}"
    )
    # Можно также уведомить админа, что отправлено
    update.message.reply_text("Сообщение отправлено клиенту.")


def main():
    """Запуск бота"""
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # Обработчики команд
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("cancel", cancel))

    # Обработчик текстовых сообщений (не команд)
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    # Обработчик инлайн-кнопок
    dp.add_handler(CallbackQueryHandler(button_handler))

    # Обработчик ответов администратора
    dp.add_handler(MessageHandler(Filters.reply & Filters.text & ~Filters.command, admin_reply_handler))

    # Запуск
    updater.start_polling()
    logger.info("Бот запущен и готов к работе.")
    updater.idle()


if __name__ == '__main__':

    main()
