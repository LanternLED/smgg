import random
import copy

# --- 데이터 테이블 ---
# 주의: FRUITS 목록을 바꾸면 slot.py의 GOLDEN_EMOJIS도 함께 갱신해야 함
# (골든 처리는 FRUITS에 속한 심볼에만 적용됨)
FRUITS = ['apple', 'watermelon', 'carrot']
NON_FRUITS = ['cake', 'cookie', 'bread', 'baked_potato', 'potato', 'poison']

# 등장 가중치 (비과일의 확률을 높이고, 과일은 낮춰 밸런스 조절)
SYMBOL_WEIGHTS = {
    'cake': 1, 'cookie': 4, 'bread': 7,
    'apple': 10, 'watermelon': 12, 'carrot': 14,
    'baked_potato': 16, 'potato': 17, 'poison': 19
}

# 심볼 기본 가치
SYMBOL_VALUES = {
    'cake': 5000, 'cookie': 3000, 'bread': 2000,
    'apple': 1200, 'watermelon': 1500, 'carrot': 1000,
    'baked_potato': 500, 'potato': 300, 'poison': 0
}

# 과일 리롤용 가중치 추출
FRUIT_WEIGHTS = [SYMBOL_WEIGHTS[f] for f in FRUITS]

# 패턴 배수: 큰 패턴이 작은 패턴을 덮는다.
MULTIPLIERS = {'V3': 3, 'D3': 3, 'H3': 3, 'H4': 2, 'H5': 2, 'S2x2': 3, 'S3x3': 44}

class SlotCell:
    def __init__(self, symbol):
        self.symbol = symbol
        self.is_golden = False

class SlotEngine:
    def __init__(self):
        self.board = []
        self.base_board = []
        self.base_match_cache = []
        self.winning_positions = []  # 마지막 calculate_reward() 결과의 당첨(또는 버스트) 좌표

    def generate_board(self):
        symbols = list(SYMBOL_WEIGHTS.keys())
        weights = list(SYMBOL_WEIGHTS.values())
        self.board = [[SlotCell(random.choices(symbols, weights=weights, k=1)[0]) for _ in range(5)] for _ in range(3)]
        self.base_board = copy.deepcopy(self.board)
        self.base_match_cache = []

    def _matches_of_board(self, board):
        matches = []

        for c in range(5):
            if board[0][c].symbol == board[1][c].symbol == board[2][c].symbol:
                matches.append({'type': 'V3', 'symbol': board[0][c].symbol, 'cells': [(0, c), (1, c), (2, c)]})

        diagonals = [
            [(0,0), (1,1), (2,2)], [(0,1), (1,2), (2,3)], [(0,2), (1,3), (2,4)],
            [(2,0), (1,1), (0,2)], [(2,1), (1,2), (0,3)], [(2,2), (1,3), (0,4)]
        ]
        for d in diagonals:
            sym = board[d[0][0]][d[0][1]].symbol
            if board[d[1][0]][d[1][1]].symbol == sym and board[d[2][0]][d[2][1]].symbol == sym:
                matches.append({'type': 'D3', 'symbol': sym, 'cells': d})

        for r in range(3):
            symbols = [board[r][c].symbol for c in range(5)]
            c = 0
            while c < 5:
                sym = symbols[c]
                streak = 1
                cells = [(r, c)]
                next_c = c + 1
                while next_c < 5 and symbols[next_c] == sym:
                    streak += 1
                    cells.append((r, next_c))
                    next_c += 1

                if streak >= 3:
                    matches.append({'type': f'H{streak}', 'symbol': sym, 'cells': cells})
                c = next_c

        for r in range(2):
            for c in range(4):
                sym = board[r][c].symbol
                cells = [(r, c), (r, c + 1), (r + 1, c), (r + 1, c + 1)]
                if all(board[rr][cc].symbol == sym for rr, cc in cells):
                    matches.append({'type': 'S2x2', 'symbol': sym, 'cells': cells})

        for r in range(1):
            for c in range(3):
                sym = board[r][c].symbol
                cells = [
                    (r, c), (r, c + 1), (r, c + 2),
                    (r + 1, c), (r + 1, c + 1), (r + 1, c + 2),
                    (r + 2, c), (r + 2, c + 1), (r + 2, c + 2),
                ]
                if all(board[rr][cc].symbol == sym for rr, cc in cells):
                    matches.append({'type': 'S3x3', 'symbol': sym, 'cells': cells})

        return matches

    def _has_poison_match(self, board):
        return any(match['symbol'] == 'poison' for match in self._matches_of_board(board))

    def trigger_golden(self):
        """
        황금 과일 연쇄 로직.

        각 연쇄는 아래 순서를 가지도록 프레임을 생성한다.
        1) 황금 과일 판정 시작: 골든 셀이 표시되지만 아직 리롤 전 상태
        2) 황금 판정 완료 + 리롤 심볼들이 돌아가기 시작
        3) 리롤 심볼들이 멈춤
        4) 다음 황금이 더 생기면 다시 1번부터 반복, 아니면 종료

        UI는 이 프레임을 순서대로 렌더링해서 의도한 전환을 구현한다.
        """
        self.base_board = copy.deepcopy(self.board)
        self.base_match_cache = self._matches_of_board(self.base_board)

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
            for r in range(3):
                for c in range(5):
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
            frames.append({
                'stage': 'initial',
                'board': copy.deepcopy(self.board),
                'animated_positions': [],
            })

            # 2) 황금 판정 완료 + 동시에 리롤될 심볼들의 스핀 시작
            reroll_positions = []
            for r in range(3):
                for c in range(5):
                    cell = self.board[r][c]
                    if cell.is_golden:
                        continue
                    cell.symbol = random.choice(FRUITS)
                    reroll_positions.append((r, c))

            if reroll_positions:
                # 리롤 직후 화면은 골든은 최종 상태, 비골든 셀은 다시 돌아가는 애니메이션
                frames.append({
                    'stage': 'rolling',
                    'board': copy.deepcopy(self.board),
                    'animated_positions': reroll_positions,
                })

                # 3) 리롤 심볼들이 멈춘 최종 상태
                frames.append({
                    'stage': 'settled',
                    'board': copy.deepcopy(self.board),
                    'animated_positions': [],
                })
            else:
                # 리롤이 없으면 바로 판정 완료 상태로 마무리
                frames.append({
                    'stage': 'settled',
                    'board': copy.deepcopy(self.board),
                    'animated_positions': [],
                })

            # 리롤 결과 독 매치가 완성되면 다음 황금 조사를 중단한다.
            if self._has_poison_match(self.board):
                break

        return frames

    def check_lines(self):
        return self._matches_of_board(self.board)

    def check_squares(self):
        return [m for m in self._matches_of_board(self.board) if m['type'] in {'S2x2', 'S3x3'}]

    def calculate_reward(self):
        all_matches = []
        if self.base_match_cache:
            all_matches.extend(self.base_match_cache)
        all_matches.extend(self.check_lines() + self.check_squares())

        deduped_matches = []
        seen = set()
        for m in all_matches:
            key = (m['type'], m['symbol'], tuple(sorted(m['cells'])))
            if key in seen:
                continue
            seen.add(key)
            deduped_matches.append(m)
        matches = deduped_matches

        poison_matches = [m for m in matches if m['symbol'] == 'poison']
        if poison_matches:
            poison_cells = []
            for m in poison_matches:
                poison_cells.extend(m['cells'])
            self.winning_positions = list(dict.fromkeys(poison_cells))
            return 0, ["☠️ 독!감!자! (당신은 버스트했다.)"]

        total_reward = 0
        details = []
        winning_cells = []

        for m in matches:
            sym = m['symbol']
            cells = m['cells']
            type_label = m['type']

            is_all_golden = all(self.board[r][c].is_golden for (r, c) in cells)

            base_val = SYMBOL_VALUES[sym]
            mult = MULTIPLIERS.get(type_label, 1)
            line_reward = base_val * mult

            if is_all_golden:
                line_reward += 777777

            total_reward += line_reward
            details.append(f"{type_label} ({sym}) +{line_reward:,}")
            winning_cells.extend(cells)

        self.winning_positions = list(dict.fromkeys(winning_cells))

        return total_reward, details

# --- 기대값(EV) 시뮬레이터 (개발용) ---
if __name__ == '__main__':
    engine = SlotEngine()
    total_earned = 0
    spins = 100000
    print("몬테카를로 시뮬레이션 시작")
    for _ in range(spins):
        engine.generate_board()
        engine.trigger_golden()
        reward, _ = engine.calculate_reward()
        total_earned += reward
    print(f"1회 스핀 평균 획득(기대값): {total_earned / spins:.2f} 칩")
