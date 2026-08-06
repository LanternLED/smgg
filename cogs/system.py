import discord
from discord.ext import commands
import asyncio
import re
from datetime import datetime, timedelta

from utils import (
    async_check_level, async_save_scores, async_load_scores, calculate_score,
    async_load_scores_all, CHIP_BUY_RATE, CHIP_SELL_COST,
    async_grant_daily_booster,
)

class SystemCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _grant_daily_booster_if_needed(self, ctx):
        user_id = str(ctx.author.id)
        result = await async_grant_daily_booster(user_id)
        if result is None:
            return None
        gained, user_scores = result
        if gained > 0:
            try:
                await ctx.send(f"{ctx.author.mention} 오늘의 부스터 +{gained} (보유: {user_scores['booster']})")
            except discord.HTTPException:
                pass
        return user_scores

    @commands.command(name='탈퇴')
    async def unregister(self, ctx):
        user_id = str(ctx.author.id)
        user_scores = calculate_score(await async_load_scores(user_id))
        user_scores['active'] = 0
        await ctx.send(f"{ctx.author.mention}님의 이름은 이제 장부에서 제외되었습니다.")
        await async_save_scores(user_id, user_scores)

    @commands.command(name='가입')
    async def register(self, ctx):
        user_id = str(ctx.author.id)
        user_scores = await async_load_scores(user_id)
        user_scores['active'] = 1
        await ctx.send(f"{ctx.author.mention}님, 닉넴빵에 합류하신 것을 환영합니다.")
        await async_save_scores(user_id, user_scores)
        await self._grant_daily_booster_if_needed(ctx)

    @commands.command(name="점수확인")
    async def check_scores_all(self, ctx):
        user_scores = await async_load_scores_all()
        msg = ""
        for user_id in user_scores:
            try:
                user = ctx.guild.get_member(int(user_id))
            except Exception:
                continue
                
            if user is None or user_scores[user_id].get("active", 0) == 0:
                continue
                
            user_name = user.display_name
            user_scores[user_id] = calculate_score(user_scores[user_id])
            current_score = user_scores[user_id]["score"]

            if current_score < 0:
                last_update = datetime.now()
                remaining_hours = abs(current_score)
                restore_time = last_update + timedelta(hours=remaining_hours)
                restore_time_str = restore_time.strftime("%m월 %d일 %H시")
                msg += f"{user_name} : {current_score} ({restore_time_str}까지)\n"
            else:
                msg += f"{user_name} : {current_score}\n"
            await async_save_scores(user_id, user_scores[user_id])
            
        if not msg:
            msg = "활성화된 유저가 없습니다."
        await ctx.send(msg)

    @commands.command(name="점수변동")
    async def change_score(self, ctx, *args):
        if len(args) % 2 != 0:
            await ctx.send("잘못된 주문이십니다... 다시 한 번 확인해 주십시오.")
            return

        msg = ""
        for i in range(0, len(args), 2):
            user_mention = args[i]
            amount = int(args[i + 1])

            m = re.search(r"\d+", user_mention)
            if not m:
                msg += f"{user_mention}님을 찾을 수 없습니다.\n"
                continue
            user_id = m.group(0)
            try:
                user = self.bot.get_user(int(user_id)) or await self.bot.fetch_user(int(user_id))
            except Exception:
                msg += f"{user_mention}님을 찾을 수 없습니다.\n"
                continue
            user_name = user.display_name
            
            user_scores = calculate_score(await async_load_scores(user_id))
            if user_scores.get('active', 0) == 0:
                msg += f"{user_name}님은 닉넴빵에 합류하지 않으셨습니다."
                await ctx.send(msg)
                return
            
            user_scores["score"] += amount
            user_scores["last_update"] = datetime.now().isoformat()
            msg += f"{user_name}님의 점수가 {user_scores['score']}(으)로 변경되었습니다.\n"
            await async_save_scores(user_id, user_scores)
            
        await ctx.send(msg)

    @commands.command(name="공격")
    async def attack(self, ctx, target: discord.Member, amount: int):
        attacker_id = str(ctx.author.id)
        attacker_score = calculate_score(await async_load_scores(attacker_id))
        attacker_name = ctx.author.display_name
        
        target_id = str(target.id)
        target_score = calculate_score(await async_load_scores(target_id))
        target_name = target.display_name

        if not attacker_score.get('active', 0):
            await ctx.send(f"{attacker_name}님을 찾을 수 없습니다.")
            return
        elif not target_score.get('active', 0):
            await ctx.send(f"{target_name}님은 닉넴빵에 합류하지 않으셨습니다.")
            return
            
        if attacker_score['score'] < amount:
            await ctx.send(f"{attacker_name}님의 시간이 부족합니다. 현재 보유 시간: {attacker_score['score']}")
            return
        if target_score['score'] - int(amount // 2) <= -10000:
            await ctx.send(f"{target_name}님은 이미 **닉넴불량자**입니다.")
            return
            
        attacker_score["score"] -= amount
        target_score["score"] -= int(amount // 2)

        now = datetime.now().isoformat()
        attacker_score["last_update"] = now
        target_score["last_update"] = now

        await async_save_scores(attacker_id, attacker_score)
        await async_save_scores(target_id, target_score)

        msg = (f"{attacker_name}님이 {amount}점을 소모하여 ")
        msg += (f"{target_name}님의 시간을 {amount // 2}만큼 감소시켰습니다!\n")
        msg += (f"{attacker_name}님의 점수가 {attacker_score['score']}(으)로,\n")
        msg += (f"{target_name}님의 점수가 {target_score['score']}(으)로 변경되었습니다.")
        await ctx.send(msg)

    @commands.command(name="내정보")
    async def info_self(self, ctx):
        user_id = str(ctx.author.id)
        try:
            await self._grant_daily_booster_if_needed(ctx)
            user_scores = await async_load_scores(user_id)
        except Exception as exc:
            print(f"info_self failed: {exc}")
            user_scores = {}

        user_scores.setdefault('level', 0)
        user_scores.setdefault('exp', 0)
        user_scores.setdefault('chips', 0)
        user_scores.setdefault('booster', 0)
        user_scores.setdefault('score', 0)

        lv = int(user_scores['level'])
        exp = int(user_scores['exp'])
        max_exp = int(pow(1.01, lv) * 1000)
        percent = round(exp / max_exp * 100, min(lv // 232 + 1, 5)) if max_exp else 0
        booster = int(user_scores.get('booster', 0))
        chips = int(user_scores.get('chips', 0))
        msg = f"{ctx.author.mention} Lv.{lv} ({percent}%) / 칩 보유: {chips} / 부스터: {booster}"
        await ctx.send(msg)

    @commands.command(name="남의정보")
    async def info_other(self, ctx, member: discord.Member):
        user_id = str(member.id)
        try:
            await self._grant_daily_booster_if_needed(ctx)
            user_scores = await async_load_scores(user_id)
        except Exception as exc:
            print(f"info_other failed: {exc}")
            user_scores = {}

        user_scores.setdefault('level', 0)
        user_scores.setdefault('exp', 0)
        user_scores.setdefault('chips', 0)
        user_scores.setdefault('booster', 0)
        user_scores.setdefault('score', 0)

        lv = int(user_scores['level'])
        exp = int(user_scores['exp'])
        max_exp = int(pow(1.01, lv) * 1000)
        percent = round(exp / max_exp * 100, min(lv // 232 + 1, 5)) if max_exp else 0
        booster = int(user_scores.get('booster', 0))
        chips = int(user_scores.get('chips', 0))
        msg = f"{member.display_name} Lv.{lv} ({percent}%) / 칩 보유: {chips} / 부스터: {booster}"
        await ctx.send(msg)

    @commands.command(name='칩구매')
    async def buy_chips(self, ctx, score: int = 0):
        user_id = str(ctx.author.id)
        user_scores = await async_check_level(user_id)
        
        if score < 0:
            await ctx.send("손님, 시간을 양수로 적어주십시오.")
            return

        if score == 0:
            score = max(0, user_scores["score"])

        if score <= 0:
            await ctx.send("구매에 사용할 보유 시간이 부족합니다.")
            return

        if user_scores["score"] < score:
            await ctx.send("죄송하지만 손님께서는 점수가 부족하십니다.")
            return

        chip = score * CHIP_BUY_RATE
        user_scores["score"] -= score
        user_scores["chips"] += int(chip)
        user_scores['exp'] += int(chip * 0.01)
        await ctx.send(f"{score}시간으로 {int(chip)}칩을 구매하셨습니다.")
        await async_save_scores(user_id, user_scores)

    @commands.command(name='칩판매')
    async def sell_chips(self, ctx, chip: int = 0):
        user_id = str(ctx.author.id)
        user_scores = await async_check_level(user_id)
        
        if chip < 0:
            await ctx.send("손님, 칩을 양수로 적어주십시오.")
            return

        if chip == 0:
            chip = user_scores.get("chips", 0)

        if chip < CHIP_SELL_COST:
            await ctx.send(f"칩이 부족합니다. 최소 {CHIP_SELL_COST}칩이 필요합니다.")
            return

        if user_scores.get("chips", 0) < chip:
            await ctx.send("죄송하지만 손님께서는 칩이 부족하십니다.")
            return

        cost = CHIP_SELL_COST
        sold_chip = 0
        score = 0
        while chip - sold_chip >= cost:
            user_scores["chips"] -= cost
            user_scores["score"] += 1
            sold_chip += cost
            score += 1

        await ctx.send(f"{sold_chip}칩으로 {score}시간을 구매하셨습니다.")
        await async_save_scores(user_id, user_scores)

async def setup(bot):
    await bot.add_cog(SystemCog(bot))