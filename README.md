# PTO Vacation Optimizer

Maximize your time off by strategically placing PTO days to bridge
weekends and holidays into longer vacation blocks.

Uses dynamic programming to find optimal PTO placements under multiple
strategies, producing several distinct options to choose from.

## Strategies

| # | Strategy | Goal |
|---|----------|------|
| 1 | **Bridge Optimizer** | Maximize total vacation days (prefers long blocks) |
| 2 | **Longest Vacation** | Maximize the single longest contiguous vacation |
| 3 | **Extended Weekends** | Many 3-4 day weekends spread across the year |
| 4 | **Quarterly Balance** | Regular breaks in every quarter |

## Installation

Requires Python 3.10+.

```bash
uv add pto
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

## CLI usage

```bash
python -m pto
# or
pto
```

## Development

```bash
git clone https://github.com/samuelduchesne/pto.git
cd pto
uv sync              # install deps
make test            # run tests
make lint            # check lint + format
make typecheck       # run pyright
make docs-serve      # preview docs at http://localhost:8000
```

Run `make help` to see all available targets.

## License

MIT
