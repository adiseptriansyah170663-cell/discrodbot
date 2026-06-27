import os
import urllib.parse
import logging
import asyncio
from curl_cffi import requests

logger = logging.getLogger(__name__)

# HenrikDev API key (free, from https://api.henrikdev.xyz/dashboard/).
# Set HENRIK_API_KEY in Railway environment variables.
HENRIK_API_KEY = os.getenv("HENRIK_API_KEY", "")
HENRIK_BASE = "https://api.henrikdev.xyz"

# curl_cffi is synchronous, so we run it in a thread
def fetch_tracker_url_sync(url: str):
    # impersonate='chrome110' flawlessly bypasses Cloudflare Datacenter blocks
    resp = requests.get(url, impersonate='chrome110')
    
    # 451 means profile is private on Tracker.gg
    if resp.status_code == 451:
        return {"status": 451, "error": "This Valorant profile is Private. You must make it public on tracker.gg to view stats."}

    # 404 means tracker.gg has no such profile
    if resp.status_code == 404:
        return {"status": 404, "error": "Profile not found. Check that the name and tag are spelled correctly."}

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
        count: Number of recent matches to return (1-5)
    
    Returns a dict with status, season stats, and a list of parsed matches.
    """
    count = max(1, min(5, count))
    
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
        
        # Top agents (from agent segments, index 1 onward)
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


# ─── !vtl recent - HenrikDev (Riot-direct) per-match stats ─────────────────
#
# vtl.lol itself sits behind Cloudflare's "Managed Challenge" (requires running
# JavaScript) so it can't be scraped from a datacenter IP like Railway's.
# HenrikDev is the Riot-backed source those lookup sites use under the hood:
# clean JSON, no Cloudflare, and it returns data even when the player's
# tracker.gg profile is private (it reads Riot, not tracker.gg).

VALID_REGIONS = {"na", "eu", "ap", "kr", "latam", "br"}


def _henrik_get(path: str) -> dict:
    """
    GET a HenrikDev endpoint with the API key.  Returns:
      {"ok": True, "data": <json data field>}            on success
      {"ok": False, "status": <code>, "error": <msg>}    on failure
    """
    if not HENRIK_API_KEY:
        return {"ok": False, "status": 401,
                "error": "HENRIK_API_KEY not set. Add it in Railway env vars "
                         "(free key from https://api.henrikdev.xyz/dashboard/)."}

    url = f"{HENRIK_BASE}{path}"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": HENRIK_API_KEY, "Accept": "application/json"},
            impersonate="chrome124",
            timeout=20,
        )
    except Exception as e:
        return {"ok": False, "status": 500, "error": f"Request failed: {e}"}

    if resp.status_code == 429:
        return {"ok": False, "status": 429, "error": "Rate limited by HenrikDev. Try again shortly."}
    if resp.status_code == 401 or resp.status_code == 403:
        return {"ok": False, "status": resp.status_code,
                "error": "HenrikDev rejected the API key (invalid or unauthorized)."}
    if resp.status_code == 404:
        return {"ok": False, "status": 404, "error": "Player or matches not found."}

    try:
        body = resp.json()
    except Exception as e:
        return {"ok": False, "status": 500, "error": f"Bad JSON from HenrikDev: {e}"}

    if resp.status_code != 200:
        # HenrikDev returns {"errors":[{"message":...}]} on failures
        msg = "Unknown error"
        if isinstance(body, dict) and body.get("errors"):
            msg = body["errors"][0].get("message", msg)
        return {"ok": False, "status": resp.status_code, "error": f"HenrikDev: {msg}"}

    return {"ok": True, "data": body.get("data") if isinstance(body, dict) else body}


def _num(v) -> float:
    """Coerce a possibly-missing/nested value to float."""
    if isinstance(v, dict):
        v = v.get("value", v.get("dealt", 0))
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _player_damage(stats: dict) -> float:
    """v4 nests damage as {dealt, received}; older shapes use a flat number/damage_made."""
    dmg = stats.get("damage")
    if isinstance(dmg, dict):
        return _num(dmg.get("dealt"))
    if dmg is not None:
        return _num(dmg)
    return _num(stats.get("damage_made"))


def _season_of(match: dict) -> str:
    """Act identifier for a match (stored-matches: meta.season; v4: metadata.season)."""
    meta = match.get("meta") or match.get("metadata") or {}
    season = meta.get("season") or {}
    if isinstance(season, dict):
        return str(season.get("short") or season.get("id") or "")
    return str(season or "")


def _extract_match(match: dict, puuid: str, name: str, tag: str) -> dict | None:
    """
    Normalise one match into the queried player's stats, handling BOTH shapes:
      • stored-matches v1 - `stats` is already the queried player; shots.{head,
        body,leg}; damage.made; team "Red"/"Blue"; teams {red,blue} round scores.
      • v4 matches - find the player in `players`; stats.headshots/...; damage.dealt;
        team_id; teams[] with won and rounds{won,lost}.
    Returns None if the player can't be found or the match has no usable data.
    """
    if not isinstance(match, dict):
        return None

    teams = match.get("teams")
    won = None
    rounds = 0
    tier_name = ""
    agent = ""

    players = match.get("players")
    if players is not None:
        # ---- v4 shape ----
        if isinstance(players, dict):
            players = players.get("all_players") or players.get("players") or []
        if not isinstance(players, list):
            return None
        me = None
        for p in players:
            if not isinstance(p, dict):
                continue
            if puuid and p.get("puuid") == puuid:
                me = p
                break
            if (p.get("name") or "").lower() == name.lower() and \
               (p.get("tag") or "").lower() == tag.lower():
                me = p
        if me is None:
            return None
        st = me.get("stats") or {}
        hs = int(_num(st.get("headshots")))
        bs = int(_num(st.get("bodyshots")))
        ls = int(_num(st.get("legshots")))
        damage = _player_damage(st)
        team = me.get("team_id") or me.get("team") or ""
        if isinstance(teams, list):
            for t in teams:
                if isinstance(t, dict) and \
                   str(t.get("team_id") or t.get("team")).lower() == str(team).lower():
                    won = t.get("won")
                    r = t.get("rounds")
                    if isinstance(r, dict):
                        rw, rl = int(_num(r.get("won"))), int(_num(r.get("lost")))
                        rounds = rw + rl
                        if won is None:
                            won = rw > rl
                    break
        tier = me.get("tier")
        if isinstance(tier, dict):
            tier_name = tier.get("name") or ""
        ag = me.get("agent")
        if isinstance(ag, dict):
            agent = ag.get("name") or ""

    elif isinstance(match.get("stats"), dict):
        # ---- stored-matches shape (stats already = queried player) ----
        st = match.get("stats") or {}
        shots = st.get("shots") or {}
        hs = int(_num(shots.get("head")))
        bs = int(_num(shots.get("body")))
        ls = int(_num(shots.get("leg")))
        dmg = st.get("damage")
        damage = _num(dmg.get("made", dmg.get("dealt"))) if isinstance(dmg, dict) else _num(dmg)
        team = st.get("team") or ""
        if isinstance(teams, dict):
            my_r = _num(teams.get(str(team).lower()))
            other = "blue" if str(team).lower() == "red" else "red"
            opp_r = _num(teams.get(other))
            rounds = int(my_r + opp_r)
            if my_r != opp_r:
                won = my_r > opp_r
        ch = st.get("character")
        if isinstance(ch, dict):
            agent = ch.get("name") or ""
        # stored-matches `tier` is a numeric id -> rank name comes from MMR instead
    else:
        return None

    k = int(_num(st.get("kills")))
    d = int(_num(st.get("deaths")))
    a = int(_num(st.get("assists")))
    score = int(_num(st.get("score")))

    # Skip empty / abandoned matches with no stat data at all
    if (k + d + a + hs + bs + ls) == 0:
        return None

    return {
        "k": k, "d": d, "a": a, "score": score,
        "hs": hs, "bs": bs, "ls": ls,
        "damage": damage, "rounds": rounds, "won": won,
        "tier_name": tier_name, "agent": agent,
        "season": _season_of(match),
    }


# ─── !vtl recent - per-match details (like !recent, but Riot-direct) ────────

def _extract_match_detail(match: dict, puuid: str, name: str, tag: str) -> dict | None:
    """Display-ready per-match details from a v4 match (agent, map, result, KDA…)."""
    base = _extract_match(match, puuid, name, tag)
    if base is None:
        return None

    meta = match.get("metadata") or match.get("meta") or {}
    mp = meta.get("map")
    map_name = mp.get("name") if isinstance(mp, dict) else (mp or "Unknown")
    q = meta.get("queue")
    mode = (q.get("name") if isinstance(q, dict) else q) or meta.get("mode") or "Competitive"

    # Locate the player again for agent id (image) and rank name
    agent_image = ""
    rank_name = base.get("tier_name") or "Unranked"
    players = match.get("players")
    if isinstance(players, dict):
        players = players.get("all_players") or players.get("players") or []
    if isinstance(players, list):
        for p in players:
            if not isinstance(p, dict):
                continue
            if (puuid and p.get("puuid") == puuid) or (
                (p.get("name") or "").lower() == name.lower()
                and (p.get("tag") or "").lower() == tag.lower()
            ):
                ag = p.get("agent") or {}
                if isinstance(ag, dict) and ag.get("id"):
                    agent_image = f"https://media.valorant-api.com/agents/{ag['id']}/displayicon.png"
                break

    won = base["won"]
    result = "VICTORY" if won is True else "DEFEAT" if won is False else "DRAW"
    shots = base["hs"] + base["bs"] + base["ls"]
    return {
        "map_name":   map_name,
        "mode":       mode,
        "agent":      base["agent"] or "Unknown",
        "agent_image": agent_image,
        "has_won":    won is True,
        "result":     result,
        "rounds_won": 0,   # filled in by the caller from the teams breakdown
        "rounds_lost": 0,
        "kills":      base["k"],
        "deaths":     base["d"],
        "assists":    base["a"],
        "score":      base["score"],
        "match_kdr":  base["k"] / max(base["d"], 1),
        "match_hs_pct": (base["hs"] / shots * 100) if shots else 0.0,
        "rank_name":  rank_name,
    }


def fetch_vtl_recent_sync(name: str, tag: str, count: int = 1) -> dict:
    """Fetch the player's last `count` competitive matches (per-match details)."""
    count = max(1, min(5, count))
    enc_name = urllib.parse.quote(name)
    enc_tag  = urllib.parse.quote(tag)

    acc = _henrik_get(f"/valorant/v2/account/{enc_name}/{enc_tag}")
    if not acc["ok"]:
        return {"status": acc["status"], "error": acc["error"]}
    acc_data = acc["data"] or {}
    puuid  = acc_data.get("puuid", "")
    region = (acc_data.get("region") or "ap").lower()
    if region not in VALID_REGIONS:
        region = "ap"

    res = _henrik_get(
        f"/valorant/v4/matches/{region}/pc/{enc_name}/{enc_tag}?mode=competitive&size={count}"
    )
    if not res["ok"]:
        return {"status": res["status"], "error": res["error"]}

    data = res["data"] or []
    if isinstance(data, dict):
        data = data.get("matches") or data.get("data") or []
    if not isinstance(data, list) or not data:
        return {"status": 404, "error": "No recent competitive matches found."}

    matches = []
    for m in data[:count]:
        # rounds won/lost need the per-team breakdown; pull from teams here
        detail = _extract_match_detail(m, puuid, name, tag)
        if detail is None:
            continue
        rw = rl = 0
        teams = m.get("teams")
        # find player's team_id then its rounds
        me_team = None
        players = m.get("players")
        if isinstance(players, dict):
            players = players.get("all_players") or players.get("players") or []
        if isinstance(players, list):
            for p in players:
                if isinstance(p, dict) and (
                    (puuid and p.get("puuid") == puuid)
                    or ((p.get("name") or "").lower() == name.lower()
                        and (p.get("tag") or "").lower() == tag.lower())
                ):
                    me_team = p.get("team_id") or p.get("team")
                    break
        if isinstance(teams, list) and me_team is not None:
            for t in teams:
                if isinstance(t, dict) and str(t.get("team_id") or t.get("team")).lower() == str(me_team).lower():
                    r = t.get("rounds") or {}
                    rw, rl = int(_num(r.get("won"))), int(_num(r.get("lost")))
                    break
        detail["rounds_won"] = rw
        detail["rounds_lost"] = rl
        matches.append(detail)

    if not matches:
        return {"status": 404, "error": "Could not parse recent match data."}
    return {"status": 200, "matches": matches}


async def get_vtl_recent(name: str, tag: str, count: int = 1) -> dict:
    """Async wrapper - fetches recent match details for a (possibly private) profile."""
    return await asyncio.to_thread(fetch_vtl_recent_sync, name, tag, count)
