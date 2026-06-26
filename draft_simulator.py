import discord
from discord.ui import View, Button, Select
from mlbb_features import mlbb_service
import math

def get_draft_order(rank="epic"):
    rank = rank.lower()
    if rank == "mythic":
        return [
            (True, "Ban 1"), (False, "Ban 1"),
            (True, "Ban 2"), (False, "Ban 2"),
            (True, "Ban 3"), (False, "Ban 3"),
            (True, "Pick 1"), (False, "Pick 1"),
            (False, "Pick 2"), (True, "Pick 2"),
            (True, "Pick 3"), (False, "Pick 3"),
            (False, "Ban 4"), (True, "Ban 4"),
            (False, "Ban 5"), (True, "Ban 5"),
            (False, "Pick 4"), (True, "Pick 4"),
            (True, "Pick 5"), (False, "Pick 5")
        ]
    elif rank == "legend":
        return [
            (True, "Ban 1"), (False, "Ban 1"),
            (True, "Ban 2"), (False, "Ban 2"),
            (True, "Pick 1"), (False, "Pick 1"),
            (False, "Pick 2"), (True, "Pick 2"),
            (True, "Pick 3"), (False, "Pick 3"),
            (False, "Ban 3"), (True, "Ban 3"),
            (False, "Ban 4"), (True, "Ban 4"),
            (False, "Pick 4"), (True, "Pick 4"),
            (True, "Pick 5"), (False, "Pick 5")
        ]
    else: # Epic
        return [
            (True, "Ban 1"), (False, "Ban 1"),
            (True, "Ban 2"), (False, "Ban 2"),
            (True, "Ban 3"), (False, "Ban 3"),
            (True, "Pick 1"), (False, "Pick 1"),
            (False, "Pick 2"), (True, "Pick 2"),
            (True, "Pick 3"), (False, "Pick 3"),
            (False, "Pick 4"), (True, "Pick 4"),
            (True, "Pick 5"), (False, "Pick 5")
        ]

class DraftSession:
    def __init__(self, owner_id: int, rank: str = "epic"):
        self.owner_id = owner_id
        self.rank = rank.lower()
        self.order = get_draft_order(self.rank)
        self.turn_index = 0
        self.blue_bans = []
        self.red_bans = []
        self.blue_picks = []
        self.red_picks = []
        self.is_finished = False

        if self.rank == "mythic":
            self.max_bans = 5
        elif self.rank == "legend":
            self.max_bans = 4
        else:
            self.max_bans = 3

    def get_current_turn(self):
        if self.turn_index >= len(self.order):
            return None
        return self.order[self.turn_index]
        
    def is_hero_already_selected(self, hero_name: str) -> bool:
        name = hero_name.lower()
        all_selected = [h.lower() for h in (self.blue_bans + self.red_bans + self.blue_picks + self.red_picks)]
        return name in all_selected

    def select_hero(self, hero_name: str):
        turn = self.get_current_turn()
        if not turn:
            return
            
        is_blue, phase = turn
        if "Ban" in phase:
            if is_blue:
                self.blue_bans.append(hero_name)
            else:
                self.red_bans.append(hero_name)
        else:
            if is_blue:
                self.blue_picks.append(hero_name)
            else:
                self.red_picks.append(hero_name)
                
        self.turn_index += 1
        if self.turn_index >= len(self.order):
            self.is_finished = True

    def generate_embed(self) -> discord.Embed:
        turn = self.get_current_turn()
        
        if self.is_finished:
            title = "🏆 Draft Completed!"
            color = discord.Color.gold()
        else:
            is_blue, phase = turn
            team_name = "Blue Team" if is_blue else "Red Team"
            title = f"[{self.rank.title()}] Current Turn: {'🔵' if is_blue else '🔴'} {team_name} {phase}"
            color = discord.Color.blue() if is_blue else discord.Color.red()
            
        embed = discord.Embed(title=title, color=color)
        
        # Helper to format lists
        def format_list(items, max_len):
            padded = items + ["-"] * (max_len - len(items))
            return "\n".join(f"{i+1}. {h}" for i, h in enumerate(padded))
            
        embed.add_field(
            name="🔵 Blue Team Bans", 
            value=format_list(self.blue_bans, self.max_bans), 
            inline=True
        )
        embed.add_field(
            name="🔴 Red Team Bans", 
            value=format_list(self.red_bans, self.max_bans), 
            inline=True
        )
        embed.add_field(name="\u200b", value="\u200b", inline=False) # Spacer
        
        embed.add_field(
            name="🔵 Blue Team Picks", 
            value=format_list(self.blue_picks, 5), 
            inline=True
        )
        embed.add_field(
            name="🔴 Red Team Picks", 
            value=format_list(self.red_picks, 5), 
            inline=True
        )
        
        return embed

class HeroSelect(Select):
    def __init__(self, page_heroes, current_page, total_pages):
        options = [discord.SelectOption(label=hero) for hero in page_heroes]
        super().__init__(
            placeholder=f"Select Hero (Page {current_page}/{total_pages})...", 
            options=options, 
            custom_id=f"draft_hero_select_{current_page}"
        )

    async def callback(self, interaction: discord.Interaction):
        hero_name = self.values[0]
        view: 'DraftView' = self.view
        
        if view.session.is_hero_already_selected(hero_name):
            await interaction.response.send_message(f"❌ '{hero_name}' has already been banned or picked!", ephemeral=True)
            return

        view.session.select_hero(hero_name)
        await view.update_message(interaction)

class DraftView(View):
    def __init__(self, session: DraftSession):
        super().__init__(timeout=600)
        self.session = session
        self.all_heroes = mlbb_service.get_all_hero_names()
        
        self.items_per_page = 25
        self.total_pages = max(1, math.ceil(len(self.all_heroes) / self.items_per_page))
        self.current_page = 1
        
        self.rebuild_components()

    def rebuild_components(self):
        self.clear_items()
        
        if self.session.is_finished:
            return

        # 1. Add Select Menu
        start_idx = (self.current_page - 1) * self.items_per_page
        end_idx = start_idx + self.items_per_page
        page_heroes = self.all_heroes[start_idx:end_idx]
        
        if page_heroes:
            self.add_item(HeroSelect(page_heroes, self.current_page, self.total_pages))
            
        # 2. Add Navigation Buttons
        prev_btn = Button(label="⬅️ Prev", style=discord.ButtonStyle.secondary, custom_id="draft_prev")
        prev_btn.callback = self.on_prev
        self.add_item(prev_btn)
        
        next_btn = Button(label="Next ➡️", style=discord.ButtonStyle.secondary, custom_id="draft_next")
        next_btn.callback = self.on_next
        self.add_item(next_btn)
        
        cancel_btn = Button(label="Cancel Draft", style=discord.ButtonStyle.danger, custom_id="draft_cancel")
        cancel_btn.callback = self.on_cancel
        self.add_item(cancel_btn)

    async def on_prev(self, interaction: discord.Interaction):
        self.current_page = (self.current_page - 2) % self.total_pages + 1
        self.rebuild_components()
        await interaction.response.edit_message(view=self)

    async def on_next(self, interaction: discord.Interaction):
        self.current_page = (self.current_page) % self.total_pages + 1
        self.rebuild_components()
        await interaction.response.edit_message(view=self)

    async def on_cancel(self, interaction: discord.Interaction):
        if interaction.user.id != self.session.owner_id and not interaction.permissions.administrator:
            await interaction.response.send_message("Only the person who started the draft or an admin can cancel it.", ephemeral=True)
            return
            
        self.session.is_finished = True
        self.clear_items()
        
        embed = self.session.generate_embed()
        embed.title = "❌ Draft Cancelled"
        embed.color = discord.Color.dark_gray()
        await interaction.response.edit_message(embed=embed, view=self)

    async def update_message(self, interaction: discord.Interaction):
        self.rebuild_components()
        embed = self.session.generate_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        self.clear_items()
        try:
            if hasattr(self, 'message'):
                embed = self.session.generate_embed()
                embed.title = "⏰ Draft Timed Out"
                embed.color = discord.Color.dark_gray()
                await self.message.edit(embed=embed, view=self)
        except Exception:
            pass
