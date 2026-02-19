import re

def calculate_profit():
    total_profit = 0.0
    wins = 0
    losses = 0
    
    try:
        with open('history.toml', 'r') as f:
            for line in f:
                if 'MARKET RESULT' in line:
                    match = re.search(r'Profit: \$([-+]?\d*\.\d+|\d+)', line)
                    if match:
                        profit = float(match.group(1))
                        total_profit += profit
                        if profit > 0:
                            wins += 1
                        else:
                            losses += 1
                            
        print(f"Total Profit: ${total_profit:.2f}")
        print(f"Wins: {wins}")
        print(f"Losses: {losses}")
        if wins + losses > 0:
            print(f"Win Rate: {(wins / (wins + losses)) * 100:.1f}%")
        else:
            print("No completed trades found.")
            
    except FileNotFoundError:
        print("history.toml not found.")

if __name__ == "__main__":
    calculate_profit()
