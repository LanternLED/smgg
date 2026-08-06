import random
import copy

# --- 데이터 테이블 ---
# 주의: FRUITS 목록을 바꾸면 slot.py의 GOLDEN_EMOJIS도 함께 갱신해야 함
# (골든 처리는 FRUITS에 속한 심볼에만 적용됨)
FRUITS = ['apple', 'watermelon', 'carrot']
NON_FRUITS = ['cake', 'cookie', 'bread', 'baked_potato', 'potato', 'poison']

# 등장 가중치 (비과일의 확률을 높이고, 과일은 낮춰 밸런스 조절)
SYMBOL_WEIGHTS = {
    'cake': 4, 'cookie': 6, 'bread': 8,
    'apple': 12, 'watermelon': 10, 'carrot': 14,
    'baked_potato': 16, 'potato': 18, 'poison': 12
}

# 심볼 기본 가치
SYMBOL_VALUES = {
    'cake': 7200, 'cookie': 4800, 'bread': 2400,
    'apple': 1200, 'watermelon': 1600, 'carrot': 800,
    'baked_potato': 500, 'potato': 200, 'poison': 0
}

# 과일 리롤용 가중치 추출
FRUIT_WEIGHTS = [SYMBOL_WEIGHTS[f] for f in FRUITS]

# 라인 배수
MULTIPLIERS = {'V3': 3, 'D3': 3, 'H3': 3, 'H4': 7, 'H5': 15}

class SlotCell:
    def __init__(self, symbol):
        self.symbol = symbol
        self.is_golden = False

class SlotEngine:
    def __init__(self):
        self.board = []
        self.winning_positions = []  # 마지막 calculate_reward() 결과의 당첨(또는 버스트) 좌표

    def generate_board(self):
        symbols = list(SYMBOL_WEIGHTS.keys())
        weights = list(SYMBOL_WEIGHTS.values())
        self.board = [[SlotCell(random.choices(symbols, weights=weights, k=1)[0]) for _ in range(5)] for _ in range(3)]

    def trigger_golden(self):
        """
        황금 과일 연쇄 로직. 애니메이션을 위해 보드 상태(Frame)의 리스트를 반환합니다.
        반환값이 빈 리스트면 황금이 발생하지 않은 것입니다.
        """
        frames = []
        is_chain_active = True
        MAX_ITERATIONS = 20  # 이론상 무한 루프 방지용 안전장치 (실제로는 거의 도달하지 않음)
        iterations = 0

        while is_chain_active:
            iterations += 1
            if iterations > MAX_ITERATIONS:
                break

            new_golden_triggered = False
            
            # 1. 황금 판정 (과일이면서 아직 황금이 아닌 칸 1%)
            for r in range(3):
                for c in range(5):
                    cell = self.board[r][c]
                    if cell.symbol in FRUITS and not cell.is_golden:
                        if random.random() < 0.01:
                            cell.is_golden = True
                            new_golden_triggered = True
            
            if not new_golden_triggered:
                break # 더 이상 황금이 발생하지 않으면 연쇄 종료
            
            # 황금 연출 프레임 저장
            frames.append(copy.deepcopy(self.board))
            
            # 2. 비과일 칸 리롤
            has_rerolled = False
            for r in range(3):
                for c in range(5):
                    cell = self.board[r][c]
                    if cell.symbol in NON_FRUITS:
                        cell.symbol = random.choices(FRUITS, weights=FRUIT_WEIGHTS, k=1)[0]
                        has_rerolled = True
            
            # 리롤 연출 프레임 저장
            if has_rerolled:
                frames.append(copy.deepcopy(self.board))
                
            # 참고: 첫 번째 루프 이후 모든 비과일이 과일로 변하므로, 
            # 다음 루프부터는 새로운 과일에 대한 1% 확률 체크만 반복됩니다.
            
        return frames

    def check_lines(self):
        matches = []
        
        # 1. 세로 (V3)
        for c in range(5):
            if self.board[0][c].symbol == self.board[1][c].symbol == self.board[2][c].symbol:
                matches.append({'type': 'V3', 'symbol': self.board[0][c].symbol, 'cells': [(0,c), (1,c), (2,c)]})
                
        # 2. 대각선 (D3)
        diagonals = [
            [(0,0), (1,1), (2,2)], [(0,1), (1,2), (2,3)], [(0,2), (1,3), (2,4)], # 우하향
            [(2,0), (1,1), (0,2)], [(2,1), (1,2), (0,3)], [(2,2), (1,3), (0,4)]  # 우상향
        ]
        for d in diagonals:
            sym = self.board[d[0][0]][d[0][1]].symbol
            if self.board[d[1][0]][d[1][1]].symbol == sym and self.board[d[2][0]][d[2][1]].symbol == sym:
                matches.append({'type': 'D3', 'symbol': sym, 'cells': d})
                
        # 3. 가로 (H3, H4, H5)
        for r in range(3):
            symbols = [self.board[r][c].symbol for c in range(5)]
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
                
        return matches

    def calculate_reward(self):
        matches = self.check_lines()
        
        # 1. ☠️ 독감자(Bust) 체크를 가장 먼저 수행
        for m in matches:
            if m['symbol'] == 'poison':
                # 독감자 3연속 이상 라인이 하나라도 발견되면, 즉시 모든 계산 중단 및 0칩 반환
                # 버스트 라인도 연출상 강조할 수 있게 좌표를 남겨둔다.
                self.winning_positions = list(dict.fromkeys(m['cells']))
                return 0, ["☠️ 독!감!자! (당신은 버스트했다.)"]

        # 2. 독감자가 없는 안전한 상태라면 정상적으로 계산
        total_reward = 0
        details = []
        winning_cells = []
        
        for m in matches:
            sym = m['symbol']
            cells = m['cells']
            
            is_all_golden = all(self.board[r][c].is_golden for (r, c) in cells)
            
            base_val = SYMBOL_VALUES[sym]
            mult = MULTIPLIERS[m['type']]
            line_reward = base_val * mult
            
            # 황금 라인 잭팟
            if is_all_golden:
                line_reward += 777777
                
            total_reward += line_reward
            details.append(f"{m['type']} ({sym}) +{line_reward:,}")
            winning_cells.extend(cells)

        # 중복 좌표 제거(순서는 유지) — 대각선/가로/세로 라인이 겹칠 수 있음
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

async def setup(bot):
    pass