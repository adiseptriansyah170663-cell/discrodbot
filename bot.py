"""
Discord Music Bot - Railway Version
Optimized for Railway platform with proper logging and error handling
"""

import asyncio
import os
import random
import logging
from collections import deque
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

import discord
from discord.ext import commands
import yt_dlp

# Load environment variables
load_dotenv()

# Setup logging for Railway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get Discord token
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
if not DISCORD_TOKEN:
    logger.error('ERROR: DISCORD_TOKEN not found in environment variables!')
    raise ValueError('DISCORD_TOKEN is required')

# FFmpeg path - Railway has ffmpeg pre-installed
FFMPEG_PATH = os.getenv('FFMPEG_PATH', 'ffmpeg')

# ---------- Bot setup ----------
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents)

# ---------- yt-dlp configuration ----------
YTDL_OPTS = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best',
    'noplaylist': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'ignoreerrors': True,
    'socket_timeout': 30,
    'skip_download': True,
}

FFMPEG_OPTS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)


def normalize_query(query: str) -> str:
    """Convert YouTube URL with list param to pure playlist URL"""
    if not query.startswith(('http://', 'https://')):
        return query
    try:
        parsed = urlparse(query)
    except ValueError:
        return query
    
    host = parsed.netloc.lower()
    if not any(h in host for h in ('youtube.com', 'youtu.be', 'music.youtube.com')):
        return query
    
    list_id = parse_qs(parsed.query).get('list', [None])[0]
    if not list_id:
        return query
    
    return f'https://www.youtube.com/playlist?list={list_id}'


class Track:
    """Represents an audio track"""
    
    def __init__(self, data, requester):
        self.title = data.get('title', 'Unknown')
        self.url = data['url']
        self.webpage_url = data.get('webpage_url', '')
        self.duration = data.get('duration', 0)
        self.requester = requester

    @classmethod
    async def from_query(cls, query, requester, loop):
        """Extract track info from YouTube"""
        def extract():
            try:
                return ytdl.extract_info(query, download=False)
            except Exception as e:
                logger.error(f'yt-dlp error: {e}')
                return None
        
        try:
            data = await asyncio.wait_for(
                loop.run_in_executor(None, extract), 
                timeout=15
            )
        except asyncio.TimeoutError:
            logger.warning(f'Timeout loading: {query}')
            return []
        except Exception as e:
            logger.error(f'Error extracting track: {e}')
            return []
        
        if data is None:
            return []
        
        if 'entries' in data:
            entries = [e for e in data['entries'] if e and e.get('url')]
        else:
            entries = [data] if data.get('url') else []
        
        return [cls(e, requester) for e in entries]


class GuildPlayer:
    """Music player for each guild"""
    
    def __init__(self, ctx):
        self.bot = ctx.bot
        self.guild = ctx.guild
        self.channel = ctx.channel
        self.queue: deque = deque()
        self.next_event = asyncio.Event()
        self.current: Track = None
        self.is_playing = False
        self.task = self.bot.loop.create_task(self._player_loop())
        logger.info(f'Player created for guild: {self.guild.name}')

    async def _player_loop(self):
        """Main player loop"""
        while True:
            self.next_event.clear()
            
            if not self.queue:
                try:
                    await asyncio.wait_for(self._wait_for_track(), timeout=300)
                except asyncio.TimeoutError:
                    logger.info(f'Queue timeout for {self.guild.name}')
                    await self._cleanup()
                    return

            self.current = self.queue.popleft()
            vc = self.guild.voice_client
            
            if vc is None:
                logger.warning(f'Voice client unavailable for {self.guild.name}')
                await self._cleanup()
                return

            try:
                logger.info(f'Creating audio source: {self.current.title}')
                source = discord.FFmpegPCMAudio(
                    self.current.url,
                    executable=FFMPEG_PATH,
                    **FFMPEG_OPTS
                )
                
                vc.play(
                    source,
                    after=lambda e: self.bot.loop.call_soon_threadsafe(self.next_event.set)
                )
                self.is_playing = True
                logger.info(f'Playing: {self.current.title}')
                
            except FileNotFoundError:
                logger.error(f'FFmpeg not found: {FFMPEG_PATH}')
                await self.channel.send(
                    'ERROR: FFmpeg not installed. Contact bot owner.'
                )
                await self._cleanup()
                return
                
            except Exception as e:
                logger.error(f'Playback error: {type(e).__name__}: {e}')
                await self.channel.send(f'ERROR: Playback failed: {str(e)[:100]}')
                self.current = None
                self.is_playing = False
                continue

            # Notify now playing
            duration_str = self._format_duration(self.current.duration)
            try:
                await self.channel.send(
                    f'Now playing: {self.current.title} {duration_str}\n'
                    f'Requested by: {self.current.requester.mention}'
                )
            except Exception as e:
                logger.warning(f'Failed to send message: {e}')
            
            await self.next_event.wait()
            self.current = None
            self.is_playing = False

    async def _wait_for_track(self):
        """Wait for track in queue"""
        while not self.queue:
            await asyncio.sleep(1)

    async def _cleanup(self):
        """Cleanup and disconnect"""
        try:
            vc = self.guild.voice_client
            if vc:
                await vc.disconnect()
        except Exception as e:
            logger.error(f'Disconnect error: {e}')
        finally:
            players.pop(self.guild.id, None)
            logger.info(f'Player cleaned up for {self.guild.name}')

    def _format_duration(self, seconds):
        """Format duration to MM:SS"""
        if not seconds:
            return '(unknown)'
        mins, secs = divmod(int(seconds), 60)
        return f'({mins}:{secs:02d})'


players: dict = {}


def get_player(ctx) -> GuildPlayer:
    """Get or create player for guild"""
    player = players.get(ctx.guild.id)
    if player is None:
        player = GuildPlayer(ctx)
        players[ctx.guild.id] = player
    return player


async def safe_voice_connect(channel, max_retries=3):
    """Safely connect to voice channel"""
    guild = channel.guild
    vc = guild.voice_client
    
    if vc is not None:
        try:
            logger.info('Disconnecting existing voice connection')
            await vc.disconnect(force=True)
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning(f'Disconnect error: {e}')
    
    for attempt in range(max_retries):
        try:
            logger.info(f'Connecting to voice (attempt {attempt + 1}/{max_retries})')
            vc = await channel.connect(timeout=30.0, reconnect=True)
            logger.info(f'Connected to {channel.name}')
            return vc
        except Exception as e:
            logger.warning(f'Connection attempt {attempt + 1} failed: {e}')
            if attempt < max_retries - 1:
                await asyncio.sleep(1 + attempt)
            else:
                raise


# ---------- Events ----------
@bot.event
async def on_ready():
    """Bot ready event"""
    logger.info(f'Bot logged in as {bot.user.name}')
    logger.info(f'Connected to {len(bot.guilds)} server(s)')
    await bot.change_presence(
        activity=discord.Game(name='!help for commands')
    )


@bot.event
async def on_command_error(ctx, error):
    """Global error handler"""
    if isinstance(error, commands.CommandNotFound):
        return
    
    logger.error(f'Command error: {error}')
    try:
        await ctx.send(f'ERROR: {str(error)[:100]}')
    except:
        pass


# ---------- Commands ----------
@bot.command(name='hello')
async def hello(ctx):
    """Say hello"""
    try:
        await ctx.send(f'Hello {ctx.author.mention}!')
    except Exception as e:
        logger.error(f'Hello command error: {e}')


@bot.command(name='roll')
async def roll(ctx, maximum: int = 100):
    """Roll random number"""
    try:
        if maximum < 1:
            await ctx.send('Please provide a positive number!')
            return
        
        result = random.randint(0, maximum)
        await ctx.send(f'{ctx.author.mention} rolled {result}')
    except Exception as e:
        logger.error(f'Roll command error: {e}')


@bot.command(name='join')
async def join(ctx):
    """Join voice channel"""
    try:
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.send('ERROR: Join a voice channel first!')
            return
        
        channel = ctx.author.voice.channel
        logger.info(f'{ctx.author.name} requested join to {channel.name}')
        
        await safe_voice_connect(channel)
        await ctx.send(f'Joined {channel.name}')
    except Exception as e:
        logger.error(f'Join error: {e}')
        await ctx.send(f'ERROR: Failed to join: {str(e)[:100]}')


@bot.command(name='leave')
async def leave(ctx):
    """Leave voice channel"""
    try:
        if ctx.voice_client is None:
            await ctx.send('ERROR: Not in voice channel!')
            return
        
        player = players.pop(ctx.guild.id, None)
        if player and player.task:
            player.task.cancel()
        
        await ctx.voice_client.disconnect()
        await ctx.send('Disconnected')
    except Exception as e:
        logger.error(f'Leave error: {e}')
        await ctx.send(f'ERROR: {str(e)[:100]}')


@bot.command(name='play')
async def play(ctx, *, query: str):
    """Play music"""
    try:
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.send('ERROR: Join voice channel first!')
            return
        
        if ctx.voice_client is None:
            try:
                logger.info('Auto-joining voice for play')
                await safe_voice_connect(ctx.author.voice.channel)
            except Exception as e:
                logger.error(f'Auto-join failed: {e}')
                await ctx.send(f'ERROR: Failed to join voice: {str(e)[:100]}')
                return
        
        async with ctx.typing():
            try:
                normalized = normalize_query(query)
                logger.info(f'Loading: {query}')
                
                tracks = await Track.from_query(
                    normalized,
                    ctx.author,
                    bot.loop
                )
                
            except Exception as e:
                logger.error(f'Track load error: {e}')
                await ctx.send(f'ERROR: Failed to load: {str(e)[:100]}')
                return

        if not tracks:
            await ctx.send('ERROR: No tracks found.')
            return

        player = get_player(ctx)
        player.queue.extend(tracks)
        
        if len(tracks) == 1:
            duration = player._format_duration(tracks[0].duration)
            await ctx.send(f'Queued: {tracks[0].title} {duration}')
        else:
            await ctx.send(
                f'Queued {len(tracks)} tracks\n'
                f'First: {tracks[0].title}'
            )
    except Exception as e:
        logger.error(f'Play error: {e}')
        await ctx.send(f'ERROR: {str(e)[:100]}')


@bot.command(name='pause')
async def pause(ctx):
    """Pause playback"""
    try:
        vc = ctx.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await ctx.send('Paused')
        else:
            await ctx.send('ERROR: Nothing playing!')
    except Exception as e:
        logger.error(f'Pause error: {e}')


@bot.command(name='resume')
async def resume(ctx):
    """Resume playback"""
    try:
        vc = ctx.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await ctx.send('Resumed')
        else:
            await ctx.send('ERROR: Nothing paused!')
    except Exception as e:
        logger.error(f'Resume error: {e}')


@bot.command(name='skip')
async def skip(ctx):
    """Skip current track"""
    try:
        vc = ctx.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await ctx.send('Skipped')
        else:
            await ctx.send('ERROR: Nothing to skip!')
    except Exception as e:
        logger.error(f'Skip error: {e}')


@bot.command(name='queue', aliases=['q'])
async def queue_cmd(ctx):
    """Show queue"""
    try:
        player = players.get(ctx.guild.id)
        
        if player is None or (not player.queue and not player.current):
            await ctx.send('Queue is empty')
            return
        
        embed = discord.Embed(
            title='Music Queue',
            color=discord.Color.blue()
        )
        
        if player.current:
            duration = player._format_duration(player.current.duration)
            embed.add_field(
                name='Now Playing',
                value=f'{player.current.title} {duration}',
                inline=False
            )
        
        if player.queue:
            queue_list = '\n'.join(
                f'{i+1}. {t.title}'
                for i, t in enumerate(list(player.queue)[:10])
            )
            embed.add_field(
                name=f'Upcoming ({len(player.queue)} tracks)',
                value=queue_list,
                inline=False
            )
        
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f'Queue error: {e}')


@bot.command(name='clear')
async def clear(ctx):
    """Clear queue"""
    try:
        player = players.get(ctx.guild.id)
        
        if player is None or not player.queue:
            await ctx.send('Queue already empty')
            return
        
        count = len(player.queue)
        player.queue.clear()
        await ctx.send(f'Cleared {count} tracks')
    except Exception as e:
        logger.error(f'Clear error: {e}')


@bot.command(name='help')
async def help_cmd(ctx):
    """Show commands"""
    try:
        embed = discord.Embed(
            title='Discord Music Bot - Commands',
            color=discord.Color.green()
        )
        
        commands_list = [
            ('join', 'Join voice channel'),
            ('leave', 'Leave voice channel'),
            ('play <query>', 'Play music'),
            ('pause', 'Pause'),
            ('resume', 'Resume'),
            ('skip', 'Skip track'),
            ('queue / q', 'Show queue'),
            ('clear', 'Clear queue'),
            ('hello', 'Say hello'),
            ('roll [max]', 'Roll number'),
        ]
        
        for cmd, desc in commands_list:
            embed.add_field(name=f'!{cmd}', value=desc, inline=False)
        
        embed.set_footer(text='Railway Music Bot v1.0')
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f'Help error: {e}')


# ---------- Main ----------
if __name__ == '__main__':
    try:
        logger.info('Starting Discord Music Bot...')
        bot.run(DISCORD_TOKEN)
    except KeyboardInterrupt:
        logger.info('Bot shutdown')
    except Exception as e:
        logger.error(f'Fatal error: {e}')
        raise
