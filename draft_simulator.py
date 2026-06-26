import discord
from discord.ui import View, Button, Modal, TextInput
from mlbb_features import mlbb_service

# Define the sequence of turns
# True = Blue Team, False = Red Team
# "Ban" or "Pick"
DRAFT_ORDER = [
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
    def __init__(self, owner_id: int):
        self.owner_id = owner_id
        self.turn_index = 0
        self.blue_bans = []
        self.red_bans = []
        self.blue_picks = []
        self.red_picks = []
        self.is_finished = False

    def get_current_turn(self):
        if self.turn_index >= len(DRAFT_ORDER):
            return None
        return DRAFT_ORDER[self.turn_index]
        
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
        if self.turn_index >= len(DRAFT_ORDER):
            self.is_finished = True

    def generate_embed(self) -> discord.Embed:
        turn = self.get_current_turn()
        
        if self.is_finished:
            title = "🏆 Draft Completed!"
            color = discord.Color.gold()
        else:
            is_blue, phase = turn
            team_name = "Blue Team" if is_blue else "Red Team"
            title = f"Current Turn: {'🔵' if is_blue else '🔴'} {team_name} {phase}"
            color = discord.Color.blue() if is_blue else discord.Color.red()
            
        embed = discord.Embed(title=title, color=color)
        
        # Helper to format lists
        def format_list(items, max_len):
            padded = items + ["-"] * (max_len - len(items))
            return "\n".join(f"{i+1}. {h}" for i, h in enumerate(padded))
            
        embed.add_field(
            name="🔵 Blue Team Bans", 
            value=format_list(self.blue_bans, 3), 
            inline=True
        )
        embed.add_field(
            name="🔴 Red Team Bans", 
            value=format_list(self.red_bans, 3), 
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


class DraftModal(Modal, title='Select Hero'):
    hero_input = TextInput(
        label='Hero Name',
        placeholder='e.g. Fanny, Chou, Miya...',
        required=True
    )

    def __init__(self, view: 'DraftView'):
        super().__init__()
        self.draft_view = view

    async def on_submit(self, interaction: discord.Interaction):
        hero_name = self.hero_input.value
        
        # Validate hero
        hero = mlbb_service.find_hero(hero_name)
        if not hero:
            await interaction.response.send_message(f"❌ Hero '{hero_name}' not found!", ephemeral=True)
            return
            
        real_name = hero.get("hero_name", hero_name)
        
        # Check if already picked/banned
        if self.draft_view.session.is_hero_already_selected(real_name):
            await interaction.response.send_message(f"❌ '{real_name}' has already been banned or picked!", ephemeral=True)
            return

        # Apply selection
        self.draft_view.session.select_hero(real_name)
        
        # Update message
        await self.draft_view.update_message(interaction)


class DraftView(View):
    def __init__(self, session: DraftSession):
        super().__init__(timeout=600) # 10 minute timeout
        self.session = session

    @discord.ui.button(label="Select Hero", style=discord.ButtonStyle.primary, custom_id="draft_select_hero")
    async def select_hero_btn(self, interaction: discord.Interaction, button: Button):
        # Open the modal to type hero name
        await interaction.response.send_modal(DraftModal(self))
        
    @discord.ui.button(label="Cancel Draft", style=discord.ButtonStyle.danger, custom_id="draft_cancel")
    async def cancel_btn(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.session.owner_id and not interaction.permissions.administrator:
            await interaction.response.send_message("Only the person who started the draft or an admin can cancel it.", ephemeral=True)
            return
            
        self.session.is_finished = True
        for child in self.children:
            child.disabled = True
            
        embed = self.session.generate_embed()
        embed.title = "❌ Draft Cancelled"
        embed.color = discord.Color.dark_gray()
        await interaction.response.edit_message(embed=embed, view=self)

    async def update_message(self, interaction: discord.Interaction):
        embed = self.session.generate_embed()
        
        if self.session.is_finished:
            for child in self.children:
                child.disabled = True
                
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message'):
                embed = self.session.generate_embed()
                embed.title = "⏰ Draft Timed Out"
                embed.color = discord.Color.dark_gray()
                await self.message.edit(embed=embed, view=self)
        except Exception:
            pass
