import discord
from discord.ext import commands
import random
import asyncio
from utils import (
    async_check_level, async_save_scores, async_grant_daily_booster,
    apply_game_reward, format_booster_gain,
)

# 💡 슬롯머신 심볼별 등장 가중치
SYMBOL_WEIGHTS = {
    'cake': 4,
    'cookie': 6,
    'bread': 8,
    'apple': 12,
    'watermelon': 10,
    'carrot': 14,
    'baked_potato': 16,
    'potato': 18,
    'poison': 12
}


def apply_spin_reward(user_scores: dict, reward: int, *, spin_cost: int = 50, exp_rate: float = 0.02) -> int:
    """Apply minislot reward in the same shared flow as other minigames."""
    user_scores["chips"] = int(user_scores.get("chips", 0) or 0) - spin_cost
    user_scores["chips"] = max(0, user_scores["chips"])
    if reward > 0:
        return apply_game_reward(user_scores, reward, exp_rate=exp_rate)
    return 0


class SlotView(discord.ui.View):
    def __init__(self, user_id, msg):
        super().__init__(timeout=600)
        self.is_roll = False
        self.user_id = user_id
        self.msg = msg
        self.slotmsg = ""
        self.slotmsg2 = ""
        self.auto_spin = False
        self.spin_count = 0
        self.bet = 0

        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id == "share":
                item.disabled = True
                break

    async def _spin_slot(self, interaction: discord.Interaction):
        await interaction.edit_original_response(view=self)
        
        self.slotmsg2 = ""
        slot_value = "<a:slot_rolling:1300138094644953088><a:slot_rolling:1300138094644953088><a:slot_rolling:1300138094644953088>"
        await interaction.edit_original_response(content=slot_value, view=self)
        await asyncio.sleep(1.9)

        # 💡 가중치를 적용하여 3개의 심볼 뽑기
        symbols = list(SYMBOL_WEIGHTS.keys())
        weights = list(SYMBOL_WEIGHTS.values())
        slot_values = random.choices(symbols, weights=weights, k=3)
        
        slot_icons = [self.get_symbol_icon(symbol, index) for index, symbol in enumerate(slot_values)]
        
        slot_value = "".join(slot_icons)
        await interaction.edit_original_response(content=slot_value, view=self)
        await asyncio.sleep(2)

        self.bet, is_sloto = self.calculate_reward(slot_values)

        if is_sloto:
            slot_icons = [self.stop_symbol_icon(symbol, 0) for index, symbol in enumerate(slot_values)]
            if slot_values[0] == slot_values[1] and slot_values[0] == slot_values[2]:
                self.slotmsg2 += "**잭팟!!!**"
                if slot_values[0] == "poison":
                    self.slotmsg2 += " ...아. "

        else:
            if slot_values.count(slot_values[0]) == 2:
                if slot_values.count(slot_values[1]) == 2:
                    slot_icons[0] = self.stop_symbol_icon(slot_values[0], 0)
                    slot_icons[1] = self.stop_symbol_icon(slot_values[1], 0)
                    slot_icons[2] = self.stop_symbol_icon(slot_values[2], 1)
                else:
                    slot_icons[0] = self.stop_symbol_icon(slot_values[0], 0)
                    slot_icons[1] = self.stop_symbol_icon(slot_values[1], 1)
                    slot_icons[2] = self.stop_symbol_icon(slot_values[2], 0)
                
            elif slot_values.count(slot_values[1]) == 2:
                slot_icons[0] = self.stop_symbol_icon(slot_values[0], 1)
                slot_icons[1] = self.stop_symbol_icon(slot_values[1], 0)
                slot_icons[2] = self.stop_symbol_icon(slot_values[2], 0)
            
            else:
                slot_icons[0] = self.stop_symbol_icon(slot_values[0], 1)
                slot_icons[1] = self.stop_symbol_icon(slot_values[1], 1)
                slot_icons[2] = self.stop_symbol_icon(slot_values[2], 1)

        is_sloto = False
        for i in range(3):
            if random.random() < 0.01 and not self.auto_spin:
                if slot_values[i] == 'apple':
                    slot_values[i] = 'golden_apple'
                    slot_icons[i] = '<a:slotg_apple:1300138918095880242>'
                    self.bet += 333
                    is_sloto = True
                elif slot_values[i] == 'watermelon':
                    slot_values[i] = 'golden_watermelon'
                    slot_icons[i] = '<a:slotg_watermelon:1300138951511900211>'
                    self.bet += 333
                    is_sloto = True
                elif slot_values[i] == 'carrot':
                    slot_values[i] = 'golden_carrot'
                    slot_icons[i] = '<a:slotg_carrot:1300138928833036351>'
                    self.bet += 333
                    is_sloto = True
        
        slot_value = "".join(slot_icons)
        await interaction.edit_original_response(content=slot_value, view=self)
        if is_sloto:
            await asyncio.sleep(1.4)
            for i in range(3):
                if slot_values[i] == 'golden_apple':
                    slot_icons[i] = '<a:slotgg_apple:1300139025222336662>'
                elif slot_values[i] == 'golden_watermelon':
                    slot_icons[i] = '<a:slotgg_watermelon:1300139062715482254>'
                elif slot_values[i] == 'golden_carrot':
                    slot_icons[i] = '<a:slotgg_carrot:1300139044453220436>'
            slot_value = "".join(slot_icons)
            self.slotmsg2 += " **황금 과일!**"
        self.slotmsg = slot_value

        user_scores = await async_check_level(self.user_id)
        bonus = apply_spin_reward(user_scores, int(self.bet), spin_cost=50, exp_rate=0.05 if self.auto_spin else 0.02)
        bonus_str = f" (부스터 +{bonus})" if bonus > 0 else ""

        await self.msg.edit(content=f"<@{int(self.user_id)}> 칩 +{self.bet}{bonus_str} (보유 칩: {user_scores['chips']})")
        self.slotmsg2 += f"{self.bet}칩 획득!"
        await async_save_scores(self.user_id, user_scores)

        if not self.auto_spin:
            await asyncio.sleep(1)
            for item in self.children:
                if isinstance(item, discord.ui.Button) and user_scores['chips'] >= 50:
                    item.disabled = False
            await interaction.edit_original_response(view=self)

    def get_symbol_icon(self, symbol, slot_index):
        slot_icons = {
            'cake': ['<a:slot1_cake:1300138335532224674>', '<a:slot2_cake:1300138577757339759>', '<a:slot3_cake:1300138756329967709>'],
            'cookie': ['<a:slot1_cookie:1300138396756344840>', '<a:slot2_cookie:1300138615103557713>', '<a:slot3_cookie:1300138797987659786>'],
            'bread': ['<a:slot1_bread:1300138319598059531>', '<a:slot2_bread:1300138561726582955>', '<a:slot3_bread:1300138740320309248>'],
            'apple': ['<a:slot1_apple:1300138283090575431>', '<a:slot2_apple:1300138503635734600>', '<a:slot3_apple:1300138691120992296>'],
            'watermelon': ['<a:slot1_watermelon:1300138452062441704>', '<a:slot2_watermelon:1300138661861654578>', '<a:slot3_watermelon:1300138887661879346>'],
            'carrot': ['<a:slot1_carrot:1300138382223081562>', '<a:slot2_carrot:1300138593209159854>', '<a:slot3_carrot:1300138775329898538>'],
            'baked_potato': ['<a:slot1_baked_potato:1300138303042883715>', '<a:slot2_baked_potato:1300138542730711060>', '<a:slot3_baked_potato:1300138716781744128>'],
            'potato': ['<a:slot1_potato:1300138428834517004>', '<a:slot2_potato:1300138647470870528>', '<a:slot3_potato:1300138875817037874>'],
            'poison': ['<a:slot1_poison:1300138412015091734>', '<a:slot2_poison:1300138627505848350>', '<a:slot3_poison:1300138813821292708>'],
        }
        return slot_icons[symbol][slot_index]

    def stop_symbol_icon(self, symbol, slot_index):
        slot_icons = {
            'cake': ['<a:sloto_cake:1300139130839367743>','<:slot_cake:1300138205344960523>'],
            'cookie': ['<a:sloto_cookie:1300139166201282622>','<:slot_cookie:1300138224479637566>'],
            'bread': ['<a:sloto_bread:1300139116737990656>','<:slot_bread:1300138195274432593>'],
            'apple': ['<a:sloto_apple:1300139082244165693>','<:slot_apple:1300138174542254132>'],
            'watermelon': ['<a:sloto_watermelon:1300139208991703203>','<:slot_watermelon:1300138265273303201>'],
            'carrot': ['<a:sloto_carrot:1300139151324217354>','<:slot_carrot:1300138214908231771>'],
            'baked_potato': ['<a:sloto_baked_potato:1300139103249240128>','<:slot_baked_potato:1300138185057239182>'],
            'potato': ['<a:sloto_potato:1300139194944978955>','<:slot_potato:1300138247267291186>'],
            'poison': ['<a:sloto_poison:1300139179568791652>','<a:slot_poison:1300138235921432586>'],
        }
        return slot_icons[symbol][slot_index]

    def calculate_reward(self, slot_values):
        category_dict = {
            'cake': 'dessert', 'cookie': 'dessert', 'bread': 'dessert',
            'apple': 'fruit', 'watermelon': 'fruit', 'carrot': 'fruit',
            'baked_potato': 'potato', 'potato': 'potato', 'poison': 'potato'
        }
        categories = [category_dict[icon] for icon in slot_values]
        
        if slot_values.count(slot_values[0]) == 3:
            if slot_values[0] == 'cake': return 999, True
            elif slot_values[0] == 'cookie': return 888, True
            elif slot_values[0] == 'bread': return 777, True
            elif slot_values[0] == 'apple': return 777, True
            elif slot_values[0] == 'watermelon': return 777, True
            elif slot_values[0] == 'carrot': return 777, True
            elif slot_values[0] == 'baked_potato': return 666, True
            elif slot_values[0] == 'potato': return 555, True
            else: return 0, False
        
        elif len(set(categories)) == 1 and len(set(slot_values)) == 3:
            if categories[0] == 'dessert': return 880, True
            elif categories[0] == 'fruit': return 770, True
            else: return 550, True 
        
        elif len(set(categories)) == 1:
            if slot_values.count('cake') == 2: return 660, True
            elif slot_values.count('cookie') == 2: return 550, True
            elif slot_values.count('bread') == 2: return 440, True
            elif slot_values.count('apple') == 2: return 330, True
            elif slot_values.count('watermelon') == 2: return 330, True
            elif slot_values.count('carrot') == 2: return 330, True
            elif slot_values.count('baked_potato') == 2: return 220, True
            elif slot_values.count('potato') == 2: return 110, True
            else: return 0, False

        else:
            return 0, False
    
    @discord.ui.button(custom_id="auto_spin_toggle", label="자동", style=discord.ButtonStyle.secondary)
    async def auto_spin_handle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("본인만 조작할 수 있습니다.", ephemeral=True)
            return
        await async_grant_daily_booster(self.user_id)

        self.auto_spin = not self.auto_spin
        self.spin_count = 0
        
        if self.auto_spin:
            button.style = discord.ButtonStyle.success
            for item in self.children:
                if isinstance(item, discord.ui.Button) and item.custom_id != "auto_spin_toggle":
                    item.disabled = True
            await interaction.response.edit_message(view=self)

            while self.auto_spin and self.spin_count < 77:
                user_scores = await async_check_level(self.user_id)
                if user_scores["chips"] < 50:
                    self.auto_spin = False
                    await interaction.followup.send("힘(재력)이 부족하여 자동 스핀이 중단됩니다.")
                    break
                
                await self._spin_slot(interaction)
                self.spin_count += 1
                button.label = f"자동 ({77-self.spin_count})"
                await interaction.edit_original_response(view=self)
                await asyncio.sleep(2)

            self.auto_spin = False
            button.style = discord.ButtonStyle.secondary
            button.label = f"자동"
            for item in self.children:
                if isinstance(item, discord.ui.Button) and item.custom_id != "auto_spin_toggle":
                    item.disabled = False
            await interaction.edit_original_response(view=self)
        
        else:
            self.auto_spin = False
            button.style = discord.ButtonStyle.secondary
            button.label = f"자동"
            await interaction.response.edit_message(view=self)

    @discord.ui.button(custom_id="action_pull", label="당기기", style=discord.ButtonStyle.primary)
    async def pull_handle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("본인만 조작할 수 있습니다.", ephemeral=True)
            return
        await async_grant_daily_booster(self.user_id)
        
        await interaction.response.defer()
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        await self._spin_slot(interaction)

    @discord.ui.button(custom_id="share", label="자랑하기", style=discord.ButtonStyle.primary)
    async def share(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) == self.user_id:
            await async_grant_daily_booster(self.user_id)
            await interaction.response.defer()
            await interaction.channel.send(f"{self.slotmsg}")
            await interaction.channel.send(f"<@{int(self.user_id)}> {self.slotmsg2}")
            for item in self.children:
                if isinstance(item, discord.ui.Button) and item.custom_id == "share":
                    item.disabled = True
            await interaction.message.edit(view=self)

# --- 메인 명령어 클래스 ---
class MiniSlotCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='미니슬롯')
    @commands.cooldown(1, 600, commands.BucketType.user)
    async def show_slot(self, ctx):
        user_id = str(ctx.author.id)
        booster_result = await async_grant_daily_booster(user_id)
        booster_notice = format_booster_gain(booster_result)
        if booster_notice:
            await ctx.send(f"{ctx.author.mention} {booster_notice}")
        user_scores = await async_check_level(user_id)
        
        if user_scores.get("chips", 0) < 50:
            await ctx.send("(슬롯머신을 돌릴 칩 50개가 없다...)")
            return
            
        msg = await ctx.send(f"{ctx.author.mention} (50 CHIPS PER 1 SPIN)")
        view = SlotView(user_id, msg)
        slot_value = "<a:slot:1300138026243981424><a:slot:1300138026243981424><a:slot:1300138026243981424>"
        await ctx.send(slot_value, view=view)

    @show_slot.error
    async def show_slot_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"동작 그만. 밑장빼기냐? (내 손목을 지키기 위해 {round(error.retry_after, 0)}초 후에 다시 시도하자.)")

async def setup(bot):
    await bot.add_cog(MiniSlotCog(bot))
