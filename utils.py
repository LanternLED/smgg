import inspect
import sqlite3
import asyncio
import math
from datetime import date, datetime, timedelta

DB_PATH = "scores.db"
ADMIN_USER_ID = 440536830404722698

# ── 칩 경제 개편: 고정 교환비 (레벨 무관) ──────────────────────────
CHIP_BUY_RATE = 100        # 1시간(score) → 100칩
CHIP_SELL_COST = 1111      # 1시간(score) 구매에 필요한 칩

# ── 부스터 ──────────────────────────────────────────────────────
BOOSTER_BASE_GAIN = 1000    # 하루 첫 상호작용 시 기본 지급량
BOOSTER_DECAY = 0.95         # 밀린 날짜의 감쇠율
BOOSTER_BASE_BONUS_PERCENT = 20

# ── 유저 데이터 갱신 ─────────────────────────────────────────────
# "읽기 → 수정 → 저장"은 반드시 update_user() / update_users()로 한 번에 처리한다.
# 함수(fn) 하나를 DB 트랜잭션(BEGIN IMMEDIATE) 안에서 실행하고, 바뀐 컬럼만 저장하므로
# 같은 유저에 대한 동시 실행이 서로의 변경을 덮어쓰지 않는다. (asyncio.Lock 불필요)
# fn은 await가 없는 동기 함수여야 한다.

def _coerce_int(value, default=0) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value).strip().replace(",", ""))
    except (ValueError, TypeError):
        return default


def calc_booster_gain(days_passed: int, level: int = 0) -> int:
    """Calculate accumulated daily boosters using the current player level."""
    total = 0
    for i in range(days_passed):
        daily_gain = BOOSTER_BASE_GAIN + max(0, _coerce_int(level, 0))
        total += int(daily_gain * pow(BOOSTER_DECAY, i))
    return total


def booster_n_percent(booster: int) -> float:
    """Return the total booster bonus percentage for the current balance."""
    if booster <= 0:
        return 0.0
    # max(기본 20%, 부스터의 제곱근 %) — 부스터가 400 이하면 20%, 그 위로는 √부스터 %
    percent = max(BOOSTER_BASE_BONUS_PERCENT, math.sqrt(booster))
    return round(percent, 2)


def apply_booster(user_scores: dict, chip_gain: int, *, exp_rate: float = 0.1) -> int:
    """미니게임 획득 칩 보상에 부스터 소모 및 추가 지급 적용."""
    booster_val = _coerce_int(user_scores.get("booster"), 0)
    if chip_gain <= 0 or booster_val <= 0:
        return 0
    # 획득 칩이 100 미만이면 부스터 비율에 (1 + (100 - 칩) / 25)를 곱한다.
    small_reward_multiplier = 1 + max(0, 100 - chip_gain) / 25
    bonus_percent_hundredths = round(
        booster_n_percent(booster_val) * small_reward_multiplier * 100
    )
    bonus = min(
        booster_val,
        chip_gain * bonus_percent_hundredths // 10_000,
    )
    if bonus <= 0:
        return 0
    user_scores["booster"] = booster_val - bonus
    user_scores["chips"] = _coerce_int(user_scores.get("chips"), 0) + bonus
    user_scores["exp"] = _coerce_int(user_scores.get("exp"), 0) + int(bonus * exp_rate)
    return bonus


def level_reward_bonus(level) -> int:
    """Return a small level-based bonus for quiz and typing rewards."""
    level = _coerce_int(level, 0)
    if level < 1:
        return 1
    return (1 + math.isqrt(8 * level - 7)) // 2


def apply_level_ups(user_scores: dict) -> bool:
    """Apply every level reached by the current EXP and report whether it changed."""
    level = _coerce_int(user_scores.get("level"), 0)
    exp = _coerce_int(user_scores.get("exp"), 0)
    max_exp = int(pow(1.01, level) * 1000)
    leveled_up = False
    while exp >= max_exp:
        level += 1
        exp -= max_exp
        max_exp = int(pow(1.01, level) * 1000)
        leveled_up = True
    user_scores["level"] = level
    user_scores["exp"] = exp
    return leveled_up


def apply_game_reward(
    user_scores: dict,
    chip_gain: int,
    *,
    exp_rate: float = 0.1,
    exp_gain: int | None = None,
    booster_gain: int | None = None,
    booster_exp_rate: float = 0.1,
) -> int:
    """Apply a mini-game reward and optionally amplify it with booster."""
    base_chip_gain = int(chip_gain)
    if base_chip_gain <= 0:
        return 0

    user_scores["chips"] = _coerce_int(user_scores.get("chips"), 0) + base_chip_gain
    exp_base = base_chip_gain if exp_gain is None else max(0, _coerce_int(exp_gain, 0))
    booster_base = base_chip_gain if booster_gain is None else max(0, _coerce_int(booster_gain, 0))
    user_scores["exp"] = _coerce_int(user_scores.get("exp"), 0) + int(exp_base * exp_rate)
    bonus = apply_booster(user_scores, booster_base, exp_rate=booster_exp_rate)
    apply_level_ups(user_scores)
    return bonus


def level_progress(user_scores: dict):
    """(레벨, 다음 레벨까지의 진행률 %)."""
    level = _coerce_int(user_scores.get("level"), 0)
    exp = _coerce_int(user_scores.get("exp"), 0)
    max_exp = int(pow(1.01, level) * 1000)
    percent = (
        round(exp / max_exp * 100, min(level // 232 + 1, 5))
        if max_exp
        else 0
    )
    return level, percent


def format_chip_balance(
    user_scores: dict,
    chip_gain: int = 0,
    booster_gain: int = 0,
) -> str:
    chips = _coerce_int(user_scores.get("chips"), 0)
    if chip_gain <= 0:
        balance = f"[보유칩: {chips}]"
    else:
        reward = f"+{int(chip_gain)}"
        if booster_gain > 0:
            reward += f"|+{int(booster_gain)}"
        balance = f"[보유칩: {chips} ({reward})]"

    level, percent = level_progress(user_scores)
    return f"{balance} [Lv.{level}|{percent}%]"


def _tune_connection(conn: sqlite3.Connection) -> sqlite3.Connection:
    # WAL: 쓰기 중에도 읽기가 막히지 않도록. busy_timeout: 락 경합 시
    # 곧바로 에러 내지 않고 잠깐 기다리도록(기본 5초보다 넉넉하게).
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _tune_connection(conn)
    return conn


_slot_ticket_column_ready = False


def _ensure_slot_ticket_column(conn: sqlite3.Connection) -> None:
    """user 테이블에 slot_ticket 컬럼이 없으면 한 번만 추가한다."""
    global _slot_ticket_column_ready
    if _slot_ticket_column_ready:
        return
    columns = conn.execute("PRAGMA table_info(user)").fetchall()
    if columns and not any(column["name"] == "slot_ticket" for column in columns):
        try:
            conn.execute(
                "ALTER TABLE user ADD COLUMN slot_ticket INTEGER NOT NULL DEFAULT 0"
            )
            conn.commit()
        except sqlite3.OperationalError:
            pass  # 다른 스레드가 먼저 추가한 경우
    _slot_ticket_column_ready = True


def _read_user(conn: sqlite3.Connection, user_id: str) -> dict:
    """유저 행을 읽어 정수 컬럼을 정규화해 돌려준다. 행이 없으면 새로 만든다(커밋은 호출자 몫)."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row is None:
        now = datetime.now()
        now_str = now.isoformat()
        yesterday_str = (now - timedelta(days=1)).isoformat()
        cursor.execute(
            'INSERT INTO user (user_id, last_update, daily_update, booster) VALUES (?, ?, ?, 0)',
            (user_id, now_str, yesterday_str)
        )
        cursor.execute("SELECT * FROM user WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
    res = dict(row) if row is not None else {}
    res["booster"] = _coerce_int(res.get("booster"), 0)
    res["chips"] = _coerce_int(res.get("chips"), 0)
    res["exp"] = _coerce_int(res.get("exp"), 0)
    res["level"] = _coerce_int(res.get("level"), 0)
    res["score"] = _coerce_int(res.get("score"), 0)
    res["active"] = _coerce_int(res.get("active"), 0)
    res["quiz_streak"] = _coerce_int(res.get("quiz_streak"), 0)
    res["typing"] = _coerce_int(res.get("typing"), 0)
    res["slot_ticket"] = _coerce_int(res.get("slot_ticket"), 0)
    # mahjong_played는 TEXT(DEFAULT NULL)라 정수 변환하지 않고 그대로 둔다
    return res


def load_scores(user_id: str):
    conn = get_db_connection()
    try:
        _ensure_slot_ticket_column(conn)
        res = _read_user(conn, user_id)
        conn.commit()
    finally:
        conn.close()
    return res


def _filter_score_updates(user_scores: dict) -> dict:
    filtered_updates = {}
    for k, v in user_scores.items():
        if k in {"user_id", "typing_accuracy_sum", "typing_accuracy_count"}:
            continue
        if v is None:
            continue
        if k in {
            "booster",
            "chips",
            "exp",
            "level",
            "score",
            "active",
            "quiz_streak",
            "typing",
            "slot_ticket",
        }:
            filtered_updates[k] = _coerce_int(v, 0)
        else:
            filtered_updates[k] = v
    return filtered_updates


def save_scores(user_id: str, user_scores: dict):
    filtered_updates = _filter_score_updates(user_scores)
    if not filtered_updates:
        return
    with sqlite3.connect(DB_PATH) as conn:
        _tune_connection(conn)
        cursor = conn.cursor()
        set_clause = ", ".join([f"{col} = ?" for col in filtered_updates])
        values = list(filtered_updates.values()) + [user_id]
        cursor.execute(f"UPDATE user SET {set_clause} WHERE user_id = ?", values)
        conn.commit()


def _write_changes(conn: sqlite3.Connection, user_id: str, before: dict, after: dict) -> None:
    """읽을 때와 달라진 컬럼만 UPDATE한다."""
    old = _filter_score_updates(before)
    new = _filter_score_updates(after)
    changed = {col: val for col, val in new.items() if old.get(col) != val}
    if not changed:
        return
    set_clause = ", ".join(f"{col} = ?" for col in changed)
    conn.execute(
        f"UPDATE user SET {set_clause} WHERE user_id = ?",
        [*changed.values(), user_id],
    )


def _update_users_sync(user_ids, fn):
    ids = sorted({str(user_id) for user_id in user_ids})
    conn = get_db_connection()
    try:
        _ensure_slot_ticket_column(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            states = {user_id: _read_user(conn, user_id) for user_id in ids}
            before = {user_id: dict(state) for user_id, state in states.items()}
            result = fn(states)
            if inspect.isawaitable(result):
                raise TypeError("update_user의 fn은 await 없는 동기 함수여야 합니다.")
            for user_id in ids:
                _write_changes(conn, user_id, before[user_id], states[user_id])
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return states, result
    finally:
        conn.close()


async def update_user(user_id, fn):
    """fn(user_scores)를 한 DB 트랜잭션 안에서 실행하고 바뀐 컬럼만 저장한다.

    fn은 user_scores(dict)를 직접 수정하는 동기 함수이며 반환값은 그대로 전달된다.
    반환: (갱신된 user_scores, fn의 반환값). fn이 예외를 던지면 아무것도 저장되지 않는다.
    """
    uid = str(user_id)
    states, result = await asyncio.to_thread(
        _update_users_sync, [uid], lambda st: fn(st[uid])
    )
    return states[uid], result


async def update_users(user_ids, fn):
    """여러 유저를 한 트랜잭션으로 갱신한다. fn({user_id: user_scores})."""
    states, result = await asyncio.to_thread(_update_users_sync, user_ids, fn)
    return states, result


def refresh_scores(user_scores: dict) -> dict:
    """점수 감쇠 + 레벨업 + 정수 보정. (async_check_level의 순수 함수 버전)"""
    calculate_score(user_scores)
    apply_level_ups(user_scores)
    user_scores["chips"] = _coerce_int(user_scores.get("chips"), 0)
    user_scores["booster"] = _coerce_int(user_scores.get("booster"), 0)
    return user_scores


def calculate_score(user_scores):
    if _coerce_int(user_scores.get("active", 0), 0) == 0:
        return user_scores
    current_time = datetime.now().replace(minute=0, second=0, microsecond=0)
    last_update = datetime.fromisoformat(user_scores["last_update"]).replace(minute=0, second=0, microsecond=0)
    hours_passed = int((current_time - last_update).total_seconds() // 3600)

    score = _coerce_int(user_scores.get("score"), 0)
    if hours_passed > 0:
        if score < 0:
            score = min(0, score + hours_passed)
        else:
            score = max(0, score - int(hours_passed / 2))
        user_scores["score"] = score
        user_scores["last_update"] = current_time.isoformat()
    return user_scores


async def async_load_scores(user_id: str):
    return await asyncio.to_thread(load_scores, str(user_id))


async def async_save_scores(user_id: str, user_scores: dict):
    await asyncio.to_thread(save_scores, str(user_id), user_scores)


async def async_check_level(user_id: str):
    user_scores, _ = await update_user(user_id, refresh_scores)
    return user_scores


def load_scores_all():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user ORDER BY score DESC")
    rows = cursor.fetchall()
    user_scores = {}
    for row in rows:
        user_data = dict(row)
        user_id = user_data.pop("user_id") 
        if user_data.get("booster") is None:
            user_data["booster"] = 0
        user_scores[user_id] = user_data
    conn.close()
    return user_scores


async def async_load_scores_all():
    return await asyncio.to_thread(load_scores_all)


def grant_daily_booster(user_scores: dict):
    today = datetime.now().date()
    last_date_str = user_scores.get("daily_update")
    last_date = None

    if last_date_str:
        try:
            if isinstance(last_date_str, str):
                last_date = datetime.fromisoformat(last_date_str).date()
            elif isinstance(last_date_str, datetime):
                last_date = last_date_str.date()
            elif isinstance(last_date_str, date):
                last_date = last_date_str
        except Exception:
            last_date = None

    if last_date is None:
        last_date = today - timedelta(days=1)

    if last_date >= today:
        return 0

    days_passed = max(1, (today - last_date).days)
    gained = calc_booster_gain(
        days_passed,
        _coerce_int(user_scores.get("level"), 0),
    )
    user_scores["booster"] = _coerce_int(user_scores.get("booster"), 0) + gained
    # 미니슬롯 티켓: 지급 일수(밀린 날짜 포함)만큼 1일 1장, 누적 상한 없음.
    user_scores["slot_ticket"] = (
        _coerce_int(user_scores.get("slot_ticket"), 0) + days_passed
    )
    user_scores["daily_update"] = today.isoformat()
    return gained


def _daily_grant(user_scores: dict) -> int:
    calculate_score(user_scores)
    return grant_daily_booster(user_scores)


async def async_grant_daily_booster(user_id: str):
    user_scores, gained = await update_user(user_id, _daily_grant)
    if gained <= 0:
        return None
    return gained, user_scores


def format_booster_gain(result) -> str:
    """Return the user-facing message for a newly granted daily booster."""
    if not result:
        return ""
    gained, user_scores = result
    return (
        f"출석 보상 부스터 **+{gained:,}** 획득! (보유: {user_scores['booster']:,})"
        " · 추가 부스터?"
    )