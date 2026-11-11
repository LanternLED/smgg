"""일일 부스터 [얻기] 버튼과 티켓제 미니슬롯.

흐름
1. 명령의 응답이나 게임 결과가 나온 뒤 send_daily_notice()가 안내 메시지를 보낸다
   (1분 뒤 자동 삭제). 메시지에는 한 번만 누를 수 있는 [얻기] 버튼이 붙는다.
2. [얻기]를 누르면 미니슬롯 세션이 열린다. 첫 판은 수동(당기기)으로 굴리고,
   이후 남은 티켓은 자동 버튼 하나로만 소진한다.
3. 자동을 멈추면(또는 끝나면) 다시 켤 수 없다. 남은 티켓은 DB에 보관된다.
4. 3분 동안 아무 조작이 없으면 세션 메시지를 삭제한다.

티켓 1장의 기대값은 TICKET_BASE_REWARD + 배당 기대값 * TICKET_PRIZE_MULTIPLIER 이다.
(현재 값 기준 약 1,000 부스터. 배당 편차를 줄이려면 TICKET_PRIZE_MULTIPLIER를
낮추고 TICKET_BASE_REWARD를 올려 합이 1,000 근처가 되게 맞출 것.)
"""
import asyncio
import logging
import random
import time

import discord

from utils import (
    async_load_scores, format_booster_gain, update_user, _coerce_int,
)

logger = logging.getLogger(__name__)

# ── 조정용 상수 ─────────────────────────────────────────────────
NOTICE_SECONDS = 60          # 일일 부스터 안내(+[얻기]) 메시지 유지 시간
IDLE_SECONDS = 180           # 미니슬롯 세션 방치 시 삭제까지의 시간
TICKET_BASE_REWARD = 600     # 미당첨이어도 받는 기본 부스터
TICKET_PRIZE_MULTIPLIER = 7.8  # 배당(110~999)에 곱하는 배수
GOLDEN_FRUIT_CHANCE = 0.01   # 수동 판에서만 심볼당 황금 과일 확률
GOLDEN_FRUIT_PRIZE = 333     # 황금 과일 1개당 추가 배당(배수 적용 전)

SYMBOL_WEIGHTS = {
    'cake': 4,
    'cookie': 6,
    'bread': 8,
    'apple': 12,
    'watermelon': 10,
    'carrot': 14,
    'baked_potato': 16,
    'potato': 18,
    'poison': 12,
}

CATEGORY = {
    'cake': 'dessert', 'cookie': 'dessert', 'bread': 'dessert',
    'apple': 'fruit', 'watermelon': 'fruit', 'carrot': 'fruit',
    'baked_potato': 'potato', 'potato': 'potato', 'poison': 'potato',
}

TRIPLE_PRIZE = {
    'cake': 999, 'cookie': 888, 'bread': 777, 'apple': 777,
    'watermelon': 777, 'carrot': 777, 'baked_potato': 666, 'potato': 555,
}
CATEGORY_TRIPLE_PRIZE = {'dessert': 880, 'fruit': 770, 'potato': 550}
PAIR_PRIZE = {
    'cake': 660, 'cookie': 550, 'bread': 440, 'apple': 330,
    'watermelon': 330, 'carrot': 330, 'baked_potato': 220, 'potato': 110,
}

SLOT_IDLE = "<a:slot:1300138026243981424>"
SLOT_ROLLING = "<a:slot_rolling:1300138094644953088>"

GOLDEN_ICON = {
    'apple': ('golden_apple', '<a:slotg_apple:1300138918095880242>', '<a:slotgg_apple:1300139025222336662>'),
    'watermelon': ('golden_watermelon', '<a:slotg_watermelon:1300138951511900211>', '<a:slotgg_watermelon:1300139062715482254>'),
    'carrot': ('golden_carrot', '<a:slotg_carrot:1300138928833036351>', '<a:slotgg_carrot:1300139044453220436>'),
}

# 심볼별 이모지: [1번 칸, 2번 칸, 3번 칸] 롤링 애니메이션
ROLL_ICONS = {
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

# 심볼별 이모지: [당첨(움직임), 비당첨(정지)]
STOP_ICONS = {
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


def calculate_prize(slot_values: list[str]) -> int:
    """심볼 3개의 배당(배수 적용 전). 당첨이 아니면 0."""
    categories = [CATEGORY[s] for s in slot_values]
    if slot_values.count(slot_values[0]) == 3:
        return TRIPLE_PRIZE.get(slot_values[0], 0)
    if len(set(categories)) == 1 and len(set(slot_values)) == 3:
        return CATEGORY_TRIPLE_PRIZE[categories[0]]
    if len(set(categories)) == 1:
        for symbol, prize in PAIR_PRIZE.items():
            if slot_values.count(symbol) == 2:
                return prize
    return 0


def ticket_reward(prize: int) -> int:
    """배당을 부스터 지급액으로 환산한다. 미당첨(prize=0)도 기본금을 받는다."""
    return TICKET_BASE_REWARD + int(prize * TICKET_PRIZE_MULTIPLIER)


class MiniSlotSession(discord.ui.View):
    """티켓제 미니슬롯 세션. 첫 판 수동, 이후 자동 버튼 하나."""

    def __init__(self, user_id: str, tickets: int):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.tickets_at_start = tickets
        self.tickets_remaining = tickets
        self.message: discord.Message | None = None
        self.result_message: discord.Message | None = None
        self.running = False
        self.manual_done = False
        self.auto_started = False
        self.auto_stop = False
        self.finished = False
        self._last_active = time.monotonic()
        self._idle_task: asyncio.Task | None = None

        self.pull_button = discord.ui.Button(label="당기기", style=discord.ButtonStyle.primary)
        self.pull_button.callback = self.on_pull
        self.auto_button = discord.ui.Button(label="자동", style=discord.ButtonStyle.secondary)
        self.auto_button.callback = self.on_auto
        self.add_item(self.pull_button)

    # ── 수명 관리 ────────────────────────────────────────────────
    def _touch(self) -> None:
        self._last_active = time.monotonic()

    async def start(self, channel) -> None:
        self.message = await channel.send(
            SLOT_IDLE * 3,
            view=self,
        )
        self._idle_task = asyncio.create_task(self._watch_idle())

    async def _watch_idle(self) -> None:
        try:
            while not self.finished:
                idle_for = time.monotonic() - self._last_active
                if not self.running and idle_for >= IDLE_SECONDS:
                    break
                wait = 5.0 if self.running else max(1.0, IDLE_SECONDS - idle_for)
                await asyncio.sleep(wait)
        except asyncio.CancelledError:
            return
        await self._delete()

    async def _delete(self) -> None:
        self.finished = True
        self.stop()
        if self.message is None:
            return
        try:
            await self.message.delete()
        except discord.NotFound:
            pass
        except discord.HTTPException:
            logger.exception("미니슬롯 세션 삭제 실패 (user_id=%s)", self.user_id)
        if self.result_message is not None:
            try:
                await self.result_message.delete()
            except discord.NotFound:
                pass
            except discord.HTTPException:
                logger.exception("미니슬롯 결과 삭제 실패 (user_id=%s)", self.user_id)

    async def _is_owner(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) == self.user_id:
            return True
        await interaction.response.send_message("본인만 조작할 수 있습니다.", ephemeral=True)
        return False

    # ── 한 판 ───────────────────────────────────────────────────
    async def _spin(self, *, manual: bool):
        """한 판을 굴리고 정산한다. 티켓이 없으면 None.

        결과를 먼저 뽑고 연출한 뒤, 연출이 끝나면 한 트랜잭션으로 티켓 차감과 지급을
        한 번에 처리한다. (연출 도중 오류가 나도 티켓은 사라지지 않는다.)
        """
        assert self.message is not None
        fast = not manual

        await self.message.edit(content=SLOT_ROLLING * 3, view=self)
        await asyncio.sleep(1.0 if fast else 1.9)

        symbols = list(SYMBOL_WEIGHTS.keys())
        weights = list(SYMBOL_WEIGHTS.values())
        slot_values = random.choices(symbols, weights=weights, k=3)

        rolled = [ROLL_ICONS[s][i] for i, s in enumerate(slot_values)]
        await self.message.edit(content="".join(rolled), view=self)
        await asyncio.sleep(1.0 if fast else 2.0)

        prize = calculate_prize(slot_values)
        won = prize > 0
        icons = [STOP_ICONS[s][0 if won else 1] for s in slot_values]
        note = ""
        if won and slot_values.count(slot_values[0]) == 3:
            note = "**잭팟!!!** "

        golden_hit = False
        if manual:
            for i in range(3):
                kind = GOLDEN_ICON.get(slot_values[i])
                if kind is not None and random.random() < GOLDEN_FRUIT_CHANCE:
                    slot_values[i] = kind[0]
                    icons[i] = kind[1]
                    prize += GOLDEN_FRUIT_PRIZE
                    golden_hit = True

        await self.message.edit(content="".join(icons), view=self)
        if golden_hit:
            await asyncio.sleep(1.4)
            for i in range(3):
                for kind in GOLDEN_ICON.values():
                    if slot_values[i] == kind[0]:
                        icons[i] = kind[2]
            note += "**황금 과일!** "
            await self.message.edit(content="".join(icons), view=self)

        reward = ticket_reward(prize)

        def settle(user_scores):
            tickets = _coerce_int(user_scores.get("slot_ticket"), 0)
            if tickets <= 0:
                return None
            user_scores["slot_ticket"] = tickets - 1
            user_scores["booster"] = _coerce_int(user_scores.get("booster"), 0) + reward
            return tickets - 1

        user_scores, left = await update_user(self.user_id, settle)
        if left is None:
            return None
        self.tickets_remaining = left
        result_content = (
            f"{note}부스터 **+{reward:,}** (보유: {user_scores['booster']:,})"
        )
        if self.result_message is None:
            self.result_message = await self.message.channel.send(result_content)
        else:
            await self.result_message.edit(content=result_content)
        return reward, left

    # ── 버튼 ────────────────────────────────────────────────────
    async def on_pull(self, interaction: discord.Interaction) -> None:
        if not await self._is_owner(interaction):
            return
        if self.running or self.manual_done:
            await interaction.response.defer()
            return
        self.running = True
        self.manual_done = True
        self._touch()
        self.remove_item(self.pull_button)
        await interaction.response.edit_message(view=self)
        left = 0
        try:
            result = await self._spin(manual=True)
            if result is not None:
                left = result[1]
        except discord.NotFound:
            self.finished = True
            self.stop()
            return
        except discord.HTTPException:
            logger.exception("미니슬롯 수동 판 진행 오류 (user_id=%s)", self.user_id)
        finally:
            self.running = False
            self._touch()

        if left > 0:
            self.auto_button.label = f"자동 ({left:,})"
            self.add_item(self.auto_button)
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            logger.exception("미니슬롯 자동 버튼 표시 오류 (user_id=%s)", self.user_id)

    async def on_auto(self, interaction: discord.Interaction) -> None:
        if not await self._is_owner(interaction):
            return
        if self.running:
            # 자동 진행 중 다시 누르면 중지 요청
            self.auto_stop = True
            await interaction.response.defer()
            return
        if self.auto_started:
            await interaction.response.defer()
            return

        self.auto_started = True
        self.running = True
        self.auto_stop = False
        self._touch()
        self.auto_button.label = "중지"
        self.auto_button.style = discord.ButtonStyle.danger
        await interaction.response.edit_message(view=self)
        try:
            while not self.auto_stop:
                result = await self._spin(manual=False)
                self._touch()
                if result is None or result[1] <= 0:
                    break
                await asyncio.sleep(0.8)
        except discord.NotFound:
            self.finished = True
            self.stop()
            return
        except discord.HTTPException:
            logger.exception("미니슬롯 자동 진행 오류 (user_id=%s)", self.user_id)
        finally:
            self.running = False
            self._touch()

        # 멈춘 경우 남은 티켓 수를 표시하되, 자동 진행은 다시 시작할 수 없다.
        if self.auto_stop and self.tickets_remaining > 0:
            self.auto_button.label = f"자동 ({self.tickets_remaining:,})"
            self.auto_button.style = discord.ButtonStyle.secondary
            self.auto_button.disabled = True
        else:
            self.remove_item(self.auto_button)
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            logger.exception("미니슬롯 종료 처리 오류 (user_id=%s)", self.user_id)


class DailyClaimView(discord.ui.View):
    """일일 부스터 안내 메시지에 붙는 1회용 [얻기] 버튼."""

    def __init__(self, user_id: str):
        super().__init__(timeout=NOTICE_SECONDS)
        self.user_id = str(user_id)
        self.claimed = False

    @discord.ui.button(label="얻기", style=discord.ButtonStyle.success)
    async def claim(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("본인만 조작할 수 있습니다.", ephemeral=True)
            return
        if self.claimed:
            await interaction.response.defer()
            return
        self.claimed = True
        self.remove_item(_button)
        self.stop()
        await interaction.response.delete_message()

        user_scores = await async_load_scores(self.user_id)
        tickets = _coerce_int(user_scores.get("slot_ticket"), 0)
        if tickets <= 0:
            await interaction.followup.send("사용할 미니슬롯 티켓이 없습니다.", ephemeral=True)
            return
        session = MiniSlotSession(self.user_id, tickets)
        await session.start(interaction.channel)


async def send_daily_notice(ctx, result) -> None:
    """일일 부스터 지급 결과 안내(+[얻기] 버튼). 지급이 없었으면 아무것도 보내지 않는다."""
    notice = format_booster_gain(result)
    if not notice:
        return
    try:
        await ctx.send(
            notice,
            view=DailyClaimView(str(ctx.author.id)),
            delete_after=NOTICE_SECONDS,
        )
    except discord.HTTPException:
        logger.exception("일일 부스터 안내 전송 실패 (user_id=%s)", ctx.author.id)
