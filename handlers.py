import logging
from datetime import date, time

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import ALLOWED_USERS
from middleware import AlbumMiddleware
from states import Post
from utils import get_wp_categories, post_to_wp

router = Router()
router.message.outer_middleware(AlbumMiddleware())
logger = logging.getLogger(__name__)

_MORE_MARKER = "###"
_MORE_TAG = "<!--more--><br>"


def _kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=list(rows))


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("У вас нет доступа к публикации.")
        return

    await state.clear()
    await message.answer(
        "Привет! Введите <b>заголовок</b> поста.\n"
        "Для отмены отправьте /cancel в любой момент."
    )
    await state.set_state(Post.title)


# ---------------------------------------------------------------------------
# /cancel
# ---------------------------------------------------------------------------

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Публикация отменена.")


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Публикация отменена.")
    await callback.answer()


# ---------------------------------------------------------------------------
# Шаг 1 — Заголовок
# ---------------------------------------------------------------------------

@router.message(Post.title, F.text)
async def get_title(message: Message, state: FSMContext) -> None:
    title = message.text.strip()
    if not title:
        await message.answer("Заголовок не может быть пустым. Попробуйте ещё раз:")
        return

    await state.update_data(title=title)
    await message.answer(
        "Введите <b>текст поста</b> (поддерживается HTML-разметка Telegram).\n"
        f"Используйте <code>{_MORE_MARKER}</code> для вставки тега «Читать далее»:"
    )
    await state.set_state(Post.body)


# ---------------------------------------------------------------------------
# Шаг 2 — Текст поста
# ---------------------------------------------------------------------------

@router.message(Post.body, F.text)
async def get_body(message: Message, state: FSMContext) -> None:
    raw = (message.html_text or message.text or "").replace(_MORE_MARKER, _MORE_TAG)

    await state.update_data(body=raw)

    try:
        categories = await get_wp_categories()
    except Exception as e:
        logger.error("Ошибка загрузки категорий: %s", e)
        await message.answer("Не удалось загрузить категории. Попробуйте позже.")
        return

    if not categories:
        await message.answer("Список категорий пуст. Проверьте настройки WordPress.")
        return

    keyboard = _kb(
        *[
            [InlineKeyboardButton(text=name, callback_data=f"cat:{cat_id}")]
            for cat_id, name in categories.items()
        ]
    )
    await message.answer("Выберите <b>категорию</b>:", reply_markup=keyboard)
    await state.set_state(Post.category)


# ---------------------------------------------------------------------------
# Шаг 3 — Категория
# ---------------------------------------------------------------------------

@router.callback_query(Post.category, F.data.startswith("cat:"))
async def get_category(callback: CallbackQuery, state: FSMContext) -> None:
    cat_id = callback.data.split(":", 1)[1]
    categories = await get_wp_categories()

    if cat_id not in categories:
        await callback.answer("Категория не найдена, попробуйте ещё раз.", show_alert=True)
        return

    await state.update_data(category=cat_id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"Категория: <b>{categories[cat_id]}</b>\n\n"
        "Введите <b>теги</b> через запятую или нажмите «Пропустить»:",
        reply_markup=_kb(
            [InlineKeyboardButton(text="Пропустить", callback_data="tags:skip")]
        ),
    )
    await state.set_state(Post.tags)
    await callback.answer()


# ---------------------------------------------------------------------------
# Шаг 4 — Теги
# ---------------------------------------------------------------------------

@router.callback_query(Post.tags, F.data == "tags:skip")
async def skip_tags(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(tags=[])
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Прикрепите <b>изображение</b> для обложки поста:")
    await state.set_state(Post.image)
    await callback.answer()


@router.message(Post.tags, F.text)
async def get_tags(message: Message, state: FSMContext) -> None:
    tags = [t.strip() for t in message.text.split(",") if t.strip()]
    await state.update_data(tags=tags)
    await message.answer("Прикрепите <b>изображение</b> для обложки поста:")
    await state.set_state(Post.image)


# ---------------------------------------------------------------------------
# Шаг 5 — Изображение
# ---------------------------------------------------------------------------

@router.message(Post.image, F.photo)
async def get_image(
    message: Message,
    state: FSMContext,
    bot: Bot,
    album: list[Message] | None = None,
) -> None:
    async def _get_url(msg: Message) -> str:
        file = await bot.get_file(msg.photo[-1].file_id)
        return f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"

    if album:
        photos = [msg for msg in album if msg.photo]
        if not photos:
            await message.answer("Не удалось получить фото из альбома.")
            return
        urls = [await _get_url(msg) for msg in photos]
        await state.update_data(image=urls[0], album_urls=urls)
        await message.answer(
            f"Получено {len(urls)} фото — будут опубликованы галереей под текстом."
        )
    else:
        url = await _get_url(message)
        await state.update_data(image=url)

    await message.answer(
        "Когда опубликовать?",
        reply_markup=_kb(
            [InlineKeyboardButton(text="Опубликовать сейчас", callback_data="pub:now")],
            [InlineKeyboardButton(text="Запланировать", callback_data="pub:schedule")],
        ),
    )
    await state.set_state(Post.publish)


@router.message(Post.image)
async def image_wrong_type(message: Message) -> None:
    await message.answer("Пожалуйста, отправьте <b>фото</b> (не файл/документ).")


# ---------------------------------------------------------------------------
# Шаг 6 — Публикация или планирование
# ---------------------------------------------------------------------------

@router.callback_query(Post.publish, F.data == "pub:now")
async def publish_now(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Публикую пост, подождите…")

    data = await state.get_data()
    await state.clear()

    try:
        result = await post_to_wp(data, publish_now=True)
        await callback.message.answer(f"Пост опубликован: {result['link']}")
    except Exception as e:
        logger.exception("Ошибка публикации для пользователя %d", callback.from_user.id)
        await callback.message.answer(f"Ошибка публикации: {e}")

    await callback.answer()


@router.callback_query(Post.publish, F.data == "pub:schedule")
async def publish_schedule(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Введите <b>дату</b> публикации в формате <code>ГГГГ-ММ-ДД</code>:"
    )
    await state.set_state(Post.schedule_date)
    await callback.answer()


# ---------------------------------------------------------------------------
# Шаг 7 — Дата
# ---------------------------------------------------------------------------

@router.message(Post.schedule_date, F.text)
async def get_schedule_date(message: Message, state: FSMContext) -> None:
    try:
        date.fromisoformat(message.text.strip())
    except ValueError:
        await message.answer(
            "Неверный формат. Введите дату в формате <code>ГГГГ-ММ-ДД</code>:"
        )
        return

    await state.update_data(schedule_date=message.text.strip())
    await message.answer(
        "Введите <b>время</b> публикации в формате <code>ЧЧ:ММ</code>:"
    )
    await state.set_state(Post.schedule_time)


# ---------------------------------------------------------------------------
# Шаг 8 — Время
# ---------------------------------------------------------------------------

@router.message(Post.schedule_time, F.text)
async def get_schedule_time(message: Message, state: FSMContext) -> None:
    try:
        time.fromisoformat(message.text.strip())
    except ValueError:
        await message.answer(
            "Неверный формат. Введите время в формате <code>ЧЧ:ММ</code>:"
        )
        return

    await state.update_data(schedule_time=message.text.strip())
    data = await state.get_data()
    await state.clear()

    await message.answer("Планирую публикацию, подождите…")
    try:
        result = await post_to_wp(data, publish_now=False)
        await message.answer(f"Пост запланирован: {result['link']}")
    except Exception as e:
        logger.exception("Ошибка планирования для пользователя %d", message.from_user.id)
        await message.answer(f"Ошибка планирования: {e}")
