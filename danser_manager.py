import os
import aiohttp
import asyncio
import logging
import uuid
import json
import zipfile
from osrparse import Replay

logger = logging.getLogger(__name__)

DANSER_VERSION = "0.9.1"
DANSER_DIR = "danser"
DANSER_URL = f"https://github.com/Wieku/danser-go/releases/download/{DANSER_VERSION}/danser-{DANSER_VERSION}-linux.zip"

class DanserManager:
    def __init__(self):
        self.danser_dir = os.path.abspath(DANSER_DIR)
        self.songs_dir = os.path.join(self.danser_dir, "Songs")
        self.replays_dir = os.path.join(self.danser_dir, "Replays")
        self.skins_dir = os.path.join(self.danser_dir, "Skins")
        
        os.makedirs(self.songs_dir, exist_ok=True)
        os.makedirs(self.replays_dir, exist_ok=True)
        os.makedirs(self.skins_dir, exist_ok=True)

    async def setup(self):
        """Downloads and extracts Danser if not present."""
        danser_bin = os.path.join(self.danser_dir, "danser")
        if not os.path.exists(danser_bin):
            logger.info("Downloading Danser...")
            zip_path = os.path.join(self.danser_dir, "danser.zip")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(DANSER_URL) as resp:
                    with open(zip_path, 'wb') as f:
                        f.write(await resp.read())
                        
            logger.info("Extracting Danser...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(self.danser_dir)
            
            if os.path.exists(zip_path):
                os.remove(zip_path)
            
            # Make executable
            try:
                os.chmod(danser_bin, 0o755)
            except Exception:
                pass
            logger.info("Danser setup complete.")

    async def download_beatmap(self, beatmap_hash: str) -> bool:
        """Finds and downloads the beatmap set into the Songs folder."""
        url = f"https://catboy.best/api/v2/search?hash={beatmap_hash}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.error("Failed to find beatmap via API.")
                    return False
                
                data = await resp.json()
                if not data or len(data) == 0:
                    logger.error("No beatmap found for hash.")
                    return False
                
                beatmapset_id = data[0].get("id")
                if not beatmapset_id:
                    return False
                
        osz_url = f"https://catboy.best/api/v2/d/{beatmapset_id}"
        osz_path = os.path.join(self.songs_dir, f"{beatmapset_id}.osz")
        
        if os.path.exists(osz_path):
            return True
            
        logger.info(f"Downloading beatmapset {beatmapset_id}...")
        async with aiohttp.ClientSession() as session:
            async with session.get(osz_url) as resp:
                if resp.status == 200:
                    with open(osz_path, 'wb') as f:
                        f.write(await resp.read())
                    return True
        return False

    async def generate_settings(self):
        """Generates Danser settings to output directly to 10MB."""
        settings_path = os.path.join(self.danser_dir, "settings.json")
        
        # Fixed bitrate to guarantee most replays under 4 minutes are < 10MB
        # 4 mins = 240 seconds. 10MB = 81.9Mbits. 81.9 / 240 = 340 kbps total.
        # Audio = 128k, Video = 210k
        vb_k = 210
        ab_k = 128
        
        settings = {
            "General": {
                "OsuSongsDir": self.songs_dir,
                "OsuSkinsDir": self.skins_dir
            },
            "Recording": {
                "FrameWidth": 1920,
                "FrameHeight": 1080,
                "FPS": 60,
                "AudioCodec": "aac",
                "AudioBitrate": f"{ab_k}k",
                "VideoCodec": "libx264",
                "VideoOptions": f"-b:v {vb_k}k -maxrate {vb_k}k -bufsize {vb_k * 2}k -preset ultrafast -pix_fmt yuv420p"
            }
        }
        
        with open(settings_path, 'w') as f:
            json.dump(settings, f, indent=4)
            
    async def process_replay(self, replay_bytes: bytes) -> str:
        """Full pipeline: returns path to rendered MP4, or None."""
        await self.setup()
        await self.generate_settings()
        
        uid = str(uuid.uuid4())
        osr_path = os.path.join(self.replays_dir, f"{uid}.osr")
        out_name = f"render_{uid}"
        out_mp4 = os.path.join(self.danser_dir, f"{out_name}.mp4")
        
        with open(osr_path, 'wb') as f:
            f.write(replay_bytes)
            
        try:
            logger.info("Parsing replay...")
            replay = Replay.from_path(osr_path)
            
            logger.info("Downloading beatmap...")
            success = await self.download_beatmap(replay.beatmap_hash)
            if not success:
                logger.error("Could not download beatmap.")
                return None
                
            logger.info("Starting xvfb-run danser...")
            # Running headless via xvfb
            cmd = ['xvfb-run', '-s', '-screen 0 1920x1080x24', './danser', '-replay', osr_path, '-record', '-out', out_name]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.danser_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                logger.error(f"Danser failed: {stderr.decode()}")
                return None
                
            if os.path.exists(out_mp4):
                return out_mp4
            return None
            
        except Exception as e:
            logger.error(f"Exception rendering replay: {e}")
            return None
        finally:
            if os.path.exists(osr_path):
                try:
                    os.remove(osr_path)
                except:
                    pass

danser_manager = DanserManager()
