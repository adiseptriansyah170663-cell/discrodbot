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
# not tracker.gg).  We aggregate the player's full current-season competitive
# matches and feed the result into calculate_tracker_score() for the estimated
# TRN score.

def calculate_tracker_score(kdr: float, hs_pct: float, winrate: float, dpr: float = 0) -> int:
    """
    Approximated TRN Performance Score on the official 0-1000 scale.

    The real tracker.gg algorithm is proprietary; this is a weighted heuristic
    of the four signals we can derive (KDR, HS%, Winrate, Damage/Round).  It is
    calibrated against a real reference point:
        KDR 1.24, HS 23.8%, WR 85.7%, DPR 168.3  ->  ~914   (real score: 910)
    Send more (stats -> real score) pairs to refine the weights/anchors.
    """
    # Each signal normalised to 0-1 against a "near-elite" reference value.
    f_kdr = min(max(kdr, 0.0) / 1.5, 1.0)
    f_hs  = min(max(hs_pct, 0.0) / 32.0, 1.0)
    f_wr  = min(max(winrate, 0.0) / 72.0, 1.0)
    # Missing damage -> neutral-average contribution instead of tanking the score.
    f_dpr = min(max(dpr, 0.0) / 170.0, 1.0) if dpr and dpr > 0 else 0.65

    perf = 0.30 * f_kdr + 0.12 * f_hs + 0.25 * f_wr + 0.33 * f_dpr
    return round(min(1000, max(0, 1000 * perf)))


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
      • stored-matches v1 — `stats` is already the queried player; shots.{head,
        body,leg}; damage.made; team "Red"/"Blue"; teams {red,blue} round scores.
      • v4 matches — find the player in `players`; stats.headshots/...; damage.dealt;
        team_id; teams[] with won + rounds{won,lost}.
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
        # stored-matches `tier` is a numeric id → rank name comes from MMR instead
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


# Pagination bounds for full-season aggregation
STORED_PAGE_SIZE   = 20
STORED_MAX_PAGES   = 12
STORED_MAX_MATCHES = 200


def fetch_vtl_profile_sync(name: str, tag: str, max_matches: int = STORED_MAX_MATCHES) -> dict:
    """
    Build a SEASON overview from HenrikDev by aggregating every competitive
    match the player has played in the current act, plus current rank (MMR).

    Walks the stored-matches endpoint page by page, keeping only matches whose
    act matches the most-recent match's act, until the act boundary is crossed
    (or a safety cap is hit).  Falls back to v4 recent matches if stored-matches
    is unavailable.

    Returns {"status": 200, "stats": {...}} or {"status": <code>, "error": ...}.
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

    # 2. Collect current-act competitive matches (paginate stored-matches)
    collected: list = []
    target_season = None
    truncated = False
    used_fallback = False
    first_err = None

    page = 1
    while page <= STORED_MAX_PAGES and len(collected) < max_matches:
        res = _henrik_get(
            f"/valorant/v1/stored-matches/{region}/{enc_name}/{enc_tag}"
            f"?mode=competitive&size={STORED_PAGE_SIZE}&page={page}"
        )
        if not res["ok"]:
            if page == 1:
                first_err = res
                # Auth / rate-limit errors won't be fixed by the v4 fallback
                if res["status"] in (401, 403, 429):
                    return {"status": res["status"], "error": res["error"]}
                used_fallback = True
            break

        data = res["data"] or []
        if isinstance(data, dict):
            data = data.get("matches") or data.get("data") or []
        if not isinstance(data, list) or not data:
            break

        crossed_boundary = False
        for m in data:
            ex = _extract_match(m, puuid, name, tag)
            if ex is None:
                continue
            s = ex["season"]
            if target_season is None and s:
                target_season = s
            if target_season and s and s != target_season:
                crossed_boundary = True   # reached previous act → stop after this page
                continue
            collected.append(ex)
            if len(collected) >= max_matches:
                truncated = True
                break

        if crossed_boundary or truncated or len(data) < STORED_PAGE_SIZE:
            break
        page += 1
    else:
        # loop exhausted pages without hitting the act boundary
        if page > STORED_MAX_PAGES:
            truncated = True

    # 3. Fallback: v4 recent matches if stored-matches gave nothing
    if used_fallback or not collected:
        v4 = _henrik_get(
            f"/valorant/v4/matches/{region}/pc/{enc_name}/{enc_tag}?mode=competitive&size=10"
        )
        if v4["ok"]:
            data = v4["data"] or []
            if isinstance(data, dict):
                data = data.get("matches") or data.get("data") or []
            collected = []
            for m in (data or []):
                ex = _extract_match(m, puuid, name, tag)
                if ex:
                    collected.append(ex)
            used_fallback = True
            target_season = None  # fallback isn't act-filtered

    if not collected:
        if first_err:
            return {"status": first_err["status"], "error": first_err["error"]}
        return {"status": 404, "error": "No competitive matches found for this player."}

    # 4. Aggregate
    tot_k   = sum(m["k"] for m in collected)
    tot_d   = sum(m["d"] for m in collected)
    tot_a   = sum(m["a"] for m in collected)
    tot_hs  = sum(m["hs"] for m in collected)
    tot_body = sum(m["bs"] for m in collected)
    tot_leg = sum(m["ls"] for m in collected)
    tot_score = sum(m["score"] for m in collected)
    tot_dmg = sum(m["damage"] for m in collected)
    tot_rounds = sum(m["rounds"] for m in collected)
    wins   = sum(1 for m in collected if m["won"] is True)
    losses = sum(1 for m in collected if m["won"] is False)
    draws  = sum(1 for m in collected if m["won"] is None)
    counted = len(collected)

    kdr     = tot_k / max(tot_d, 1)
    shots   = tot_hs + tot_body + tot_leg
    hs_pct  = (tot_hs / shots * 100) if shots else 0.0
    decided = wins + losses
    winrate = (wins / decided * 100) if decided else 0.0
    dpr     = (tot_dmg / tot_rounds) if tot_rounds else 0.0
    acs     = (tot_score / tot_rounds) if tot_rounds else 0.0

    # Most-recent match (first collected) supplies fallback rank + last agent
    latest_agent = collected[0].get("agent", "")
    latest_tier  = collected[0].get("tier_name", "")

    # 5. Current rank from MMR (authoritative); fall back to latest match tier
    rank_name = latest_tier or "Unranked"
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
            "season":     target_season or "",
            "is_season":  bool(target_season) and not used_fallback,
            "truncated":  truncated,
        },
    }


async def get_vtl_profile(name: str, tag: str, max_matches: int = STORED_MAX_MATCHES) -> dict:
    """Async wrapper — aggregates the player's current-act matches in a thread."""
    return await asyncio.to_thread(fetch_vtl_profile_sync, name, tag, max_matches)
