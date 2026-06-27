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
