# Telegram Bot для публикации в WordPress

Этот бот позволяет пользователям создавать и публиковать посты в WordPress через Telegram. Бот поддерживает как немедленную, так и отложенную публикацию, а также предоставляет удобный интерфейс для ввода данных.

---

## Требования

1. **Python**: Версия 3.8 или выше.
2. **Библиотеки Python** (установите их с помощью `pip`):
   - `python-telegram-bot`
   - `httpx`
   - `cachetools`
   - `sqlite3` (входит в стандартную библиотеку Python)
   - `aiosqlite` (опционально, если вы хотите использовать асинхронную базу данных)
   - `dotenv` (`python-dotenv`)
   - `structlog` (для структурированного логирования)

   **Список библиотек**:
   Сохраните этот текст в файл `requirements.txt`:
    ```env
    python-telegram-bot==20.7
    httpx==0.24.1
    cachetools==5.3.0
    python-dotenv==1.0.0
    aiosqlite==0.19.0
    structlog==23.1.0
    ```
3. **WordPress**:
- Убедитесь, что ваш WordPress имеет включенный REST API.
- Создайте учетные данные для доступа к API (username и password).
- Если используете Basic Auth, установите плагин [WP REST API Basic Auth](https://wordpress.org/plugins/rest-api-basic-auth/).
---

## Установка и настройка
1. Создание файла `.env`
Создайте файл `.env` в корне проекта и заполните его следующими переменными:

    ```env
    TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
    WP_URL=https://your-wordpress-site.com
    WP_USERNAME=your_wordpress_username
    WP_PASSWORD=your_wordpress_password
    ALLOWED_USERS=user_id1,user_id2
    ```
- TELEGRAM_BOT_TOKEN: Токен вашего Telegram бота.
- WP_URL: URL вашего WordPress сайта.
- WP_USERNAME и WP_PASSWORD: Учетные данные для доступа к WordPress API.
- ALLOWED_USERS: Список ID Telegram пользователей, которые могут использовать бота. Разделите ID пользователей запятой.

#### 2. Установка зависимостей
Установите необходимые библиотеки с помощью pip:
```python
pip install -r requirements.txt
```
#### 3. Настройка базы данных
Бот использует SQLite для временного хранения данных. База данных будет автоматически создана при первом запуске бота.

#### 4. Запуск бота
Запустите бота командой:
```python
python main.py
```

## Использование бота
1. Начните диалог с ботом командой `/start`.
2. Введите данные для создания поста:
    - Заголовок
    - Текст поста
    - Категорию
    - Теги (опционально)
    - Изображение для обложки
    - Выберите время публикации (сейчас или отложить)
3. После завершения всех шагов бот опубликует пост в WordPress.
Для отмены процесса создания поста используйте команду `/cancel`.

## Авторство и благодарности
Этот бот был разработан с использованием технологий искусственного интеллекта. Документация и некоторые части кода были сгенерированы с помощью Qwen , нейросетевой модели, разработанной Alibaba Cloud.
- Сайт : [Qwen](https://www.qwen.ai/?spm=5aebb161.2ef5001f.0.0.4a59c921c1Czmk)
- GitHub : [Alibaba Cloud Qwen Repository](https://github.com/alibaba/Qwen?spm=5aebb161.2ef5001f.0.0.4a59c921c1Czmk)
- Лицензия : MIT License

Если у вас есть вопросы или предложения по улучшению бота, пожалуйста, свяжитесь с разработчиками.