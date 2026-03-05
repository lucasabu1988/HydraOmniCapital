import pandas as pd
import numpy as np

daily = pd.read_csv('backtests/v84_overlay_daily.csv', parse_dates=['date'])
trades = pd.read_csv('backtests/v84_overlay_trades.csv', parse_dates=['entry_date', 'exit_date'])
spy = pd.read_csv('backtests/spy_benchmark.csv', parse_dates=['date'])

daily['ret'] = daily['value'].pct_change()
spy['spy_ret'] = spy['close'].pct_change()
merged = pd.merge(daily, spy[['date','close','spy_ret']], on='date', how='inner')

print('=== 2006 ATTRIBUTION ===')
d06 = merged[merged['date'].dt.year==2006].copy()
t06 = trades[trades['entry_date'].dt.year==2006].copy()

risk_off = d06[d06['risk_on']==False]
risk_on = d06[d06['risk_on']==True]
spy_ro = (1+risk_off['spy_ret'].fillna(0)).prod()-1
cpass_ro = (1+risk_off['ret'].fillna(0)).prod()-1
spy_ri = (1+risk_on['spy_ret'].fillna(0)).prod()-1
cpass_ri = (1+risk_on['ret'].fillna(0)).prod()-1

print(f'Risk-off days: {len(risk_off)} ({len(risk_off)/len(d06):.1%})')
print(f'  SPY during risk-off: {spy_ro:.2%}   COMPASS: {cpass_ro:.2%}   Gap: {cpass_ro-spy_ro:.2%}')
print(f'Risk-on days: {len(risk_on)} ({len(risk_on)/len(d06):.1%})')
print(f'  SPY during risk-on: {spy_ri:.2%}   COMPASS: {cpass_ri:.2%}   Gap: {cpass_ri-spy_ri:.2%}')

full_ri = d06[(d06['positions']==5) & (d06['risk_on']==True)]
x = full_ri['spy_ret'].values
y = full_ri['ret'].values
beta = np.cov(x, y)[0,1] / np.var(x)
alpha_annual = (np.mean(y) - beta*np.mean(x)) * 252
print(f'Beta (fully invested, risk-on): {beta:.3f}   Alpha: {alpha_annual:.2%}/yr')

win_rate = (t06['return']>0).mean()
payoff = t06[t06['return']>0]['return'].mean() / abs(t06[t06['return']<0]['return'].mean())
print(f'Win rate: {win_rate:.1%}   Payoff ratio: {payoff:.2f}x')

# Aug-Dec bull run
aug_dec = d06[(d06['date']>='2006-08-01')]
print(f'\nAug-Dec 2006: COMPASS {(1+aug_dec["ret"].fillna(0)).prod()-1:.2%}  SPY {(1+aug_dec["spy_ret"].fillna(0)).prod()-1:.2%}')

# Worst losing symbols in 2006
print('\nTop 5 P&L losers by symbol in 2006:')
sym_pnl = t06.groupby('symbol')['pnl'].sum().sort_values().head(5)
print(sym_pnl.to_string())

print()
print('=== 2007 ATTRIBUTION ===')
d07 = merged[merged['date'].dt.year==2007].copy()
t07 = trades[trades['entry_date'].dt.year==2007].copy()

for label, s, e in [('Q1','2007-01-01','2007-03-31'),
                     ('Q2+Q3','2007-04-01','2007-09-30'),
                     ('Q4','2007-10-01','2007-12-31')]:
    sub = d07[(d07['date']>=s) & (d07['date']<=e)]
    cr = (1+sub['ret'].fillna(0)).prod()-1
    sr = (1+sub['spy_ret'].fillna(0)).prod()-1
    print(f'{label}: COMPASS {cr:.2%}  SPY {sr:.2%}  Gap {cr-sr:.2%}')

nov_stops = trades[
    (trades['exit_date'].dt.year==2007) &
    (trades['exit_date'].dt.month==11) &
    (trades['exit_reason']=='position_stop')
]
print(f'Nov position stops PnL: ${nov_stops["pnl"].sum():,.0f}')

print('\nQ1 2007 stock selection:')
q1_trades = t07[t07['entry_date']<='2007-03-31']
q1s = q1_trades.groupby('symbol').agg(total_pnl=('pnl','sum'), n=('pnl','count')).sort_values('total_pnl')
print(q1s.to_string())

win_rate7 = (t07['return']>0).mean()
payoff7 = t07[t07['return']>0]['return'].mean() / abs(t07[t07['return']<0]['return'].mean())
print(f'Win rate: {win_rate7:.1%}   Payoff ratio: {payoff7:.2f}x')

# 2007 regime recovery speed
print('\n2007 post-crash (Feb 27) regime recovery:')
post = d07[(d07['date']>='2007-02-27') & (d07['date']<='2007-04-05')]
print(post[['date','positions','risk_on','regime_score','ret','spy_ret']].to_string(index=False))
