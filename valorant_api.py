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


# ─── !vtl  — HenrikDev (Riot-direct) stats + computed Tracker Score ────────
#
# Why not vtl.lol directly?  vtl.lol sits behind Cloudflare's "Managed
# Challenge" (cf-mitigated: challenge) which REQUIRES executing JavaScript to
# solve — no TLS-impersonation / header trick can pass it, especially from a
# datacenter IP like Railway's.  HenrikDev is the Riot-backed source those
# lookup sites use under the hood: clean JSON, no Cloudflare, and it returns
# data even when the player's tracker.gg profile is private (it reads Riot,
# not tracker.gg).  We aggregate recent competitive matches and feed the
# result into calculate_tracker_score() for the estimated TRN score.

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


def fetch_vtl_profile_sync(name: str, tag: str, size: int = 10) -> dict:
    """
    Build a season-style overview from HenrikDev by aggregating the player's
    recent competitive matches, plus current rank from the MMR endpoint.

    Returns {"status": 200, "stats": {...}} or {"status": <code>, "error": ...}.
    The stats dict matches what the !vtl command consumes.
    """
    enc_name = urllib.parse.quote(name)
    enc_tag  = urllib.parse.quote(tag)

    # 1. Account → puuid + region (region needed for match/mmr endpoints)
    acc = _henrik_get(f"/valorant/v2/account/{enc_name}/{enc_tag}")
    if not acc["ok"]:
        return {"status": acc["status"], "error": acc["error"]}

    acc_data = acc["data"] or {}
    puuid  = acc_data.get("puuid", "")
    region = (acc_data.get("region") or "ap").lower()
    if region not in VALID_REGIONS:
        region = "ap"

    # Avatar from player card (v2 returns card as an id string; v1 as an object)
    avatar_url = ""
    card = acc_data.get("card")
    if isinstance(card, dict):
        avatar_url = card.get("small", "") or card.get("large", "")
    elif isinstance(card, str) and card:
        avatar_url = f"https://media.valorant-api.com/playercards/{card}/smallart.png"

    # 2. Recent competitive matches (v4) → aggregate the target player's stats
    matches_res = _henrik_get(
        f"/valorant/v4/matches/{region}/pc/{enc_name}/{enc_tag}"
        f"?mode=competitive&size={size}"
    )
    if not matches_res["ok"]:
        return {"status": matches_res["status"], "error": matches_res["error"]}

    matches = matches_res["data"] or []
    # v4 returns data as a bare list; be defensive about a {"matches": [...]} wrapper
    if isinstance(matches, dict):
        matches = matches.get("matches") or matches.get("data") or []
    if not isinstance(matches, list) or not matches:
        return {"status": 404, "error": "No recent competitive matches found."}

    tot_k = tot_d = tot_a = 0
    tot_hs = tot_body = tot_leg = 0
    tot_dmg = 0.0
    tot_rounds = 0
    tot_score = 0
    wins = losses = draws = 0
    counted = 0
    latest_rank = "Unranked"
    latest_agent = ""

    for match in matches:
        if not isinstance(match, dict):
            continue
        players = match.get("players")
        # v4: players is a list. (Defensive: some shapes wrap in {"all_players": [...]})
        if isinstance(players, dict):
            players = players.get("all_players") or players.get("players") or []
        if not isinstance(players, list):
            continue

        # Find the queried player by puuid (fallback to name/tag match)
        me = None
        for p in players:
            if not isinstance(p, dict):
                continue
            if puuid and p.get("puuid") == puuid:
                me = p
                break
            pn = (p.get("name") or "").lower()
            pt = (p.get("tag") or "").lower()
            if pn == name.lower() and pt == tag.lower():
                me = p
        if me is None:
            continue

        st = me.get("stats") or {}
        k = int(_num(st.get("kills")))
        d = int(_num(st.get("deaths")))
        a = int(_num(st.get("assists")))
        hs = int(_num(st.get("headshots")))
        bs = int(_num(st.get("bodyshots")))
        ls = int(_num(st.get("legshots")))
        score = int(_num(st.get("score")))

        # Skip empty/abandoned matches that have no shot data at all
        if (k + d + a + hs + bs + ls) == 0:
            continue

        tot_k += k; tot_d += d; tot_a += a
        tot_hs += hs; tot_body += bs; tot_leg += ls
        tot_score += score
        tot_dmg += _player_damage(st)

        # Team + win/loss
        team_id = me.get("team_id") or me.get("team") or ""
        teams = match.get("teams")
        my_team = None
        if isinstance(teams, list):
            for t in teams:
                t_id = t.get("team_id") or t.get("team") if isinstance(t, dict) else None
                if t_id is not None and str(t_id).lower() == str(team_id).lower():
                    my_team = t
                    break
        elif isinstance(teams, dict):
            # older shape: {"red": {...}, "blue": {...}} or {"red": <rounds>}
            my_team = teams.get(str(team_id).lower())

        match_rounds = 0
        if isinstance(my_team, dict):
            won_flag = my_team.get("won")
            rounds = my_team.get("rounds")
            if isinstance(rounds, dict):
                rw = int(_num(rounds.get("won")))
                rl = int(_num(rounds.get("lost")))
                match_rounds = rw + rl
                if won_flag is None:
                    won_flag = rw > rl
            if won_flag is True:
                wins += 1
            elif won_flag is False:
                losses += 1
            else:
                draws += 1

        # Fallback rounds count from metadata if team rounds were unavailable
        if match_rounds == 0:
            meta = match.get("metadata") or {}
            match_rounds = int(_num(meta.get("rounds_played") or meta.get("total_rounds")))
        tot_rounds += match_rounds

        # Most-recent match (first in list) supplies current rank + agent
        if counted == 0:
            tier = me.get("tier")
            if isinstance(tier, dict):
                latest_rank = tier.get("name") or latest_rank
            agent = me.get("agent")
            if isinstance(agent, dict):
                latest_agent = agent.get("name") or ""
        counted += 1

    if counted == 0:
        return {"status": 404, "error": "Could not find the player's stats in recent matches."}

    # Aggregate metrics
    kdr      = tot_k / max(tot_d, 1)
    shots    = tot_hs + tot_body + tot_leg
    hs_pct   = (tot_hs / shots * 100) if shots else 0.0
    decided  = wins + losses
    winrate  = (wins / decided * 100) if decided else 0.0
    dpr      = (tot_dmg / tot_rounds) if tot_rounds else 0.0
    acs      = (tot_score / tot_rounds) if tot_rounds else 0.0

    # 3. Current rank from MMR (authoritative); fall back to latest match tier
    rank_name = latest_rank or "Unranked"
    mmr_res = _henrik_get(f"/valorant/v3/mmr/{region}/pc/{enc_name}/{enc_tag}")
    if mmr_res["ok"]:
        cur = (mmr_res["data"] or {}).get("current") or {}
        tier = cur.get("tier") or {}
        if isinstance(tier, dict) and tier.get("name"):
            rank_name = tier["name"]

    est_score = calculate_tracker_score(kdr, hs_pct, winrate, dpr)

    return {
        "status": 200,
        "stats": {
            "kdr":        kdr,
            "kills":      tot_k,
            "deaths":     tot_d,
            "assists":    tot_a,
            "hs_pct":     hs_pct,
            "winrate":    winrate,
            "matches":    counted,
            "wins":       wins,
            "losses":     losses,
            "draws":      draws,
            "dpr":        dpr,
            "acs":        acs,
            "rank_name":  rank_name,
            "avatar_url": avatar_url,
            "agent":      latest_agent,
            "tracker_score": est_score,
            "sample_size": counted,
        },
    }


async def get_vtl_profile(name: str, tag: str, size: int = 10) -> dict:
    """Async wrapper — aggregates HenrikDev competitive matches in a thread."""
    return await asyncio.to_thread(fetch_vtl_profile_sync, name, tag, size)
