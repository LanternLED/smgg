import sqlite3
import asyncio
import math
from collections import defaultdict
from datetime import date, datetime, timedelta

DB_PATH = "scores.db"

# ── 칩 경제 개편: 고정 교환비 (레벨 무관) ──────────────────────────
CHIP_BUY_RATE = 100        # 1시간(score) → 100칩
CHIP_SELL_COST = 1111      # 1시간(score) 구매에 필요한 칩

# ── 부스터 ──────────────────────────────────────────────────────
BOOSTER_BASE_GAIN = 1000    # 하루 첫 상호작용 시 기본 지급량
BOOSTER_DECAY = 0.9         # 밀린 날짜의 감쇠율

# N%(미니게임 보상 부스팅 소모율) 곡선: 두 기준점을 지나는 로그 곡선
# 튜플 구조: (부스터 보유량 기준, 소모 가능 비율 N%)
BOOSTER_N_REF_LOW = (1000, 20)
BOOSTER_N_REF_HIGH = (100000, 500)
BOOSTER_N_MAX = BOOSTER_N_REF_HIGH[1]  # 최대 비율(500%)

# (비율2 - 비율1) / log(수치2 / 수치1)
_N_LOG_K = (BOOSTER_N_REF_HIGH[1] - BOOSTER_N_REF_LOW[1]) / math.log(
    BOOSTER_N_REF_HIGH[0] / BOOSTER_N_REF_LOW[0]
)

# ── 유저 단위 락 ────────────────────────────────────────────────
# load_scores → (메모리 상에서 수정) → save_scores 사이 구간은 DB
# 트랜잭션으로 보호되지 않으므로, 같은 유저에 대해 이 구간을 동시에
# 여러 커맨드가 실행하면 lost update가 발생할 수 있다.
# "점수 읽기 → 수정 → 저장"을 한 덩어리로 묶어야 하는 모든 커맨드는
# 아래 get_user_lock(user_id)로 감싸서 사용할 것.
_user_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def get_user_lock(user_id: str) -> asyncio.Lock:
    """유저별 asyncio.Lock을 반환한다. read-modify-write 구간 전체를
    이 락으로 감싸면 동시 실행으로 인한 점수 덮어쓰기를 막을 수 있다.

    사용 예:
        async with get_user_lock(user_id):
            user_scores = await async_load_scores(user_id)
            ... # user_scores 수정
            await async_save_scores(user_id, user_scores)
    """
    return _user_locks[str(user_id)]


def _coerce_int(value, default=0) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


def calc_booster_gain(days_passed: int) -> int:
    """밀린 일수만큼 감쇠 지급."""
    total = 0
    for i in range(days_passed):
        total += int(BOOSTER_BASE_GAIN * pow(BOOSTER_DECAY, i))
    return total


def booster_n_percent(booster: int) -> float:
    """보유 부스터량에 따른 소모 가능 비율(%)."""
    if booster <= 0:
        return 0.0
    ref_amount, ref_percent = BOOSTER_N_REF_LOW
    # 비율 계산 공식 적용
    n = ref_percent + _N_LOG_K * math.log(booster / ref_amount)
    return max(0.0, min(float(BOOSTER_N_MAX), n))


def apply_booster(user_scores: dict, chip_gain: int) -> int:
    """미니게임 획득 칩 보상에 부스터 소모 및 추가 지급 적용."""
    booster_val = _coerce_int(user_scores.get("booster"), 0)
    if chip_gain <= 0 or booster_val <= 0:
        return 0
    n_percent = booster_n_percent(booster_val)
    max_consumable = int(chip_gain * n_percent / 100)
    consumed = min(max_consumable, booster_val)
    if consumed <= 0:
        return 0
    user_scores["booster"] = booster_val - consumed
    user_scores["chips"] = _coerce_int(user_scores.get("chips"), 0) + consumed
    user_scores["exp"] = _coerce_int(user_scores.get("exp"), 0) + int(consumed * 0.1)
    return consumed


def apply_game_reward(user_scores: dict, chip_gain: int, *, exp_rate: float = 0.1) -> int:
    """Apply a mini-game reward and optionally amplify it with booster."""
    base_chip_gain = int(chip_gain)
    if base_chip_gain <= 0:
        return 0

    user_scores["chips"] = _coerce_int(user_scores.get("chips"), 0) + base_chip_gain
    user_scores["exp"] = _coerce_int(user_scores.get("exp"), 0) + int(base_chip_gain * exp_rate)
    return apply_booster(user_scores, base_chip_gain)


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


def load_scores(user_id: str):
    conn = get_db_connection()
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
        conn.commit()
        cursor.execute("SELECT * FROM user WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
    conn.close()
    res = dict(row) if row is not None else {}
    res["booster"] = _coerce_int(res.get("booster"), 0)
    res["chips"] = _coerce_int(res.get("chips"), 0)
    res["exp"] = _coerce_int(res.get("exp"), 0)
    res["level"] = _coerce_int(res.get("level"), 0)
    res["score"] = _coerce_int(res.get("score"), 0)
    res["active"] = _coerce_int(res.get("active"), 0)
    res["quiz_streak"] = _coerce_int(res.get("quiz_streak"), 0)
    res["lottery_pity"] = _coerce_int(res.get("lottery_pity"), 0)
    # mahjong_played는 TEXT(DEFAULT NULL)라 정수 변환하지 않고 그대로 둔다
    return res


def _filter_score_updates(user_scores: dict) -> dict:
    filtered_updates = {}
    for k, v in user_scores.items():
        if k == "user_id":
            continue
        if v is None:
            continue
        if k in {"booster", "chips", "exp", "level", "score", "active", "quiz_streak", "lottery_pity"}:
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
    user_scores = calculate_score(await async_load_scores(user_id))
    level = _coerce_int(user_scores.get('level'), 0)
    exp = _coerce_int(user_scores.get('exp'), 0)
    max_exp = int(pow(1.01, level) * 1000)
    islevelup = False
    while exp >= max_exp:
        level += 1
        islevelup = True
        exp -= max_exp
        max_exp = int(pow(1.01, level) * 1000)
    if islevelup:
        user_scores['level'] = level
        user_scores['exp'] = exp
    user_scores['chips'] = _coerce_int(user_scores.get('chips'), 0)
    user_scores['booster'] = _coerce_int(user_scores.get('booster'), 0)
    await async_save_scores(user_id, user_scores)
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
    gained = calc_booster_gain(days_passed)
    user_scores["booster"] = _coerce_int(user_scores.get("booster"), 0) + gained
    user_scores["daily_update"] = today.isoformat()
    return gained


async def async_grant_daily_booster(user_id: str):
    async with get_user_lock(user_id):
        user_scores = calculate_score(await async_load_scores(user_id))
        gained = grant_daily_booster(user_scores)
        if gained <= 0:
            return None
        await async_save_scores(user_id, user_scores)
        return gained, user_scores