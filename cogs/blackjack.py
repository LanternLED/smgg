import discord
from discord.ext import commands
import random
import asyncio
import os
import json
from utils import (
    async_check_level, async_save_scores, async_grant_daily_booster,
    apply_game_reward,
)

active_blackjack_games = {}
blackjack_data = {"deck": []}
DECK_FILE = "blackjack_deck.json"

async def async_load_deck():
    global blackjack_data
    if os.path.exists(DECK_FILE):
        with open(DECK_FILE, "r", encoding="utf-8") as f:
            blackjack_data = json.load(f)

async def async_save_deck():
    with open(DECK_FILE, "w", encoding="utf-8") as f:
        json.dump(blackjack_data, f, ensure_ascii=False)

def create_deck():
    suits = ['♠', '♥', '♦', '♣']
    values = list(range(1, 14))
    deck = [[value, suit] for value in values for suit in suits] * 8
    return deck

def card_value_to_string(value):
    return {1: 'A', 11: 'J', 12: 'Q', 13: 'K'}.get(value, str(value))

def format_card(card):
    value, suit = card
    return f"{card_value_to_string(value)}{suit}"

def calculate_hand_value(hand):
    value = 0
    aces = 0
    for card in hand:
        if card[0] == 1:
            aces += 1
            value += 11
        else:
            value += min(card[0], 10)
    while value > 21 and aces:
        value -= 10
        aces -= 1
    return value

class BlackjackGame:
    def __init__(self, user_id, bet, deck):
        self.user_id = user_id
        self.bet = bet
        self.deck = deck
        self.player_cards = [self.deck.pop(), self.deck.pop()]
        self.dealer_cards = [self.deck.pop(), self.deck.pop()]
        self.player_stood = False

    def player_total(self):
        return calculate_hand_value(self.player_cards)

    def dealer_total(self):
        return calculate_hand_value(self.dealer_cards)

    def player_double_down(self):
        self.bet *= 2
        card = self.deck.pop()
        self.player_cards.append(card)
        if self.player_total() > 21:
            self.bet *= -1
        self.player_stood = True
        return card
    
    def player_hit(self):
        card = self.deck.pop()
        self.player_cards.append(card)
        total = self.player_total()
        if total >= 21:
            if total > 21:
                self.bet *= -1
            self.player_stood = True
        return card

    def player_stand(self):
        self.player_stood = True

    def dealer_hit(self):
        card = self.deck.pop()
        self.dealer_cards.append(card)
        return card, self.dealer_total()

class BlackjackView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=None)
        self.game = game

    def make_embed(self, user_scores: dict):
        player_str = " ".join(format_card(card) for card in self.game.player_cards)
        dealer_first = format_card(self.game.dealer_cards[0])
        deck_count = len(self.game.deck)
        embed = discord.Embed(title="블랙잭", description=f"베팅: {self.game.bet}칩 | 덱 남음: {deck_count}")
        embed.add_field(name="플레이어", value=f"{player_str}\n합: {self.game.player_total()}", inline=False)
        embed.add_field(name="딜러(공개)", value=f"[{dealer_first}, ??]", inline=False)
        return embed

    @discord.ui.button(custom_id="action_double_down", label="더블 다운", style=discord.ButtonStyle.primary)
    async def double_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) == self.game.user_id:
            await async_grant_daily_booster(self.game.user_id)
            self.game.player_double_down()
            await interaction.response.defer()
            user_scores = await async_check_level(self.game.user_id)
            embed = self.make_embed(user_scores)
            self.clear_items()
            await interaction.message.edit(embed=embed, view=self)
            self.stop()

    @discord.ui.button(custom_id="action_hit", label="히트", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) == self.game.user_id:
            await async_grant_daily_booster(self.game.user_id)
            self.game.player_hit()
            await interaction.response.defer()
            for child in self.children:
                if child.custom_id == "action_double_down":
                    child.disabled = True
            user_scores = await async_check_level(self.game.user_id)
            embed = self.make_embed(user_scores)
            
            if self.game.player_total() >= 21:
                self.clear_items()
            await interaction.message.edit(embed=embed, view=self)
            
            if self.game.player_total() >= 21:
                self.stop()

    @discord.ui.button(custom_id="action_stand", label="스탠드", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) == self.game.user_id:
            await async_grant_daily_booster(self.game.user_id)
            self.game.player_stand()
            await interaction.response.defer()
            user_scores = await async_check_level(self.game.user_id)
            embed = self.make_embed(user_scores)
            self.clear_items()
            await interaction.message.edit(embed=embed, view=self)
            self.stop()

class BlackjackCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(name='블랙잭판엎기')
    async def blackjack_shuffle(self, ctx):
        await async_grant_daily_booster(str(ctx.author.id))
        await async_load_deck()
        blackjack_data["deck"] = create_deck()
        await ctx.send("손님...! 이러시면 안됩니다...!\n카드가 다 쏟아졌으니, 덱을 새로 준비해드리는게 낫겠습니다...")
        random.shuffle(blackjack_data["deck"])
        await async_save_deck()

    @commands.command(name='블랙잭')
    async def blackjack(self, ctx, bet: int = 500):
        await async_load_deck()
        user_id = str(ctx.author.id)
        await async_grant_daily_booster(user_id)
        if user_id in active_blackjack_games:
            await ctx.send("이미 진행 중인 블랙잭 게임이 있습니다.")
            return
        
        active_blackjack_games[user_id] = True
        
        try:
            user_scores = await async_check_level(user_id)
        
            if len(blackjack_data.get("deck", [])) <= 104:
                blackjack_data["deck"] = create_deck()
                await ctx.send("새로운 덱으로 준비해 드리지요...")
                random.shuffle(blackjack_data["deck"])
                await async_save_deck()
                
            deck = blackjack_data["deck"]
            
            if user_scores.get("chips", 0) < bet:
                await ctx.send(f"죄송합니다, {ctx.author.display_name}님. 가지고 계신 칩의 개수가 부족합니다.\n매일 첫 활동으로 지급되는 부스터를 활용해 보세요.")
                return
            elif bet > 500:
                await ctx.send("최대 배팅은 칩 500개입니다.")
                return
            elif bet < 1:
                await ctx.send("칩을... 걸어주십시오.")
                return
        
            game = BlackjackGame(user_id, bet, deck)
            view = BlackjackView(game)
            user_scores = await async_check_level(user_id)
            embed = view.make_embed(user_scores)
            msg = await ctx.send(embed=embed, view=view)
            
            await asyncio.sleep(0.5)
            while not game.player_stood:
                await view.wait()
                await asyncio.sleep(0.2)

            if game.player_total() <= 21:
                await asyncio.sleep(0.4)
                while game.dealer_total() < 17:
                    game.dealer_hit()
                    user_scores = await async_check_level(user_id)
                    await msg.edit(embed=view.make_embed(user_scores), view=None)
                    await asyncio.sleep(0.6)

            msg2_value = ""

            is_player_natural = (game.player_total() == 21 and len(game.player_cards) == 2)
            is_dealer_natural = (game.dealer_total() == 21 and len(game.dealer_cards) == 2)

            if is_player_natural and not is_dealer_natural:
                msg2_value = "블랙잭! 1.5배의 배당금을 받습니다."
                game.bet = int(game.bet * 1.5)
            elif game.dealer_total() > 21:
                msg2_value = "딜러가 버스트했습니다. 승리하셨습니다."
            elif game.dealer_total() == game.player_total():
                if is_dealer_natural and not is_player_natural:
                    msg2_value = "딜러의 블랙잭! 패배하셨습니다."
                    game.bet *= -1
                else:
                    msg2_value = "무승부입니다."
                    game.bet = 0
            elif game.dealer_total() > game.player_total():
                msg2_value = "딜러가 합이 더 크므로, 패배하셨습니다."
                game.bet *= -1
            else:
                msg2_value = "손님의 합이 더 크므로, 승리하셨습니다."

            if game.bet >= 0:
                bonus = apply_game_reward(user_scores, int(abs(game.bet)), exp_rate=0.05)
                bonus_str = f" (부스터 +{bonus})" if bonus > 0 else ""
                msg2_value += f"\n칩 +{game.bet}{bonus_str} (보유 칩: {user_scores['chips']})"
            else:
                msg2_value += f"\n칩 {game.bet} (보유 칩: {user_scores['chips']})"

            final_embed = discord.Embed(title="블랙잭 결과", description=msg2_value)
            final_embed.add_field(name="플레이어 최종", value=f"{' '.join(format_card(card) for card in game.player_cards)} (합: {game.player_total()})", inline=False)
            final_embed.add_field(name="딜러 최종", value=f"{' '.join(format_card(card) for card in game.dealer_cards)} (합: {game.dealer_total()})", inline=False)
            await msg.edit(embed=final_embed, view=None)
            
            await async_save_scores(user_id, user_scores)
            await async_save_deck()
            
        finally:
            active_blackjack_games.pop(user_id, None)

async def setup(bot):
    await bot.add_cog(BlackjackCog(bot))