import asyncio
from typing import Any, Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


class AlbumMiddleware(BaseMiddleware):
    """
    Собирает сообщения одного media-group в список и передаёт
    его первому обработчику как `album: list[Message]`.
    Все последующие сообщения той же группы молча отбрасываются.
    """

    def __init__(self, latency: float = 0.3) -> None:
        self.latency = latency
        self._cache: dict[str, list[Message]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.media_group_id:
            return await handler(event, data)

        gid = event.media_group_id
        is_first = gid not in self._cache
        self._cache.setdefault(gid, []).append(event)

        if not is_first:
            # остальные сообщения группы обработает первое
            return

        await asyncio.sleep(self.latency)
        data["album"] = self._cache.pop(gid)
        return await handler(event, data)
