"""PTO Vacation Optimizer.

Maximize your time off by strategically placing PTO days to bridge
weekends and holidays into longer vacation blocks.
"""

from pto.optimizer import Plan, PTOOptimizer, VacationBlock

__all__ = ["PTOOptimizer", "Plan", "VacationBlock"]
