"""PTO Vacation Optimizer.

Maximize your time off by strategically placing PTO days to bridge
weekends and holidays into longer vacation blocks.
"""

from pto.holidays import get_holidays, us_holidays
from pto.optimizer import (
    GroupAllocation,
    HolidayGroup,
    MultiGroupOptimizer,
    MultiGroupPlan,
    Plan,
    PTOOptimizer,
    VacationBlock,
)

__all__ = [
    "GroupAllocation",
    "HolidayGroup",
    "MultiGroupOptimizer",
    "MultiGroupPlan",
    "PTOOptimizer",
    "Plan",
    "VacationBlock",
    "get_holidays",
    "us_holidays",
]
