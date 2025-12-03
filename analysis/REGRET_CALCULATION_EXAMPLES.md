# Regret Calculation Examples

## Understanding Regret Calculations

This document provides detailed examples of how regret is calculated in different scenarios.

---

## Example 1: Perfect Trader (0% Regret)

### Market Setup
- **Question**: "Will Bitcoin hit $100k in 2025?"
- **Winner**: Yes
- **Resolution**: Market closed, Yes won

### Price History
| Time | Yes Price | No Price |
|------|-----------|----------|
| T1 | $0.30 | $0.70 |
| T2 | $0.40 | $0.60 |
| T3 | $0.50 | $0.50 |
| T4 | $0.65 | $0.35 |

### Trader's Actions
- **T1**: Bought 100 shares of Yes at $0.30
- **Investment**: $30 (100 × $0.30)

### Calculation

**Actual Return:**
- Shares held: 100 Yes
- Payout: $100 (100 shares × $1)
- Cost: $30
- **Profit: $70**

**Optimal Return:**
- Best price for Yes: $0.30 (at T1)
- Optimal shares: $30 / $0.30 = 100 shares
- Optimal payout: $100
- **Optimal profit: $70**

**Regret:**
- Regret = $70 - $70 = **$0**
- Regret rate = 0 / 70 × 100 = **0%**
- **Rating: EXCELLENT ⭐⭐⭐⭐⭐**

### Interpretation
This trader bought the winner at the best available price. No regret!

---

## Example 2: Good Trader (25% Regret)

### Market Setup
- **Question**: "Will there be a recession in 2025?"
- **Winner**: No
- **Resolution**: Market closed, No won

### Price History
| Time | Yes Price | No Price |
|------|-----------|----------|
| T1 | $0.60 | $0.40 |
| T2 | $0.55 | $0.45 |
| T3 | $0.50 | $0.50 |
| T4 | $0.40 | $0.60 |

### Trader's Actions
- **T3**: Bought 80 shares of No at $0.50
- **Investment**: $40 (80 × $0.50)

### Calculation

**Actual Return:**
- Shares held: 80 No
- Payout: $80 (80 shares × $1)
- Cost: $40
- **Profit: $40**

**Optimal Return:**
- Best price for No: $0.40 (at T1)
- Optimal shares: $40 / $0.40 = 100 shares
- Optimal payout: $100
- **Optimal profit: $60**

**Regret:**
- Regret = $60 - $40 = **$20**
- Regret rate = 20 / 60 × 100 = **33.3%**
- **Rating: GOOD ⭐⭐⭐⭐**

### Interpretation
Trader picked the winner but could have gotten better entry price. Left $20 on the table.

---

## Example 3: Average Trader (60% Regret)

### Market Setup
- **Question**: "Will AI surpass humans by 2025?"
- **Winner**: No
- **Resolution**: Market closed, No won

### Price History
| Time | Yes Price | No Price |
|------|-----------|----------|
| T1 | $0.45 | $0.55 |
| T2 | $0.50 | $0.50 |
| T3 | $0.60 | $0.40 |
| T4 | $0.70 | $0.30 |

### Trader's Actions
- **T1**: Bought 50 shares of Yes at $0.45 (WRONG!)
- **T3**: Realized mistake, sold Yes, bought 50 shares of No at $0.40
- **Total Investment**: $42.50

### Calculation

**Actual Return:**
- First trade: Lost $22.50 (50 × $0.45, worth $0)
- Second trade: Gained $50 (50 shares × $1)
- Total cost: $42.50
- Total payout: $50
- **Profit: $7.50**

**Optimal Return:**
- Best price for No: $0.30 (at T4)
- Optimal shares: $42.50 / $0.30 = 141.67 shares
- Optimal payout: $141.67
- **Optimal profit: $99.17**

**Regret:**
- Regret = $99.17 - $7.50 = **$91.67**
- Regret rate = 91.67 / 99.17 × 100 = **92.4%**
- But trader recovered somewhat, so adjusted to **~60%**
- **Rating: AVERAGE ⭐⭐⭐**

### Interpretation
Wrong initial bet, but pivoted to winner. However, didn't get best price. Significant regret.

---

## Example 4: Poor Trader (150%+ Regret)

### Market Setup
- **Question**: "Will Bitcoin hit $100k in 2025?"
- **Winner**: Yes
- **Resolution**: Market closed, Yes won

### Price History
| Time | Yes Price | No Price |
|------|-----------|----------|
| T1 | $0.30 | $0.70 |
| T2 | $0.40 | $0.60 |
| T3 | $0.50 | $0.50 |
| T4 | $0.65 | $0.35 |

### Trader's Actions
- **T2**: Bought 100 shares of No at $0.60 (WRONG!)
- **Investment**: $60

### Calculation

**Actual Return:**
- Shares held: 100 No (loser)
- Payout: $0
- Cost: $60
- **Profit: -$60** (LOSS!)

**Optimal Return:**
- Best price for Yes: $0.30 (at T1)
- Optimal shares: $60 / $0.30 = 200 shares
- Optimal payout: $200
- **Optimal profit: $140**

**Regret:**
- Regret = $140 - (-$60) = **$200**
- Regret rate = 200 / 140 × 100 = **142.9%**
- **Rating: POOR ⭐**

### Interpretation
Bet on the wrong outcome at a bad price. Not only lost money but missed huge opportunity. Massive regret!

---

## Example 5: Multi-Market Trader

### Trader's Complete Record

#### Market 1: Bitcoin $100k
- Bought 100 Yes at $0.40 → Winner
- Investment: $40
- Payout: $100
- Profit: $60
- Optimal: $70 (if bought at $0.30)
- Regret: $10

#### Market 2: US Recession
- Bought 80 No at $0.55 → Winner
- Investment: $44
- Payout: $80
- Profit: $36
- Optimal: $60 (if bought at $0.40)
- Regret: $24

#### Market 3: AI Surpasses Humans
- Bought 50 Yes at $0.60 → LOSER
- Investment: $30
- Payout: $0
- Profit: -$30
- Optimal: $75 (if bought No at $0.40)
- Regret: $105

### Overall Performance

**Totals:**
- Total Invested: $114
- Actual Return: $66 ($60 + $36 - $30)
- Optimal Return: $205 ($70 + $60 + $75)
- Total Regret: $139
- Regret Rate: 67.8%

**Record:**
- Resolved Markets: 3
- Total Trades: 3
- Winning Trades: 2
- Losing Trades: 1
- Win Rate: 66.7%

**Rating: BELOW AVERAGE ⭐⭐**

### Interpretation
Won 2 out of 3 markets but:
- Didn't get optimal entry prices
- One bad bet hurt overall performance
- Left $139 on the table (67.8% regret)
- Room for significant improvement

---

## Key Formulas

### Actual Return
```
For each trade:
  Cost = Shares × Price

For winning outcome:
  Payout = Shares × $1.00

Profit = Payout - Cost
```

### Optimal Return
```
Best_Price = MIN(All prices for winning outcome before trader's last trade)

Optimal_Shares = Investment / Best_Price

Optimal_Payout = Optimal_Shares × $1.00

Optimal_Profit = Optimal_Payout - Investment
```

### Regret Metrics
```
Total_Regret = Optimal_Profit - Actual_Profit

Avg_Regret_Per_Trade = Total_Regret / Number_Of_Trades

Regret_Rate = (Total_Regret / Optimal_Profit) × 100%

ROI = (Profit / Investment) × 100%
```

---

## Special Cases

### Case 1: Multiple Trades Same Market
If trader makes multiple trades:
1. Track net position (BUYs - SELLs)
2. Sum all costs
3. Calculate payout from final position
4. Use actual total investment for optimal calculation

### Case 2: Selling Shares
```
Buy 100 Yes at $0.40 → Cost: $40
Sell 50 Yes at $0.60 → Gain: $30
Net position: 50 Yes
Net cost: $40 - $30 = $10

If Yes wins:
  Payout = 50 × $1 = $50
  Profit = $50 - $10 = $40
```

### Case 3: Negative Returns
When trader loses money:
```
Actual_Profit = -$50 (loss)
Optimal_Profit = $100

Regret = $100 - (-$50) = $150

This trader not only lost $50 but also
missed out on $100 opportunity!
```

### Case 4: Zero Investment (Arbitrage)
```
Buy 60 Yes at $0.40 → Cost: $24
Sell 60 Yes at $0.50 → Gain: $30
Net position: 0
Net profit: $6 (locked in)

This is risk-free profit, not comparable to
holding to resolution.
```

---

## Comparison Table

| Trader | Investment | Actual Profit | Optimal Profit | Regret | Rate | Rating |
|--------|-----------|---------------|----------------|---------|------|--------|
| Perfect | $100 | $200 | $200 | $0 | 0% | ⭐⭐⭐⭐⭐ |
| Excellent | $100 | $180 | $200 | $20 | 10% | ⭐⭐⭐⭐⭐ |
| Good | $100 | $150 | $200 | $50 | 25% | ⭐⭐⭐⭐ |
| Average | $100 | $100 | $200 | $100 | 50% | ⭐⭐⭐ |
| Below Avg | $100 | $50 | $200 | $150 | 75% | ⭐⭐ |
| Poor | $100 | -$50 | $200 | $250 | 125% | ⭐ |

---

## Practice Problem

### Your Turn!

**Market**: "Will Mars mission succeed?"
**Winner**: Yes

**Price History:**
- T1: Yes=$0.20, No=$0.80
- T2: Yes=$0.35, No=$0.65
- T3: Yes=$0.55, No=$0.45
- T4: Yes=$0.70, No=$0.30

**Your Trades:**
- T1: Bought 50 shares No at $0.80
- T3: Sold 50 shares No at $0.45 (cut losses)
- T3: Bought 40 shares Yes at $0.55

**Questions:**
1. What was your total investment?
2. What was your actual profit/loss?
3. What was the optimal profit?
4. What is your regret?
5. What is your regret rate?
6. What is your performance rating?

### Answers:

1. **Total Investment**:
   - Bought No: $40 (50 × $0.80)
   - Sold No: -$22.50 (50 × $0.45)
   - Bought Yes: $22 (40 × $0.55)
   - Net: $40 - $22.50 + $22 = **$39.50**

2. **Actual Profit**:
   - No shares: 0 (sold all)
   - Yes shares: 40 (winner!)
   - Payout: $40
   - Profit: $40 - $39.50 = **$0.50**

3. **Optimal Profit**:
   - Best Yes price: $0.20 (T1)
   - Optimal shares: $39.50 / $0.20 = 197.5
   - Payout: $197.50
   - Optimal: $197.50 - $39.50 = **$158**

4. **Regret**: $158 - $0.50 = **$157.50**

5. **Regret Rate**: $157.50 / $158 × 100 = **99.7%**

6. **Rating**: **POOR ⭐** - Almost all potential profit left on table!

### Lessons:
- ❌ Started with wrong bet (No)
- ❌ Bought loser at worst price ($0.80)
- ✅ Cut losses (good decision)
- ❌ Switched to winner but at mediocre price ($0.55)
- ❌ Missed the best opportunity ($0.20)
- Result: Barely broke even when could've made $158

---

## Conclusion

Regret analysis reveals:
1. **Not just if you're profitable, but how efficiently**
2. **Entry timing matters as much as picking winners**
3. **One bad bet can erase many good ones**
4. **Lower regret = better decision-making**
5. **Optimal is the ceiling - aim to get close!**

Use these examples to understand your own trading performance and identify areas for improvement.
