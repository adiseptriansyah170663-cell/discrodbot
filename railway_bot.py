"""
Discord Music Bot - Railway Version
Optimized for Railway platform with proper logging and error handling
"""

import asyncio
import os
import random
import logging
from collections import deque
import urllib.parse
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

import discord
from discord.ext import commands
import yt_dlp
import valorant_api

# Load environment variables
load_dotenv()

# Setup logging for Railway
logging.basicConfig(
  level=logging.INFO,
  format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Set discord logger to WARNING to suppress 'RESUMED session' INFO logs
logging.getLogger('discord').setLevel(logging.WARNING)

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

YTDL_BASE_OPTS = {
  'format': 'bestaudio/best',
  'noplaylist': False,
  'quiet': True,
  'no_warnings': True,
  'default_search': 'ytsearch',
  'ignoreerrors': True,
  'socket_timeout': 30,
  'skip_download': True,
}

# Lightweight search options (flat extraction = no stream URL fetching)
YTDL_SEARCH_OPTS = {
  'quiet': True,
  'no_warnings': True,
  'extract_flat': True,
  'ignoreerrors': True,
  'socket_timeout': 15,
  'skip_download': True,
}

# Timeout for search selection (seconds)
SEARCH_TIMEOUT = 30

FFMPEG_OPTS = {
  'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
  'options': '-vn',
}

# ---------- Piped API (YouTube proxy, no auth needed) ----------
import urllib.request
import json as _json
import re as _re

PIPED_INSTANCES = [
  'https://pipedapi.kavin.rocks',
  'https://pipedapi.adminforge.de',
  'https://pipedapi.in.projectsegfau.lt',
  'https://api.piped.yt',
]


def extract_video_id(url: str) -> str:
  """Extract YouTube video ID from various URL formats"""
  patterns = [
    r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
    r'(?:embed|shorts)/([a-zA-Z0-9_-]{11})',
  ]
  for pattern in patterns:
    match = _re.search(pattern, url)
    if match:
      return match.group(1)
  return ''


def fetch_piped_stream(video_id: str) -> dict:
  """Fetch audio stream URL from Piped API instances (tried in order)"""
  for instance in PIPED_INSTANCES:
    try:
      api_url = f'{instance}/streams/{video_id}'
      req = urllib.request.Request(api_url)
      req.add_header('User-Agent', 'Mozilla/5.0')
      with urllib.request.urlopen(req, timeout=15) as resp:
        data = _json.loads(resp.read().decode())

      audio_streams = data.get('audioStreams', [])
      if not audio_streams:
        logger.warning(f'Piped {instance}: no audio streams')
        continue

      # Pick highest bitrate audio stream
      best = max(audio_streams, key=lambda s: s.get('bitrate', 0))
      logger.info(f'Piped {instance}: got stream ({best.get("quality", "?")})')
      return {
        'url': best['url'],
        'title': data.get('title', 'Unknown'),
        'webpage_url': f'https://www.youtube.com/watch?v={video_id}',
        'duration': data.get('duration', 0),
      }
    except Exception as e:
      logger.warning(f'Piped {instance} failed: {e}')
      continue

  return None


# ---------- yt-dlp fallback instances ----------
def get_ytdl_instances():
  """yt-dlp fallback instances (cookies + mobile client). Used when Piped fails."""
  has_cookies = os.path.exists('cookies.txt')
  instances = []

  # 1. Cookies (may work if YouTube hasn't flagged the session)
  if has_cookies:
    opts1 = YTDL_BASE_OPTS.copy()
    opts1['cookiefile'] = 'cookies.txt'
    instances.append(yt_dlp.YoutubeDL(opts1))

  # 2. Mobile client tanpa auth (last resort)
  opts2 = YTDL_BASE_OPTS.copy()
  opts2['extractor_args'] = {'youtube': {'client': ['ANDROID_MUSIC', 'MWEB']}}
  instances.append(yt_dlp.YoutubeDL(opts2))

  return instances


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
    """Extract track info from YouTube with multi-fallback (for URLs/playlists)"""
    def extract():
      # Try Piped API for single video URLs first
      video_id = extract_video_id(query)
      if video_id:
        logger.info(f'from_query trying Piped API for: {query}')
        piped_data = fetch_piped_stream(video_id)
        if piped_data:
          return piped_data

      instances = get_ytdl_instances()
      for ytdl in instances:
        try:
          data = ytdl.extract_info(query, download=False)
          if data is not None and ('entries' in data or 'url' in data):
            entries = data.get('entries', [data])
            if any(e and e.get('url') for e in entries):
              return data
        except Exception as e:
          logger.debug(f'yt-dlp extraction fallback failed: {e}')
          continue
      return None
    
    try:
      data = await asyncio.wait_for(
        loop.run_in_executor(None, extract), 
        timeout=30
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

  @classmethod
  async def from_url(cls, url, requester, loop):
    """Extract a single track from a URL (full extraction for stream URL)"""
    def extract():
      # Try Piped API first
      video_id = extract_video_id(url)
      if video_id:
        logger.info(f'from_url trying Piped API for: {url}')
        piped_data = fetch_piped_stream(video_id)
        if piped_data:
          return piped_data

      instances = get_ytdl_instances()
      for i, ytdl in enumerate(instances, 1):
        try:
          logger.info(f'from_url attempt {i}/{len(instances)} for: {url}')
          data = ytdl.extract_info(url, download=False)
          if data is not None and data.get('url'):
            logger.info(f'from_url succeeded on attempt {i}')
            return data
          logger.warning(f'from_url attempt {i}: no stream URL in response')
        except Exception as e:
          logger.warning(f'from_url attempt {i} failed: {type(e).__name__}: {e}')
          continue
      logger.error(f'All {len(instances)} extraction attempts failed for: {url}')
      return None

    try:
      data = await asyncio.wait_for(
        loop.run_in_executor(None, extract),
        timeout=30
      )
    except asyncio.TimeoutError:
      logger.warning(f'Timeout loading URL: {url}')
      return None
    except Exception as e:
      logger.error(f'Error extracting URL: {e}')
      return None

    if data is None:
      return None

    return cls(data, requester)


class SearchResult:
  """Lightweight search result (no stream URL, just metadata)"""

  def __init__(self, title, video_url, duration):
    self.title = title
    self.url = video_url # webpage URL like https://youtube.com/watch?v=xxx
    self.duration = duration


async def search_youtube(query, loop, max_results=5):
  """Search YouTube with flat extraction (no stream URL fetching, avoids bot detection)"""
  def do_search():
    search_query = f'ytsearch{max_results}:{query}'
    try:
      with yt_dlp.YoutubeDL(YTDL_SEARCH_OPTS) as ytdl:
        data = ytdl.extract_info(search_query, download=False)
        if data and 'entries' in data:
          results = []
          for entry in data['entries']:
            if entry is None:
              continue
            title = entry.get('title', 'Unknown')
            video_url = entry.get('url', '')
            if not video_url and entry.get('id'):
              video_url = f'https://www.youtube.com/watch?v={entry["id"]}'
            duration = entry.get('duration', 0)
            results.append(SearchResult(title, video_url, duration))
          return results
    except Exception as e:
      logger.error(f'Search failed: {e}')
    return []

  try:
    results = await asyncio.wait_for(
      loop.run_in_executor(None, do_search),
      timeout=15
    )
  except asyncio.TimeoutError:
    logger.warning(f'Search timeout: {query}')
    return []
  except Exception as e:
    logger.error(f'Search error: {e}')
    return []

  return results


def is_url(query: str) -> bool:
  """Check if a query is a URL"""
  return query.startswith(('http://', 'https://'))


def format_duration(seconds):
  """Format duration to MM:SS"""
  if not seconds:
    return ''
  mins, secs = divmod(int(seconds), 60)
  return f'({mins}:{secs:02d})'


class SearchSelect(discord.ui.Select):
  """Dropdown menu for selecting a search result"""

  def __init__(self, results: list):
    self.results = results
    options = []
    for i, result in enumerate(results[:5]):
      dur = format_duration(result.duration)
      label = result.title[:100]
      options.append(
        discord.SelectOption(
          label=label,
          value=str(i),
          description=f'#{i+1} {dur}'.strip()
        )
      )
    super().__init__(
      placeholder='Pick a song...',
      min_values=1,
      max_values=1,
      options=options
    )

  async def callback(self, interaction: discord.Interaction):
    idx = int(self.values[0])
    selected = self.results[idx]
    self.view.selected_result = selected
    self.view.stop()

    # Acknowledge and update the message
    embed = discord.Embed(
      title='Song Selected',
      description=f'**{selected.title}** {format_duration(selected.duration)}',
      color=discord.Color.green()
    )
    await interaction.response.edit_message(embed=embed, view=None)


class CancelButton(discord.ui.Button):
  """Cancel button for search view"""

  def __init__(self):
    super().__init__(label='Cancel', style=discord.ButtonStyle.secondary)

  async def callback(self, interaction: discord.Interaction):
    self.view.selected_track = None
    self.view.stop()
    embed = discord.Embed(
      title='Search Cancelled',
      color=discord.Color.greyple()
    )
    await interaction.response.edit_message(embed=embed, view=None)


class SearchView(discord.ui.View):
  """View with dropdown + cancel for search results"""

  def __init__(self, results: list, author_id: int):
    super().__init__(timeout=SEARCH_TIMEOUT)
    self.selected_result = None
    self.author_id = author_id
    self.add_item(SearchSelect(results))
    self.add_item(CancelButton())

  async def interaction_check(self, interaction: discord.Interaction) -> bool:
    """Only the command author can interact"""
    if interaction.user.id != self.author_id:
      await interaction.response.send_message(
        'Only the person who searched can select!', ephemeral=True
      )
      return False
    return True

  async def on_timeout(self):
    """Disable all items on timeout"""
    self.selected_result = None
    self.stop()


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
async def on_message(message):
  # Ignore messages from bots
  if message.author.bot:
    return

  # Process other commands
  await bot.process_commands(message)


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


# Remove default help command so we can create our own
bot.remove_command('help')

# ---------- Commands ----------

@bot.command(name='hello')
async def hello(ctx):
  """Say hello"""
  try:
    await ctx.send(f'Hello {ctx.author.mention}!')
  except Exception as e:
    logger.error(f'Hello command error: {e}')

@bot.command(name='recent')
async def recent(ctx, *, riot_id: str = None):
  """Fetch recent Valorant match(es) (e.g. !recent TenZ#0303 or !recent TenZ#0303 3)"""
  if not riot_id or '#' not in riot_id:
    await ctx.send("Usage: `!recent <name>#<tag> [count]`\nExample: `!recent TenZ#0303` or `!recent TenZ#0303 3`")
    return

  # Parse count from the end of the input (e.g. "TenZ#0303 2")
  parts = riot_id.rsplit(' ', 1)
  count = 1
  if len(parts) == 2 and parts[1].isdigit():
    count = max(1, min(3, int(parts[1])))
    riot_id = parts[0]

  if '#' not in riot_id:
    await ctx.send("Usage: `!recent <name>#<tag> [count]`\nExample: `!recent TenZ#0303` or `!recent TenZ#0303 3`")
    return

  name, tag = riot_id.split('#', 1)
  name = name.strip()
  tag = tag.strip()

  msg = await ctx.send(f"Fetching {count} recent match(es) for **{name}#{tag}**...")

  try:
    stats = await valorant_api.get_valorant_stats(name, tag, count=count)
    if stats["status"] != 200:
      await msg.edit(content=f"Error: {stats.get('error', 'Unknown error')}")
      return

    matches = stats["matches"]
    s_tracker_score = stats["season_tracker_score"]
    s_kills, s_deaths = stats["s_kills"], stats["s_deaths"]
    s_matches, s_wins = stats["s_matches"], stats["s_wins"]
    s_hs, s_body, s_leg = stats["s_hs"], stats["s_body"], stats["s_leg"]

    def fmt_delta(val, is_pct=False):
      sign = "+" if val > 0 else ""
      pct = "%" if is_pct else ""
      return f"{sign}{val:.2f}{pct}"

    embeds = []
    for idx, m in enumerate(matches):
      win_status = m["result"]
      color = discord.Color.green() if m["has_won"] else discord.Color.red()
      if win_status == "DRAW":
        color = discord.Color.light_gray()

      title = f"{name}#{tag}"
      if len(matches) > 1:
        title = f"Match {idx + 1}/{len(matches)} - {name}#{tag}"

      embed = discord.Embed(
        title=title,
        description=f"**{win_status}** ({m['rounds_won']} - {m['rounds_lost']}) on **{m['map_name']}** ({m['mode']})",
        color=color
      )

      embed.add_field(name="Agent", value=m["agent"], inline=True)
      embed.add_field(name="K/D/A", value=f"{m['kills']} / {m['deaths']} / {m['assists']}", inline=True)
      embed.add_field(name="Score", value=str(m["score"]), inline=True)
      embed.add_field(name="KDR", value=f"{m['match_kdr']:.2f}", inline=True)
      embed.add_field(name="HS%", value=f"{m['match_hs_pct']:.1f}%", inline=True)

      if m["rank_name"] != "Unranked":
        embed.add_field(name="Rank", value=m["rank_name"], inline=True)
      else:
        embed.add_field(name="\u200b", value="\u200b", inline=True)

      # Season deltas only on the first (most recent) match
      if idx == 0:
        current_kdr = s_kills / max(s_deaths, 1)
        p_kills = s_kills - m["kills"]
        p_deaths = s_deaths - m["deaths"]
        prev_kdr = p_kills / max(p_deaths, 1)
        kdr_delta = current_kdr - prev_kdr

        m_win = 1 if m["has_won"] else 0
        current_wr = (s_wins / max(s_matches, 1)) * 100
        p_matches = s_matches - 1
        p_wins = s_wins - m_win
        prev_wr = (p_wins / max(p_matches, 1)) * 100 if p_matches > 0 else 0
        wr_delta = current_wr - prev_wr

        s_total = s_hs + s_body + s_leg
        current_hs = (s_hs / max(s_total, 1)) * 100
        p_hs = s_hs - m["m_hs"]
        p_total = s_total - (m["m_hs"] + m["m_body"] + m["m_leg"])
        prev_hs = (p_hs / max(p_total, 1)) * 100
        hs_delta = current_hs - prev_hs

        embed.add_field(name="Season KDR", value=f"{current_kdr:.2f} ({fmt_delta(kdr_delta)})", inline=True)
        embed.add_field(name="Season HS%", value=f"{current_hs:.1f}% ({fmt_delta(hs_delta, True)})", inline=True)
        embed.add_field(name="Season WR", value=f"{current_wr:.1f}% ({fmt_delta(wr_delta, True)})", inline=True)

        m_tracker_score = m.get("match_tracker_score")
        if m_tracker_score and s_tracker_score:
          trn_delta = (m_tracker_score - s_tracker_score) / max(s_matches, 1)
          embed.add_field(name="Tracker Score (Season)", value=f"{s_tracker_score} ({fmt_delta(trn_delta)})", inline=True)
          embed.add_field(name="Tracker Score (Match)", value=str(m_tracker_score), inline=True)
          embed.add_field(name="\u200b", value="\u200b", inline=True)

      if m["agent_image"]:
        embed.set_thumbnail(url=m["agent_image"])

      embed.set_footer(text="Data from Tracker.gg")
      embeds.append(embed)

    # Send first embed as edit to the loading message, rest as new messages
    await msg.edit(content="", embed=embeds[0])
    for extra_embed in embeds[1:]:
      await ctx.send(embed=extra_embed)

  except Exception as e:
    logger.error(f"Error in recent command: {e}")
    await msg.edit(content="An error occurred while fetching the stats.")


@bot.command(name='tracker')
async def tracker(ctx, *, riot_id: str = None):
  """Show season profile stats from Tracker.gg (e.g. !tracker TenZ#0303)"""
  if not riot_id or '#' not in riot_id:
    await ctx.send("Usage: `!tracker <name>#<tag>`\nExample: `!tracker TenZ#0303`")
    return

  name, tag = riot_id.split('#', 1)
  name = name.strip()
  tag = tag.strip()

  msg = await ctx.send(f"Fetching season profile for **{name}#{tag}**...")

  try:
    profile = await valorant_api.get_season_profile(name, tag)

    if profile["status"] == 451:
      await msg.edit(
        content=f"This profile is private on Tracker.gg.\n"
                f"Try `!vtl {name}#{tag}` — it reads stats directly from Riot (works for private profiles)."
      )
      return

    if profile["status"] != 200:
      await msg.edit(content=f"Error: {profile.get('error', 'Unknown error')}")
      return

    embed = discord.Embed(
      title=f"Season Profile: {name}#{tag}",
      color=discord.Color.dark_teal()
    )

    embed.add_field(name="Rank", value=profile["rank_name"], inline=True)
    embed.add_field(name="Tracker Score", value=str(profile["tracker_score"]), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    embed.add_field(name="KDR", value=f"{profile['kdr']:.2f}", inline=True)
    embed.add_field(name="HS%", value=f"{profile['hs_pct']:.1f}%", inline=True)
    embed.add_field(name="Winrate", value=f"{profile['winrate']:.1f}%", inline=True)

    embed.add_field(name="Matches", value=str(profile["matches_played"]), inline=True)
    embed.add_field(name="W / L", value=f"{profile['matches_won']} / {profile['matches_lost']}", inline=True)
    embed.add_field(name="DMG/Round", value=f"{profile['damage_per_round']:.1f}", inline=True)

    embed.add_field(name="K / D / A", value=f"{profile['kills']} / {profile['deaths']} / {profile['assists']}", inline=True)
    if profile["kast"]:
      embed.add_field(name="KAST", value=f"{profile['kast']:.1f}%", inline=True)
    else:
      embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    # Top agents
    if profile["top_agents"]:
      agent_lines = []
      for a in profile["top_agents"]:
        wr = (a["wins"] / max(a["matches"], 1)) * 100
        agent_lines.append(f"{a['name']} -- {a['matches']} games, {wr:.0f}% WR, {a['kdr']:.2f} KDR")
      embed.add_field(name="Top Agents", value="\n".join(agent_lines), inline=False)

    if profile.get("avatar_url"):
      embed.set_thumbnail(url=profile["avatar_url"])

    embed.set_footer(text="Data from Tracker.gg")
    await msg.edit(content="", embed=embed)

  except Exception as e:
    logger.error(f"Error in tracker command: {e}")
    await msg.edit(content="An error occurred while fetching the profile.")


@bot.command(name='vtl')
async def vtl(ctx, *, riot_id: str = None):
  """Recent-form stats + estimated Tracker Score (works for private Tracker.gg profiles)"""
  if not riot_id or '#' not in riot_id:
    await ctx.send("Usage: `!vtl <name>#<tag>`\nExample: `!vtl TenZ#0303`")
    return

  name, tag = riot_id.split('#', 1)
  name = name.strip()
  tag = tag.strip()

  vtl_url = f"https://vtl.lol/id/{urllib.parse.quote(name)}_{urllib.parse.quote(tag)}"
  msg = await ctx.send(f"Fetching stats for **{name}#{tag}**...")

  try:
    result = await valorant_api.get_vtl_profile(name, tag)
    stats = result.get("stats")

    # ── Failure: link-only fallback embed ─────────────────────────────────
    if result.get("status") != 200 or stats is None:
      err = result.get("error", "Unknown error")
      embed = discord.Embed(
        title=f"Valorant Profile: {name}#{tag}",
        description=(
          f"Could not load stats: {err}\n\n"
          f"[View profile on vtl.lol]({vtl_url})"
        ),
        color=discord.Color.orange()
      )
      embed.set_footer(text="HenrikDev (Riot)")
      await msg.edit(content="", embed=embed)
      return

    # ── Rich stats embed ──────────────────────────────────────────────────
    kdr       = stats.get("kdr", 0.0)
    hs_pct    = stats.get("hs_pct", 0.0)
    winrate   = stats.get("winrate", 0.0)
    dpr       = stats.get("dpr", 0.0)
    acs       = stats.get("acs", 0.0)
    kills     = stats.get("kills", 0)
    deaths    = stats.get("deaths", 0)
    assists   = stats.get("assists", 0)
    sample    = stats.get("sample_size", stats.get("matches", 0))
    wins      = stats.get("wins", 0)
    losses    = stats.get("losses", 0)
    rank      = stats.get("rank_name", "Unranked")
    avatar    = stats.get("avatar_url", "")
    est_score = stats.get("tracker_score") or valorant_api.calculate_tracker_score(kdr, hs_pct, winrate, dpr)

    embed = discord.Embed(
      title=f"Valorant Profile: {name}#{tag}",
      url=vtl_url,
      description=f"Aggregated from last **{sample}** competitive match(es)",
      color=discord.Color.dark_teal()
    )

    embed.add_field(name="Rank", value=rank, inline=True)
    embed.add_field(name="Est. Tracker Score", value=f"~{est_score}", inline=True)
    embed.add_field(name="​", value="​", inline=True)

    embed.add_field(name="KDR", value=f"{kdr:.2f}", inline=True)
    embed.add_field(name="HS%", value=f"{hs_pct:.1f}%", inline=True)
    embed.add_field(name="Winrate", value=f"{winrate:.1f}%", inline=True)

    embed.add_field(name="W / L", value=f"{wins} / {losses}", inline=True)
    if dpr > 0:
      embed.add_field(name="DMG/Round", value=f"{dpr:.1f}", inline=True)
    else:
      embed.add_field(name="​", value="​", inline=True)
    if acs > 0:
      embed.add_field(name="ACS", value=f"{acs:.0f}", inline=True)
    else:
      embed.add_field(name="​", value="​", inline=True)

    if kills > 0 or deaths > 0 or assists > 0:
      embed.add_field(name="K / D / A (total)", value=f"{kills} / {deaths} / {assists}", inline=True)

    if avatar:
      embed.set_thumbnail(url=avatar)

    embed.set_footer(text="Data from HenrikDev (Riot) • Tracker Score is estimated, not official • Works for private Tracker.gg profiles")
    await msg.edit(content="", embed=embed)

  except Exception as e:
    logger.error(f"Error in vtl command: {e}")
    embed = discord.Embed(
      title=f"Valorant Profile: {name}#{tag}",
      description=f"An error occurred while fetching stats.\n\n[View profile on vtl.lol]({vtl_url})",
      color=discord.Color.orange()
    )
    embed.set_footer(text="HenrikDev (Riot)")
    await msg.edit(content="", embed=embed)


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
  """Play music (shows top 5 results for search queries)"""
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
    
    # If it's a URL, do full extraction and queue directly
    if is_url(query):
      async with ctx.typing():
        try:
          normalized = normalize_query(query)
          logger.info(f'Loading URL: {query}')
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
        duration = format_duration(tracks[0].duration)
        await ctx.send(f'Queued: {tracks[0].title} {duration}')
      else:
        await ctx.send(
          f'Queued {len(tracks)} tracks\n'
          f'First: {tracks[0].title}'
        )
      return

    # Search query -- lightweight flat search (no bot detection)
    async with ctx.typing():
      try:
        logger.info(f'Searching: {query}')
        results = await search_youtube(query, bot.loop)
      except Exception as e:
        logger.error(f'Search error: {e}')
        await ctx.send(f'ERROR: Failed to search: {str(e)[:100]}')
        return

    if not results:
      await ctx.send('ERROR: No results found.')
      return

    # Show top 5 results for user selection
    results = results[:5]
    embed = discord.Embed(
      title=f'Search results for: {query[:200]}',
      description='Select a song from the dropdown below:',
      color=discord.Color.blurple()
    )
    for i, result in enumerate(results):
      dur = format_duration(result.duration)
      embed.add_field(
        name=f'#{i+1}. {result.title}',
        value=f'{dur}' if dur else '(unknown duration)',
        inline=False
      )
    embed.set_footer(text=f'Select within {SEARCH_TIMEOUT}s or it will be cancelled.')

    view = SearchView(results, ctx.author.id)
    msg = await ctx.send(embed=embed, view=view)

    # Wait for user selection
    timed_out = await view.wait()

    if timed_out or view.selected_result is None:
      if timed_out:
        timeout_embed = discord.Embed(
          title='Search Timed Out',
          description='No song was selected.',
          color=discord.Color.greyple()
        )
        try:
          await msg.edit(embed=timeout_embed, view=None)
        except Exception:
          pass
      return

    # User selected a result -- now do full extraction for just this one video
    selected = view.selected_result
    loading_msg = await ctx.send(f'Loading: {selected.title}...')

    track = await Track.from_url(selected.url, ctx.author, bot.loop)
    if track is None:
      await loading_msg.edit(content=f'ERROR: Failed to load "{selected.title}". Try another result.')
      return

    player = get_player(ctx)
    player.queue.append(track)
    duration = format_duration(track.duration)
    await loading_msg.edit(content=f'Queued: {track.title} {duration}')

  except Exception as e:
    logger.error(f'Play error: {e}')
    await ctx.send(f'ERROR: {str(e)[:100]}')


@bot.command(name='search')
async def search(ctx, *, query: str):
  """Search for a song without auto-queueing"""
  try:
    async with ctx.typing():
      try:
        logger.info(f'Searching: {query}')
        results = await search_youtube(query, bot.loop)
      except Exception as e:
        logger.error(f'Search error: {e}')
        await ctx.send(f'ERROR: Failed to search: {str(e)[:100]}')
        return

    if not results:
      await ctx.send('ERROR: No results found.')
      return

    results = results[:5]
    embed = discord.Embed(
      title=f'Search results for: {query[:200]}',
      description='Use `!play <URL>` to play a specific result, or select below to queue it.',
      color=discord.Color.blurple()
    )
    for i, result in enumerate(results):
      dur = format_duration(result.duration)
      url_text = f'[Link]({result.url})' if result.url else ''
      embed.add_field(
        name=f'#{i+1}. {result.title}',
        value=f'{dur} {url_text}'.strip() or '(unknown)',
        inline=False
      )
    embed.set_footer(text=f'Select within {SEARCH_TIMEOUT}s or it will be cancelled.')

    # Only allow queueing if user is in a voice channel
    if ctx.author.voice and ctx.author.voice.channel:
      view = SearchView(results, ctx.author.id)
      msg = await ctx.send(embed=embed, view=view)

      timed_out = await view.wait()
      if timed_out or view.selected_result is None:
        if timed_out:
          timeout_embed = discord.Embed(
            title='Search Timed Out',
            description='No song was selected.',
            color=discord.Color.greyple()
          )
          try:
            await msg.edit(embed=timeout_embed, view=None)
          except Exception:
            pass
        return

      selected = view.selected_result

      # Auto-join voice if not already connected
      if ctx.voice_client is None:
        try:
          await safe_voice_connect(ctx.author.voice.channel)
        except Exception as e:
          await ctx.send(f'ERROR: Failed to join voice: {str(e)[:100]}')
          return

      # Full extraction for the selected result
      loading_msg = await ctx.send(f'Loading: {selected.title}...')
      track = await Track.from_url(selected.url, ctx.author, bot.loop)
      if track is None:
        await loading_msg.edit(content=f'ERROR: Failed to load "{selected.title}". Try another result.')
        return

      player = get_player(ctx)
      player.queue.append(track)
      duration = format_duration(track.duration)
      await loading_msg.edit(content=f'Queued: {track.title} {duration}')
    else:
      # Not in voice -- just show results
      await ctx.send(embed=embed)

  except Exception as e:
    logger.error(f'Search error: {e}')
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


@bot.command(name='commands')
async def commands_cmd(ctx):
  """Show all commands"""
  try:
    embed = discord.Embed(
      title='Discord Music Bot - Commands',
      color=discord.Color.green()
    )
    
    commands_list = [
      ('recent <name>#<tag> [count]', 'Recent match stats (1-3 matches)'),
      ('tracker <name>#<tag>', 'Season profile from Tracker.gg'),
      ('vtl <name>#<tag>', 'Recent-form stats + est. Tracker Score (private profiles too)'),
      ('join', 'Join voice channel'),
      ('leave', 'Leave voice channel'),
      ('play <query>', 'Search & pick from top 5, or play URL directly'),
      ('search <query>', 'Search top 5 without auto-queueing'),
      ('pause', 'Pause'),
      ('resume', 'Resume'),
      ('skip', 'Skip track'),
      ('queue / q', 'Show queue'),
      ('clear', 'Clear queue'),
      ('hello', 'Say hello'),
      ('roll [max]', 'Roll number'),
      ('commands', 'Show this message'),
    ]
    
    for cmd, desc in commands_list:
      embed.add_field(name=f'!{cmd}', value=desc, inline=False)
    
    embed.set_footer(text='Railway Music Bot v1.0')
    await ctx.send(embed=embed)
  except Exception as e:
    logger.error(f'Commands error: {e}')


# ---------- Main ----------
if __name__ == '__main__':
  try:
    logger.info('Starting Discord Music Bot...')
    bot.run(DISCORD_TOKEN, log_handler=None)
  except KeyboardInterrupt:
    logger.info('Bot shutdown')
  except Exception as e:
    logger.error(f'Fatal error: {e}')
    raise