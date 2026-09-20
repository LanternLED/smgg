import asyncio
import discord
from discord.ext import commands
import random
from typing import List, Optional, Tuple
from collections import Counter
from utils import (
    async_check_level, async_save_scores, async_grant_daily_booster,
    apply_game_reward, format_booster_gain,
)

TILE_EMOJI = {
    "1m":   "<:1man:1485342473407434895>", "9m":   "<:9man:1485342488158929067>",
    "1p":   "<:1tong:1485342818095468707>", "9p":   "<:9tong:1485342819328589919>",
    "1s":   "<:1sak:1485342689334395041>", "2s":   "<:2sak:1485342477153206412>",
    "3s":   "<:3sak:1485342478918881471>", "4s":   "<:4sak:1485342480382562569>",
    "5s":   "<:5sak:1485342482500685914>", "6s":   "<:6sak:1485342483939594270>",
    "7s":   "<:7sak:1485342485302481048>", "8s":   "<:8sak:1485342486409773158>",
    "9s":   "<:9sak:1485342691461173410>", "1z":   "<:dong:1485342694426415266>",
    "2z":   "<:nam:1485342491753451562>", "3z":   "<:ser:1485342821085876377>",
    "4z":   "<:buk:1485342892099637378>", "5z":   "<:baek:1485342944159334461>",
    "6z":   "<:bal:1485342972064043273>", "7z":   "<:zung:1485343005639577631>",
    "back": "<:back:1485343949609631814>",
}
 
TILE_EMOJI_DORA = {
    "1m":   "<a:dora_1m:000000000000000000>", "9m":   "<a:dora_9m:000000000000000000>",
    "1p":   "<a:dora_1p:000000000000000000>", "9p":   "<a:dora_9p:000000000000000000>",
    "1s":   "<a:dora_1s:000000000000000000>", "2s":   "<a:dora_2s:000000000000000000>",
    "3s":   "<a:dora_3s:000000000000000000>", "4s":   "<a:dora_4s:000000000000000000>",
    "5s":   "<a:dora_5s:000000000000000000>", "6s":   "<a:dora_6s:000000000000000000>",
    "7s":   "<a:dora_7s:000000000000000000>", "8s":   "<a:dora_8s:000000000000000000>",
    "9s":   "<a:dora_9s:000000000000000000>", "1z":   "<a:dora_ton:000000000000000000>",
    "2z":   "<a:dora_nan:000000000000000000>", "3z":   "<a:dora_sha:000000000000000000>",
    "4z":   "<a:dora_pei:000000000000000000>", "5z":   "<a:dora_hak:000000000000000000>",
    "6z":   "<a:dora_hat:000000000000000000>", "7z":   "<a:dora_chu:000000000000000000>",
}
 
TILE_LABEL = {
    "1m": "1만", "9m": "9만", "1p": "1통", "9p": "9통",
    "1s": "1삭", "2s": "2삭", "3s": "3삭", "4s": "4삭", "5s": "5삭",
    "6s": "6삭", "7s": "7삭", "8s": "8삭", "9s": "9삭",
    "1z": "東", "2z": "南", "3z": "西", "4z": "北",
    "5z": "白", "6z": "發", "7z": "中",
}
 
VALID_TILES: List[str] = [
    "1m", "9m", "1p", "9p",
    "1s", "2s", "3s", "4s", "5s", "6s", "7s", "8s", "9s",
    "1z", "2z", "3z", "4z", "5z", "6z", "7z",
]
 
FULL_DECK: List[str] = VALID_TILES * 4
 
_DORA_NEXT = {
    "1m": "9m", "9m": "1m", "1p": "9p", "9p": "1p",
    "1s": "2s", "2s": "3s", "3s": "4s", "4s": "5s", "5s": "6s",
    "6s": "7s", "7s": "8s", "8s": "9s", "9s": "1s",
    "1z": "2z", "2z": "3z", "3z": "4z", "4z": "1z",
    "5z": "6z", "6z": "7z", "7z": "5z",
}

async def async_judge_all(**kwargs):
    """Run the CPU-heavy mahjong judge_all in a thread to avoid blocking the event loop."""
    return await asyncio.to_thread(lambda: judge_all(**kwargs)) 

def get_dora(indicator: str) -> Optional[str]:
    return _DORA_NEXT.get(indicator)
 
def tile_emoji(tile: str) -> str:
    return TILE_EMOJI.get(tile, TILE_LABEL.get(tile, tile))
 
def tile_emoji_dora(tile: str) -> str:
    e = TILE_EMOJI_DORA.get(tile, "")
    if "000000000000000000" in e:
        return tile_emoji(tile)
    return e
 
def tiles_to_str(tiles: List[str]) -> str:
    return "".join(tile_emoji(t) for t in sorted(tiles, key=VALID_TILES.index))
 
def build_wall() -> dict:
    deck = FULL_DECK.copy()
    random.shuffle(deck)
    dead_wall = deck[:14]
    return {
        "draw_wall":       deck[14:],
        "rinshan_tiles":   dead_wall[0:4],
        "dora_indicators": dead_wall[4:9],
        "ura_indicators":  dead_wall[9:14],
        "rinshan_used":    0,
        "dora_count":      1,
    }
 
def deal_hand(wall: dict) -> List[str]:
    hand = wall["draw_wall"][:13]
    wall["draw_wall"] = wall["draw_wall"][13:]
    return hand
 
def draw_tile(wall: dict) -> Optional[str]:
    if not wall["draw_wall"]:
        return None
    return wall["draw_wall"].pop(0)
 
def draw_rinshan(wall: dict) -> Optional[str]:
    idx = wall["rinshan_used"]
    if idx >= 4:
        return None
    wall["rinshan_used"] += 1
    wall["dora_count"] = min(wall["rinshan_used"] + 1, 5)
    return wall["rinshan_tiles"][idx]
 
def get_active_doras(wall: dict) -> List[str]:
    return [d for ind in wall["dora_indicators"][:wall["dora_count"]]
            if (d := get_dora(ind))]
 
def get_ura_doras(wall: dict) -> List[str]:
    return [d for ind in wall["ura_indicators"][:wall["dora_count"]]
            if (d := get_dora(ind))]
 
def remaining_draws(wall: dict) -> int:
    return len(wall["draw_wall"])
 
class MahjongGame:
    def __init__(self, user_id: str):
        self.user_id   = user_id
        self.wall      = build_wall()
        self.hand: List[str]       = deal_hand(self.wall)
        self.draw: Optional[str]   = None
        self.kans: List[List[str]] = []
        self.discards: List[str]   = []
        self.hand_msg: Optional[discord.Message] = None
 
        self.riichi        = False
        self.double_riichi = False
        self.ippatsu       = False
        self.tsumo_tile: Optional[str] = None
        self.rinshan_win   = False
        self.finished      = False
        self.win           = False
        self.draw_count    = 0
 
    def do_draw(self) -> Optional[str]:
        tile = draw_tile(self.wall)
        if tile is None:
            self.finished = True
            return None
        self.draw = tile
        self.draw_count += 1
        return tile
 
    def do_rinshan_draw(self) -> Optional[str]:
        tile = draw_rinshan(self.wall)
        if tile is None:
            self.finished = True
            return None
        self.draw        = tile
        self.rinshan_win = True
        return tile
 
    def do_discard(self, tile: str) -> bool:
        if self.riichi:
            if tile != self.draw:
                return False
            self.discards.append(tile)
            self.draw    = None
            self.ippatsu = False
            return True
 
        if self.draw == tile:
            self.discards.append(tile)
            self.draw = None
        elif tile in self.hand:
            self.hand.remove(tile)
            self.discards.append(tile)
            if self.draw is not None:
                self.hand.append(self.draw)
                self.draw = None
        else:
            return False
 
        self.ippatsu = False
        return True
 
    def can_riichi(self) -> bool:
        if self.riichi or self.draw is None:
            return False
        full = self.hand + [self.draw]
        for candidate in set(full):
            test = full.copy()
            test.remove(candidate)
            if is_tenpai(test):
                return True
        return False
 
    def do_riichi(self, discard_tile: str) -> bool:
        if not self.can_riichi():
            return False
        if not self.do_discard(discard_tile):
            return False
        self.riichi  = True
        self.ippatsu = True
        if self.draw_count == 1:
            self.double_riichi = True
        return True
 
    def can_ankan(self) -> List[str]:
        if self.wall["rinshan_used"] >= 4:
            return []
        full   = self.hand + ([self.draw] if self.draw else [])
        counts = Counter(full)
        candidates = [t for t, c in counts.items() if c == 4]
        if self.riichi:
            if self.draw and counts[self.draw] == 4:
                return [self.draw]
            return []
        return candidates
 
    def do_ankan(self, tile: str) -> bool:
        if tile not in self.can_ankan():
            return False
        full = self.hand + ([self.draw] if self.draw else [])
        for _ in range(4):
            full.remove(tile)
        self.hand        = full
        self.draw        = None
        self.kans.append([tile] * 4)
        self.ippatsu     = False
        self.rinshan_win = False
        return True
 
    def can_tsumo(self) -> bool:
        if self.draw is None:
            return False
        return is_winning_hand(self.hand + [self.draw])
 
    def do_tsumo_win(self):
        self.tsumo_tile = self.draw
        self.finished   = True
        self.win        = True
 
    def score_tiles(self) -> dict:
        return {
            "hand":          self.hand + ([self.tsumo_tile] if self.tsumo_tile else []),
            "kans":          self.kans,
            "tsumo_tile":    self.tsumo_tile,
            "riichi":        self.riichi,
            "double_riichi": self.double_riichi,
            "ippatsu":       self.ippatsu,
            "rinshan_win":   self.rinshan_win,
            "doras":         get_active_doras(self.wall),
            "ura_doras":     get_ura_doras(self.wall) if self.riichi else [],
            "is_last_draw":  remaining_draws(self.wall) == 0,
        }
 
    def dora_str(self) -> str:
        result = ""
        for i, ind in enumerate(self.wall["dora_indicators"]):
            if i < self.wall["dora_count"]:
                result += tile_emoji_dora(ind)
            else:
                result += tile_emoji("back")
        return result
 
    def status_str(self) -> str:
        flags = []
        if self.double_riichi:
            flags.append("⚡더블리치")
        elif self.riichi:
            flags.append("⚡리치")
        if self.ippatsu:
            flags.append("✨일발")
        return " ".join(flags) if flags else "대기중"
 
def _is_sequential_suit(tile: str) -> bool:
    return tile.endswith("s")
 
def _tile_num(tile: str) -> int:
    return int(tile[0])
 
def _next_tile(tile: str) -> Optional[str]:
    if not _is_sequential_suit(tile):
        return None
    n = _tile_num(tile)
    if n >= 9:
        return None
    return f"{n+1}s"
 
def _try_decompose(counts: Counter, _melds: list) -> bool:
    remaining = [t for t, c in counts.items() if c > 0]
    if not remaining:
        return True
    tile = min(remaining, key=lambda t: VALID_TILES.index(t))
 
    if counts[tile] >= 3:
        counts[tile] -= 3
        if _try_decompose(counts, _melds):
            counts[tile] += 3
            return True
        counts[tile] += 3
 
    if _is_sequential_suit(tile):
        t2 = _next_tile(tile)
        t3 = _next_tile(t2) if t2 else None
        if t2 and t3 and counts[t2] > 0 and counts[t3] > 0:
            counts[tile] -= 1
            counts[t2]   -= 1
            counts[t3]   -= 1
            if _try_decompose(counts, _melds):
                counts[tile] += 1
                counts[t2]   += 1
                counts[t3]   += 1
                return True
            counts[tile] += 1
            counts[t2]   += 1
            counts[t3]   += 1
 
    return False
 
def _can_form_melds(tiles: List[str]) -> bool:
    return _try_decompose(Counter(tiles), [])
 
def _is_regular_win(hand14: List[str]) -> bool:
    counts = Counter(hand14)
    for tile in set(hand14):
        if counts[tile] >= 2:
            counts[tile] -= 2
            if _can_form_melds(list(counts.elements())):
                counts[tile] += 2
                return True
            counts[tile] += 2
    return False
 
def _is_chiitoitsu(hand14: List[str]) -> bool:
    counts = Counter(hand14)
    return len([t for t, c in counts.items() if c == 2]) == 7 and len(counts) == 7
 
_KOKUSHI_TILES = {"1m","9m","1p","9p","1s","9s","1z","2z","3z","4z","5z","6z","7z"}
 
def _is_kokushi(hand14: List[str]) -> bool:
    counts = Counter(hand14)
    if not _KOKUSHI_TILES.issubset(set(counts.keys())):
        return False
    return any(counts[t] >= 2 for t in _KOKUSHI_TILES)
 
def is_winning_hand(hand14: List[str]) -> bool:
    return _is_regular_win(hand14) or _is_chiitoitsu(hand14) or _is_kokushi(hand14)
 
def tenpai_tiles(hand13: List[str]) -> List[str]:
    return [t for t in VALID_TILES if is_winning_hand(hand13 + [t])]
 
def is_tenpai(hand13: List[str]) -> bool:
    return len(tenpai_tiles(hand13)) > 0
 
def is_kokushi_13(hand14: List[str], tsumo_tile: str) -> bool:
    counts = Counter(hand14)
    if not _KOKUSHI_TILES.issubset(set(counts.keys())):
        return False
    if counts[tsumo_tile] != 2:
        return False
    return all(counts[t] == 1 for t in _KOKUSHI_TILES if t != tsumo_tile)
 
def _get_jantai_candidates(hand14: List[str]) -> List[str]:
    counts = Counter(hand14)
    result = []
    for tile in set(hand14):
        if counts[tile] >= 2:
            counts[tile] -= 2
            if _can_form_melds(list(counts.elements())):
                result.append(tile)
            counts[tile] += 2
    return result
 
def is_suuankou_tanki(hand14: List[str], tsumo_tile: str, kans: List[List[str]]) -> bool:
    jantai_list = _get_jantai_candidates(hand14)
    if tsumo_tile in jantai_list:
        counts = Counter(hand14)
        counts[tsumo_tile] -= 2
        triplets = [t for t, c in counts.items() if c == 3]
        if len(kans) + len(triplets) == 4:
            return True
    return False
 
def _all_tiles(hand14: List[str], kans: List[List[str]]) -> List[str]:
    result = hand14.copy()
    for kan in kans:
        result += kan
    return result
 
def _check_suuankou(hand14, kans, tsumo_tile) -> Tuple[bool, bool]:
    counts   = Counter(hand14)
    tanki    = is_suuankou_tanki(hand14, tsumo_tile, kans)
    triplets = sum(1 for c in counts.values() if c >= 3)
    if triplets + len(kans) >= 4:
        return True, tanki
    return False, False
 
def _check_kokushi(hand14, tsumo_tile) -> Tuple[bool, bool]:
    if _is_kokushi(hand14):
        return True, is_kokushi_13(hand14, tsumo_tile)
    return False, False
 
def _check_daisangen(hand14, kans) -> bool:
    counts = Counter(_all_tiles(hand14, kans))
    return all(counts[t] >= 3 for t in ("5z", "6z", "7z"))
 
def _check_shousangen(hand14, kans) -> bool:
    counts   = Counter(_all_tiles(hand14, kans))
    triplets = sum(1 for t in ("5z","6z","7z") if counts[t] >= 3)
    pairs    = sum(1 for t in ("5z","6z","7z") if counts[t] == 2)
    return triplets == 2 and pairs == 1
 
def _check_tsuuiisou(hand14, kans) -> bool:
    return all(t.endswith("z") for t in _all_tiles(hand14, kans))
 
def _check_chinroutou(hand14, kans) -> bool:
    _ROUTOU = {"1m","9m","1p","9p","1s","9s"}
    return all(t in _ROUTOU for t in _all_tiles(hand14, kans))
 
def _check_ryuuiisou(hand14, kans) -> bool:
    _GREEN = {"2s","3s","4s","6s","8s","6z"}
    return all(t in _GREEN for t in _all_tiles(hand14, kans))
 
def _check_chuurenpoutou(hand14, kans, tsumo_tile=None) -> Tuple[bool, bool]:
    all_t = _all_tiles(hand14, kans)
    if not all(t.endswith("s") for t in all_t):
        return False, False
    counts = Counter(all_t)
    base   = {"1s":3,"2s":1,"3s":1,"4s":1,"5s":1,"6s":1,"7s":1,"8s":1,"9s":3}
    for t, min_c in base.items():
        if counts[t] < min_c:
            return False, False
    pure9 = False
    if tsumo_tile:
        tenpai_hand = hand14.copy()
        tenpai_hand.remove(tsumo_tile)
        pure9 = Counter(tenpai_hand) == Counter(base)
    return True, pure9
 
def _check_suukantsu(kans) -> bool:
    return len(kans) == 4
 
def _check_daisuushii(hand14, kans) -> bool:
    counts = Counter(_all_tiles(hand14, kans))
    return all(counts[t] >= 3 for t in ("1z","2z","3z","4z"))
 
def _check_shousuushii(hand14, kans) -> bool:
    counts   = Counter(_all_tiles(hand14, kans))
    triplets = sum(1 for t in ("1z","2z","3z","4z") if counts[t] >= 3)
    pairs    = sum(1 for t in ("1z","2z","3z","4z") if counts[t] == 2)
    return triplets == 3 and pairs == 1
 
def judge_yakuman(hand14, kans, tsumo_tile, riichi, ippatsu, rinshan_win, is_first_draw) -> dict:
    if not is_winning_hand(hand14):
        return {"yakuman": [], "total_multiplier": 0, "is_win": False}
 
    results = []
 
    if is_first_draw:
        results.append(("천화", 1))
 
    suua, tanki = _check_suuankou(hand14, kans, tsumo_tile)
    if suua:
        results.append(("쓰안커 단기", 2) if tanki else ("쓰안커", 1))
 
    koku, k13 = _check_kokushi(hand14, tsumo_tile)
    if koku:
        results.append(("국사무쌍 13면", 2) if k13 else ("국사무쌍", 1))
 
    if _check_daisuushii(hand14, kans):
        results.append(("대사희", 2))
    elif _check_shousuushii(hand14, kans):
        results.append(("소사희", 1))
 
    if _check_daisangen(hand14, kans):
        results.append(("대삼원", 1))
    elif _check_shousangen(hand14, kans):
        results.append(("소삼원", 1))
 
    if _check_tsuuiisou(hand14, kans):
        results.append(("자일색", 1))
    if _check_chinroutou(hand14, kans):
        results.append(("청노두", 1))
    if _check_ryuuiisou(hand14, kans):
        results.append(("녹일색", 1))
 
    chuu, pure9 = _check_chuurenpoutou(hand14, kans, tsumo_tile)
    if chuu:
        results.append(("구련보등 순정9면", 2) if pure9 else ("구련보등", 1))
 
    if _check_suukantsu(kans):
        results.append(("사깡쯔", 1))
 
    total = sum(m for _, m in results)
    if total == 0:
        return {"yakuman": [], "total_multiplier": 0, "is_win": False}
 
    return {"yakuman": results, "total_multiplier": total, "is_win": True}
 
MELD_KOUTSU     = "koutsu"
MELD_SHUNTSU    = "shuntsu"
MELD_KANTSU     = "kantsu"
HAND_CHIITOITSU = "chiitoitsu"
HAND_KOKUSHI    = "kokushi"
 
def _is_terminal_or_honor(tile: str) -> bool:
    return tile.endswith("z") or _tile_num(tile) in (1, 9)
 
def _make_meld(meld_type: str, tiles: list) -> dict:
    return {
        "type":  meld_type,
        "tiles": tiles,
        "is_terminal_or_honor": any(_is_terminal_or_honor(t) for t in tiles),
    }
 
def _extract_melds_from(counts: Counter) -> Optional[List[dict]]:
    remaining = [t for t, c in counts.items() if c > 0]
    if not remaining:
        return []
    tile = min(remaining, key=lambda t: VALID_TILES.index(t))
 
    if counts[tile] >= 3:
        counts[tile] -= 3
        sub = _extract_melds_from(counts)
        if sub is not None:
            counts[tile] += 3
            return [_make_meld(MELD_KOUTSU, [tile]*3)] + sub
        counts[tile] += 3
 
    if _is_sequential_suit(tile):
        t2 = _next_tile(tile)
        t3 = _next_tile(t2) if t2 else None
        if t2 and t3 and counts[t2] > 0 and counts[t3] > 0:
            counts[tile] -= 1
            counts[t2]   -= 1
            counts[t3]   -= 1
            sub = _extract_melds_from(counts)
            if sub is not None:
                counts[tile] += 1
                counts[t2]   += 1
                counts[t3]   += 1
                return [_make_meld(MELD_SHUNTSU, [tile, t2, t3])] + sub
            counts[tile] += 1
            counts[t2]   += 1
            counts[t3]   += 1
 
    return None
 
def decompose_hand(hand14: List[str], kans: List[List[str]]) -> Optional[dict]:
    kan_melds = [_make_meld(MELD_KANTSU, k) for k in kans]
 
    if _is_kokushi(hand14):
        return {"hand_type": HAND_KOKUSHI, "melds": [], "jantai": [], "pairs": []}
 
    if _is_chiitoitsu(hand14):
        counts = Counter(hand14)
        pairs  = [[t, t] for t, c in counts.items() if c == 2]
        return {"hand_type": HAND_CHIITOITSU, "melds": [], "jantai": [], "pairs": pairs}
 
    counts = Counter(hand14)
    for jantai_tile in sorted(set(hand14), key=lambda t: VALID_TILES.index(t)):
        if counts[jantai_tile] < 2:
            continue
        counts[jantai_tile] -= 2
        melds = _extract_melds_from(Counter(counts))
        counts[jantai_tile] += 2
        if melds is not None:
            return {
                "hand_type": "regular",
                "melds":     kan_melds + melds,
                "jantai":    [jantai_tile, jantai_tile],
                "pairs":     [],
            }
 
    return None
 
def _all_melds_and_jantai(decomp: dict) -> Tuple[List[dict], List[str]]:
    return decomp["melds"], decomp["jantai"]
 
def _count_koutsu(melds: List[dict]) -> int:
    return sum(1 for m in melds if m["type"] in (MELD_KOUTSU, MELD_KANTSU))
 
def _count_shuntsu(melds: List[dict]) -> int:
    return sum(1 for m in melds if m["type"] == MELD_SHUNTSU)
 
def _han_ippatsu(ippatsu: bool, has_riichi: bool) -> int:
    return 1 if (has_riichi and ippatsu) else 0
 
def _han_tanyao(hand14: List[str], kans: List[List[str]]) -> int:
    _CHUNCHAN = {"2s","3s","4s","5s","6s","7s","8s"}
    return 1 if all(t in _CHUNCHAN for t in _all_tiles(hand14, kans)) else 0
 
def _han_pinfu(decomp: dict, tsumo_tile: str) -> int:
    if decomp["hand_type"] != "regular":
        return 0
    melds, jantai = _all_melds_and_jantai(decomp)
    if _count_shuntsu(melds) != 4:
        return 0
    _YAKUHAI = {"1z", "5z", "6z", "7z"}
    if jantai and jantai[0] in _YAKUHAI:
        return 0
    for meld in melds:
        if meld["type"] == MELD_SHUNTSU:
            tiles = meld["tiles"]
            if tsumo_tile == tiles[0] and _tile_num(tiles[0]) != 1:
                return 1
            if tsumo_tile == tiles[2] and _tile_num(tiles[2]) != 9:
                return 1
    return 0
 
def _han_iipeiko(decomp: dict) -> int:
    if decomp["hand_type"] != "regular":
        return 0
    melds, _ = _all_melds_and_jantai(decomp)
    shuntsus = [tuple(m["tiles"]) for m in melds if m["type"] == MELD_SHUNTSU]
    return 1 if any(c >= 2 for c in Counter(shuntsus).values()) else 0
 
def _han_yakuhai(decomp: dict) -> List[Tuple[str, int]]:
    if decomp["hand_type"] != "regular":
        return []
    melds, _ = _all_melds_and_jantai(decomp)
    _YAKUHAI_LABEL = {"1z":"동","5z":"백","6z":"발","7z":"중"}
    return [
        (f"역패({_YAKUHAI_LABEL[m['tiles'][0]]})", 1)
        for m in melds
        if m["type"] in (MELD_KOUTSU, MELD_KANTSU) and m["tiles"][0] in _YAKUHAI_LABEL
    ]
 
def _han_dora(hand14, kans, doras, ura_doras) -> int:
    counts = Counter(_all_tiles(hand14, kans))
    return sum(counts[d] for d in doras) + sum(counts[d] for d in ura_doras)
 
def _han_toitoi(decomp: dict) -> int:
    if decomp["hand_type"] != "regular":
        return 0
    melds, _ = _all_melds_and_jantai(decomp)
    return 2 if _count_koutsu(melds) == 4 else 0
 
def _han_chiitoitsu(decomp: dict) -> int:
    return 2 if decomp["hand_type"] == HAND_CHIITOITSU else 0
 
def _han_chanta(decomp: dict) -> int:
    if decomp["hand_type"] in (HAND_CHIITOITSU, HAND_KOKUSHI):
        return 0
    melds, jantai = _all_melds_and_jantai(decomp)
    if not jantai or not _is_terminal_or_honor(jantai[0]):
        return 0
    if not all(m["is_terminal_or_honor"] for m in melds):
        return 0
    if _count_shuntsu(melds) == 0:
        return 0
    return 2
 
def _han_ittsu(decomp: dict) -> int:
    if decomp["hand_type"] != "regular":
        return 0
    melds, _ = _all_melds_and_jantai(decomp)
    shuntsus = [m["tiles"] for m in melds if m["type"] == MELD_SHUNTSU]
    if (any(s[0] == "1s" for s in shuntsus) and
        any(s[0] == "4s" for s in shuntsus) and
        any(s[0] == "7s" for s in shuntsus)):
        return 2
    return 0
 
def _han_sanankou(decomp: dict) -> int:
    if decomp["hand_type"] != "regular":
        return 0
    melds, _ = _all_melds_and_jantai(decomp)
    return 2 if _count_koutsu(melds) == 3 else 0
 
def _han_shousangen_normal(decomp: dict) -> int:
    if decomp["hand_type"] != "regular":
        return 0
    melds, jantai = _all_melds_and_jantai(decomp)
    _SANGEN = {"5z","6z","7z"}
    triplets = sum(1 for m in melds
                   if m["type"] in (MELD_KOUTSU, MELD_KANTSU) and m["tiles"][0] in _SANGEN)
    pairs = 1 if jantai and jantai[0] in _SANGEN else 0
    return 2 if triplets == 2 and pairs == 1 else 0
 
def _han_honroutou(hand14, kans) -> int:
    _RH = {"1m","9m","1p","9p","1s","9s","1z","2z","3z","4z","5z","6z","7z"}
    return 2 if all(t in _RH for t in _all_tiles(hand14, kans)) else 0
 
def _han_honitsu(hand14, kans) -> int:
    suits = {t[-1] for t in _all_tiles(hand14, kans)}
    if suits == {"z"}:
        return 0
    return 3 if (len(suits - {"z"}) == 1 and "z" in suits) else 0
 
def _han_junchan(decomp: dict) -> int:
    if decomp["hand_type"] in (HAND_CHIITOITSU, HAND_KOKUSHI):
        return 0
    melds, jantai = _all_melds_and_jantai(decomp)
    if not jantai:
        return 0
    _TERMINALS = {"1m","9m","1p","9p","1s","9s"}
    if jantai[0] not in _TERMINALS:
        return 0
    for m in melds:
        if not any(t in _TERMINALS for t in m["tiles"]) or any(t.endswith("z") for t in m["tiles"]):
            return 0
    if _count_shuntsu(melds) == 0:
        return 0
    return 3
 
def _han_ryanpeiko(decomp: dict) -> int:
    if decomp["hand_type"] != "regular":
        return 0
    melds, _ = _all_melds_and_jantai(decomp)
    shuntsus = [tuple(m["tiles"]) for m in melds if m["type"] == MELD_SHUNTSU]
    return 3 if sum(1 for c in Counter(shuntsus).values() if c >= 2) >= 2 else 0
 
def _han_chinitsu(hand14, kans) -> int:
    suits = {t[-1] for t in _all_tiles(hand14, kans)}
    return 6 if (len(suits) == 1 and "z" not in suits) else 0
 
def judge_han(
    hand14, kans, tsumo_tile,
    riichi, double_riichi, ippatsu, rinshan_win,
    is_last_draw, doras, ura_doras,
) -> dict:
    if not is_winning_hand(hand14):
        return {"yaku": [], "total_han": 0}
 
    decomp = decompose_hand(hand14, kans)
    if decomp is None:
        return {"yaku": [], "total_han": 0}
 
    yaku = []
    has_riichi = riichi or double_riichi
 
    if double_riichi: yaku.append(("더블리치", 2))
    elif riichi: yaku.append(("리치", 1))
 
    if _han_ippatsu(ippatsu, has_riichi):
        yaku.append(("일발", 1))
 
    yaku.append(("멘젠쯔모", 1))
 
    h = _han_tanyao(hand14, kans)
    if h: yaku.append(("탕야오", h))
 
    h = _han_pinfu(decomp, tsumo_tile)
    if h: yaku.append(("핑후", h))
 
    for entry in _han_yakuhai(decomp):
        yaku.append(entry)
 
    if is_last_draw:
        yaku.append(("하저로어", 1))
 
    if rinshan_win:
        yaku.append(("영상개화", 1))
 
    h = _han_toitoi(decomp)
    if h: yaku.append(("또이또이", h))
 
    h = _han_chiitoitsu(decomp)
    if h: yaku.append(("치또이츠", h))
 
    junchan = _han_junchan(decomp)
    if junchan:
        yaku.append(("준찬타", junchan))
    else:
        h = _han_chanta(decomp)
        if h: yaku.append(("찬타", h))
 
    h = _han_ittsu(decomp)
    if h: yaku.append(("일기통관", h))
 
    h = _han_sanankou(decomp)
    if h: yaku.append(("산안커", h))
 
    h = _han_shousangen_normal(decomp)
    if h: yaku.append(("소삼원", h))
 
    h = _han_honroutou(hand14, kans)
    if h: yaku.append(("혼노두", h))
 
    ryanpeiko = _han_ryanpeiko(decomp)
    if ryanpeiko:
        yaku.append(("량페코", ryanpeiko))
    else:
        h = _han_iipeiko(decomp)
        if h: yaku.append(("이페코", h))
 
    chinitsu = _han_chinitsu(hand14, kans)
    if chinitsu:
        yaku = [(n, v) for n, v in yaku if n != "혼일색"]
        yaku.append(("청일색", chinitsu))
    else:
        h = _han_honitsu(hand14, kans)
        if h: yaku.append(("혼일색", h))
 
    dora_han = _han_dora(hand14, kans, doras, ura_doras)
    if dora_han:
        yaku.append(("도라", dora_han))
 
    non_dora = [y for y in yaku if y[0] != "도라"]
    if not non_dora:
        return {"yaku": [], "total_han": 0}
 
    return {"yaku": yaku, "total_han": sum(v for _, v in yaku)}
 
def is_kazoe_yakuman(total_han: int) -> bool:
    return total_han >= 13
 
def judge_all(
    hand14, kans, tsumo_tile,
    riichi, double_riichi, ippatsu, rinshan_win,
    is_first_draw, is_last_draw, doras, ura_doras,
) -> dict:
    if not is_winning_hand(hand14):
        return _no_win()
 
    ym = judge_yakuman(hand14, kans, tsumo_tile, riichi, ippatsu, rinshan_win, is_first_draw)
    if ym["is_win"]:
        return {
            "result_type":      "yakuman",
            "yakuman":          ym["yakuman"],
            "yaku":             [],
            "total_multiplier": ym["total_multiplier"],
            "total_han":        ym["total_multiplier"] * 13,
            "is_win":           True,
            "reward_eligible":  True,
        }
 
    hr = judge_han(hand14, kans, tsumo_tile, riichi, double_riichi,
                   ippatsu, rinshan_win, is_last_draw, doras, ura_doras)
 
    if not hr["yaku"]:
        return {
            "result_type": "no_yaku", "yakuman": [], "yaku": [],
            "total_multiplier": 0, "total_han": 0,
            "is_win": True, "reward_eligible": False,
        }
 
    total_han = hr["total_han"]
 
    if is_kazoe_yakuman(total_han):
        return {
            "result_type":      "kazoe",
            "yakuman":          [("헤아림역만", 1)],
            "yaku":             hr["yaku"],
            "total_multiplier": 1,
            "total_han":        total_han,
            "is_win":           True,
            "reward_eligible":  True,
        }
 
    return {
        "result_type": "normal", "yakuman": [], "yaku": hr["yaku"],
        "total_multiplier": 0, "total_han": total_han,
        "is_win": True, "reward_eligible": False,
    }
 
def _no_win() -> dict:
    return {
        "result_type": "no_win", "yakuman": [], "yaku": [],
        "total_multiplier": 0, "total_han": 0,
        "is_win": False, "reward_eligible": False,
    }
 
def _mahjong_hand_str(game: MahjongGame) -> str:
    hand  = tiles_to_str(sorted(game.hand, key=lambda t: VALID_TILES.index(t)))
    draw  = tile_emoji(game.draw) if game.draw else ""
    kan   = "  ".join(tiles_to_str(k) for k in game.kans) if game.kans else ""
    parts = [p for p in [hand, draw, kan] if p]
    return "  ".join(parts)
 
def _mahjong_info_str(game: MahjongGame, title: str = "🀄 마작 도전") -> str:
    return (
        f"**{title}**\n"
        f"도라: {game.dora_str()}  패산: {remaining_draws(game.wall)}장  {game.status_str()}"
    )
 
def _dora_display(game: MahjongGame) -> str:
    dora_str = "".join(
        tile_emoji_dora(t) if i < game.wall["dora_count"] else tile_emoji("back")
        for i, t in enumerate(game.wall["dora_indicators"])
    )
    ura_str = "".join(
        tile_emoji_dora(t) if i < game.wall["dora_count"] else tile_emoji("back")
        for i, t in enumerate(game.wall["ura_indicators"])
    ) if game.riichi else tile_emoji("back") * 5
    return f"도라{dora_str} 뒷도라{ura_str}"
 
def mahjong_result_msg(game: MahjongGame, result: dict, reward: int, bonus: int = 0) -> str:
    dora_line    = _dora_display(game)
    remaining    = remaining_draws(game.wall)
    bonus_str    = f" (부스터 +{bonus:,})" if bonus > 0 else ""

    if result["result_type"] == "yakuman":
        yaku_str = " / ".join(
            f"{'【더블】' if m == 2 else '【역만】'}{name}"
            for name, m in result["yakuman"]
        )
        return (
            f"🀄 **역만 화료!** {yaku_str}\n"
            f"{dora_line}\n"
            f"패산 {remaining}장 / {result['total_multiplier']}배 / **{reward:,}칩**{bonus_str}"
        )

    if result["result_type"] == "kazoe":
        yaku_str = " / ".join(f"{n} {v}판" for n, v in result["yaku"])
        return (
            f"🀄 **헤아림역만!** ({result['total_han']}판)\n"
            f"{yaku_str}\n"
            f"{dora_line}\n"
            f"패산 {remaining}장 / **{reward:,}칩**{bonus_str}"
        )

    if result["result_type"] == "normal":
        yaku_str = " / ".join(f"{n} {v}판" for n, v in result["yaku"])
        return (
            f"✅ **화료** ({result['total_han']}판 — 역만 미달, 보상 없음)\n"
            f"{yaku_str}\n"
            f"{dora_line}"
        )

    if result["result_type"] == "no_yaku":
        return f"❌ **역 없음** — 화료 패형이지만 역이 없습니다.\n{dora_line}"

    return "❌ 판정 오류"
 
def mahjong_fail_msg(game: MahjongGame) -> str:
    hand_display = tiles_to_str(sorted(game.hand, key=lambda t: VALID_TILES.index(t)))
    waits = tenpai_tiles(game.hand)
    wait_line = f"\n대기패: {tiles_to_str(waits)} (텐파이였지만 패산 소진)" if waits else ""
    return f"**패산 소진 — 유국**\n{hand_display}{wait_line}"
 
def mahjong_calc_reward(yakuman_multiplier: int, remaining: int) -> int:
    base_reward = yakuman_multiplier * 100 + remaining
    return base_reward
 
active_mahjong_games: dict = {}
 
class MahjongDiscardView(discord.ui.View):
    def __init__(self, game: MahjongGame, message: discord.Message):
        super().__init__(timeout=180)
        self.game    = game
        self.message = message

        sorted_hand = sorted(game.hand, key=lambda t: VALID_TILES.index(t))
        last_row    = (len(sorted_hand) - 1) // 4

        for i, tile in enumerate(sorted_hand):
            btn = discord.ui.Button(
                label     = TILE_LABEL.get(tile, tile),
                custom_id = f"mj_discard_{i}_{tile}",
                style     = discord.ButtonStyle.secondary,
                disabled  = game.riichi,
                row       = i // 4
            )
            btn.callback = self._make_discard_cb(tile)
            self.add_item(btn)

        if game.draw:
            tsumo_available = game.riichi and game.can_tsumo()
            draw_btn = discord.ui.Button(
                label     = f"★{TILE_LABEL.get(game.draw, game.draw)}",
                custom_id = f"mj_discard_draw_{game.draw}",
                style     = discord.ButtonStyle.primary,
                disabled  = tsumo_available,
                row       = last_row
            )
            draw_btn.callback = self._make_discard_cb(game.draw)
            self.add_item(draw_btn)

        tsumo_ok  = game.can_tsumo()
        riichi_ok = game.can_riichi()
        ankan_ok  = bool(game.can_ankan())
        action_row = min(last_row + 1, 4)

        for label, cid, ok, style_on in [
            ("쯔모", "mj_tsumo",  tsumo_ok,  discord.ButtonStyle.success),
            ("리치", "mj_riichi", riichi_ok, discord.ButtonStyle.danger),
            ("안깡", "mj_ankan",  ankan_ok,  discord.ButtonStyle.primary),
        ]:
            btn = discord.ui.Button(
                label     = label,
                custom_id = cid,
                style     = style_on if ok else discord.ButtonStyle.secondary,
                disabled  = not ok,
                row       = action_row
            )
            if cid == "mj_tsumo":   btn.callback = self._tsumo_cb
            elif cid == "mj_riichi": btn.callback = self._riichi_cb
            else:                    btn.callback = self._ankan_cb
            self.add_item(btn)
 
    async def _check_user(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.game.user_id:
            await interaction.response.send_message("이 게임은 호출자만 조작할 수 있습니다.", ephemeral=True)
            return False
        await async_grant_daily_booster(self.game.user_id)
        return True
 
    def _make_discard_cb(self, tile: str):
        async def callback(interaction: discord.Interaction):
            if not await self._check_user(interaction):
                return
            if not self.game.do_discard(tile):
                await interaction.response.send_message("버릴 수 없는 패입니다.", ephemeral=True)
                return
            self.stop()
            await interaction.response.defer()
            await _mahjong_next_turn(interaction, self.game, self.message)
        return callback
 
    async def _tsumo_cb(self, interaction: discord.Interaction):
        if not await self._check_user(interaction):
            return
        self.game.do_tsumo_win()
        self.stop()
        await interaction.response.defer()
        await _mahjong_end(interaction, self.game, self.message)
 
    async def _riichi_cb(self, interaction: discord.Interaction):
        if not await self._check_user(interaction):
            return
        self.stop()
        await interaction.response.defer()
        view = MahjongRiichiSelectView(self.game, self.message)
        await self.message.edit(
            content=_mahjong_info_str(self.game, "🀄 리치 — 버릴 패 선택"),
            view=view
        )
 
    async def _ankan_cb(self, interaction: discord.Interaction):
        if not await self._check_user(interaction):
            return
        candidates = self.game.can_ankan()
        self.stop()
        await interaction.response.defer()
        if len(candidates) == 1:
            self.game.do_ankan(candidates[0])
            tile = self.game.do_rinshan_draw()
            if tile is None:
                await _mahjong_end_empty(interaction, self.game, self.message)
                return
            if self.game.hand_msg:
                await self.game.hand_msg.edit(content=_mahjong_hand_str(self.game))
            view = MahjongDiscardView(self.game, self.message)
            await self.message.edit(
                content=_mahjong_info_str(self.game, "🀄 안깡 — 영상패 드로우"),
                view=view
            )
        else:
            view = MahjongAnkanSelectView(self.game, self.message, candidates)
            await self.message.edit(
                content=_mahjong_info_str(self.game, "🀄 안깡할 패 선택"),
                view=view
            )
 
    async def on_timeout(self):
        active_mahjong_games.pop(self.game.user_id, None)
        try:
            if self.game.hand_msg:
                await self.game.hand_msg.edit(content="⏰ 시간 초과")
            await self.message.edit(content="", view=None)
        except Exception:
            pass
 
class MahjongRiichiSelectView(discord.ui.View):
    def __init__(self, game: MahjongGame, message: discord.Message):
        super().__init__(timeout=60)
        self.game    = game
        self.message = message
        full = game.hand + ([game.draw] if game.draw else [])
 
        for i, tile in enumerate(sorted(full, key=lambda t: VALID_TILES.index(t))):
            test = full.copy()
            test.remove(tile)
            can = is_tenpai(test)
            btn = discord.ui.Button(
                label     = TILE_LABEL.get(tile, tile),
                custom_id = f"mj_riichi_sel_{i}_{tile}",
                style     = discord.ButtonStyle.primary if can else discord.ButtonStyle.secondary,
                disabled  = not can,
                row       = i // 4
            )
            btn.callback = self._make_cb(tile)
            self.add_item(btn)
 
    def _make_cb(self, tile: str):
        async def callback(interaction: discord.Interaction):
            if str(interaction.user.id) != self.game.user_id:
                await interaction.response.send_message("호출자만 조작할 수 있습니다.", ephemeral=True)
                return
            await async_grant_daily_booster(self.game.user_id)
            self.game.do_riichi(tile)
            self.stop()
            await interaction.response.defer()
            await _mahjong_next_turn(interaction, self.game, self.message)
        return callback
 
class MahjongAnkanSelectView(discord.ui.View):
    def __init__(self, game: MahjongGame, message: discord.Message, candidates: list):
        super().__init__(timeout=60)
        self.game    = game
        self.message = message
        for tile in candidates:
            btn = discord.ui.Button(
                label     = TILE_LABEL.get(tile, tile),
                custom_id = f"mj_ankan_sel_{tile}",
                style     = discord.ButtonStyle.primary
            )
            btn.callback = self._make_cb(tile)
            self.add_item(btn)
 
    def _make_cb(self, tile: str):
        async def callback(interaction: discord.Interaction):
            if str(interaction.user.id) != self.game.user_id:
                await interaction.response.send_message("호출자만 조작할 수 있습니다.", ephemeral=True)
                return
            await async_grant_daily_booster(self.game.user_id)
            self.game.do_ankan(tile)
            rinshan = self.game.do_rinshan_draw()
            self.stop()
            await interaction.response.defer()
            if rinshan is None:
                await _mahjong_end_empty(interaction, self.game, self.message)
                return
            if self.game.hand_msg:
                await self.game.hand_msg.edit(content=_mahjong_hand_str(self.game))
            view = MahjongDiscardView(self.game, self.message)
            await self.message.edit(
                content=_mahjong_info_str(self.game, "🀄 안깡 — 영상패 드로우"),
                view=view
            )
        return callback
 
class MahjongRiichiWaitView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="자동 진행 중...",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            row=0
        ))
 
async def _mahjong_next_turn(interaction, game: MahjongGame, message: discord.Message):
    tile = game.do_draw()
    if tile is None:
        await _mahjong_end_empty(interaction, game, message)
        return
 
    if game.hand_msg:
        await game.hand_msg.edit(content=_mahjong_hand_str(game))
 
    if game.riichi:
        if game.can_tsumo():
            view = MahjongDiscardView(game, message)
            await message.edit(content=_mahjong_info_str(game), view=view)
        else:
            await message.edit(content=_mahjong_info_str(game), view=MahjongRiichiWaitView())
            await asyncio.sleep(1)
            game.do_discard(game.draw)
            await _mahjong_next_turn(interaction, game, message)
    else:
        view = MahjongDiscardView(game, message)
        await message.edit(content=_mahjong_info_str(game), view=view)
 
async def _mahjong_end(interaction, game: MahjongGame, message: discord.Message):
    user_id = game.user_id
    data    = game.score_tiles()
    result  = await async_judge_all(
        hand14        = data["hand"],
        kans          = data["kans"],
        tsumo_tile    = data["tsumo_tile"],
        riichi        = data["riichi"],
        double_riichi = data["double_riichi"],
        ippatsu       = data["ippatsu"],
        rinshan_win   = data["rinshan_win"],
        is_first_draw = len(game.discards) == 0 and len(game.kans) == 0,
        is_last_draw  = data["is_last_draw"],
        doras         = data["doras"],
        ura_doras     = data["ura_doras"],
    )
    active_mahjong_games.pop(user_id, None)

    if game.hand_msg:
        full_hand = game.hand + ([game.tsumo_tile] if game.tsumo_tile else [])
        await game.hand_msg.edit(
            content=tiles_to_str(sorted(full_hand, key=lambda t: VALID_TILES.index(t)))
        )

    reward = 0
    if result["reward_eligible"]:
        reward = mahjong_calc_reward(result["total_multiplier"], remaining_draws(game.wall))

    user_scores = await async_check_level(user_id)
    bonus = 0
    if result["reward_eligible"]:
        bonus = apply_game_reward(user_scores, reward, exp_rate=0.25)

    await async_save_scores(user_id, user_scores)

    await message.edit(content=mahjong_result_msg(game, result, reward, bonus), view=None)
 
async def _mahjong_end_empty(interaction, game: MahjongGame, message: discord.Message):
    user_id = game.user_id
    await async_check_level(user_id)
    active_mahjong_games.pop(user_id, None)

    if game.hand_msg:
        await game.hand_msg.edit(content=_mahjong_hand_str(game))
    await message.edit(content=mahjong_fail_msg(game), view=None)

class MahjongCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="마작")
    async def mahjong_start(self, ctx):
        user_id = str(ctx.author.id)
        booster_result = await async_grant_daily_booster(user_id)
        booster_notice = format_booster_gain(booster_result)
        if booster_notice:
            await ctx.send(f"{ctx.author.mention} {booster_notice}")
        await async_check_level(user_id)

        if user_id in active_mahjong_games:
            await ctx.send(f"{ctx.author.mention} 이미 진행 중인 게임이 있습니다.")
            return

        game = MahjongGame(user_id)
        active_mahjong_games[user_id] = game
    
        tile = game.do_draw()
        if tile is None:
            await ctx.send("패산 오류가 발생했습니다.")
            active_mahjong_games.pop(user_id, None)
            return
    
        hand_msg      = await ctx.send(content=_mahjong_hand_str(game))
        game.hand_msg = hand_msg
        msg           = await ctx.send(content=_mahjong_info_str(game, "🀄 마작 도전 시작!"))
        view          = MahjongDiscardView(game, msg)
        await msg.edit(view=view)

async def setup(bot):
    await bot.add_cog(MahjongCog(bot))