import json
import sqlite3
from datetime import date, datetime

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect("user_data.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_data (
            user_id INTEGER PRIMARY KEY,
            data TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_user_data(user_id: int, data: dict):
    """Сохраняет данные пользователя в базу данных"""
    def serialize(obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")

    serialized_data = json.dumps(data, default=serialize)
    conn = sqlite3.connect("user_data.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO user_data (user_id, data)
        VALUES (?, ?)
    """, (user_id, serialized_data))
    conn.commit()
    conn.close()

def load_user_data(user_id: int) -> dict:
    """Загружает данные пользователя из базы данных"""
    conn = sqlite3.connect("user_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT data FROM user_data WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()

    if result is None:
        return {}

    def deserialize(obj):
        if isinstance(obj, str):
            try:
                return datetime.fromisoformat(obj)
            except ValueError:
                pass
        return obj

    return json.loads(result[0], object_hook=lambda d: {k: deserialize(v) for k, v in d.items()})

def delete_user_data(user_id: int):
    """Удаляет данные пользователя из базы данных"""
    conn = sqlite3.connect("user_data.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_data WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()