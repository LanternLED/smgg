import discord
from discord.ext import commands
import sqlite3
import random
import asyncio
import re
import logging
from utils import (
    async_check_level, async_save_scores, async_grant_daily_booster,
    apply_game_reward, format_booster_gain,
)

QUIZ_DB_PATH = "dictionary.db"
user_quiz_sessions = {}
logger = logging.getLogger(__name__)

def get_quiz_db_connection():
    conn = sqlite3.connect(QUIZ_DB_PATH)
    conn.row_factory = sqlite3.Row  
    return conn

def clean_word(word):
    word = word.replace('-', '')
    word = re.sub(r'[0-9]{2,}$', '', word)
    return word

def get_random_word_and_definition():
    conn = get_quiz_db_connection()
    cursor = conn.cursor()
    try:
        # 1. 100% 성공하는 무작위 문제 뽑기
        cursor.execute("SELECT target_code FROM quiz_index ORDER BY RANDOM() LIMIT 1")
        row = cursor.fetchone()
        if not row: return None
        target_code = row[0]

        # 2. 뽑힌 번호의 상세 정보 가져오기
        query = """
            SELECT w.word, s.definition, s.pos, w.target_code, s.category, o.language_type
            FROM words w
            JOIN senses s ON w.target_code = s.target_code
            LEFT JOIN original_languages o ON w.target_code = o.target_code
            WHERE w.target_code = ? LIMIT 1
        """
        cursor.execute(query, (target_code,))
        row = cursor.fetchone()
        if row:
            w = clean_word(row["word"])
            definition = re.sub(r'</?sp_no>', '', row["definition"])
            # row.get() 에러 방지를 위해 ['속성']으로 접근
            return w, definition, row["pos"], row["target_code"], row["category"], row["target_code"], row["language_type"]
    finally:
        conn.close()
    return None

async def async_get_random_word_and_definition():
    return await asyncio.to_thread(get_random_word_and_definition)

def get_wrong_choices(
    exclude_word,
    pos,
    num_choices=4,
    category=None,
    language_type=None,
    related=True,
):
    conn = get_quiz_db_connection()
    cursor = conn.cursor()
    filtered_words = []
    filtered_defs = {}

    def add_to_choices(rows):
        for row in rows:
            if len(filtered_words) >= num_choices: break
            w = clean_word(row["word"])
            if w and w != exclude_word and w not in filtered_words:
                filtered_words.append(w)
                filtered_defs[w] = re.sub(r'</?sp_no>', '', row["definition"])

    try:
        if related and category:
            cursor.execute("""
                SELECT w.word, s.definition FROM words w
                JOIN senses s ON w.target_code = s.target_code
                WHERE s.pos = ? AND s.category = ? AND w.word != ?
                ORDER BY RANDOM() LIMIT ?
            """, (pos, category, exclude_word, num_choices))
            add_to_choices(cursor.fetchall())

        if related and len(filtered_words) < num_choices:
            needed = num_choices - len(filtered_words)
            placeholders = ','.join('?' for _ in filtered_words)
            query = f"""
                SELECT w.word, s.definition FROM words w
                JOIN senses s ON w.target_code = s.target_code
                WHERE s.pos = ? AND w.word != ? 
                {"AND w.word NOT IN (" + placeholders + ")" if filtered_words else ""}
                ORDER BY RANDOM() LIMIT ?
            """
            params = [pos, exclude_word] + filtered_words + [needed]
            cursor.execute(query, params)
            add_to_choices(cursor.fetchall())

        if len(filtered_words) < num_choices:
            needed = num_choices - len(filtered_words)
            cursor.execute("""
                SELECT w.word, s.definition FROM words w
                JOIN senses s ON w.target_code = s.target_code
                WHERE w.word != ?
                ORDER BY RANDOM() LIMIT ?
            """, (exclude_word, needed * 3))
            add_to_choices(cursor.fetchall())

        return filtered_words, filtered_defs
    finally:
        conn.close()

async def async_get_wrong_choices(*args):
    return await asyncio.to_thread(get_wrong_choices, *args)

class QuizView(discord.ui.View):
    def __init__(
        self,
        user_id,
        word,
        definition,
        correct_idx,
        choices,
        infinite,
        choice_defs,
        no_answer_idx=None,
    ):
        super().__init__(timeout=20)
        self.user_id = user_id
        self.word = word
        self.definition = definition
        self.correct_idx = correct_idx
        self.choices = choices
        self.infinite = infinite
        self.choice_defs = choice_defs
        self.no_answer_idx = no_answer_idx
        self.message = None
        self.answered = False
        
        for i, choice in enumerate(choices):
            label = "정답 없음" if i == no_answer_idx else choice
            self.add_item(QuizButton(label=label, index=i, view_ref=self))

    async def disable_all(self, correct_idx=None, answer_word=None, user_idx=None):
        for i, item in enumerate(self.children):
            item.disabled = True
            if correct_idx is not None:
                if i == correct_idx: item.style = discord.ButtonStyle.success
                elif user_idx is not None and i == user_idx: item.style = discord.ButtonStyle.danger
                else: item.style = discord.ButtonStyle.secondary
            if i == self.no_answer_idx and correct_idx == self.no_answer_idx:
                item.label = answer_word if answer_word else "정답 없음"
        await self.message.edit(view=self)

    async def on_timeout(self):
        if not self.answered and self.message:
            user_scores = await async_check_level(self.user_id)
            user_scores["quiz_streak"] = 0
            await async_save_scores(self.user_id, user_scores)
            await self.disable_all(correct_idx=self.correct_idx, answer_word=self.word)
            await self.message.edit(content=f"'{self.definition}'의 뜻을 가진 단어는?\n(⏰ 시간 초과! 정답은 **{self.word}**입니다.)", view=self)
        if self.user_id in user_quiz_sessions:
            del user_quiz_sessions[self.user_id]

class QuizButton(discord.ui.Button):
    def __init__(self, label, index, view_ref):
        super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id=f"quiz_{index}")
        self.index = index
        self.view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        view = self.view_ref
        if str(interaction.user.id) != view.user_id:
            await interaction.response.send_message("이 퀴즈는 호출자만 답할 수 있습니다!", ephemeral=True)
            return
        await async_grant_daily_booster(view.user_id)
        if view.answered: return
            
        view.answered = True
        user_scores = await async_check_level(view.user_id)
        
        if self.index == view.correct_idx:
            user_scores["quiz_streak"] += 1
            reward = -2 + user_scores["quiz_streak"] * 3
            bonus = apply_game_reward(user_scores, reward, exp_rate=0.5)
            bonus_str = f" (부스터 +{bonus})" if bonus > 0 else ""
            result_msg = f"⭕ '{view.definition}'의 뜻을 가진 단어는?\n(+{reward}{bonus_str}) (보유 칩: {user_scores['chips']})"
        else:
            user_scores["quiz_streak"] = 0
            if self.index == view.no_answer_idx:
                result_msg = f"❌ '{view.definition}'의 뜻을 가진 단어는?\n💡 **정답이 있는 문제였습니다!**"
            else:
                wrong_word = view.choices[self.index]
                wrong_def = view.choice_defs.get(wrong_word, "사전 뜻을 찾을 수 없습니다.")
                result_msg = f"❌ '{view.definition}'의 뜻을 가진 단어는?\n💡 참고: **{wrong_word}**의 뜻은 '{wrong_def}'입니다."
            view.infinite = False
            
        await async_save_scores(view.user_id, user_scores)
        await view.disable_all(correct_idx=view.correct_idx, answer_word=view.word, user_idx=self.index)
        await interaction.response.edit_message(content=result_msg, view=view)
        
        if view.infinite:
            next_msg = await interaction.channel.send("문제 준비중...")
            await view.cog_ref.quiz_set(view.user_id, next_msg, infinite=True)
        elif view.user_id in user_quiz_sessions:
            del user_quiz_sessions[view.user_id]

class QuizCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def quiz_set(self, user_id, msg, infinite=False):
        try:
            # 터미널 대신 디스코드로 에러를 직접 쏘기 위한 안전망(Try-Except)
            word_data = await async_get_random_word_and_definition()
            if not word_data:
                await msg.edit(content="사전 데이터를 불러올 수 없습니다. DB를 확인해 주세요.")
                return
            word, definition, pos, target_code, category, sense_id, language_type = word_data

            user_scores = await async_check_level(user_id)
            streak = int(user_scores.get("quiz_streak", 0) or 0)
            if streak < 5:
                word_choice_count = 2
            elif streak < 10:
                word_choice_count = 3
            elif streak < 15:
                word_choice_count = 4
            elif streak < 20:
                word_choice_count = 5
            else:
                word_choice_count = 4

            include_no_answer = streak >= 20
            wrong_choice_count = word_choice_count - 1
            use_random_distractors = int(user_scores.get("booster", 0) or 0) > 0
            wrong_choices, wrong_defs = await async_get_wrong_choices(
                word,
                pos,
                wrong_choice_count,
                category,
                language_type,
                not use_random_distractors,
            )
            choices = [word] + wrong_choices
            random.shuffle(choices)

            correct_idx = choices.index(word)
            no_answer_idx = None
            if include_no_answer:
                no_answer_idx = len(choices)
                choices.append("정답 없음")
            
            choice_defs = {word: definition}
            choice_defs.update(wrong_defs)

            view = QuizView(
                user_id,
                word,
                definition,
                correct_idx,
                choices,
                infinite,
                choice_defs,
                no_answer_idx,
            )
            view.cog_ref = self
            await msg.edit(content=f"'{definition}'의 뜻을 가진 단어는?", view=view)
            view.message = msg
            user_quiz_sessions[user_id] = view

        except Exception:
            logger.exception("퀴즈 준비 중 오류 발생 (user_id=%s)", user_id)
            await msg.edit(content="퀴즈를 준비하지 못했습니다. 잠시 후 다시 시도해주세요.")

    @commands.command(name='퀴즈')
    async def quiz(self, ctx):
        await ctx.message.delete()
        user_id = str(ctx.author.id)
        booster_result = await async_grant_daily_booster(user_id)
        booster_notice = format_booster_gain(booster_result)
        if booster_notice:
            await ctx.send(f"{ctx.author.mention} {booster_notice}")
        if user_id in user_quiz_sessions:
            await ctx.send(f"이전 퀴즈를 먼저 풀어주세요.", delete_after=5)
            return
        msg = await ctx.send("퀴즈 준비중...")
        await self.quiz_set(user_id, msg)

    @commands.command(name='무한퀴즈')
    async def quizinf(self, ctx):
        await ctx.message.delete()
        user_id = str(ctx.author.id)
        booster_result = await async_grant_daily_booster(user_id)
        booster_notice = format_booster_gain(booster_result)
        if booster_notice:
            await ctx.send(f"{ctx.author.mention} {booster_notice}")
        if user_id in user_quiz_sessions:
            await ctx.send(f"이전 퀴즈를 먼저 풀어주세요.", delete_after=5)
            return
        msg = await ctx.send("퀴즈 준비중...")
        await self.quiz_set(user_id, msg, infinite=True)

async def setup(bot):
    await bot.add_cog(QuizCog(bot))