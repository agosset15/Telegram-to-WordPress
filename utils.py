import asyncio
import logging
import httpx
from cachetools import TTLCache

from config import WP_URL, WP_USERNAME, WP_PASSWORD

logger = logging.getLogger(__name__)

_categories_cache: TTLCache = TTLCache(maxsize=1, ttl=3600)


def _auth() -> httpx.BasicAuth:
    return httpx.BasicAuth(WP_USERNAME, WP_PASSWORD)


async def get_wp_categories() -> dict[str, str]:
    """Возвращает {category_id: name}, кэшируется на 1 час."""
    if "categories" in _categories_cache:
        return _categories_cache["categories"]

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{WP_URL}/wp-json/wp/v2/categories",
            auth=_auth(),
        )

    if resp.status_code != 200:
        logger.error("Ошибка загрузки категорий: %s", resp.text)
        return {}

    result = {str(cat["id"]): cat["name"] for cat in resp.json()}
    _categories_cache["categories"] = result
    return result


async def _get_all_tags() -> dict[str, int]:
    """Возвращает {tag_name_lower: tag_id}, обходит пагинацию."""
    all_tags: dict[str, int] = {}
    page = 1

    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.get(
                f"{WP_URL}/wp-json/wp/v2/tags",
                auth=_auth(),
                params={"per_page": 100, "page": page},
            )
            if resp.status_code != 200:
                logger.error("Ошибка загрузки тегов (страница %d): %s", page, resp.text)
                break
            tags = resp.json()
            if not tags:
                break
            for tag in tags:
                all_tags[tag["name"].lower()] = tag["id"]
            page += 1

    return all_tags


async def _resolve_tag(tag_name: str, existing: dict[str, int]) -> int | None:
    """Возвращает ID тега, создаёт его если не существует."""
    normalized = tag_name.strip().lower()
    if normalized in existing:
        return existing[normalized]

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{WP_URL}/wp-json/wp/v2/tags",
            auth=_auth(),
            json={"name": tag_name.strip()},
        )

    if resp.status_code == 201:
        tag_id: int = resp.json()["id"]
        logger.info("Создан тег '%s' (id=%d)", tag_name, tag_id)
        return tag_id

    if resp.status_code == 400 and "term_exists" in resp.text:
        refreshed = await _get_all_tags()
        tag_id = refreshed.get(normalized)
        if tag_id:
            return tag_id
        logger.error("Тег '%s' существует, но ID не найден", tag_name)
        return None

    logger.error("Не удалось создать тег '%s': %s", tag_name, resp.text)
    return None


async def upload_image_to_wp(image_url: str) -> dict | None:
    """
    Скачивает изображение из Telegram CDN и загружает в WordPress.
    Возвращает {'id': int, 'source_url': str} или None при ошибке.
    """
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", image_url) as img_resp:
                img_resp.raise_for_status()
                image_data = await img_resp.aread()

            upload_resp = await client.post(
                f"{WP_URL}/wp-json/wp/v2/media",
                auth=_auth(),
                files={"file": ("image.jpg", image_data, "image/jpeg")},
            )
            upload_resp.raise_for_status()
            result = upload_resp.json()
            return {"id": result["id"], "source_url": result["source_url"]}
    except Exception as e:
        logger.error("Ошибка загрузки изображения: %s", e)
        return None


def _build_gallery_block(media_items: list[dict]) -> str:
    """Строит Gutenberg-блок галереи из списка {'id', 'source_url'}."""
    inner = "".join(
        f'<!-- wp:image {{"id":{item["id"]},"sizeSlug":"large","linkDestination":"none"}} -->\n'
        f'<figure class="wp-block-image size-large">'
        f'<img src="{item["source_url"]}" alt="" class="wp-image-{item["id"]}"/>'
        f'</figure>\n'
        f'<!-- /wp:image -->\n'
        for item in media_items
    )
    return (
        '<!-- wp:gallery {"linkTo":"none"} -->\n'
        '<figure class="wp-block-gallery has-nested-images columns-default is-cropped">\n'
        f'{inner}'
        '</figure>\n'
        '<!-- /wp:gallery -->'
    )


async def post_to_wp(data: dict, publish_now: bool) -> dict:
    """
    Публикует или планирует пост в WordPress.

    Если в data есть 'album_urls' — загружает все фото параллельно,
    первое становится featured image, все вместе — галереей в конце контента.
    Возвращает JSON-ответ API (содержит 'link', 'id' и др.).
    Бросает RuntimeError при ошибке.
    """
    album_urls: list[str] | None = data.get("album_urls")

    if album_urls:
        uploads = await asyncio.gather(*[upload_image_to_wp(u) for u in album_urls])
        media_items = [m for m in uploads if m is not None]
        if not media_items:
            raise RuntimeError("Не удалось загрузить ни одного изображения")
        featured_id: int = media_items[0]["id"]
        content: str = data.get("body", "") + "\n\n" + _build_gallery_block(media_items)
        logger.info("Загружено %d фото для галереи", len(media_items))
    else:
        item = await upload_image_to_wp(data["image"])
        if item is None:
            raise RuntimeError("Не удалось загрузить изображение")
        featured_id = item["id"]
        content = data.get("body", "")

    existing_tags = await _get_all_tags()
    tag_ids: list[int] = []
    for tag_name in data.get("tags", []):
        tag_id = await _resolve_tag(tag_name, existing_tags)
        if tag_id is not None:
            tag_ids.append(tag_id)

    post_data: dict = {
        "title": data.get("title", ""),
        "content": content,
        "categories": [int(data["category"])],
        "tags": tag_ids,
        "featured_media": featured_id,
        "status": "publish" if publish_now else "future",
    }

    if not publish_now:
        sched_date = data.get("schedule_date", "")
        sched_time = data.get("schedule_time", "")
        if sched_date and sched_time:
            post_data["date"] = f"{sched_date}T{sched_time}:00"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{WP_URL}/wp-json/wp/v2/posts",
            auth=_auth(),
            json=post_data,
        )

    if resp.status_code == 201:
        result = resp.json()
        logger.info("Пост создан: %s", result.get("link"))
        return result

    raise RuntimeError(
        f"Ошибка создания поста [{resp.status_code}]: {resp.text[:300]}"
    )
