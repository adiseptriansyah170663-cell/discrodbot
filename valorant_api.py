import aiohttp
import os
import logging
import urllib.parse

logger = logging.getLogger(__name__)

API_BASE = "https://api.henrikdev.xyz/valorant"

async def _fetch(endpoint: str) -> dict:
    api_key = os.getenv("HENRIK_API_KEY")
    if not api_key:
        return {"status": 401, "error": "API key not configured in .env (HENRIK_API_KEY)"}
    
    headers = {
        "Authorization": api_key,
        "User-Agent": "DiscordBot/1.0"
    }
    
    url = f"{API_BASE}{endpoint}"
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url) as response:
                data = await response.json()
                if response.status != 200:
                    error_msg = data.get("message") or data.get("errors", "Unknown API error")
                    return {"status": response.status, "error": error_msg}
                return {"status": 200, "data": data.get("data")}
    except Exception as e:
        logger.error(f"Valorant API request failed: {e}")
        return {"status": 500, "error": str(e)}

async def get_account(name: str, tag: str) -> dict:
    """Fetch basic account info to get the region."""
    # Endpoint: /v1/account/{name}/{tag}
    return await _fetch(f"/v1/account/{urllib.parse.quote(name)}/{urllib.parse.quote(tag)}")

async def get_mmr(region: str, name: str, tag: str) -> dict:
    """Fetch current rank and MMR changes."""
    # Endpoint: /v1/mmr/{region}/{name}/{tag}
    return await _fetch(f"/v1/mmr/{region}/{urllib.parse.quote(name)}/{urllib.parse.quote(tag)}")

async def get_latest_match(region: str, name: str, tag: str) -> dict:
    """Fetch the single latest match."""
    # Endpoint: /v3/matches/{region}/{name}/{tag}?size=1
    return await _fetch(f"/v3/matches/{region}/{urllib.parse.quote(name)}/{urllib.parse.quote(tag)}?size=1")

async def get_valorant_stats(name: str, tag: str) -> dict:
    """Combines all endpoints to get a comprehensive recent match overview."""
    
    # 1. Get Account (for Region)
    acc_res = await get_account(name, tag)
    if acc_res["status"] != 200:
        return acc_res
        
    region = acc_res["data"].get("region")
    if not region:
        return {"status": 404, "error": "Could not determine account region."}
        
    # 2. Get MMR (for Rank and RR changes)
    mmr_res = await get_mmr(region, name, tag)
    
    # 3. Get Matches (for recent game stats)
    match_res = await get_latest_match(region, name, tag)
    
    if match_res["status"] != 200:
        return match_res
        
    matches = match_res.get("data", [])
    if not matches:
        return {"status": 404, "error": "No recent matches found for this player."}
        
    match = matches[0]
    
    # Find player in match
    player_data = None
    all_players = match.get("players", {}).get("all_players", [])
    for p in all_players:
        if p.get("name", "").lower() == name.lower() and p.get("tag", "").lower() == tag.lower():
            player_data = p
            break
            
    if not player_data:
        return {"status": 404, "error": "Player data not found in match."}
        
    # Find if their team won
    team_color = player_data.get("team", "").lower() # "red" or "blue"
    team_data = match.get("teams", {}).get(team_color, {})
    has_won = team_data.get("has_won", False)
    
    return {
        "status": 200,
        "account": acc_res["data"],
        "mmr": mmr_res.get("data", {}) if mmr_res["status"] == 200 else {},
        "match": match,
        "player_stats": player_data.get("stats", {}),
        "agent": player_data.get("character"),
        "has_won": has_won,
        "team_color": team_color,
        "rounds_won": team_data.get("rounds_won", 0),
        "rounds_lost": team_data.get("rounds_lost", 0)
    }
