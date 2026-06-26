import aiohttp
import sqlite3
import logging
import asyncio
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

ORDR_API_BASE = "https://apis.issou.best/ordr"

class OrdrManager:
    def __init__(self, db_path="ordr_skins.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Initialize the SQLite database for storing user skin preferences."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_skins (
                        user_id TEXT PRIMARY KEY,
                        skin_id INTEGER NOT NULL
                    )
                ''')
                conn.commit()
            logger.info("Ordr SQLite database initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize ordr DB: {e}")

    def get_user_skin(self, user_id: str) -> Optional[int]:
        """Get a user's preferred skin ID from the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT skin_id FROM user_skins WHERE user_id = ?', (str(user_id),))
                row = cursor.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error(f"Error fetching user skin: {e}")
            return None

    def set_user_skin(self, user_id: str, skin_id: int):
        """Set a user's preferred skin ID in the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO user_skins (user_id, skin_id)
                    VALUES (?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET skin_id = excluded.skin_id
                ''', (str(user_id), skin_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Error setting user skin: {e}")

    async def fetch_available_skins(self, page_size: int = 100) -> list:
        """Fetch a list of available skins from the o!rdr API."""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{ORDR_API_BASE}/skins?pageSize={page_size}"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("skins", [])
                    else:
                        logger.error(f"Failed to fetch skins, status: {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Exception fetching skins: {e}")
            return []

    async def submit_render(self, replay_file_bytes: bytes, skin_id: int) -> Dict[str, Any]:
        """Submit a replay file to o!rdr to be rendered."""
        try:
            data = aiohttp.FormData()
            data.add_field('replayFile',
                           replay_file_bytes,
                           filename='replay.osr',
                           content_type='application/octet-stream')
            data.add_field('resolution', '1920x1080')
            data.add_field('skin', str(skin_id) if skin_id else '1')
            
            async with aiohttp.ClientSession() as session:
                url = f"{ORDR_API_BASE}/renders"
                async with session.post(url, data=data) as response:
                    res_json = await response.json()
                    res_json['http_status'] = response.status
                    return res_json
        except Exception as e:
            logger.error(f"Exception submitting render: {e}")
            return {"error": str(e), "http_status": 500}

    async def check_render_status(self, render_id: int) -> Dict[str, Any]:
        """Poll the status of a rendering job."""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{ORDR_API_BASE}/renders?renderID={render_id}"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        # The API returns a list of renders matching the ID (usually 1)
                        if data.get("renders") and len(data["renders"]) > 0:
                            return data["renders"][0]
                    return {}
        except Exception as e:
            logger.error(f"Exception checking render status: {e}")
            return {}

# Global singleton
ordr_manager = OrdrManager()
