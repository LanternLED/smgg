import discord
from discord.ext import commands
import re
from datetime import datetime, timedelta

from daily_claim import send_daily_notice
from utils import (
    async_load_scores, calculate_score, async_load_scores_all, CHIP_BUY_RATE,
    CHIP_SELL_COST, async_grant_daily_booster, update_user, update_users,
    refresh_scores, level_progress, ADMIN_USER_ID,
)

class SystemCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _grant_daily_booster_if_needed(self, ctx):
        user_id = str(ctx.author.id)
        return await async_grant_daily_booster(user_id)

    @commands.command(name='탈퇴')
    async def unregister(self, ctx):
        user_id = str(ctx.author.id)
        await update_user(
            user_id, lambda s: (calculate_score(s), s.__setitem__('active', 0))
        )
        await ctx.send(f"{ctx.author.mention}님의 이름은 이제 장부에서 제외되었습니다.")

    @commands.command(name='가입')
    async def register(self, ctx):
        user_id = str(ctx.author.id)
        await update_user(user_id, lambda s: s.__setitem__('active', 1))
        await ctx.send(f"{ctx.author.mention}님, 닉넴빵에 합류하신 것을 환영합니다.")
        booster_result = await self._grant_daily_booster_if_needed(ctx)
        await send_daily_notice(ctx, booster_result)

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
            user_scores[user_id], _ = await update_user(user_id, calculate_score)
            current_score = user_scores[user_id]["score"]

            if current_score < 0:
                last_update = datetime.now()
                remaining_hours = abs(current_score)
                restore_time = last_update + timedelta(hours=remaining_hours)
                restore_time_str = restore_time.strftime("%m월 %d일 %H시")
                msg += f"{user_name} : {current_score} ({restore_time_str}까지)\n"
            else:
                msg += f"{user_name} : {current_score}\n"

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
            
            def apply_change(user_scores, amount=amount):
                calculate_score(user_scores)
                if user_scores.get('active', 0) == 0:
                    return False
                user_scores["score"] += amount
                user_scores["last_update"] = datetime.now().isoformat()
                return True

            user_scores, applied = await update_user(user_id, apply_change)
            if not applied:
                msg += f"{user_name}님은 닉넴빵에 합류하지 않으셨습니다."
                await ctx.send(msg)
                return

            msg += f"{user_name}님의 점수가 {user_scores['score']}(으)로 변경되었습니다.\n"
            
        await ctx.send(msg)

    @commands.command(name="공격")
    async def attack(self, ctx, target: discord.Member, amount: int):
        attacker_id = str(ctx.author.id)
        attacker_name = ctx.author.display_name
        target_id = str(target.id)
        target_name = target.display_name

        def resolve_attack(states):
            attacker_score = calculate_score(states[attacker_id])
            target_score = calculate_score(states[target_id])
            if not attacker_score.get('active', 0):
                return "no_attacker"
            if not target_score.get('active', 0):
                return "no_target"
            if attacker_score['score'] < amount:
                return "no_time"
            if target_score['score'] - int(amount // 2) <= -10000:
                return "bad_target"
            attacker_score["score"] -= amount
            target_score["score"] -= int(amount // 2)
            now = datetime.now().isoformat()
            attacker_score["last_update"] = now
            target_score["last_update"] = now
            return "ok"

        # 두 유저의 점수 확인과 차감을 한 트랜잭션으로 처리한다.
        states, status = await update_users([attacker_id, target_id], resolve_attack)
        attacker_score = states[attacker_id]
        target_score = states[target_id]

        if status == "no_attacker":
            await ctx.send(f"{attacker_name}님을 찾을 수 없습니다.")
            return
        if status == "no_target":
            await ctx.send(f"{target_name}님은 닉넴빵에 합류하지 않으셨습니다.")
            return
        if status == "no_time":
            await ctx.send(f"{attacker_name}님의 시간이 부족합니다. 현재 보유 시간: {attacker_score['score']}")
            return
        if status == "bad_target":
            await ctx.send(f"{target_name}님은 이미 **닉넴불량자**입니다.")
            return

        msg = (f"{attacker_name}님이 {amount}점을 소모하여 ")
        msg += (f"{target_name}님의 시간을 {amount // 2}만큼 감소시켰습니다!\n")
        msg += (f"{attacker_name}님의 점수가 {attacker_score['score']}(으)로,\n")
        msg += (f"{target_name}님의 점수가 {target_score['score']}(으)로 변경되었습니다.")
        await ctx.send(msg)

    @commands.command(name="내정보", aliases=["출석"])
    async def info_self(self, ctx):
        user_id = str(ctx.author.id)
        booster_result = None
        try:
            booster_result = await self._grant_daily_booster_if_needed(ctx)
            user_scores = await async_load_scores(user_id)
        except Exception as exc:
            await ctx.send(f"정보를 불러오지 못했습니다. 잠시 후 다시 시도해주세요. (오류: {type(exc).__name__})")
            await send_daily_notice(ctx, booster_result)
            return

        user_scores.setdefault('level', 0)
        user_scores.setdefault('exp', 0)
        user_scores.setdefault('chips', 0)
        user_scores.setdefault('booster', 0)
        user_scores.setdefault('score', 0)

        lv, percent = level_progress(user_scores)
        booster = int(user_scores.get('booster', 0))
        chips = int(user_scores.get('chips', 0))
        msg = f"{ctx.author.mention} Lv.{lv} ({percent}%) / 칩 보유: {chips} / 부스터: {booster}"
        await ctx.send(msg)
        await send_daily_notice(ctx, booster_result)

    @commands.command(name="남의정보")
    async def info_other(self, ctx, member: discord.Member):
        user_id = str(member.id)
        booster_result = None
        try:
            booster_result = await self._grant_daily_booster_if_needed(ctx)
            user_scores = await async_load_scores(user_id)
        except Exception as exc:
            await ctx.send(f"정보를 불러오지 못했습니다. 잠시 후 다시 시도해주세요. (오류: {type(exc).__name__})")
            await send_daily_notice(ctx, booster_result)
            return

        user_scores.setdefault('level', 0)
        user_scores.setdefault('exp', 0)
        user_scores.setdefault('chips', 0)
        user_scores.setdefault('booster', 0)
        user_scores.setdefault('score', 0)

        lv, percent = level_progress(user_scores)
        booster = int(user_scores.get('booster', 0))
        chips = int(user_scores.get('chips', 0))
        msg = f"{member.display_name} Lv.{lv} ({percent}%) / 칩 보유: {chips} / 부스터: {booster}"
        await ctx.send(msg)
        await send_daily_notice(ctx, booster_result)

    @commands.command(name="시간여행")
    async def time_travel(self, ctx):
        if ctx.author.id != ADMIN_USER_ID:
            await ctx.send("관리자 전용 명령어입니다.")
            return

        def travel(user_scores):
            last_attendance = user_scores.get("daily_update")
            if not isinstance(last_attendance, str):
                return None
            try:
                last_date = datetime.fromisoformat(last_attendance).date()
            except ValueError:
                return None

            shifted_date = last_date - timedelta(days=1)
            deduction = 2000 + user_scores["level"]
            user_scores["daily_update"] = shifted_date.isoformat()
            user_scores["chips"] -= deduction
            return last_date, shifted_date, deduction

        user_scores, result = await update_user(str(ctx.author.id), travel)
        if result is None:
            await ctx.send("저장된 출석 날짜를 확인할 수 없어 시간여행을 실행하지 못했습니다.")
            return

        last_date, shifted_date, deduction = result
        await ctx.send(
            f"{ctx.author.mention} 출석일을 {last_date.isoformat()}에서 "
            f"{shifted_date.isoformat()}으로 변경하고 칩 {deduction:,}개를 차감했습니다. "
            f"(보유: {user_scores['chips']:,})"
        )

    @commands.command(name='칩구매')
    async def buy_chips(self, ctx, score: int = 0):
        user_id = str(ctx.author.id)

        if score < 0:
            await ctx.send("손님, 시간을 양수로 적어주십시오.")
            return

        def buy(user_scores):
            refresh_scores(user_scores)
            amount = score if score != 0 else max(0, user_scores["score"])
            if amount <= 0:
                return "empty", 0, 0
            if user_scores["score"] < amount:
                return "short", 0, 0
            chip = int(amount * CHIP_BUY_RATE)
            user_scores["score"] -= amount
            user_scores["chips"] += chip
            user_scores['exp'] += int(chip * 0.01)
            return "ok", amount, chip

        # 점수 확인과 교환을 한 트랜잭션으로 처리해 중복 구매(칩 복사)를 막는다.
        _, (status, amount, chip) = await update_user(user_id, buy)

        if status == "empty":
            await ctx.send("구매에 사용할 보유 시간이 부족합니다.")
            return
        if status == "short":
            await ctx.send("죄송하지만 손님께서는 점수가 부족하십니다.")
            return
        await ctx.send(f"{amount}시간으로 {chip}칩을 구매하셨습니다.")

    @commands.command(name='칩판매')
    async def sell_chips(self, ctx, chip: int = 0):
        user_id = str(ctx.author.id)

        if chip < 0:
            await ctx.send("손님, 칩을 양수로 적어주십시오.")
            return

        def sell(user_scores):
            refresh_scores(user_scores)
            wanted = chip if chip != 0 else user_scores.get("chips", 0)
            if wanted < CHIP_SELL_COST:
                return "min", 0, 0
            if user_scores.get("chips", 0) < wanted:
                return "short", 0, 0
            hours = wanted // CHIP_SELL_COST
            sold_chip = hours * CHIP_SELL_COST
            user_scores["chips"] -= sold_chip
            user_scores["score"] += hours
            return "ok", sold_chip, hours

        # 칩 확인과 교환을 한 트랜잭션으로 처리해 중복 판매(시간 복사)를 막는다.
        _, (status, sold_chip, hours) = await update_user(user_id, sell)

        if status == "min":
            await ctx.send(f"칩이 부족합니다. 최소 {CHIP_SELL_COST}칩이 필요합니다.")
            return
        if status == "short":
            await ctx.send("죄송하지만 손님께서는 칩이 부족하십니다.")
            return
        await ctx.send(f"{sold_chip}칩으로 {hours}시간을 구매하셨습니다.")

async def setup(bot):
    await bot.add_cog(SystemCog(bot))