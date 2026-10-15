import asyncio
import hashlib
import logging
import math
import random
import re
import sqlite3
import unicodedata

import discord
from discord.ext import commands

from utils import (
    apply_game_reward,
    async_check_level,
    async_grant_daily_booster,
    async_save_scores,
    format_booster_gain,
    get_db_connection,
    get_user_lock,
)

DICTIONARY_DB_PATH = "dictionary.db"
TYPING_TIMEOUT_SECONDS = 60
TYPING_MARKERS = ("§", "※", "◆", "◇", "★", "☆", "♠", "♣", "♥", "♦")
ESCAPE_MESSAGE = "무한타자연습에서 탈출했습니다."
logger = logging.getLogger(__name__)
active_typing_sessions: set[str] = set()
typing_escape_events: dict[str, asyncio.Event] = {}


def ensure_typing_column():
    conn = get_db_connection()
    try:
        columns = conn.execute("PRAGMA table_info(user)").fetchall()
        if not any(column["name"] == "typing" for column in columns):
            conn.execute(
                "ALTER TABLE user ADD COLUMN typing INTEGER NOT NULL DEFAULT 0"
            )
        conn.commit()
    finally:
        conn.close()


def load_example_ids() -> tuple[int, ...]:
    conn = sqlite3.connect(DICTIONARY_DB_PATH)
    try:
        rows = conn.execute(
            "SELECT id FROM examples "
            "WHERE example IS NOT NULL AND length(trim(example)) > 0 "
            "ORDER BY id"
        ).fetchall()
        example_ids = tuple(int(row[0]) for row in rows)
    finally:
        conn.close()

    if not example_ids:
        raise RuntimeError("dictionary.db의 examples 테이블에 예문이 없습니다.")
    return example_ids


def get_user_permutation_params(user_id: str, count: int) -> tuple[int, int]:
    if count == 1:
        return 1, 0

    digest = hashlib.sha256(f"typing:{user_id}".encode("ascii")).digest()
    multiplier = int.from_bytes(digest[:16], "big") % count or 1
    while math.gcd(multiplier, count) != 1:
        multiplier = (multiplier + 1) % count or 1
    offset = int.from_bytes(digest[16:], "big") % count
    return multiplier, offset


def get_example_id(user_id: str, progress: int, example_ids: tuple[int, ...]) -> int:
    multiplier, offset = get_user_permutation_params(user_id, len(example_ids))
    index = (multiplier * (progress % len(example_ids)) + offset) % len(example_ids)
    return example_ids[index]


def load_example(example_id: int) -> str:
    conn = sqlite3.connect(DICTIONARY_DB_PATH)
    try:
        row = conn.execute(
            "SELECT example FROM examples WHERE id = ?", (example_id,)
        ).fetchone()
    finally:
        conn.close()

    if row is None or not isinstance(row[0], str) or not row[0].strip():
        raise ValueError(f"예문 ID {example_id}의 내용이 비어 있거나 없습니다.")
    return row[0]


def join_parts(*parts: str) -> str:
    return "\n\n".join(part for part in parts if part)


def normalize_typing_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", normalized).strip()


def insert_typing_markers(text: str) -> str:
    """예문에 특수기호를 삽입한다. 기본 1개 + 10글자마다 1개씩 추가."""
    markers = tuple(marker for marker in TYPING_MARKERS if marker not in text)
    if not markers:
        markers = tuple(
            chr(codepoint)
            for codepoint in range(0x2600, 0x2800)
            if unicodedata.category(chr(codepoint)).startswith("S")
            and chr(codepoint) not in text
        )
    markers = markers or TYPING_MARKERS

    marker_count = min(1 + len(text) // 10, len(text) + 1)
    # 뒤에서부터 끼워 넣어야 앞쪽 삽입 위치가 밀리지 않는다.
    positions = sorted(random.sample(range(len(text) + 1), marker_count), reverse=True)
    for position in positions:
        text = f"{text[:position]}{random.choice(markers)}{text[position:]}"
    return text


def typing_edit_distance(left: str, right: str) -> int:
    """자모 단위 편집 거리 (Damerau-Levenshtein, OSA 방식).

    오타(치환), 추가 입력(삽입), 누락(삭제), 인접한 자모의 순서 바뀜(전위)을
    각각 1로 센다.
    """
    left = unicodedata.normalize("NFD", left)
    right = unicodedata.normalize("NFD", right)

    two_rows_ago: list[int] | None = None
    previous_row = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current_row = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            substitution_cost = 0 if left_char == right_char else 1
            best = min(
                previous_row[right_index] + 1,
                current_row[right_index - 1] + 1,
                previous_row[right_index - 1] + substitution_cost,
            )
            if (
                two_rows_ago is not None
                and left_index > 1
                and right_index > 1
                and left_char == right[right_index - 2]
                and left[left_index - 2] == right_char
            ):
                best = min(best, two_rows_ago[right_index - 2] + 1)
            current_row.append(best)
        two_rows_ago, previous_row = previous_row, current_row
    return previous_row[-1]


class TypingGameCog(commands.Cog):
    def __init__(self, bot: commands.Bot, example_ids: tuple[int, ...]):
        self.bot = bot
        self.example_ids = example_ids

    @commands.command(name="타자연습", aliases=["타자"])
    async def typing_game(self, ctx: commands.Context):
        await self._run_typing_game(ctx, infinite=False)

    @commands.command(name="무한타자", aliases=["무한타자연습"])
    async def infinite_typing_game(self, ctx: commands.Context):
        await self._run_typing_game(ctx, infinite=True)

    def request_escape(self, user_id: str) -> bool:
        escape_event = typing_escape_events.get(user_id)
        if escape_event is None or escape_event.is_set():
            return False
        escape_event.set()
        return True

    async def _run_typing_game(self, ctx: commands.Context, *, infinite: bool):
        user_id = str(ctx.author.id)
        if user_id in active_typing_sessions:
            await ctx.send("진행 중인 타자연습을 먼저 마쳐주세요.", delete_after=5)
            return
        active_typing_sessions.add(user_id)
        escape_event = asyncio.Event() if infinite else None
        if escape_event is not None:
            typing_escape_events[user_id] = escape_event
        session_message = None
        last_result = ""
        try:
            booster_result = await async_grant_daily_booster(user_id)
            booster_notice = format_booster_gain(booster_result)
            if booster_notice:
                await ctx.send(f"{ctx.author.mention} {booster_notice}")
            session_message = await ctx.send("타자연습을 준비 중입니다...")

            allowed_mentions = discord.AllowedMentions(
                users=[ctx.author],
                roles=False,
                everyone=False,
            )

            def is_answer(message: discord.Message) -> bool:
                return (
                    message.author.id == ctx.author.id
                    and message.channel.id == ctx.channel.id
                    and not message.content.startswith(ctx.prefix)
                )

            example_offset = 0
            accuracy_sum = 0.0
            accuracy_count = 0
            while True:
                if escape_event is not None and escape_event.is_set():
                    await session_message.edit(
                        content=join_parts(last_result, ESCAPE_MESSAGE),
                        allowed_mentions=allowed_mentions,
                    )
                    return
                user_scores = await async_check_level(user_id)
                progress = int(user_scores.get("typing", 0) or 0)
                example_id = get_example_id(
                    user_id,
                    progress + example_offset,
                    self.example_ids,
                )
                example = await asyncio.to_thread(load_example, example_id)
                target = normalize_typing_text(example)
                if not target:
                    raise ValueError(f"예문 ID {example_id}의 내용이 비어 있습니다.")

                marked_example = insert_typing_markers(target)
                prompt = (
                    f"{ctx.author.mention} 아래 문장을 입력하세요. "
                    f"(제한 시간 {TYPING_TIMEOUT_SECONDS}초, "
                    "삽입된 특수기호는 입력하지 마세요.)\n"
                    f"> {marked_example}"
                )
                await session_message.edit(
                    content=join_parts(last_result, prompt),
                    allowed_mentions=allowed_mentions,
                )

                try:
                    if escape_event is None:
                        answer_message = await self.bot.wait_for(
                            "message",
                            timeout=TYPING_TIMEOUT_SECONDS,
                            check=is_answer,
                        )
                    else:
                        answer_task = asyncio.create_task(
                            self.bot.wait_for(
                                "message",
                                timeout=TYPING_TIMEOUT_SECONDS,
                                check=is_answer,
                            )
                        )
                        escape_task = asyncio.create_task(escape_event.wait())
                        done, pending = await asyncio.wait(
                            (answer_task, escape_task),
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        for task in pending:
                            task.cancel()
                        await asyncio.gather(*pending, return_exceptions=True)
                        if escape_task in done and escape_event.is_set():
                            await session_message.edit(
                                content=join_parts(last_result, ESCAPE_MESSAGE),
                                allowed_mentions=allowed_mentions,
                            )
                            return
                        answer_message = answer_task.result()
                except asyncio.TimeoutError:
                    last_result = (
                        "시간 초과! 이번 예문은 진행도에 반영되지 않았습니다."
                    )
                    if infinite:
                        example_offset += 1
                        continue
                    await session_message.edit(
                        content=last_result,
                        allowed_mentions=allowed_mentions,
                    )
                    return

                try:
                    await answer_message.delete()
                except discord.NotFound:
                    pass
                except discord.HTTPException:
                    logger.exception(
                        "타자 입력 메시지 삭제 실패 (user_id=%s)", user_id
                    )

                answer = normalize_typing_text(answer_message.content)
                distance = await asyncio.to_thread(
                    typing_edit_distance,
                    target,
                    answer,
                )
                phoneme_count = len(unicodedata.normalize("NFD", target))
                score = max(0, phoneme_count - distance) // 3
                accuracy = max(0.0, 1.0 - distance / phoneme_count)

                async with get_user_lock(user_id):
                    user_scores = await async_check_level(user_id)
                    user_scores["typing"] = int(user_scores.get("typing", 0) or 0) + 1
                    if infinite:
                        accuracy_sum += accuracy
                        accuracy_count += 1
                        average_accuracy = accuracy_sum / accuracy_count
                    booster_bonus = apply_game_reward(
                        user_scores,
                        score,
                        exp_rate=0.5,
                    )
                    await async_save_scores(user_id, user_scores)

                bonus_str = f" (부스터 +{booster_bonus})" if booster_bonus > 0 else ""
                accuracy_result = f"이번 문장 정확도 **{accuracy:.1%}**"
                if infinite:
                    accuracy_result += f" · 세션 평균 정확도 **{average_accuracy:.1%}**"
                # 점수 문구는 퀴즈(cogs/quiz.py)와 동일한 형식
                last_result = (
                    f"{ctx.author.display_name} {accuracy_result}\n"
                    f"(+{score}{bonus_str}) (보유 칩: {user_scores['chips']})"
                )
                if not infinite:
                    await session_message.edit(
                        content=last_result,
                        allowed_mentions=allowed_mentions,
                    )
                    return
        except (sqlite3.Error, OSError, ValueError, RuntimeError):
            logger.exception("타자연습 진행 중 오류 발생 (user_id=%s)", user_id)
            error_message = "타자연습을 진행하지 못했습니다. 잠시 후 다시 시도해주세요."
            if session_message is not None:
                await session_message.edit(
                    content=join_parts(last_result, error_message)
                )
            else:
                await ctx.send(error_message)
        finally:
            active_typing_sessions.discard(user_id)
            if typing_escape_events.get(user_id) is escape_event:
                typing_escape_events.pop(user_id, None)


async def setup(bot: commands.Bot):
    await asyncio.to_thread(ensure_typing_column)
    example_ids = await asyncio.to_thread(load_example_ids)
    await bot.add_cog(TypingGameCog(bot, example_ids))