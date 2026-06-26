import json
import logging
import urllib.request
import asyncio
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MLBB_API_URL = "https://raw.githubusercontent.com/p3hndrx/MLBB-API/main/v1/hero-meta-final.json"

class MLBBService:
    def __init__(self):
        self.heroes: Dict[str, dict] = {}
        self._data_loaded = False

    async def fetch_data(self):
        """Fetch the hero meta JSON asynchronously from GitHub"""
        if self._data_loaded:
            return

        def download():
            req = urllib.request.Request(MLBB_API_URL, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode())
        
        try:
            logger.info("Fetching MLBB meta data...")
            data = await asyncio.to_thread(download)
            if "data" in data:
                # Store heroes in a dictionary keyed by lowercase name for easy lookup
                for hero in data["data"]:
                    # Skip empty/null entries
                    if hero.get("hero_name", "None").lower() != "none" and hero.get("mlid"):
                        self.heroes[hero["hero_name"].lower()] = hero
                self._data_loaded = True
                logger.info(f"Successfully loaded {len(self.heroes)} MLBB heroes.")
            else:
                logger.error("Failed to parse MLBB data: 'data' key not found.")
        except Exception as e:
            logger.error(f"Error fetching MLBB data: {e}")

    def find_hero(self, query: str) -> Optional[dict]:
        """Find a hero by exact or partial name match"""
        if not self._data_loaded:
            return None
        
        query = query.lower().strip()
        
        # 1. Exact match
        if query in self.heroes:
            return self.heroes[query]
            
        # 2. Partial match
        matches = [h for name, h in self.heroes.items() if query in name]
        if len(matches) == 1:
            return matches[0]
            
        # Return exact prefix match if multiple
        for h in matches:
            if h["hero_name"].lower().startswith(query):
                return h
                
        return None

    def get_all_hero_names(self) -> List[str]:
        """Returns a sorted list of all hero names"""
        if not self._data_loaded:
            return []
        return sorted([hero.get("hero_name") for hero in self.heroes.values() if hero.get("hero_name")])

    def get_heroes_by_lane(self, lane: str) -> List[dict]:
        """Get all heroes that can play a specific lane"""
        lane = lane.lower().strip()
        matched_heroes = []
        for hero in self.heroes.values():
            lanes = [l.lower() for l in hero.get("laning", [])]
            if any(lane in l for l in lanes):
                matched_heroes.append(hero)
        return matched_heroes

    def recommend_draft(self, lane: str, enemy_heroes: List[str]) -> List[dict]:
        """
        Provide draft recommendations for a lane based on countering enemies.
        Returns a sorted list of heroes based on counter score.
        """
        lane_heroes = self.get_heroes_by_lane(lane)
        if not lane_heroes:
            return []
            
        # Resolve enemy hero names to their IDs or exact names
        resolved_enemies = []
        for eh in enemy_heroes:
            hero = self.find_hero(eh)
            if hero:
                resolved_enemies.append(hero)
                
        if not resolved_enemies:
            # If no valid enemies provided, just return top 5 heroes for that lane arbitrarily
            return lane_heroes[:5]

        # Calculate scores
        scores = []
        for hero in lane_heroes:
            score = 0
            counters = [c.get("heroname", "").lower() for c in hero.get("counters", [])]
            
            for enemy in resolved_enemies:
                enemy_name = enemy["hero_name"].lower()
                if enemy_name in counters:
                    score += 20 # +20 score if it counters the enemy (inspired by MetaForge)
            
            scores.append((score, hero))
            
        # Sort by score descending
        scores.sort(key=lambda x: x[0], reverse=True)
        
        # Return top 5 recommendations
        return [item[1] for item in scores[:5] if item[0] >= 0] # Filter if you only want ones with positive scores, or just top 5

# Global singleton
mlbb_service = MLBBService()
