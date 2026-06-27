import json
import re
import urllib.parse
import logging
import asyncio
from curl_cffi import requests

logger = logging.getLogger(__name__)

# curl_cffi is synchronous, so we run it in a thread
def fetch_tracker_url_sync(url: str):
    # impersonate='chrome110' flawlessly bypasses Cloudflare Datacenter blocks
    resp = requests.get(url, impersonate='chrome110')
    
    # 451 means profile is private on Tracker.gg
    if resp.status_code == 451:
        return {"status": 451, "error": "This Valorant profile is Private. You must make it public on tracker.gg to view stats."}
    
    if resp.status_code != 200:
        return {"status": resp.status_code, "error": f"Failed to fetch data from tracker.gg (HTTP {resp.status_code})"}
        
    try:
        return {"status": 200, "data": resp.json().get("data")}
    except Exception as e:
        return {"status": 500, "error": f"Failed to parse tracker.gg response: {e}"}

async def fetch_tracker_url(url: str) -> dict:
    return await asyncio.to_thread(fetch_tracker_url_sync, url)


def _parse_single_match(match: dict) -> dict:
    """Parse a single match object into a flat stats dict."""
    meta = match.get("metadata", {})
    seg = match["segments"][0]
    stats = seg.get("stats", {})
    
    map_name = meta.get("mapName", "Unknown Map")
    mode = meta.get("modeName", "Competitive")
    result = meta.get("result", "Unknown")  # 'victory', 'defeat', 'draw'
    has_won = (result == 'victory')
    
    agent = seg.get("metadata", {}).get("agentName", "Unknown Agent")
    agent_image = seg.get("metadata", {}).get("agentImageUrl", "")
    
    # Match Stats
    kills = stats.get("kills", {}).get("value", 0)
    deaths = stats.get("deaths", {}).get("value", 0)
    assists = stats.get("assists", {}).get("value", 0)
    score = stats.get("score", {}).get("value", 0)
    
    m_hs = stats.get("dealtHeadshots", {}).get("value", 0)
    m_body = stats.get("dealtBodyshots", {}).get("value", 0)
    m_leg = stats.get("dealtLegshots", {}).get("value", 0)
    
    match_tracker_score = stats.get("trnPerformanceScore", {}).get("value")
    
    # Win/Loss rounds
    rounds_won = stats.get("roundsWon", {}).get("value", 0)
    rounds_lost = stats.get("roundsLost", {}).get("value", 0)
    
    # Rank info (from the match data)
    rank_name = stats.get("rank", {}).get("metadata", {}).get("tierName", "Unranked")
    
    # Match HS%
    m_total = m_hs + m_body + m_leg
    match_hs_pct = (m_hs / max(m_total, 1)) * 100
    
    # Match KDR
    match_kdr = kills / max(deaths, 1)
    
    return {
        "agent": agent,
        "agent_image": agent_image,
        "has_won": has_won,
        "result": result.upper(),
        "kills": int(kills),
        "deaths": int(deaths),
        "assists": int(assists),
        "score": int(score),
        "rounds_won": int(rounds_won),
        "rounds_lost": int(rounds_lost),
        "map_name": map_name,
        "mode": mode,
        "rank_name": rank_name,
        "match_tracker_score": match_tracker_score,
        "m_hs": m_hs, "m_body": m_body, "m_leg": m_leg,
        "match_hs_pct": match_hs_pct,
        "match_kdr": match_kdr,
    }


async def get_valorant_stats(name: str, tag: str, count: int = 1) -> dict:
    """Combines Profile and Matches endpoints to get recent match overview(s).
    
    Args:
        name: Riot name
        tag: Riot tag
        count: Number of recent matches to return (1-3)
    
    Returns a dict with status, season stats, and a list of parsed matches.
    """
    count = max(1, min(3, count))
    
    player_id = f"{urllib.parse.quote(name)}%23{urllib.parse.quote(tag)}"
    
    # 1. Fetch Profile (for Tracker Score and Season Stats)
    profile_url = f"https://api.tracker.gg/api/v2/valorant/standard/profile/riot/{player_id}"
    profile_res = await fetch_tracker_url(profile_url)
    
    if profile_res["status"] != 200:
        return profile_res
        
    profile_data = profile_res["data"]
    
    # Extract Tracker Score
    tracker_score = 0
    try:
        overview_stats = profile_data["segments"][0]["stats"]
        if "trnPerformanceScore" in overview_stats:
            tracker_score = overview_stats["trnPerformanceScore"]["value"]
    except Exception:
        pass
        
    # Extract Season Stats for Delta Math
    s_stats = profile_data["segments"][0]["stats"]
    s_kills = s_stats.get("kills", {}).get("value", 0)
    s_deaths = s_stats.get("deaths", {}).get("value", 0)
    s_matches = s_stats.get("matchesPlayed", {}).get("value", 0)
    s_wins = s_stats.get("matchesWon", {}).get("value", 0)
    
    s_hs = s_stats.get("dealtHeadshots", {}).get("value", 0)
    s_body = s_stats.get("dealtBodyshots", {}).get("value", 0)
    s_leg = s_stats.get("dealtLegshots", {}).get("value", 0)
    
    # 2. Fetch Matches
    matches_url = f"https://api.tracker.gg/api/v2/valorant/standard/matches/riot/{player_id}?type=competitive"
    match_res = await fetch_tracker_url(matches_url)
    
    if match_res["status"] != 200:
        return match_res
        
    matches = match_res.get("data", {}).get("matches", [])
    if not matches:
        return {"status": 404, "error": "No recent competitive matches found."}
    
    # Parse up to `count` matches
    parsed_matches = []
    for i, match in enumerate(matches[:count]):
        try:
            parsed = _parse_single_match(match)
            parsed_matches.append(parsed)
        except Exception as e:
            logger.error(f"Error parsing match {i}: {e}")
            continue
    
    if not parsed_matches:
        return {"status": 500, "error": "Failed to parse match data structure."}
    
    return {
        "status": 200,
        "season_tracker_score": tracker_score,
        "s_kills": s_kills, "s_deaths": s_deaths,
        "s_matches": s_matches, "s_wins": s_wins,
        "s_hs": s_hs, "s_body": s_body, "s_leg": s_leg,
        "matches": parsed_matches,
    }


async def get_season_profile(name: str, tag: str) -> dict:
    """Fetch season-level overview stats from tracker.gg profile for the !tracker command."""
    
    player_id = f"{urllib.parse.quote(name)}%23{urllib.parse.quote(tag)}"
    
    profile_url = f"https://api.tracker.gg/api/v2/valorant/standard/profile/riot/{player_id}"
    profile_res = await fetch_tracker_url(profile_url)
    
    if profile_res["status"] != 200:
        return profile_res
    
    profile_data = profile_res["data"]
    
    try:
        # Player info
        platform_info = profile_data.get("platformInfo", {})
        avatar_url = platform_info.get("avatarUrl", "")
        
        # Overview segment (index 0)
        overview = profile_data["segments"][0]
        s_stats = overview.get("stats", {})
        
        # Core stats
        tracker_score = 0
        if "trnPerformanceScore" in s_stats:
            tracker_score = s_stats["trnPerformanceScore"]["value"]
        
        matches_played = s_stats.get("matchesPlayed", {}).get("value", 0)
        matches_won = s_stats.get("matchesWon", {}).get("value", 0)
        matches_lost = matches_played - matches_won
        winrate = (matches_won / max(matches_played, 1)) * 100
        
        kills = s_stats.get("kills", {}).get("value", 0)
        deaths = s_stats.get("deaths", {}).get("value", 0)
        assists = s_stats.get("assists", {}).get("value", 0)
        kdr = kills / max(deaths, 1)
        
        s_hs = s_stats.get("dealtHeadshots", {}).get("value", 0)
        s_body = s_stats.get("dealtBodyshots", {}).get("value", 0)
        s_leg = s_stats.get("dealtLegshots", {}).get("value", 0)
        s_total = s_hs + s_body + s_leg
        hs_pct = (s_hs / max(s_total, 1)) * 100
        
        damage_per_round = s_stats.get("damagePerRound", {}).get("value", 0)
        
        kast = s_stats.get("kAST", {}).get("value", 0)
        
        # Rank from the most recent season data
        rank_name = s_stats.get("rank", {}).get("metadata", {}).get("tierName", "Unranked")
        
        # Top agents (from agent segments, indices 1+)
        top_agents = []
        for seg in profile_data.get("segments", [])[1:]:
            if seg.get("type") == "agent":
                agent_name = seg.get("metadata", {}).get("name", "Unknown")
                agent_matches = seg.get("stats", {}).get("matchesPlayed", {}).get("value", 0)
                agent_wins = seg.get("stats", {}).get("matchesWon", {}).get("value", 0)
                agent_kdr_val = seg.get("stats", {}).get("kDRatio", {}).get("value", 0)
                top_agents.append({
                    "name": agent_name,
                    "matches": agent_matches,
                    "wins": agent_wins,
                    "kdr": agent_kdr_val,
                })
            if len(top_agents) >= 3:
                break
        
        return {
            "status": 200,
            "avatar_url": avatar_url,
            "rank_name": rank_name,
            "tracker_score": tracker_score,
            "matches_played": matches_played,
            "matches_won": matches_won,
            "matches_lost": matches_lost,
            "winrate": winrate,
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "kdr": kdr,
            "hs_pct": hs_pct,
            "damage_per_round": damage_per_round,
            "kast": kast,
            "top_agents": top_agents,
        }
        
    except Exception as e:
        logger.error(f"Error parsing season profile: {e}")
        return {"status": 500, "error": "Failed to parse profile data structure."}


# ─── VTL.LOL scraping with Cloudflare bypass ───────────────────────────────

def calculate_tracker_score(kdr: float, hs_pct: float, winrate: float, dpr: float = 0) -> int:
    """
    Approximated TRN Performance Score.
    Not the official tracker.gg algorithm — used when that score isn't available.
    Outputs in the same 0-2000 range as the official score.
    """
    kdr_comp  = (max(0.0, kdr)     ** 0.8) * 400
    hs_comp   = (max(0.0, hs_pct)  ** 0.7) * 15
    wr_comp   = max(0.0, winrate) * 3.5
    dpr_comp  = (max(0.0, dpr) ** 0.65) * 7 if dpr > 0 else 100
    return round(min(2000, max(0, kdr_comp + hs_comp + wr_comp + dpr_comp)))


def _parse_vtl_sveltekit_nodes(raw: dict) -> dict | None:
    """
    SvelteKit __data.json embeds page-load data in a nested nodes list.
    Walk it and return the richest dict we find.
    """
    try:
        nodes = raw.get("nodes") or []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            data = node.get("data")
            if isinstance(data, list):
                # devalue arrays: index 0 is often the root object index
                # real objects are the dicts inside
                for item in data:
                    if isinstance(item, dict) and len(item) >= 3:
                        return item
            elif isinstance(data, dict) and len(data) >= 3:
                return data
    except Exception as e:
        logger.debug(f"vtl SvelteKit node parse error: {e}")
    return None


def _normalise_vtl_stats(raw: dict) -> dict | None:
    """
    Normalise a raw dict (from __data.json or an API endpoint) into a flat
    stats dict the !vtl command can consume.  Handles many possible key names
    because we don't know vtl.lol's exact schema.
    """
    if not isinstance(raw, dict):
        return None

    # Drill into common wrappers
    for wrapper in ("stats", "competitive", "season", "data", "player", "profile"):
        if wrapper in raw and isinstance(raw[wrapper], dict):
            inner = _normalise_vtl_stats(raw[wrapper])
            if inner:
                return inner

    def _v(d, *keys, default=0.0):
        for k in keys:
            v = d.get(k)
            if v is None:
                continue
            if isinstance(v, dict):
                v = v.get("value") or v.get("val") or 0
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
        return default

    kdr     = _v(raw, "kdr", "kd", "kDRatio", "kdRatio", "k_d")
    kills   = _v(raw, "kills")
    deaths  = _v(raw, "deaths")
    assists = _v(raw, "assists")
    hs_pct  = _v(raw, "hs_pct", "hsPct", "headshots_pct", "headshotPct", "hs", "headshots")
    winrate = _v(raw, "winrate", "win_rate", "winRate", "wRate", "wins_pct")
    matches = int(_v(raw, "matches", "matches_played", "matchesPlayed", "games"))
    wins    = int(_v(raw, "wins", "matches_won", "matchesWon", "w"))
    losses  = int(_v(raw, "losses", "matches_lost", "matchesLost", "l"))
    dpr     = _v(raw, "dpr", "damage_per_round", "damagePerRound", "acs", "avgDamagePerRound")

    # Derive KDR from K/D when not explicit
    if kdr == 0 and (kills > 0 or deaths > 0):
        kdr = kills / max(deaths, 1)

    # Convert ratio → percentage where applicable
    if 0 < hs_pct <= 1.0:
        hs_pct *= 100
    if 0 < winrate <= 1.0:
        winrate *= 100

    # Need at least one meaningful stat
    if kdr == 0 and kills == 0 and matches == 0:
        return None

    rank_raw = raw.get("rank") or raw.get("currentRank") or {}
    rank_name = (
        rank_raw.get("name") or rank_raw.get("tier_name") or rank_raw.get("tierName")
        if isinstance(rank_raw, dict) else str(rank_raw)
    ) or raw.get("rank_name") or raw.get("rankName") or "Unknown"

    avatar = (
        raw.get("avatar") or raw.get("avatar_url") or raw.get("avatarUrl")
        or raw.get("profileImage") or raw.get("card", {}).get("small", "")
        if isinstance(raw.get("card"), dict) else ""
    ) or ""

    return {
        "kdr":      kdr,
        "kills":    int(kills),
        "deaths":   int(deaths),
        "assists":  int(assists),
        "hs_pct":   hs_pct,
        "winrate":  winrate,
        "matches":  matches,
        "wins":     wins,
        "losses":   losses,
        "dpr":      dpr,
        "rank_name": str(rank_name),
        "avatar_url": str(avatar),
    }


def fetch_vtl_profile_sync(name: str, tag: str) -> dict:
    """
    Fetch vtl.lol profile stats, bypassing Cloudflare with curl_cffi.

    Strategy (tried in order for each impersonation profile):
      1. Warm-up GET on vtl.lol homepage to acquire CF cookies.
      2. SvelteKit __data.json — cleanest: returns JSON without JS execution.
      3. Common custom API endpoint guesses (e.g. /api/player/name/tag).
      4. Full page HTML — last resort; parse embedded JSON blobs.
    """
    vtl_id      = f"{name}_{tag}"
    encoded_id  = urllib.parse.quote(vtl_id)
    profile_url = f"https://vtl.lol/id/{encoded_id}"
    data_url    = f"{profile_url}/__data.json"

    nav_hdrs = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }
    json_hdrs = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://vtl.lol/",
    }

    # Candidate API paths to probe (vtl.lol may expose one of these)
    enc_name = urllib.parse.quote(name)
    enc_tag  = urllib.parse.quote(tag)
    api_paths = [
        f"/api/player/{enc_name}/{enc_tag}",
        f"/api/profile/{enc_name}/{enc_tag}",
        f"/api/stats/{enc_name}/{enc_tag}",
        f"/api/v1/player/{enc_name}/{enc_tag}",
        f"/api/v1/profile/{enc_name}/{enc_tag}",
    ]

    for impersonate in ("chrome124", "chrome120", "chrome110", "safari17_0"):
        try:
            session = requests.Session()

            # ── Step 1: warm-up to get CF clearance cookies ──────────────────
            try:
                session.get("https://vtl.lol/", impersonate=impersonate,
                            headers=nav_hdrs, timeout=10)
            except Exception:
                pass  # cookies may still be set even on timeout

            # ── Step 2: SvelteKit __data.json ────────────────────────────────
            try:
                resp = session.get(data_url, impersonate=impersonate,
                                   headers=json_hdrs, timeout=15)
                if resp.status_code == 200:
                    raw = resp.json()
                    logger.info(f"vtl.lol __data.json OK ({impersonate})")
                    candidate = _parse_vtl_sveltekit_nodes(raw) or raw
                    stats = _normalise_vtl_stats(candidate)
                    if stats:
                        return {"status": 200, "stats": stats}
                    logger.warning(f"vtl.lol __data.json unparseable: {str(raw)[:400]}")
            except Exception as e:
                logger.debug(f"vtl.lol __data.json ({impersonate}): {e}")

            # ── Step 3: API endpoint probes ───────────────────────────────────
            for path in api_paths:
                try:
                    resp = session.get(f"https://vtl.lol{path}",
                                       impersonate=impersonate,
                                       headers=json_hdrs, timeout=10)
                    if resp.status_code == 200:
                        raw = resp.json()
                        stats = _normalise_vtl_stats(raw)
                        if stats:
                            logger.info(f"vtl.lol API {path} OK ({impersonate})")
                            return {"status": 200, "stats": stats}
                except Exception:
                    pass

            # ── Step 4: full HTML page ────────────────────────────────────────
            resp = session.get(profile_url, impersonate=impersonate,
                               headers=nav_hdrs, timeout=15)
            if resp.status_code == 200:
                html = resp.text
                logger.info(f"vtl.lol HTML OK ({impersonate}, {len(html)} bytes)")

                # Search for embedded JSON blobs in <script> tags
                for pat in (
                    r'"(?:stats|player|profile|competitive)"\s*:\s*(\{[^\n<]{80,})',
                    r'window\.__(?:DATA|STATE|INITIAL(?:_DATA|_STATE)?)__\s*=\s*(\{.{60,}?\})\s*[;\n]',
                    r'<script[^>]*>\s*(\{[^<]{200,}\})\s*</script>',
                ):
                    m = re.search(pat, html, re.DOTALL)
                    if m:
                        try:
                            raw = json.loads(m.group(1))
                            stats = _normalise_vtl_stats(raw)
                            if stats:
                                return {"status": 200, "stats": stats}
                        except Exception:
                            pass

                # Got through CF but couldn't parse — return partial result
                return {"status": 200, "stats": None}

            elif resp.status_code in (403, 503, 429):
                logger.warning(f"vtl.lol CF block {resp.status_code} ({impersonate})")
                continue
            else:
                logger.warning(f"vtl.lol HTTP {resp.status_code} ({impersonate})")

        except Exception as e:
            logger.warning(f"vtl.lol {impersonate} exception: {e}")
            continue

    return {"status": 403, "error": "vtl.lol blocked all requests (Cloudflare)"}


async def get_vtl_profile(name: str, tag: str) -> dict:
    """Async wrapper — runs fetch_vtl_profile_sync in a thread pool."""
    return await asyncio.to_thread(fetch_vtl_profile_sync, name, tag)
