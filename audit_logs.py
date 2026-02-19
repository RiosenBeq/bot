
import re

log_file = 'production.log'
total_cost = 0.0
total_revenue = 0.0
wins = 0
losses = 0
active_positions = 0

# Regex patterns
buy_pattern = re.compile(r'BUY ORDER \|.*?Cost: \$([\d.]+)')
sell_pattern = re.compile(r'SELL ORDER.*?Revenue: \$([\d.]+)')
profit_pattern = re.compile(r'Profit: \$(-?[\d.]+)')
loss_pattern = re.compile(r'Loss: \$(-?[\d.]+)')
redemption_pattern = re.compile(r'REDEMPTION SUCCESSFUL!.*?Amount redeemed: \$([\d.]+)') # Check if this exists

with open(log_file, 'r') as f:
    for line in f:
        buy_match = buy_pattern.search(line)
        if buy_match:
            total_cost += float(buy_match.group(1))
            active_positions += 1
            
        sell_match = sell_pattern.search(line)
        if sell_match:
            total_revenue += float(sell_match.group(1))
            active_positions -= 1
            
        profit_match = profit_pattern.search(line)
        if profit_match:
            p = float(profit_match.group(1))
            if p > 0:
                wins += 1
            else:
                losses += 1
                
        loss_match = loss_pattern.search(line)
        if loss_match:
            losses += 1

print(f"--- Log Audit Results ---")
print(f"Total USDC Spent (Buy): ${total_cost:.2f}")
print(f"Total USDC Earned (Sell): ${total_revenue:.2f}")
print(f"Net Profit (Closed Trades): ${total_revenue - total_cost:.2f}")
print(f"Wins: {wins}")
print(f"Losses: {losses}")
print(f"Estimated Stuck/Active Positions: {active_positions}")
