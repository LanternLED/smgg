"""필사 기능: 관리자가 작품 문장을 모으는 `내용추가`, 직전 문장을 지우는 `수정`,
모아둔 작품으로 타자연습을 하는 `필사`.

데이터는 scores.db 안의 아래 테이블에 저장한다. (봇이 켜질 때 자동 생성)
  works                 작품 (제목·작가)
  work_sentences        작품별 문장 (순서·내용·필사 글자수)
  transcribe_progress   유저별 작품 진행도 (이어하기용)
  transcribe_done       유저별 작품 완료 횟수 (재완료 보상 감소용)
"""
import asyncio
import logging
import math
import re
import sqlite3
import unicodedata
from datetime import datetime

import discord
from discord.ext import commands

from cogs.typing_game import (
    insert_typing_markers,
    join_parts,
    typing_edit_distance,
)
from utils import (
    apply_game_reward,
    async_check_level,
    async_grant_daily_booster,
    async_save_scores,
    format_booster_gain,
    get_db_connection,
    get_user_lock,
)

ADMIN_USER_ID = 440536830404722698
MAX_SENTENCE_LENGTH = 400
ADD_TIMEOUT_SECONDS = 600  # 내용추가: 입력이 이만큼 없으면 탈출과 같게 종료
TRANSCRIBE_BASE_TIMEOUT_SECONDS = 300  # 필사: 문장당 기본 제한시간 (+ 문장 글자수만큼 가산)
PICKER_TIMEOUT_SECONDS = 180  # 필사: 작품 목록을 고르는 시간
PAGE_SIZE = 10
REPEAT_COMPLETION_RATE = 0.5  # 이미 완료한 작품을 다시 완료했을 때의 보상 비율
logger = logging.getLogger(__name__)


# ── 텍스트 유틸 ─────────────────────────────────────────────
def clean_input(text: str) -> str:
    """입력 문장 정리: NFC 정규화 + 공백 정리."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def make_title_key(text: str) -> str:
    """작품명 비교용 키: 공백을 모두 없애고 대소문자를 무시한다."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text)).casefold()


def count_chars(text: str) -> int:
    """필사에서 실제로 치는 글자 수 (공백 제외)."""
    return len(re.sub(r"\s", "", clean_input(text)))


def format_duration(seconds: int) -> str:
    minutes, rest = divmod(seconds, 60)
    if minutes and rest:
        return f"{minutes}분 {rest}초"
    if minutes:
        return f"{minutes}분"
    return f"{rest}초"


def shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def plain(text: str) -> str:
    """디스코드 마크다운이 먹히지 않게 이스케이프."""
    return discord.utils.escape_markdown(text)


# ── DB ──────────────────────────────────────────────────────
def ensure_tables():
    conn = get_db_connection()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS works ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "title TEXT NOT NULL, "
            "title_key TEXT NOT NULL UNIQUE, "
            "author TEXT NOT NULL DEFAULT '', "
            "created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS work_sentences ("
            "work_id INTEGER NOT NULL, "
            "seq INTEGER NOT NULL, "
            "content TEXT NOT NULL, "
            "chars INTEGER NOT NULL, "
            "PRIMARY KEY (work_id, seq))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS transcribe_progress ("
            "user_id TEXT NOT NULL, "
            "work_id INTEGER NOT NULL, "
            "pos INTEGER NOT NULL DEFAULT 0, "
            "accuracy_sum REAL NOT NULL DEFAULT 0, "
            "answered INTEGER NOT NULL DEFAULT 0, "
            "updated_at TEXT NOT NULL, "
            "PRIMARY KEY (user_id, work_id))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS transcribe_done ("
            "user_id TEXT NOT NULL, "
            "work_id INTEGER NOT NULL, "
            "count INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY (user_id, work_id))"
        )
        conn.commit()
    finally:
        conn.close()


def find_work(title_key: str) -> dict | None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id, title, author FROM works WHERE title_key = ?", (title_key,)
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def get_work(work_id: int) -> dict | None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id, title, author FROM works WHERE id = ?", (work_id,)
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def create_work(title: str, title_key: str, author: str) -> int:
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO works (title, title_key, author, created_at) VALUES (?, ?, ?, ?)",
            (title, title_key, author, datetime.now().isoformat()),
        )
        conn.commit()
        return int(cursor.lastrowid or 0)
    finally:
        conn.close()


def work_stats(work_id: int) -> tuple[int, int, str | None]:
    """(문장 수, 총 글자수, 마지막 문장)."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT content FROM work_sentences WHERE work_id = ? ORDER BY seq",
            (work_id,),
        ).fetchall()
        contents = [row[0] for row in rows]
        total_chars = sum(count_chars(content) for content in contents)
        return len(contents), total_chars, (contents[-1] if contents else None)
    finally:
        conn.close()


def add_sentence(work_id: int, content: str, chars: int) -> int:
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM work_sentences WHERE work_id = ?", (work_id,)
        ).fetchone()
        seq = int(row[0]) + 1
        conn.execute(
            "INSERT INTO work_sentences (work_id, seq, content, chars) VALUES (?, ?, ?, ?)",
            (work_id, seq, content, chars),
        )
        conn.commit()
        return seq
    finally:
        conn.close()


def delete_last_sentence(work_id: int) -> tuple[int, str, tuple[int, str] | None] | None:
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        sentence_rows = conn.execute(
            "SELECT seq, content FROM work_sentences "
            "WHERE work_id = ? ORDER BY seq DESC LIMIT 2",
            (work_id,),
        ).fetchall()
        if not sentence_rows:
            return None
        deleted = sentence_rows[0]
        previous = (
            (int(sentence_rows[1]["seq"]), str(sentence_rows[1]["content"]))
            if len(sentence_rows) > 1
            else None
        )
        conn.execute(
            "DELETE FROM work_sentences WHERE work_id = ? AND seq = ?",
            (work_id, deleted["seq"]),
        )
        conn.commit()
        return int(deleted["seq"]), str(deleted["content"]), previous
    finally:
        conn.close()


def list_works(user_id: str) -> list[dict]:
    """문장이 1개 이상 있는 작품 목록 (유저의 진행도·완료 횟수 포함)."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT w.id AS id, w.title AS title, w.author AS author, "
            "COUNT(s.seq) AS sentences, COALESCE(SUM(s.chars), 0) AS chars, "
            "COALESCE(p.pos, 0) AS pos, COALESCE(d.count, 0) AS done "
            "FROM works w "
            "LEFT JOIN work_sentences s ON s.work_id = w.id "
            "LEFT JOIN transcribe_progress p ON p.work_id = w.id AND p.user_id = ? "
            "LEFT JOIN transcribe_done d ON d.work_id = w.id AND d.user_id = ? "
            "GROUP BY w.id HAVING COUNT(s.seq) > 0 ORDER BY w.title",
            (user_id, user_id),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def load_sentences(work_id: int) -> list[str]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT content FROM work_sentences WHERE work_id = ? ORDER BY seq", (work_id,)
        ).fetchall()
        return [str(row["content"]) for row in rows]
    finally:
        conn.close()


def load_progress(user_id: str, work_id: int) -> tuple[int, float, int]:
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT pos, accuracy_sum, answered FROM transcribe_progress "
            "WHERE user_id = ? AND work_id = ?",
            (user_id, work_id),
        ).fetchone()
        if row is None:
            return 0, 0.0, 0
        return int(row["pos"]), float(row["accuracy_sum"]), int(row["answered"])
    finally:
        conn.close()


_UPSERT_PROGRESS = (
    "INSERT INTO transcribe_progress (user_id, work_id, pos, accuracy_sum, answered, updated_at) "
    "VALUES (?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(user_id, work_id) DO UPDATE SET "
    "pos = excluded.pos, accuracy_sum = excluded.accuracy_sum, "
    "answered = excluded.answered, updated_at = excluded.updated_at"
)


def save_progress(user_id: str, work_id: int, pos: int, accuracy_sum: float, answered: int):
    conn = get_db_connection()
    try:
        conn.execute(
            _UPSERT_PROGRESS,
            (user_id, work_id, pos, accuracy_sum, answered, datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def complete_work(user_id: str, work_id: int) -> int:
    """완료 처리: 완료 횟수 +1, 진행도 초기화. 완료 전의 완료 횟수를 돌려준다."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT count FROM transcribe_done WHERE user_id = ? AND work_id = ?",
            (user_id, work_id),
        ).fetchone()
        previous = int(row["count"]) if row is not None else 0
        conn.execute(
            "INSERT INTO transcribe_done (user_id, work_id, count) VALUES (?, ?, 1) "
            "ON CONFLICT(user_id, work_id) DO UPDATE SET count = count + 1",
            (user_id, work_id),
        )
        conn.execute(
            _UPSERT_PROGRESS,
            (user_id, work_id, 0, 0.0, 0, datetime.now().isoformat()),
        )
        conn.commit()
        return previous
    finally:
        conn.close()


# ── 디스코드 유틸 ───────────────────────────────────────────
async def wait_for_message_or_escape(
    bot: commands.Bot,
    check,
    timeout: float,
    escape_event: asyncio.Event,
) -> discord.Message | None:
    """메시지를 기다린다. 탈출하면 None, 시간이 지나면 asyncio.TimeoutError."""
    answer_task = asyncio.create_task(bot.wait_for("message", timeout=timeout, check=check))
    escape_task = asyncio.create_task(escape_event.wait())
    done, pending = await asyncio.wait((answer_task, escape_task), return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    if escape_event.is_set():
        if answer_task.done() and not answer_task.cancelled():
            answer_task.exception()  # 결과를 회수해 경고가 남지 않게 한다
        return None
    return answer_task.result()


async def delete_message(message: discord.Message):
    try:
        await message.delete()
    except discord.NotFound:
        pass
    except discord.HTTPException:
        logger.exception("입력 메시지 삭제 실패 (message_id=%s)", message.id)


class SearchModal(discord.ui.Modal, title="작품 검색"):
    keyword: discord.ui.TextInput = discord.ui.TextInput(
        label="작품명 또는 작가명 (비우면 전체 보기)",
        required=False,
        max_length=50,
    )

    def __init__(self, picker: "WorkPickerView"):
        super().__init__()
        self.picker = picker

    async def on_submit(self, interaction: discord.Interaction):
        self.picker.query = str(self.keyword.value or "").strip()
        self.picker.page = 0
        self.picker.rebuild()
        await interaction.response.edit_message(content=self.picker.render_content(), view=self.picker)


class WorkPickerView(discord.ui.View):
    """작품 목록: 10개씩 페이지로 넘기며 드롭다운으로 고른다. 검색 가능."""

    def __init__(self, author_id: int, works: list[dict], query: str = ""):
        super().__init__(timeout=PICKER_TIMEOUT_SECONDS)
        self.author_id = author_id
        self.works = works
        self.query = query
        self.page = 0
        self.selected_id: int | None = None
        self.rebuild()

    def filtered(self) -> list[dict]:
        key = make_title_key(self.query)
        if not key:
            return self.works
        return [
            work for work in self.works
            if key in make_title_key(work["title"]) or key in make_title_key(work["author"] or "")
        ]

    def page_count(self) -> int:
        return max(1, math.ceil(len(self.filtered()) / PAGE_SIZE))

    def render_content(self) -> str:
        works = self.filtered()
        header = f"📖 필사할 작품을 고르세요. ({self.page + 1}/{self.page_count()}페이지 · 작품 {len(works)}개"
        if self.query:
            header += f" · 검색: {self.query}"
        header += ")"
        if not works:
            header += "\n검색 결과가 없습니다. 🔍 검색을 눌러 다시 찾아보세요."
        return header

    def rebuild(self):
        self.clear_items()
        works = self.filtered()
        self.page = min(self.page, self.page_count() - 1)
        start = self.page * PAGE_SIZE
        page_items = works[start:start + PAGE_SIZE]

        if page_items:
            options = []
            for index, work in enumerate(page_items, start=start + 1):
                parts = []
                if work["author"]:
                    parts.append(work["author"])
                parts.append(f"{work['sentences']}문장 · {work['chars']}자")
                if work["pos"] > 0:
                    parts.append(f"진행 {work['pos']}/{work['sentences']}")
                if work["done"] > 0:
                    parts.append(f"완료 {work['done']}회")
                options.append(
                    discord.SelectOption(
                        label=shorten(f"{index}. {work['title']}", 100),
                        description=shorten(" · ".join(parts), 100),
                        value=str(work["id"]),
                    )
                )
            select = discord.ui.Select(placeholder="작품 선택", options=options)

            async def on_select(interaction: discord.Interaction):
                self.selected_id = int(select.values[0])
                self.stop()
                await interaction.response.edit_message(content="작품을 불러오는 중입니다...", view=None)

            select.callback = on_select  # type: ignore[method-assign]
            self.add_item(select)

        previous_button = discord.ui.Button(
            label="이전", style=discord.ButtonStyle.secondary, disabled=self.page <= 0, row=1
        )
        next_button = discord.ui.Button(
            label="다음",
            style=discord.ButtonStyle.secondary,
            disabled=self.page >= self.page_count() - 1,
            row=1,
        )
        search_button = discord.ui.Button(label="🔍 검색", style=discord.ButtonStyle.primary, row=1)

        async def on_previous(interaction: discord.Interaction):
            self.page -= 1
            self.rebuild()
            await interaction.response.edit_message(content=self.render_content(), view=self)

        async def on_next(interaction: discord.Interaction):
            self.page += 1
            self.rebuild()
            await interaction.response.edit_message(content=self.render_content(), view=self)

        async def on_search(interaction: discord.Interaction):
            await interaction.response.send_modal(SearchModal(self))

        previous_button.callback = on_previous  # type: ignore[method-assign]
        next_button.callback = on_next  # type: ignore[method-assign]
        search_button.callback = on_search  # type: ignore[method-assign]
        self.add_item(previous_button)
        self.add_item(next_button)
        self.add_item(search_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("명령어를 사용한 분만 고를 수 있습니다.", ephemeral=True)
            return False
        return True


class AddSession:
    """내용추가 세션 상태. `수정` 명령어가 같은 상태를 보고 직전 문장을 지운다."""

    def __init__(self):
        self.work_id: int | None = None
        self.title = ""
        self.added = 0
        self.lock = asyncio.Lock()


class TranscribeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.escape_events: dict[str, asyncio.Event] = {}
        self.add_sessions: dict[str, AddSession] = {}

    # `탈출`(cogs/quiz.py)이 호출한다.
    def request_escape(self, user_id: str) -> bool:
        escape_event = self.escape_events.get(user_id)
        if escape_event is None or escape_event.is_set():
            return False
        escape_event.set()
        return True

    def has_session(self, user_id: str) -> bool:
        return user_id in self.escape_events

    def _is_busy(self, user_id: str) -> bool:
        if self.has_session(user_id):
            return True
        typing_cog = self.bot.get_cog("TypingGameCog")
        return typing_cog is not None and typing_cog.has_session(user_id)  # type: ignore[attr-defined]

    def _start(self, user_id: str) -> asyncio.Event:
        escape_event = asyncio.Event()
        self.escape_events[user_id] = escape_event
        return escape_event

    def _finish(self, user_id: str, escape_event: asyncio.Event):
        if self.escape_events.get(user_id) is escape_event:
            self.escape_events.pop(user_id, None)

    # ── 내용추가 (관리자 전용) ──────────────────────────────
    @commands.command(name="내용추가")
    async def add_content(self, ctx: commands.Context):
        if ctx.author.id != ADMIN_USER_ID:
            return
        user_id = str(ctx.author.id)
        if self._is_busy(user_id):
            await ctx.send("진행 중인 세션을 먼저 마쳐주세요.", delete_after=5)
            return
        escape_event = self._start(user_id)
        session = AddSession()
        self.add_sessions[user_id] = session
        try:
            try:
                await self._run_add(ctx, session, escape_event)
            except asyncio.TimeoutError:
                await ctx.send("입력이 없어 내용추가를 종료합니다.")
            await self._send_add_summary(ctx, session)
        except (sqlite3.Error, OSError, ValueError, RuntimeError, discord.HTTPException):
            logger.exception("내용추가 진행 중 오류 발생 (user_id=%s)", user_id)
            await ctx.send("내용추가 중 오류가 발생했습니다. 지금까지 입력한 문장은 저장되어 있습니다.")
        finally:
            self._finish(user_id, escape_event)
            if self.add_sessions.get(user_id) is session:
                self.add_sessions.pop(user_id, None)

    async def _run_add(self, ctx: commands.Context, session: AddSession, escape_event: asyncio.Event):
        def is_input(message: discord.Message) -> bool:
            return (
                message.author.id == ctx.author.id
                and message.channel.id == ctx.channel.id
                and bool(message.content.strip())
                and not message.content.startswith(str(ctx.prefix))
            )

        async def receive() -> str | None:
            message = await wait_for_message_or_escape(self.bot, is_input, ADD_TIMEOUT_SECONDS, escape_event)
            if message is None:
                return None
            await delete_message(message)
            return clean_input(message.content)

        no_mentions = discord.AllowedMentions.none()
        await ctx.send(f"📖 내용을 추가할 작품명을 입력하세요. (종료: `{ctx.prefix}탈출`)")
        title = await receive()
        if not title:
            return
        title_key = make_title_key(title)

        existing = await asyncio.to_thread(find_work, title_key)
        author = ""
        if existing is not None:
            session.work_id = existing["id"]
            session.title = existing["title"]
            sentence_count, char_count, last = await asyncio.to_thread(work_stats, existing["id"])
            notice = (
                f"『{plain(existing['title'])}』 ({plain(existing['author'])}) 작품이 이미 있습니다. "
                f"현재 {sentence_count}문장 · {char_count}자"
            )
            if last is not None:
                notice += f"\n마지막 문장: {plain(last)}"
            notice += "\n이어서 한 문장씩 입력하세요."
            await ctx.send(notice, allowed_mentions=no_mentions)
        else:
            session.title = title
            await ctx.send(f"새 작품입니다. 『{plain(title)}』의 작가명을 입력하세요.", allowed_mentions=no_mentions)
            author = await receive() or ""
            if not author:
                return
            await ctx.send(
                f"『{plain(title)}』 ({plain(author)}) 새 작품으로 시작합니다. "
                f"첫 문장부터 한 문장씩 입력하세요.\n"
                f"(직전 문장 삭제: `{ctx.prefix}수정` · 종료: `{ctx.prefix}탈출`)",
                allowed_mentions=no_mentions,
            )

        while True:
            text = await receive()
            if not text:
                return
            if len(text) > MAX_SENTENCE_LENGTH:
                await ctx.send(
                    f"문장이 너무 깁니다. ({len(text)}자 / 최대 {MAX_SENTENCE_LENGTH}자) 나눠서 다시 입력해주세요.",
                    delete_after=8,
                )
                continue
            chars = count_chars(text)
            if chars == 0:
                await ctx.send("필사할 글자가 없는 문장입니다. (괄호 안 내용만 있는 경우 등)", delete_after=8)
                continue
            async with session.lock:
                if session.work_id is None:
                    session.work_id = await asyncio.to_thread(create_work, title, title_key, author)
                seq = await asyncio.to_thread(add_sentence, session.work_id, text, chars)
                session.added += 1
            await ctx.send(f"✅ {seq}번째 문장: {plain(text)}", allowed_mentions=no_mentions)

    async def _send_add_summary(self, ctx: commands.Context, session: AddSession):
        if session.work_id is None:
            await ctx.send("📚 내용추가를 종료했습니다. 추가된 문장이 없어 새 작품은 만들어지지 않았습니다.")
            return
        sentence_count, char_count, _ = await asyncio.to_thread(work_stats, session.work_id)
        await ctx.send(
            f"📚 내용추가를 종료했습니다. 『{plain(session.title)}』 이번에 {session.added}문장 추가 · "
            f"총 {sentence_count}문장 ({char_count}자) 저장했습니다.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="수정")
    async def edit_last_sentence(self, ctx: commands.Context):
        if ctx.author.id != ADMIN_USER_ID:
            return
        session = self.add_sessions.get(str(ctx.author.id))
        if session is None:
            await ctx.send("진행 중인 내용추가가 없습니다.", delete_after=5)
            return
        async with session.lock:
            deleted = None
            if session.work_id is not None:
                deleted = await asyncio.to_thread(delete_last_sentence, session.work_id)
        if deleted is None:
            await ctx.send("삭제할 문장이 없습니다.", delete_after=5)
            return
        seq, content, previous = deleted
        previous_note = (
            f"📌 바로 앞 문장 ({previous[0]}번째):\n> {plain(previous[1])}\n"
            if previous is not None
            else ""
        )
        await ctx.send(
            f"{previous_note}🗑️ {seq}번째 문장을 삭제했습니다.\n"
            f"> {plain(content)}\n수정할 문장을 입력해주세요.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    # ── 필사 ────────────────────────────────────────────────
    @commands.command(name="필사")
    async def transcribe(self, ctx: commands.Context, *, query: str = ""):
        user_id = str(ctx.author.id)
        if self._is_busy(user_id):
            await ctx.send("진행 중인 세션을 먼저 마쳐주세요.", delete_after=5)
            return
        escape_event = self._start(user_id)
        session_message: discord.Message | None = None
        try:
            works = await asyncio.to_thread(list_works, user_id)
            if not works:
                await ctx.send("아직 필사할 수 있는 작품이 없습니다.", delete_after=8)
                return

            booster_result = await async_grant_daily_booster(user_id)
            booster_notice = format_booster_gain(booster_result)
            if booster_notice:
                await ctx.send(f"{ctx.author.mention} {booster_notice}")

            view = WorkPickerView(ctx.author.id, works, query.strip())
            session_message = await ctx.send(view.render_content(), view=view)
            work_id = await self._pick_work(view, session_message, escape_event)
            if work_id is None:
                return
            await self._run_transcribe(ctx, session_message, work_id, escape_event)
        except (sqlite3.Error, OSError, ValueError, RuntimeError, discord.HTTPException):
            logger.exception("필사 진행 중 오류 발생 (user_id=%s)", user_id)
            error_message = "필사를 진행하지 못했습니다. 잠시 후 다시 시도해주세요."
            if session_message is not None:
                await session_message.edit(content=error_message, view=None)
            else:
                await ctx.send(error_message)
        finally:
            self._finish(user_id, escape_event)

    async def _pick_work(
        self,
        view: WorkPickerView,
        session_message: discord.Message,
        escape_event: asyncio.Event,
    ) -> int | None:
        view_task = asyncio.create_task(view.wait())
        escape_task = asyncio.create_task(escape_event.wait())
        _, pending = await asyncio.wait((view_task, escape_task), return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if escape_event.is_set():
            view.stop()
            await session_message.edit(content="필사를 취소했습니다.", view=None)
            return None
        if view.selected_id is None:
            await session_message.edit(content="시간이 지나 작품 목록을 닫았습니다.", view=None)
            return None
        return view.selected_id

    async def _run_transcribe(
        self,
        ctx: commands.Context,
        session_message: discord.Message,
        work_id: int,
        escape_event: asyncio.Event,
    ):
        user_id = str(ctx.author.id)
        work = await asyncio.to_thread(get_work, work_id)
        sentences = await asyncio.to_thread(load_sentences, work_id)
        if work is None or not sentences:
            await session_message.edit(content="작품을 불러오지 못했습니다.", view=None)
            return
        title = plain(work["title"])
        total = len(sentences)
        pos, accuracy_sum, answered = await asyncio.to_thread(load_progress, user_id, work_id)
        if pos >= total:
            pos, accuracy_sum, answered = 0, 0.0, 0

        allowed_mentions = discord.AllowedMentions(users=[ctx.author], roles=False, everyone=False)

        def is_answer(message: discord.Message) -> bool:
            return (
                message.author.id == ctx.author.id
                and message.channel.id == ctx.channel.id
                and not message.content.startswith(str(ctx.prefix))
            )

        last_result = ""
        if pos > 0:
            last_result = f"『{title}』 이어서 진행합니다. ({pos}/{total})"

        async def stop_with(notice: str):
            await session_message.edit(
                content=join_parts(last_result, notice),
                view=None,
                allowed_mentions=allowed_mentions,
            )

        while pos < total:
            if escape_event.is_set():
                await stop_with(f"필사를 중단했습니다. ({pos}/{total} 진행, 다음에 이어서 하실 수 있습니다.)")
                return
            target = clean_input(sentences[pos])
            if not target:
                pos += 1
                await asyncio.to_thread(save_progress, user_id, work_id, pos, accuracy_sum, answered)
                continue

            timeout = TRANSCRIBE_BASE_TIMEOUT_SECONDS + len(target)
            prompt = (
                f"{ctx.author.mention} 『{title}』 {pos + 1}/{total}번째 문장입니다. 아래 문장을 입력하세요. "
                f"(제한 시간 {format_duration(timeout)}, 삽입된 특수기호는 입력하지 마세요.)\n"
                f"> {insert_typing_markers(target)}"
            )
            await session_message.edit(
                content=join_parts(last_result, prompt),
                view=None,
                allowed_mentions=allowed_mentions,
            )

            try:
                answer_message = await wait_for_message_or_escape(self.bot, is_answer, timeout, escape_event)
            except asyncio.TimeoutError:
                await stop_with(f"시간 초과! 필사를 종료합니다. ({pos}/{total} 진행, 다음에 이어서 하실 수 있습니다.)")
                return
            if answer_message is None:
                await stop_with(f"필사를 중단했습니다. ({pos}/{total} 진행, 다음에 이어서 하실 수 있습니다.)")
                return
            await delete_message(answer_message)

            answer = clean_input(answer_message.content)
            distance = await asyncio.to_thread(typing_edit_distance, target, answer)
            phoneme_count = len(unicodedata.normalize("NFD", target))
            score = max(0, phoneme_count - distance) // 3
            accuracy = max(0.0, 1.0 - distance / phoneme_count)
            pos += 1
            answered += 1
            accuracy_sum += accuracy
            average_accuracy = accuracy_sum / answered

            async with get_user_lock(user_id):
                user_scores = await async_check_level(user_id)
                booster_bonus = apply_game_reward(user_scores, score, exp_rate=0.5)
                await async_save_scores(user_id, user_scores)
            await asyncio.to_thread(save_progress, user_id, work_id, pos, accuracy_sum, answered)

            bonus_str = f" (부스터 +{booster_bonus})" if booster_bonus > 0 else ""
            last_result = (
                f"{ctx.author.display_name} 이번 문장 정확도 **{accuracy:.1%}** · 작품 평균 정확도 **{average_accuracy:.1%}**\n"
                f"(+{score}{bonus_str}) (보유 칩: {user_scores['chips']})"
            )

        # 끝까지 쳤다: 완료 보상 = 작품 글자수 × 평균 정확도 (재완료는 50%)
        total_chars = sum(count_chars(sentence) for sentence in sentences)
        average_accuracy = accuracy_sum / answered if answered else 0.0
        previous_count = await asyncio.to_thread(complete_work, user_id, work_id)
        reward = int(total_chars * average_accuracy)
        if previous_count > 0:
            reward = int(reward * REPEAT_COMPLETION_RATE)
        async with get_user_lock(user_id):
            user_scores = await async_check_level(user_id)
            booster_bonus = apply_game_reward(user_scores, reward, exp_rate=0.5)
            await async_save_scores(user_id, user_scores)

        bonus_str = f" (부스터 +{booster_bonus})" if booster_bonus > 0 else ""
        repeat_note = f" (재완료 {int(REPEAT_COMPLETION_RATE * 100)}%)" if previous_count > 0 else ""
        await stop_with(
            f"🎉 『{title}』 필사 완료! ({total}문장 · {total_chars}자)\n"
            f"평균 정확도 **{average_accuracy:.1%}** · 완료 보상 +{reward}{repeat_note}{bonus_str} "
            f"(보유 칩: {user_scores['chips']})"
        )


async def setup(bot: commands.Bot):
    await asyncio.to_thread(ensure_tables)
    await bot.add_cog(TranscribeCog(bot))