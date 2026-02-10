# PTO Vacation Optimizer

Maximize your time off by strategically placing PTO days to bridge
weekends and holidays into longer vacation blocks.

## Installation

```bash
uv add pto
```

Or install from source:

```bash
git clone https://github.com/samuelduchesne/pto.git
cd pto
uv sync
```

## Quick start

```python
import datetime
from pto import PTOOptimizer

holidays = [
    datetime.date(2025, 1, 1),   # New Year's Day
    datetime.date(2025, 7, 4),   # Independence Day
    datetime.date(2025, 12, 25), # Christmas Day
]

optimizer = PTOOptimizer(year=2025, pto_budget=15, holidays=holidays)
plans = optimizer.generate_all_plans()

for plan in plans:
    print(plan.name, "->", sum(b.total_days for b in plan.blocks), "days off")
```

## Strategies

| # | Strategy | Goal |
|---|----------|------|
| 1 | **Bridge Optimizer** | Maximize total vacation days (prefers long blocks) |
| 2 | **Longest Vacation** | Maximize the single longest contiguous vacation |
| 3 | **Extended Weekends** | Many 3-4 day weekends spread across the year |
| 4 | **Quarterly Balance** | Regular breaks in every quarter |

## CLI usage

```bash
# Run as a module
python -m pto

# Or via the entry point
pto
```
