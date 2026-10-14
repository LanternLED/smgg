import asyncio
import hashlib
import logging
import math
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
logger = logging.getLogger(__name__)
active_typing_sessions: set[str] = set()


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


def normalize_typing_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", normalized).strip()


def levenshtein_distance(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left

    previous_row = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current_row = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            substitution_cost = 0 if left_char == right_char else 1
            current_row.append(
                min(
                    previous_row[right_index] + 1,
                    current_row[right_index - 1] + 1,
                    previous_row[right_index - 1] + substitution_cost,
                )
            )
        previous_row = current_row
    return previous_row[-1]


class TypingGameCog(commands.Cog):
    def __init__(self, bot: commands.Bot, example_ids: tuple[int, ...]):
        self.bot = bot
        self.example_ids = example_ids

    @commands.command(name="타자연습", aliases=["타자"])
    async def typing_game(self, ctx: commands.Context):
        await ctx.message.delete()
        user_id = str(ctx.author.id)
        if user_id in active_typing_sessions:
            await ctx.send("진행 중인 타자연습을 먼저 마쳐주세요.", delete_after=5)
            return
        active_typing_sessions.add(user_id)

        try:
            booster_result = await async_grant_daily_booster(user_id)
            booster_notice = format_booster_gain(booster_result)
            if booster_notice:
                await ctx.send(f"{ctx.author.mention} {booster_notice}")

            user_scores = await async_check_level(user_id)
            progress = int(user_scores.get("typing", 0) or 0)
            example_id = get_example_id(user_id, progress, self.example_ids)
            example = await asyncio.to_thread(load_example, example_id)
            target = normalize_typing_text(example)
            if not target:
                raise ValueError(f"예문 ID {example_id}의 내용이 비어 있습니다.")

            await ctx.send(
                f"{ctx.author.mention} 아래 문장을 그대로 입력하세요. "
                f"(제한 시간 {TYPING_TIMEOUT_SECONDS}초)\n> {example}",
                allowed_mentions=discord.AllowedMentions(
                    users=[ctx.author],
                    roles=False,
                    everyone=False,
                ),
            )

            def is_answer(message: discord.Message) -> bool:
                return (
                    message.author.id == ctx.author.id
                    and message.channel.id == ctx.channel.id
                    and not message.content.startswith(ctx.prefix)
                )

            try:
                answer_message = await self.bot.wait_for(
                    "message",
                    timeout=TYPING_TIMEOUT_SECONDS,
                    check=is_answer,
                )
            except asyncio.TimeoutError:
                await ctx.send("시간 초과! 이번 예문은 진행도에 반영되지 않았습니다.")
                return

            answer = normalize_typing_text(answer_message.content)
            distance = await asyncio.to_thread(
                levenshtein_distance,
                target,
                answer,
            )
            score = max(0, len(target) - distance)
            accuracy = max(0.0, 1.0 - distance / len(target))

            async with get_user_lock(user_id):
                user_scores = await async_check_level(user_id)
                user_scores["typing"] = int(user_scores.get("typing", 0) or 0) + 1
                booster_bonus = apply_game_reward(
                    user_scores,
                    score,
                    exp_rate=0.5,
                )
                await async_save_scores(user_id, user_scores)

            cycle_progress = user_scores["typing"] % len(self.example_ids)
            if cycle_progress == 0:
                cycle_progress = len(self.example_ids)
            cycle_count = (user_scores["typing"] - 1) // len(self.example_ids) + 1
            bonus_notice = f" (부스터 +{booster_bonus})" if booster_bonus > 0 else ""
            await ctx.send(
                f"{ctx.author.mention} 정확도 **{accuracy:.1%}** "
                f"(편집 거리 {distance}) — **+{score}점**{bonus_notice}\n"
                f"진행도: {cycle_progress:,}/{len(self.example_ids):,} "
                f"(전체 {user_scores['typing']:,}회, {cycle_count}회차) · "
                f"보유 칩: {user_scores['chips']:,}",
                allowed_mentions=discord.AllowedMentions(
                    users=[ctx.author],
                    roles=False,
                    everyone=False,
                ),
            )
        except (sqlite3.Error, OSError, ValueError, RuntimeError):
            logger.exception("타자연습 진행 중 오류 발생 (user_id=%s)", user_id)
            await ctx.send("타자연습을 진행하지 못했습니다. 잠시 후 다시 시도해주세요.")
        finally:
            active_typing_sessions.discard(user_id)


async def setup(bot: commands.Bot):
    await asyncio.to_thread(ensure_typing_column)
    example_ids = await asyncio.to_thread(load_example_ids)
    await bot.add_cog(TypingGameCog(bot, example_ids))
