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
from utils import post_to_wp

router = Router()
router.message.outer_middleware(AlbumMiddleware())
logger = logging.getLogger(__name__)

_MORE_MARKER = "###"
_MORE_TAG = "<!--more--><br>"


def _kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=list(rows))


async def _photo_url(bot: Bot, msg: Message) -> str:
    file = await bot.get_file(msg.photo[-1].file_id)
    return f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"


async def _store_photos(
    message: Message,
    state: FSMContext,
    bot: Bot,
    album: list[Message] | None,
) -> bool:
    """Сохраняет фото из одиночного сообщения или альбома в FSM.
    Возвращает False, если фото получить не удалось."""
    photos = [m for m in (album or [message]) if m.photo]
    if not photos:
        return False

    urls = [await _photo_url(bot, m) for m in photos]
    if len(urls) > 1:
        await state.update_data(image=urls[0], album_urls=urls)
        await message.answer(
            f"Получено {len(urls)} фото — будут опубликованы галереей под текстом."
        )
    else:
        await state.update_data(image=urls[0])
    return True


async def _ask_publish(message: Message, state: FSMContext) -> None:
    await message.answer(
        "Когда опубликовать?",
        reply_markup=_kb(
            [InlineKeyboardButton(text="Опубликовать сейчас", callback_data="pub:now")],
            [InlineKeyboardButton(text="Запланировать", callback_data="pub:schedule")],
        ),
    )
    await state.set_state(Post.publish)


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

    await message.answer("Прикрепите <b>изображение</b> для обложки поста:")
    await state.set_state(Post.image)


@router.message(Post.body, F.photo)
async def get_body_with_media(
    message: Message,
    state: FSMContext,
    bot: Bot,
    album: list[Message] | None = None,
) -> None:
    """Текст поста прислали сразу с фото/альбомом: подпись = тело поста,
    фото запоминаем, шаг Post.image пропускаем."""
    # подпись Telegram прикрепляет к первому фото группы (мин. message_id)
    src = min(album, key=lambda m: m.message_id) if album else message
    raw = (src.html_text or src.caption or "").replace(_MORE_MARKER, _MORE_TAG)
    await state.update_data(body=raw)

    if not await _store_photos(message, state, bot, album):
        await message.answer("Не удалось получить фото. Попробуйте ещё раз.")
        return

    await _ask_publish(message, state)


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
    if not await _store_photos(message, state, bot, album):
        await message.answer("Не удалось получить фото из альбома.")
        return

    await _ask_publish(message, state)


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
