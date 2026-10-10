from dataclasses import dataclass
import random
import copy

# --- 데이터 테이블 ---
# 주의: FRUITS 목록을 바꾸면 slot.py의 GOLDEN_EMOJIS도 함께 갱신해야 함
# (골든 처리는 FRUITS에 속한 심볼에만 적용됨)
FRUITS = ['apple', 'watermelon', 'carrot']
NON_FRUITS = ['cake', 'cookie', 'bread', 'baked_potato', 'potato', 'poison']

# 등장 가중치 (비과일의 확률을 높이고, 과일은 낮춰 밸런스 조절)
SYMBOL_WEIGHTS = {
    'cake': 2, 'cookie': 4, 'bread': 6,
    'watermelon': 8, 'apple': 10, 'carrot': 12,
    'baked_potato': 15, 'potato': 20, 'poison': 25
}

# 심볼 기본 가치
SYMBOL_VALUES = {
    'cake': 7000, 'cookie': 5000, 'bread': 3000,
    'watermelon': 2000, 'apple': 1600, 'carrot': 1200,
    'baked_potato': 800, 'potato': 600, 'poison': 0
}

# 과일 리롤용 가중치 추출
FRUIT_WEIGHTS = [SYMBOL_WEIGHTS[f] for f in FRUITS]
SIMULATION_SYMBOLS = tuple(SYMBOL_WEIGHTS)
SIMULATION_WEIGHTS = tuple(SYMBOL_WEIGHTS.values())
SIMULATION_SYMBOL_IDS = {
    symbol: index for index, symbol in enumerate(SIMULATION_SYMBOLS)
}
SIMULATION_FRUIT_IDS = tuple(SIMULATION_SYMBOL_IDS[symbol] for symbol in FRUITS)
SIMULATION_SYMBOL_VALUES = tuple(
    SYMBOL_VALUES[symbol] for symbol in SIMULATION_SYMBOLS
)
SIMULATION_POISON_ID = SIMULATION_SYMBOL_IDS["poison"]

# 패턴 배수: 두 슬롯이 같은 패턴에는 같은 배율을 사용한다.
MULTIPLIERS = {
    'V3': 3, 'D3': 3, 'H3': 3, 'S2x2': 3,
    'H4': 5, 'H5': 7, 'H6': 9,
    'S3x3': 6, 'S4x4': 9, 'S5x5': 12,
}

class SlotCell:
    def __init__(self, symbol):
        self.symbol = symbol
        self.is_golden = False

class SlotEngine:
    def __init__(self, rows=3, cols=5, multipliers=None):
        self.rows = rows
        self.cols = cols
        self.multipliers = dict(MULTIPLIERS if multipliers is None else multipliers)
        self.board = []
        self.base_board = []
        self.base_match_cache = []
        self.golden_match_cache = []
        self.winning_positions = []  # 마지막 calculate_reward() 결과의 당첨(또는 버스트) 좌표

    def generate_board(self, *, preserve_snapshot=True):
        symbols = list(SYMBOL_WEIGHTS.keys())
        weights = list(SYMBOL_WEIGHTS.values())
        self.board = [
            [SlotCell(random.choices(symbols, weights=weights, k=1)[0]) for _ in range(self.cols)]
            for _ in range(self.rows)
        ]
        if preserve_snapshot:
            self.base_board = copy.deepcopy(self.board)
        self.base_match_cache = []
        self.golden_match_cache = []

    def _matches_of_board(self, board):
        matches = []
        rows = len(board)
        cols = len(board[0])

        for r in range(rows - 2):
            for c in range(cols):
                sym = board[r][c].symbol
                if board[r + 1][c].symbol == sym == board[r + 2][c].symbol:
                    matches.append({
                        'type': 'V3', 'symbol': sym,
                        'cells': [(r, c), (r + 1, c), (r + 2, c)],
                    })

        for r in range(rows - 2):
            for c in range(cols - 2):
                down_right = [(r + offset, c + offset) for offset in range(3)]
                sym = board[down_right[0][0]][down_right[0][1]].symbol
                if all(board[row][col].symbol == sym for row, col in down_right[1:]):
                    matches.append({'type': 'D3', 'symbol': sym, 'cells': down_right})

        for r in range(rows - 2):
            for c in range(cols - 2):
                up_right = [(r + 2 - offset, c + offset) for offset in range(3)]
                sym = board[up_right[0][0]][up_right[0][1]].symbol
                if all(board[row][col].symbol == sym for row, col in up_right[1:]):
                    matches.append({'type': 'D3', 'symbol': sym, 'cells': up_right})

        for r in range(rows):
            symbols = [board[r][c].symbol for c in range(cols)]
            c = 0
            while c < cols:
                sym = symbols[c]
                streak = 1
                cells = [(r, c)]
                next_c = c + 1
                while next_c < cols and symbols[next_c] == sym:
                    streak += 1
                    cells.append((r, next_c))
                    next_c += 1

                if streak >= 3:
                    matches.append({'type': f'H{streak}', 'symbol': sym, 'cells': cells})
                c = next_c

        for size in range(2, min(rows, cols) + 1):
            for r in range(rows - size + 1):
                for c in range(cols - size + 1):
                    sym = board[r][c].symbol
                    is_match = True
                    for row in range(r, r + size):
                        for col in range(c, c + size):
                            if board[row][col].symbol != sym:
                                is_match = False
                                break
                        if not is_match:
                            break

                    if is_match:
                        cells = [
                            (row, col)
                            for row in range(r, r + size)
                            for col in range(c, c + size)
                        ]
                        matches.append({
                            'type': f'S{size}x{size}', 'symbol': sym, 'cells': cells,
                        })

        return matches

    def _has_poison_match(self, board):
        return any(match['symbol'] == 'poison' for match in self._matches_of_board(board))

    def trigger_golden(self, *, collect_frames=True):
        """
        황금 과일 연쇄 로직.

        각 연쇄는 아래 순서를 가지도록 프레임을 생성한다.
        1) 황금 과일 판정 시작: 골든 셀이 표시되지만 아직 리롤 전 상태
        2) 황금 판정 완료 + 리롤 심볼들이 돌아가기 시작
        3) 리롤 심볼들이 멈춤
        4) 다음 황금이 더 생기면 다시 1번부터 반복, 아니면 종료

        UI는 이 프레임을 순서대로 렌더링해서 의도한 전환을 구현한다.
        """
        if collect_frames:
            self.base_board = copy.deepcopy(self.board)
            base_match_board = self.base_board
        else:
            self.base_board = self.board
            base_match_board = self.board
        self.base_match_cache = self._matches_of_board(base_match_board)
        self.golden_match_cache = []

        frames = []
        MAX_ITERATIONS = 20
        iterations = 0

        # 독 매치가 이미 완성된 경우에는 골든 과일을 조사하지 않는다.
        if any(match['symbol'] == 'poison' for match in self.base_match_cache):
            return frames

        while True:
            iterations += 1
            if iterations > MAX_ITERATIONS:
                break

            golden_candidates = []
            for r in range(self.rows):
                for c in range(self.cols):
                    cell = self.board[r][c]
                    if cell.symbol in FRUITS and not cell.is_golden and random.random() < 0.01:
                        golden_candidates.append((r, c))

            if not golden_candidates:
                break

            # 한 라운드에 새 후보가 여러 개면 가장 비싼 과일 하나를 우선한다.
            golden_position = max(
                golden_candidates,
                key=lambda position: SYMBOL_VALUES[self.board[position[0]][position[1]].symbol],
            )
            golden_r, golden_c = golden_position
            self.board[golden_r][golden_c].is_golden = True

            # 1) 황금 판정 시작: 골든 셀만 초기 애니메이션 상태로 보여준다.
            if collect_frames:
                frames.append({
                    'stage': 'initial',
                    'board': copy.deepcopy(self.board),
                    'animated_positions': [],
                })

            # 2) 황금 판정 완료 + 동시에 리롤될 심볼들의 스핀 시작
            reroll_positions = []
            for r in range(self.rows):
                for c in range(self.cols):
                    cell = self.board[r][c]
                    if cell.is_golden:
                        continue
                    cell.symbol = random.choice(FRUITS)
                    reroll_positions.append((r, c))

            if reroll_positions:
                # 리롤 직후 화면은 골든은 최종 상태, 비골든 셀은 다시 돌아가는 애니메이션
                if collect_frames:
                    frames.append({
                        'stage': 'rolling',
                        'board': copy.deepcopy(self.board),
                        'animated_positions': reroll_positions,
                    })

                # 3) 리롤 심볼들이 멈춘 최종 상태
                if collect_frames:
                    frames.append({
                        'stage': 'settled',
                        'board': copy.deepcopy(self.board),
                        'animated_positions': [],
                    })
            else:
                # 리롤이 없으면 바로 판정 완료 상태로 마무리
                if collect_frames:
                    frames.append({
                        'stage': 'settled',
                        'board': copy.deepcopy(self.board),
                        'animated_positions': [],
                    })

            board_matches = self._matches_of_board(self.board)
            for match in board_matches:
                is_all_golden = all(
                    self.board[row][col].is_golden
                    for row, col in match['cells']
                )
                self.golden_match_cache.append((match, is_all_golden))

            # 리롤 결과 독 매치가 완성되면 다음 황금 조사를 중단한다.
            if any(match['symbol'] == 'poison' for match in board_matches):
                break

        return frames

    def check_lines(self):
        return self._matches_of_board(self.board)

    def check_squares(self):
        return [m for m in self._matches_of_board(self.board) if m['type'].startswith('S')]

    def calculate_reward(self):
        final_board_matches = self._matches_of_board(self.board)
        matches_by_key = {}
        for match in self.base_match_cache + final_board_matches:
            is_all_golden = all(
                self.board[row][col].is_golden
                for row, col in match['cells']
            )
            key = (match['type'], match['symbol'], tuple(sorted(match['cells'])))
            matches_by_key[key] = (match, is_all_golden)

        for match, was_all_golden in self.golden_match_cache:
            key = (match['type'], match['symbol'], tuple(sorted(match['cells'])))
            existing = matches_by_key.get(key)
            matches_by_key[key] = (
                match,
                was_all_golden or (existing[1] if existing else False),
            )

        matches = list(matches_by_key.values())

        poison_matches = [
            match for match, _ in matches if match['symbol'] == 'poison'
        ]
        if poison_matches:
            poison_cells = []
            for match in final_board_matches:
                if match['symbol'] == 'poison':
                    poison_cells.extend(match['cells'])
            self.winning_positions = list(dict.fromkeys(poison_cells))
            return 0, ["☠️ 독!감!자! (당신은 버스트했다.)"]

        total_reward = 0
        details = []
        winning_cells = []

        for m, is_all_golden in matches:
            sym = m['symbol']
            type_label = m['type']

            base_val = SYMBOL_VALUES[sym]
            mult = self.multipliers.get(type_label, 1)
            line_reward = base_val * mult

            if is_all_golden:
                line_reward += 777777

            total_reward += line_reward
            details.append(f"{type_label} ({sym}) +{line_reward:,}")

        for match in final_board_matches:
            winning_cells.extend(match['cells'])

        self.winning_positions = list(dict.fromkeys(winning_cells))

        return total_reward, details

@dataclass
class RunningStats:
    count: int = 0
    mean: float = 0.0
    sum_squared_deviations: float = 0.0
    maximum: float = 0.0

    def add(self, value: float) -> None:
        self.count += 1
        self.maximum = max(self.maximum, value)
        delta = value - self.mean
        self.mean += delta / self.count
        self.sum_squared_deviations += delta * (value - self.mean)

    @property
    def standard_error(self) -> float:
        if self.count < 2:
            return 0.0
        sample_variance = self.sum_squared_deviations / (self.count - 1)
        return (sample_variance / self.count) ** 0.5


def _confidence_interval(stats: RunningStats) -> tuple[float, float]:
    margin = 1.96 * stats.standard_error
    return stats.mean - margin, stats.mean + margin


def _print_estimate(label: str, stats: RunningStats) -> None:
    low, high = _confidence_interval(stats)
    print(
        f"  {label}: {stats.mean:,.2f}칩/회 "
        f"(근사 95% CI {low:,.2f}~{high:,.2f})"
    )


def _simulation_matches(board):
    matches = []
    rows = len(board)
    cols = len(board[0])
    row_symbol_masks = [{} for _ in range(rows)]
    for row in range(rows):
        for col, symbol in enumerate(board[row]):
            row_symbol_masks[row][symbol] = (
                row_symbol_masks[row].get(symbol, 0) | (1 << col)
            )

    for row in range(rows - 2):
        for col in range(cols):
            symbol = board[row][col]
            if board[row + 1][col] == symbol == board[row + 2][col]:
                cells = (
                    (1 << (row * cols + col))
                    | (1 << ((row + 1) * cols + col))
                    | (1 << ((row + 2) * cols + col))
                )
                matches.append(("V3", symbol, cells))

    for row in range(rows - 2):
        for col in range(cols - 2):
            symbol = board[row][col]
            if (
                board[row + 1][col + 1] == symbol
                and board[row + 2][col + 2] == symbol
            ):
                cells = (
                    (1 << (row * cols + col))
                    | (1 << ((row + 1) * cols + col + 1))
                    | (1 << ((row + 2) * cols + col + 2))
                )
                matches.append(("D3", symbol, cells))

            symbol = board[row + 2][col]
            if (
                board[row + 1][col + 1] == symbol
                and board[row][col + 2] == symbol
            ):
                cells = (
                    (1 << ((row + 2) * cols + col))
                    | (1 << ((row + 1) * cols + col + 1))
                    | (1 << (row * cols + col + 2))
                )
                matches.append(("D3", symbol, cells))

    for row in range(rows):
        col = 0
        while col < cols:
            symbol = board[row][col]
            end = col + 1
            while end < cols and board[row][end] == symbol:
                end += 1
            if end - col >= 3:
                cells = ((1 << (end - col)) - 1) << (row * cols + col)
                matches.append((f"H{end - col}", symbol, cells))
            col = end

    for size in range(2, min(rows, cols) + 1):
        required_columns = (1 << size) - 1
        for row in range(rows - size + 1):
            for col in range(cols - size + 1):
                symbol = board[row][col]
                required = required_columns << col
                is_match = True
                for current_row in range(row, row + size):
                    if row_symbol_masks[current_row].get(symbol, 0) & required != required:
                        is_match = False
                        break
                if is_match:
                    cells = sum(
                        required << (current_row * cols)
                        for current_row in range(row, row + size)
                    )
                    matches.append((f"S{size}x{size}", symbol, cells))

    return matches


def _simulate_spin_reward(rows: int, cols: int, multipliers: dict) -> tuple[int, bool]:
    board = [
        [
            random.choices(
                range(len(SIMULATION_SYMBOLS)),
                weights=SIMULATION_WEIGHTS,
                k=1,
            )[0]
            for _ in range(cols)
        ]
        for _ in range(rows)
    ]
    golden_mask = 0
    base_matches = _simulation_matches(board)
    golden_matches = []

    if not any(symbol == SIMULATION_POISON_ID for _, symbol, _ in base_matches):
        for _ in range(20):
            golden_candidate = None
            golden_candidate_value = -1
            for row in range(rows):
                for col in range(cols):
                    symbol = board[row][col]
                    if (
                        symbol in SIMULATION_FRUIT_IDS
                        and not golden_mask & (1 << (row * cols + col))
                        and random.random() < 0.01
                    ):
                        value = SIMULATION_SYMBOL_VALUES[symbol]
                        if value > golden_candidate_value:
                            golden_candidate = (row, col)
                            golden_candidate_value = value

            if golden_candidate is None:
                break

            golden_row, golden_col = golden_candidate
            golden_mask |= 1 << (golden_row * cols + golden_col)

            for row in range(rows):
                for col in range(cols):
                    if not golden_mask & (1 << (row * cols + col)):
                        board[row][col] = random.choice(SIMULATION_FRUIT_IDS)

            current_matches = _simulation_matches(board)
            for pattern, symbol, cells in current_matches:
                all_golden = golden_mask & cells == cells
                golden_matches.append((pattern, symbol, cells, all_golden))

            if any(
                symbol == SIMULATION_POISON_ID
                for _, symbol, _ in current_matches
            ):
                break

    final_matches = _simulation_matches(board)
    matches_by_key = {}
    for pattern, symbol, cells in base_matches + final_matches:
        all_golden = golden_mask & cells == cells
        key = (pattern, symbol, cells)
        matches_by_key[key] = (symbol, all_golden)

    for pattern, symbol, cells, was_all_golden in golden_matches:
        key = (pattern, symbol, cells)
        existing = matches_by_key.get(key)
        matches_by_key[key] = (
            symbol,
            was_all_golden or (existing[1] if existing else False),
        )

    if any(
        symbol == SIMULATION_POISON_ID
        for symbol, _ in matches_by_key.values()
    ):
        return 0, False

    total_reward = 0
    golden_bonus = False
    for (pattern, symbol, _), (_, is_all_golden) in matches_by_key.items():
        total_reward += (
            SIMULATION_SYMBOL_VALUES[symbol] * multipliers.get(pattern, 1)
            + (777777 if is_all_golden else 0)
        )
        golden_bonus |= is_all_golden

    return total_reward, golden_bonus


def _simulate_board(
    name: str,
    rows: int,
    cols: int,
    cost: int,
    spins: int,
) -> None:
    engine = SlotEngine(rows=rows, cols=cols)

    rewards = RunningStats()
    golden_bonus_spins = 0

    print(
        f"\n{name} {rows}x{cols} | 비용 {cost:,}칩 | {spins:,}회",
        flush=True,
    )
    print(
        f"  심볼 가중치: {SYMBOL_WEIGHTS}\n"
        f"  패턴 배율: {engine.multipliers}",
        flush=True,
    )

    for completed in range(1, spins + 1):
        reward, has_golden_bonus = _simulate_spin_reward(
            rows, cols, engine.multipliers
        )
        golden_bonus_spins += has_golden_bonus
        rewards.add(reward)

        if completed % 100_000 == 0 or completed == spins:
            print(
                f"  진행 {completed:,}/{spins:,}회 | "
                f"현재 EV {rewards.mean:,.2f}칩/회",
                flush=True,
            )

    low, high = _confidence_interval(rewards)
    print(f"\n{name} 최종 결과")
    _print_estimate("평균 지급액", rewards)
    print(f"  순기대값(평균 지급액-비용): {rewards.mean - cost:+,.2f}칩/회")
    print(
        f"황금 패턴 보너스 관측: {golden_bonus_spins:,}회 | "
        f"최대 지급액: {rewards.maximum:,.0f}칩"
    )


def _run_ev_simulation() -> None:
    spins = 1_000_000
    configurations = {
        "1": ("일반 슬롯", 3, 5, 1_000),
        "2": ("빅슬롯", 5, 6, 3_300),
        "3": None,
    }
    print(
        "기대값을 시뮬레이션할 슬롯을 선택하세요:\n"
        "1. 일반 슬롯 (3x5, 1,000칩)\n"
        "2. 빅슬롯 (5x6, 3,300칩)\n"
        "3. 둘 다"
    )
    choice = input("선택 (1/2/3): ").strip()
    if choice not in configurations:
        print("잘못된 선택입니다. 1, 2, 3 중 하나를 입력하세요.")
        return

    selected = (
        (configurations["1"], configurations["2"])
        if choice == "3"
        else (configurations[choice],)
    )
    for configuration in selected:
        if configuration is not None:
            _simulate_board(*configuration, spins)


if __name__ == '__main__':
    _run_ev_simulation()
