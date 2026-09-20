import discord
from discord.ext import commands
import asyncio
import logging
import random
from slot_engine import SlotEngine
from utils import (
    async_load_scores, async_save_scores, async_grant_daily_booster,
    apply_game_reward, format_booster_gain, get_user_lock,
)

logger = logging.getLogger(__name__)

# --- 이모지 설정 ---
SLOT_INIT = "<a:slot:1300138026243981424>"
SLOT_ROLLING = "<a:slot_rolling:1300138094644953088>"

ANIMATED_ICONS = {
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

STATIC_ICONS = {
    'cake': '<:slot_cake:1300138205344960523>',
    'cookie': '<:slot_cookie:1300138224479637566>',
    'bread': '<:slot_bread:1300138195274432593>',
    'apple': '<:slot_apple:1300138174542254132>',
    'watermelon': '<:slot_watermelon:1300138265273303201>',
    'carrot': '<:slot_carrot:1300138214908231771>',
    'baked_potato': '<:slot_baked_potato:1300138185057239182>',
    'potato': '<:slot_potato:1300138247267291186>',
    'poison': '<a:slot_poison:1300138235921432586>',
}

# 당첨(또는 버스트) 라인에 속한 칸에 쓰는 번쩍이는 애니메이션 이모지
WINNING_ICONS = {
    'cake': '<a:sloto_cake:1300139130839367743>',
    'cookie': '<a:sloto_cookie:1300139166201282622>',
    'bread': '<a:sloto_bread:1300139116737990656>',
    'apple': '<a:sloto_apple:1300139082244165693>',
    'watermelon': '<a:sloto_watermelon:1300139208991703203>',
    'carrot': '<a:sloto_carrot:1300139151324217354>',
    'baked_potato': '<a:sloto_baked_potato:1300139103249240128>',
    'potato': '<a:sloto_potato:1300139194944978955>',
    'poison': '<a:sloto_poison:1300139179568791652>',
}

GOLDEN_EMOJIS = {
    'apple': {
        'initial': '<a:slotg_apple:1300138918095880242>',
        'final': '<a:slotgg_apple:1300139025222336662>'
    },
    'watermelon': {
        'initial': '<a:slotg_watermelon:1300138951511900211>',
        'final': '<a:slotgg_watermelon:1300139062715482254>'
    },
    'carrot': {
        'initial': '<a:slotg_carrot:1300138928833036351>',
        'final': '<a:slotgg_carrot:1300139044453220436>'
    }
}

# --- 렌더링 함수 ---
def render_board_animated(board):
    """15칸 각각에 1, 2, 3번 타이밍 GIF를 무작위로 할당"""
    lines = []
    for r in range(3):
        res = ""
        for c in range(5):
            sym = board[r][c].symbol
            res += ANIMATED_ICONS[sym][random.choice([0, 1, 2])]
        lines.append(res)
    return "\n".join(lines)

def render_board_static(
    board,
    winning_positions=None,
    golden_variant='final',
    animated_positions=None,
):
    """최종 완전히 정지된 상태 (황금 과일, 당첨 라인 번쩍임 포함)

    winning_positions: [(r, c), ...] — 이 좌표들은 골든이 아닌 한 WINNING_ICONS로 렌더링됨.
    황금(is_golden)이 최우선이고, 그다음이 당첨 라인 번쩍임, 마지막이 기본 정지 아이콘.
    golden_variant: 'initial' 또는 'final'로 황금 과일의 애니메이션 단계를 선택한다.
    """
    winning_set = set(winning_positions) if winning_positions else set()
    animated_set = set(animated_positions) if animated_positions else set()
    lines = []
    for r in range(3):
        res = ""
        for c, cell in enumerate(board[r]):
            if cell.is_golden and cell.symbol in GOLDEN_EMOJIS:
                variant_map = GOLDEN_EMOJIS[cell.symbol]
                res += variant_map.get(golden_variant, variant_map['final'])
            elif (r, c) in animated_set:
                res += ANIMATED_ICONS[cell.symbol][random.choice([0, 1, 2])]
            elif (r, c) in winning_set:
                res += WINNING_ICONS[cell.symbol]
            else:
                res += STATIC_ICONS[cell.symbol]
        lines.append(res)
    return "\n".join(lines)


class SlotView(discord.ui.View):
    def __init__(self, user_id, slot_msg=None):
        super().__init__(timeout=600)
        self.user_id = str(user_id)
        self.slot_msg = slot_msg  # 점보지용 대형 보드 메시지
        self.is_rolling = False
        self.slotmsg = ""
        self.slotmsg2 = ""
        self.control_msg = None  # on_timeout에서 버튼을 비활성화하기 위해 컨트롤 메시지를 기억해둠

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.control_msg is not None:
            try:
                await self.control_msg.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(custom_id="action_pull", label="당기기", style=discord.ButtonStyle.primary)
    async def pull_handle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("본인만 조작할 수 있습니다.", ephemeral=True)
            return
        await async_grant_daily_booster(self.user_id)

        if self.is_rolling:
            # 이미 굴러가는 중 — 조용히 무시하지 않고 상호작용에는 응답해서
            # 디스코드 클라이언트에 "상호작용 실패"가 뜨지 않게 한다.
            if not interaction.response.is_done():
                await interaction.response.defer()
            return

        self.is_rolling = True

        await interaction.response.defer()

        button.disabled = True
        await interaction.message.edit(view=self)

        try:
            user_scores = await async_load_scores(self.user_id)
            if int(user_scores.get("chips", 0) or 0) < 1000:
                button.disabled = False
                await interaction.message.edit(view=self)
                await interaction.followup.send(
                    "다시 돌리려면 칩 1,000개가 필요합니다.",
                    ephemeral=True,
                )
                return

            engine = SlotEngine()
            engine.generate_board()

            # 단계 1: 전체 슬롯이 팽팽 돌기 시작 (API Edit #1)
            rolling_board = "\n".join([SLOT_ROLLING * 5] * 3)
            await self.slot_msg.edit(content=rolling_board)
            await asyncio.sleep(1.0)

            # 단계 2: 심볼별로 1~3번 타임차가 적용된 애니메이션으로 전환 (API Edit #2)
            await self.slot_msg.edit(content=render_board_animated(engine.board))
            await asyncio.sleep(2.0)  # 가장 긴 3번 애니메이션 종료 대기

            # 단계 3: 황금 연쇄 발생 시 미니슬롯처럼 초기/최종 두 단계로 애니메이션 표시
            golden_frames = engine.trigger_golden()
            if golden_frames:
                for frame in golden_frames:
                    await self.slot_msg.edit(content=render_board_static(frame, golden_variant='initial'))
                    await asyncio.sleep(0.7)
                    animated_positions = [
                        (r, c)
                        for r, row in enumerate(frame)
                        for c, cell in enumerate(row)
                        if cell.symbol not in GOLDEN_EMOJIS
                    ]
                    if animated_positions:
                        await self.slot_msg.edit(
                            content=render_board_static(
                                frame,
                                golden_variant='final',
                                animated_positions=animated_positions,
                            )
                        )
                        await asyncio.sleep(0.7)

            # 단계 4: 결과 계산 후, 당첨(또는 버스트) 라인을 강조한 최종 화면 적용 (API Edit #3)
            reward, details = engine.calculate_reward()
            final_board_text = render_board_static(engine.board, winning_positions=engine.winning_positions)
            await self.slot_msg.edit(content=final_board_text)

            # load → 수정 → save 구간은 다른 커맨드(예: 칩판매)와
            # 동시에 실행되면 서로의 변경을 덮어쓸 수 있으므로 락으로 보호한다.
            async with get_user_lock(self.user_id):
                user_scores = await async_load_scores(self.user_id)
                user_scores["chips"] = int(user_scores.get("chips", 0) or 0) - 1000
                user_scores["chips"] = max(0, user_scores["chips"])

                if reward > 0:
                    bonus = apply_game_reward(user_scores, reward, exp_rate=0.02)
                else:
                    bonus = 0

                await async_save_scores(self.user_id, user_scores)

            if reward > 0:
                if details:
                    summary = " / ".join(details[:3])
                    if len(details) > 3:
                        summary += " / ..."
                    result_text = f"🎉 **총 {reward:,} 칩 획득!** | {summary}"
                else:
                    result_text = f"🎉 **총 {reward:,} 칩 획득!**"
                if bonus > 0:
                    result_text += f" | ⚡ 부스터 +{bonus:,}"
            elif details:
                result_text = "☠️ 독!감!자! (당신은 버스트했다.)"
            else:
                result_text = "💥 꽝"
            result_text += f" | 보유 칩: {user_scores['chips']:,}"

            self.slotmsg = final_board_text
            self.slotmsg2 = result_text

            pull_button = next(
                (item for item in self.children
                 if getattr(item, "custom_id", None) == "action_pull"),
                None,
            )
            if pull_button is not None:
                pull_button.label = "다시 돌리기"
                pull_button.disabled = user_scores["chips"] < 1000
            if not any(
                getattr(item, "custom_id", None) == "share"
                for item in self.children
            ):
                share_button = discord.ui.Button(
                    custom_id="share", label="자랑하기", style=discord.ButtonStyle.primary
                )
                share_button.callback = self.share
                self.add_item(share_button)

            await interaction.message.edit(content=f"<@{self.user_id}>\n{result_text}", view=self)

        except discord.NotFound:
            pass
        except discord.HTTPException:
            logger.exception("슬롯 진행 중 디스코드 API 오류 발생 (user_id=%s)", self.user_id)
            try:
                await interaction.followup.send(
                    "슬롯 진행 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                pass
        except Exception:
            logger.exception("슬롯 진행 중 예상치 못한 오류 발생 (user_id=%s)", self.user_id)
            try:
                await interaction.followup.send(
                    "알 수 없는 오류가 발생했습니다. 관리자에게 문의해주세요.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                pass
        finally:
            self.is_rolling = False

    async def share(self, interaction: discord.Interaction):
        if str(interaction.user.id) == self.user_id:
            await async_grant_daily_booster(self.user_id)
            await interaction.response.defer()
            await interaction.channel.send(f"{self.slotmsg}")
            await interaction.channel.send(f"<@{int(self.user_id)}> {self.slotmsg2}")

            for item in self.children:
                if isinstance(item, discord.ui.Button) and item.custom_id == "share":
                    item.disabled = True
            await interaction.message.edit(view=self)


class SlotCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='슬롯')
    async def show_slot_v2(self, ctx):
        booster_result = await async_grant_daily_booster(str(ctx.author.id))
        booster_notice = format_booster_gain(booster_result)
        if booster_notice:
            await ctx.send(f"{ctx.author.mention} {booster_notice}")
        user_scores = await async_load_scores(str(ctx.author.id))
        chips = int(user_scores.get("chips", 0) or 0)
        if chips < 1000:
            await ctx.send(f"{ctx.author.mention} 칩이 부족합니다. 슬롯을 시작하려면 최소 1,000칩이 필요합니다. (보유: {chips}칩)")
            return

        init_board = "\n".join([SLOT_INIT * 5] * 3)

        # 1. 텍스트 없는 pure 이모지 메시지 (3x5 점보지 크기)
        slot_msg = await ctx.send(init_board)

        # 2. 하단 멘션 및 버튼 컨트롤 메시지
        view = SlotView(ctx.author.id, slot_msg=slot_msg)
        control_msg = await ctx.send(f"{ctx.author.mention} **1,000 CHIPS BET!**", view=view)
        view.control_msg = control_msg

    @show_slot_v2.error
    async def show_slot_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            minutes = int(error.retry_after // 60)
            seconds = int(error.retry_after % 60)
            message = f"⚠️ ({minutes}분 {seconds}초 후 가능)"
            try:
                await ctx.send(message, delete_after=5, ephemeral=True)
            except TypeError:
                try:
                    await ctx.send(message, delete_after=5)
                except discord.Forbidden:
                    pass
            except discord.Forbidden:
                pass


async def setup(bot):
    await bot.add_cog(SlotCog(bot))