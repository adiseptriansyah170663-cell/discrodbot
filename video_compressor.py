import asyncio
import aiohttp
import os
import logging
import uuid
import math
import re

logger = logging.getLogger(__name__)

async def get_direct_video_url(url: str) -> str:
    """If the URL is a link.issou.best wrapper, fetch the actual mp4 from og:video."""
    if "link.issou.best" in url:
        # We MUST use a crawler User-Agent (like Discordbot or Python-urllib) 
        # so the server returns the metadata HTML instead of HTTP redirecting to the web player.
        headers = {"User-Agent": "Discordbot/2.0"}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url) as response:
                    text = await response.text()
                    match = re.search(r'<meta property="og:video" content="([^"]+\.mp4)"', text)
                    if match:
                        return match.group(1)
                    # Also try og:video:url just in case
                    match2 = re.search(r'<meta property="og:video:url" content="([^"]+\.mp4)"', text)
                    if match2:
                        return match2.group(1)
        except Exception as e:
            logger.error(f"Failed to extract direct video URL: {e}")
    return url

async def download_video(url: str, filepath: str, callback=None) -> bool:
    """Download the raw video from a URL."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.error(f"Failed to download video: HTTP {response.status}")
                    return False
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                with open(filepath, 'wb') as f:
                    while True:
                        chunk = await response.content.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if callback and total_size > 0:
                            pct = (downloaded / total_size) * 100
                            callback(f"Downloading... ({pct:.1f}%)")
        return True
    except Exception as e:
        logger.error(f"Exception downloading video: {e}")
        return False

async def get_video_duration(filepath: str) -> float:
    """Get the duration of a video using ffprobe."""
    try:
        process = await asyncio.create_subprocess_exec(
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', filepath,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            return float(stdout.decode().strip())
        else:
            logger.error(f"ffprobe error: {stderr.decode()}")
            return 0.0
    except Exception as e:
        logger.error(f"Exception getting video duration: {e}")
        return 0.0

async def compress_video(input_path: str, output_path: str, target_size_mb: float = 9.5, callback=None) -> bool:
    """Compress video to fit within a target size (default 9.5MB for Discord's 10MB limit)."""
    duration = await get_video_duration(input_path)
    if duration <= 0:
        logger.error("Invalid duration, cannot calculate bitrate.")
        return False
        
    # Target size in bits (1 MB = 8388608 bits)
    target_size_bits = target_size_mb * 8388608
    
    # Total required bitrate in bps
    total_bitrate = target_size_bits / duration
    
    # Audio bitrate (default to 128 kbps = 128000 bps)
    audio_bitrate = 128000
    
    # Video bitrate
    video_bitrate = total_bitrate - audio_bitrate
    
    # If the video is extremely long, the bitrate might drop too low or go negative
    # Cap it at a minimum of 100kbps so it doesn't fail, even though it might exceed 10MB.
    if video_bitrate < 100000:
        video_bitrate = 100000
        
    vb_k = math.floor(video_bitrate / 1000)
    ab_k = 128
    
    logger.info(f"Compressing video. Duration: {duration:.2f}s, Target Video Bitrate: {vb_k}k, Audio: {ab_k}k")
    
    try:
        # Run ffmpeg to compress
        process = await asyncio.create_subprocess_exec(
            'ffmpeg', '-y', '-i', input_path,
            '-b:v', f'{vb_k}k',
            '-maxrate', f'{vb_k}k',
            '-bufsize', f'{vb_k * 2}k',
            '-b:a', f'{ab_k}k',
            '-progress', 'pipe:1',
            output_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            line_str = line.decode('utf-8', errors='ignore').strip()
            if line_str.startswith('out_time_us=') and callback and duration > 0:
                try:
                    us_str = line_str.split('=')[1]
                    if us_str != 'N/A':
                        current_time = float(us_str) / 1000000.0
                        pct = (current_time / duration) * 100
                        callback(f"Compressing... ({min(pct, 100):.1f}%)")
                except ValueError:
                    pass
                    
        await process.wait()
        
        if process.returncode == 0 and os.path.exists(output_path):
            return True
        else:
            stderr = await process.stderr.read()
            logger.error(f"ffmpeg error: {stderr.decode('utf-8', errors='ignore')}")
            return False
    except Exception as e:
        logger.error(f"Exception running ffmpeg: {e}")
        return False

async def process_and_compress(url: str, target_size_mb: float = 9.5, callback=None) -> str:
    """
    Downloads and compresses the video.
    Returns the path to the compressed video if successful, else None.
    Remember to os.remove() the returned path when done!
    """
    temp_dir = "temp_videos"
    os.makedirs(temp_dir, exist_ok=True)
    
    uid = str(uuid.uuid4())
    raw_path = os.path.join(temp_dir, f"raw_{uid}.mp4")
    compressed_path = os.path.join(temp_dir, f"compressed_{uid}.mp4")
    
    direct_url = await get_direct_video_url(url)
    success = await download_video(direct_url, raw_path, callback)
    if not success:
        if os.path.exists(raw_path):
            os.remove(raw_path)
        return None
        
    success = await compress_video(raw_path, compressed_path, target_size_mb, callback)
    
    # Delete the raw video right after compression
    if os.path.exists(raw_path):
        os.remove(raw_path)
        
    if success:
        return compressed_path
    else:
        if os.path.exists(compressed_path):
            os.remove(compressed_path)
        return None
