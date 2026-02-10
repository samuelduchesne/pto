"""PTO Vacation Optimizer

Maximize your time off by strategically placing PTO days to bridge
weekends and holidays into longer vacation blocks.

Uses dynamic programming to find optimal PTO placements under multiple
strategies, producing several distinct options to choose from.

Strategies:
  1. Bridge Optimizer  - maximize total vacation days (prefers long blocks)
  2. Longest Vacation  - maximize the single longest contiguous vacation
  3. Extended Weekends - many 3-4 day weekends spread across the year
  4. Quarterly Balance - regular breaks in every quarter
"""

from __future__ import annotations

import calendar
import datetime
import math
from collections.abc import Callable, Iterable
from functools import cache
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class VacationBlock(NamedTuple):
    """A contiguous block of days off that includes at least one PTO day."""

    start_date: datetime.date
    end_date: datetime.date
    total_days: int
    pto_days: int
    holidays: int
    weekend_days: int


class Plan(NamedTuple):
    """A complete vacation plan."""

    name: str
    description: str
    blocks: list[VacationBlock]
    pto_dates: list[datetime.date]
    floating_dates: list[datetime.date]


class HolidayGroup(NamedTuple):
    """A group with its own holiday calendar and PTO budget.

    Examples: a person's company holidays, a daycare closure schedule, etc.
    """

    name: str
    holidays: list[datetime.date]
    pto_budget: int
    floating_holidays: int = 0


class GroupAllocation(NamedTuple):
    """PTO allocation for one group within a multi-group plan."""

    group_name: str
    pto_dates: list[datetime.date]
    floating_dates: list[datetime.date]


class MultiGroupPlan(NamedTuple):
    """A vacation plan optimized across multiple groups."""

    name: str
    description: str
    blocks: list[VacationBlock]
    group_allocations: list[GroupAllocation]


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------

ValueFn = Callable[[int, int], float]
"""Signature: value_fn(day_index, streak_position) -> incremental value.

streak_position is 1 for the first off-day in a streak, 2 for the second, etc.
"""


class PTOOptimizer:
    """Optimizes PTO placement to maximize vacation duration through bridging.

    The core idea: weekends and holidays are already days off. By placing PTO
    days in the short gaps between them you *bridge* separate off-blocks into
    much longer contiguous vacations.

    A consecutive-day counter tracks streak length.  Maximising
    ``sum(streak_pos)`` yields ``L*(L+1)/2`` per block of length *L*, giving
    a quadratic preference for fewer, longer blocks — exactly the
    bridge-maximising behaviour we want.
    """

    def __init__(
        self,
        year: int,
        pto_budget: int,
        holidays: list[datetime.date],
        floating_holidays: int = 0,
        *,
        pinned_dates: Iterable[datetime.date] = (),
        blackout_dates: Iterable[datetime.date] = (),
        max_block_days: int | None = None,
        min_gap_days: int = 0,
        monthly_pto_cap: int | None = None,
        seasonal_weights: dict[int, float] | None = None,
    ):
        self.year = year
        self.pto_budget = pto_budget
        self.holidays = set(holidays)
        self.floating_holidays = floating_holidays

        # Heuristic options
        self.pinned_dates = set(pinned_dates)
        self.blackout_dates = set(blackout_dates)
        self.max_block_days = max_block_days
        self.min_gap_days = min_gap_days
        self.monthly_pto_cap = monthly_pto_cap
        self.seasonal_weights = seasonal_weights

        self.start_date = datetime.date(year, 1, 1)
        self.end_date = datetime.date(year, 12, 31)
        self.num_days = (self.end_date - self.start_date).days + 1

        self.dates: list[datetime.date] = [
            self.start_date + datetime.timedelta(days=d) for d in range(self.num_days)
        ]
        self.is_weekend: list[bool] = [d.weekday() >= 5 for d in self.dates]
        self.is_holiday: list[bool] = [d in self.holidays for d in self.dates]
        self.is_natural_off: list[bool] = [
            w or h for w, h in zip(self.is_weekend, self.is_holiday, strict=True)
        ]

        # Pre-compute per-day lookups for heuristics
        self._is_pinned: list[bool] = [d in self.pinned_dates for d in self.dates]
        self._is_blackout: list[bool] = [d in self.blackout_dates for d in self.dates]
        self._month_of: list[int] = [d.month for d in self.dates]

    # ------------------------------------------------------------------
    # Core DP solver
    # ------------------------------------------------------------------

    def _wrap_value_fn(self, value_fn: ValueFn) -> ValueFn:
        """Apply max-block and seasonal-weight modifiers to a value function."""
        max_block = self.max_block_days
        sw = self.seasonal_weights
        month_of = self._month_of

        if max_block is None and sw is None:
            return value_fn

        def wrapped(d: int, s: int) -> float:
            v = value_fn(d, s)
            # Diminishing returns past max_block_days — incremental value
            # drops to near-zero so PTO is better spent on a fresh block.
            if max_block is not None and s > max_block:
                v = math.log1p(s - max_block) * 0.1
            # Seasonal multiplier
            if sw is not None:
                v *= sw.get(month_of[d], 1.0)
            return v

        return wrapped

    def _solve_dp(
        self,
        value_fn: ValueFn,
        pto_budget: int | None = None,
        float_budget: int | None = None,
    ) -> tuple[list[int], list[int]]:
        """Find optimal PTO placement using dynamic programming.

        Parameters
        ----------
        value_fn : (day_index, streak_position) -> float
            Incremental reward for having an off-day at *streak_position*
            within a contiguous block, on calendar day *day_index*.
        pto_budget : int, optional
            Override the default PTO budget.
        float_budget : int, optional
            Override the default floating-holiday budget.

        Returns
        -------
        (pto_day_indices, floating_day_indices)
        """
        # Apply value-function modifiers (max block cap, seasonal weights)
        value_fn = self._wrap_value_fn(value_fn)

        p_budget = self.pto_budget if pto_budget is None else pto_budget
        f_budget = self.floating_holidays if float_budget is None else float_budget
        num_days = self.num_days
        natural_off = self.is_natural_off
        is_pinned = self._is_pinned
        is_blackout = self._is_blackout

        # Heuristic flags
        use_gap = self.min_gap_days > 0
        min_gap = self.min_gap_days
        use_cap = self.monthly_pto_cap is not None
        monthly_cap = self.monthly_pto_cap or 0
        month_of = self._month_of

        # Pre-compute month boundaries for monthly-cap bookkeeping.
        # month_start[d] = day index of the first day in d's month.
        month_start: list[int] = []
        if use_cap:
            cur_m = -1
            cur_start = 0
            for i in range(num_days):
                if month_of[i] != cur_m:
                    cur_m = month_of[i]
                    cur_start = i
                month_start.append(cur_start)

        # Build pinned set (workdays only — weekends/holidays are already off)
        pinned_set: set[int] = set()
        for d in range(num_days):
            if is_pinned[d] and not natural_off[d]:
                pinned_set.add(d)

        # Reserve budget for pinned days upfront so the DP can't spend it.
        # In the DP, pinned days are treated as free off-days (like weekends).
        pinned_count = len(pinned_set)
        pin_from_float = min(f_budget, pinned_count)
        pin_from_pto = min(p_budget, pinned_count - pin_from_float)
        p_budget -= pin_from_pto
        f_budget -= pin_from_float

        # ---- DP with optional gap / monthly-cap state ---------------------
        # State: (day, p_rem, f_rem, streak, gap_cooldown, month_used)
        #   gap_cooldown: workdays remaining before PTO is allowed again
        #   month_used:   PTO days spent in the current month so far
        #
        # To keep the state space manageable we only add extra dimensions
        # when the corresponding heuristic is enabled.

        if use_gap or use_cap:
            # Extended DP with extra state dimensions
            memo: dict[tuple, float] = {}

            def dp_ext(
                day: int,
                p_rem: int,
                f_rem: int,
                streak: int,
                gap_cd: int,
                m_used: int,
            ) -> float:
                if day >= num_days:
                    return 0.0
                key = (day, p_rem, f_rem, streak, gap_cd, m_used)
                if key in memo:
                    return memo[key]

                # Reset month_used at month boundaries
                if use_cap and day > 0 and month_of[day] != month_of[day - 1]:
                    m_used = 0

                # Pinned days: budget already reserved, treat like free off-day
                if natural_off[day] or day in pinned_set:
                    ns = streak + 1
                    val = value_fn(day, ns) + dp_ext(day + 1, p_rem, f_rem, ns, gap_cd, m_used)
                    memo[key] = val
                    return val

                # Workday: gap cooldown ticks down
                new_gap = max(0, gap_cd - 1) if use_gap else 0

                # Check if taking PTO is allowed
                can_take = True
                if is_blackout[day]:
                    can_take = False
                if use_gap and gap_cd > 0 and streak == 0:
                    can_take = False  # still in cooldown
                if use_cap and m_used >= monthly_cap:
                    can_take = False

                # Work option — gap cooldown only applies when breaking a streak
                work_gap = new_gap if streak == 0 else (min_gap if use_gap else 0)
                best = dp_ext(day + 1, p_rem, f_rem, 0, work_gap, m_used)

                if can_take:
                    ns = streak + 1
                    incr = value_fn(day, ns)
                    next_m = m_used + 1

                    if p_rem > 0:
                        v = incr + dp_ext(day + 1, p_rem - 1, f_rem, ns, 0, next_m)
                        if v > best:
                            best = v
                    if f_rem > 0:
                        v = incr + dp_ext(day + 1, p_rem, f_rem - 1, ns, 0, next_m)
                        if v > best:
                            best = v

                memo[key] = best
                return best

            dp_ext(0, p_budget, f_budget, 0, 0, 0)

            # Backtrack
            pto_days: list[int] = []
            float_days: list[int] = []
            day, p_rem, f_rem, streak = 0, p_budget, f_budget, 0
            gap_cd, m_used = 0, 0

            while day < num_days:
                if use_cap and day > 0 and month_of[day] != month_of[day - 1]:
                    m_used = 0

                # Pinned days: record as PTO/float (budget already reserved)
                if natural_off[day]:
                    streak += 1
                    day += 1
                    continue

                if day in pinned_set:
                    # Record with reserved budget (not deducting from p_rem/f_rem)
                    if pin_from_float > 0:
                        float_days.append(day)
                    else:
                        pto_days.append(day)
                    streak += 1
                    gap_cd = 0
                    day += 1
                    continue

                new_gap = max(0, gap_cd - 1) if use_gap else 0

                can_take = True
                if is_blackout[day]:
                    can_take = False
                if use_gap and gap_cd > 0 and streak == 0:
                    can_take = False
                if use_cap and m_used >= monthly_cap:
                    can_take = False

                work_gap = new_gap if streak == 0 else (min_gap if use_gap else 0)

                work_val = dp_ext(day + 1, p_rem, f_rem, 0, work_gap, m_used)
                best_val = work_val
                action = "work"

                if can_take:
                    ns = streak + 1
                    incr = value_fn(day, ns)
                    next_m = m_used + 1

                    if p_rem > 0:
                        v = incr + dp_ext(day + 1, p_rem - 1, f_rem, ns, 0, next_m)
                        if v > best_val:
                            best_val = v
                            action = "pto"
                    if f_rem > 0:
                        v = incr + dp_ext(day + 1, p_rem, f_rem - 1, ns, 0, next_m)
                        if v > best_val:
                            best_val = v
                            action = "float"

                if action == "pto":
                    pto_days.append(day)
                    p_rem -= 1
                    streak = streak + 1
                    gap_cd = 0
                    m_used += 1
                elif action == "float":
                    float_days.append(day)
                    f_rem -= 1
                    streak = streak + 1
                    gap_cd = 0
                    m_used += 1
                else:
                    gap_cd = work_gap if streak == 0 else (min_gap if use_gap else 0)
                    streak = 0

                day += 1

            memo.clear()
            return pto_days, float_days

        # ---- Simple DP (no gap / monthly-cap — original fast path) --------
        @cache
        def dp(day: int, p_rem: int, f_rem: int, streak: int) -> float:
            if day >= num_days:
                return 0.0

            # Pinned days: budget already reserved, treat like free off-day
            if natural_off[day] or day in pinned_set:
                ns = streak + 1
                return value_fn(day, ns) + dp(day + 1, p_rem, f_rem, ns)

            # Blackout: only work
            if is_blackout[day]:
                return dp(day + 1, p_rem, f_rem, 0)

            best = dp(day + 1, p_rem, f_rem, 0)  # work

            ns = streak + 1
            incr = value_fn(day, ns)

            if p_rem > 0:
                v = incr + dp(day + 1, p_rem - 1, f_rem, ns)
                if v > best:
                    best = v

            if f_rem > 0:
                v = incr + dp(day + 1, p_rem, f_rem - 1, ns)
                if v > best:
                    best = v

            return best

        # Forward pass — compute optimal value (populates cache)
        dp(0, p_budget, f_budget, 0)

        # Backtrack to recover the optimal actions
        pto_days = []
        float_days = []

        day, p_rem, f_rem, streak = 0, p_budget, f_budget, 0

        while day < num_days:
            if natural_off[day]:
                streak += 1
                day += 1
                continue

            # Pinned day: record as PTO/float (budget already reserved)
            if day in pinned_set:
                if pin_from_float > 0:
                    float_days.append(day)
                else:
                    pto_days.append(day)
                streak += 1
                day += 1
                continue

            if is_blackout[day]:
                streak = 0
                day += 1
                continue

            ns = streak + 1
            incr = value_fn(day, ns)

            work_val = dp(day + 1, p_rem, f_rem, 0)
            best_val = work_val
            action = "work"

            if p_rem > 0:
                v = incr + dp(day + 1, p_rem - 1, f_rem, ns)
                if v > best_val:
                    best_val = v
                    action = "pto"

            if f_rem > 0:
                v = incr + dp(day + 1, p_rem, f_rem - 1, ns)
                if v > best_val:
                    best_val = v
                    action = "float"

            if action == "pto":
                pto_days.append(day)
                p_rem -= 1
                streak = ns
            elif action == "float":
                float_days.append(day)
                f_rem -= 1
                streak = ns
            else:
                streak = 0

            day += 1

        dp.cache_clear()
        return pto_days, float_days

    # ------------------------------------------------------------------
    # Block extraction
    # ------------------------------------------------------------------

    def _make_plan(
        self,
        name: str,
        description: str,
        pto_idx: list[int],
        float_idx: list[int],
    ) -> Plan:
        off_set = set()
        for d in range(self.num_days):
            if self.is_natural_off[d] or d in set(pto_idx) or d in set(float_idx):
                off_set.add(d)

        blocks = self._extract_blocks(off_set, set(pto_idx), set(float_idx))

        return Plan(
            name=name,
            description=description,
            blocks=blocks,
            pto_dates=[self.dates[i] for i in pto_idx],
            floating_dates=[self.dates[i] for i in float_idx],
        )

    def _extract_blocks(
        self,
        off_set: set[int],
        pto_set: set[int],
        float_set: set[int],
    ) -> list[VacationBlock]:
        if not off_set:
            return []

        sorted_off = sorted(off_set)
        blocks: list[VacationBlock] = []
        start = prev = sorted_off[0]

        for d in sorted_off[1:]:
            if d == prev + 1:
                prev = d
            else:
                blk = self._make_block(start, prev, pto_set, float_set)
                if blk.pto_days > 0:
                    blocks.append(blk)
                start = prev = d

        blk = self._make_block(start, prev, pto_set, float_set)
        if blk.pto_days > 0:
            blocks.append(blk)

        return blocks

    def _make_block(
        self,
        start: int,
        end: int,
        pto_set: set[int],
        float_set: set[int],
    ) -> VacationBlock:
        rng = range(start, end + 1)
        return VacationBlock(
            start_date=self.dates[start],
            end_date=self.dates[end],
            total_days=end - start + 1,
            pto_days=sum(1 for d in rng if d in pto_set or d in float_set),
            holidays=sum(1 for d in rng if self.is_holiday[d]),
            weekend_days=sum(1 for d in rng if self.is_weekend[d]),
        )

    # ------------------------------------------------------------------
    # Strategies
    # ------------------------------------------------------------------

    def optimize_max_bridges(self) -> Plan:
        """Maximize total vacation by bridging gaps between off-blocks.

        Value per off-day = streak position  →  block of length L contributes
        L*(L+1)/2, giving quadratic preference for longer blocks.
        """
        pto, flt = self._solve_dp(value_fn=lambda _d, s: s)
        return self._make_plan(
            "Bridge Optimizer",
            "Maximizes total vacation days by bridging gaps between "
            "weekends and holidays into long contiguous blocks.",
            pto,
            flt,
        )

    def optimize_longest_vacation(self) -> Plan:
        """Concentrate PTO to create the single longest contiguous vacation.

        Uses a sliding window to find the longest feasible contiguous block,
        then runs bridge DP for remaining PTO.
        """
        total_budget = self.pto_budget + self.floating_holidays

        # Sliding window: find longest window where workdays <= budget
        best_start = best_end = 0
        best_len = 0
        workdays = 0
        left = 0

        for right in range(self.num_days):
            if not self.is_natural_off[right]:
                workdays += 1
            while workdays > total_budget:
                if not self.is_natural_off[left]:
                    workdays -= 1
                left += 1
            if right - left + 1 > best_len:
                best_len = right - left + 1
                best_start = left
                best_end = right

        # Assign PTO within the best window
        window = set(range(best_start, best_end + 1))

        # DP with a large bonus for days in the target window
        def value_fn(_d: int, s: int) -> float:
            if _d in window:
                return 1000 + s  # overwhelming preference for the window
            return s  # remaining PTO used for bridges elsewhere

        pto, flt = self._solve_dp(value_fn=value_fn)

        return self._make_plan(
            "Longest Single Vacation",
            "Concentrates PTO to create the single longest possible vacation "
            "block, with remaining days used for bridges elsewhere.",
            pto,
            flt,
        )

    def optimize_extended_weekends(self) -> Plan:
        """Spread PTO across many 3-4 day weekends.

        Penalises streak positions > 4 to discourage long blocks, favouring
        many short getaways instead.
        """

        def value_fn(_d: int, s: int) -> float:
            if s <= 4:
                return float(s)
            return s - 10.0 * (s - 4)  # heavy penalty past 4 days

        pto, flt = self._solve_dp(value_fn=value_fn)

        return self._make_plan(
            "Extended Weekends",
            "Spreads PTO across many 3-4 day weekends throughout the year "
            "for regular short getaways.",
            pto,
            flt,
        )

    def optimize_quarterly(self) -> Plan:
        """Distribute PTO across quarters for year-round breaks.

        Runs the bridge DP independently per quarter, then combines.
        A small overlap at quarter boundaries handles cross-quarter bridges.
        """
        quarter_bounds = [
            (datetime.date(self.year, 1, 1), datetime.date(self.year, 3, 31)),
            (datetime.date(self.year, 4, 1), datetime.date(self.year, 6, 30)),
            (datetime.date(self.year, 7, 1), datetime.date(self.year, 9, 30)),
            (datetime.date(self.year, 10, 1), datetime.date(self.year, 12, 31)),
        ]

        total_budget = self.pto_budget + self.floating_holidays
        base = total_budget // 4
        remainder = total_budget % 4

        # Allocate budget: give extra days to quarters with more holidays
        quarter_holiday_counts = []
        for qs, qe in quarter_bounds:
            count = sum(1 for h in self.holidays if qs <= h <= qe)
            quarter_holiday_counts.append(count)

        # Sort quarters by holiday count descending for remainder allocation
        ranked = sorted(range(4), key=lambda i: -quarter_holiday_counts[i])
        budgets = [base] * 4
        for i in range(remainder):
            budgets[ranked[i]] += 1

        all_pto: list[int] = []
        all_float: list[int] = []

        for qi, (qs, qe) in enumerate(quarter_bounds):
            q_start_idx = (qs - self.start_date).days
            q_end_idx = (qe - self.start_date).days

            q_budget = budgets[qi]
            if q_budget == 0:
                continue

            # Decide PTO vs floating split for this quarter
            float_for_q = min(self.floating_holidays - len(all_float), q_budget)
            pto_for_q = q_budget - max(0, float_for_q)
            float_for_q = max(0, float_for_q)

            # DP restricted to this quarter's date range
            def make_value_fn(start: int, end: int) -> ValueFn:
                def vfn(d: int, s: int) -> float:
                    if start <= d <= end:
                        return float(s)
                    return 0.0

                return vfn

            # Run full-year DP but only reward days in this quarter
            # (PTO placed outside the quarter yields 0 value, so it won't be)
            pto, flt = self._solve_dp(
                value_fn=make_value_fn(q_start_idx, q_end_idx),
                pto_budget=pto_for_q,
                float_budget=float_for_q,
            )
            all_pto.extend(pto)
            all_float.extend(flt)

        all_pto.sort()
        all_float.sort()

        return self._make_plan(
            "Quarterly Balance",
            "Distributes PTO across all four quarters for regular breaks "
            "year-round, with bridges optimised within each quarter.",
            all_pto,
            all_float,
        )

    # ------------------------------------------------------------------
    # Generate all plans
    # ------------------------------------------------------------------

    def generate_all_plans(self) -> list[Plan]:
        strategies = [
            ("optimize_max_bridges", self.optimize_max_bridges),
            ("optimize_longest_vacation", self.optimize_longest_vacation),
            ("optimize_extended_weekends", self.optimize_extended_weekends),
            ("optimize_quarterly", self.optimize_quarterly),
        ]
        plans: list[Plan] = []
        for name, func in strategies:
            try:
                plans.append(func())
            except Exception as e:
                print(f"  [Warning] Strategy '{name}' failed: {e}")
        return plans


class MultiGroupOptimizer:
    """Optimizes PTO placement across multiple groups for shared vacation time.

    Each group has its own holiday calendar and PTO budget.  A day counts as
    shared vacation only when **every** group is off — either naturally (weekend
    or that group's holiday) or by spending PTO.

    The DP uses a tuple of per-group remaining budgets as state, keeping the
    solver general for 2-4 groups with typical budgets.
    """

    def __init__(self, year: int, groups: list[HolidayGroup]):
        if not groups:
            raise ValueError("At least one group is required.")
        self.year = year
        self.groups = groups
        self.num_groups = len(groups)

        self.start_date = datetime.date(year, 1, 1)
        self.end_date = datetime.date(year, 12, 31)
        self.num_days = (self.end_date - self.start_date).days + 1

        self.dates: list[datetime.date] = [
            self.start_date + datetime.timedelta(days=d) for d in range(self.num_days)
        ]
        self.is_weekend: list[bool] = [d.weekday() >= 5 for d in self.dates]

        # Per-group precomputation
        self.group_holiday_sets: list[set[datetime.date]] = []
        self.group_is_holiday: list[list[bool]] = []
        self.group_is_natural_off: list[list[bool]] = []
        self.group_budgets: list[int] = []

        for g in groups:
            hset = set(g.holidays)
            self.group_holiday_sets.append(hset)
            is_hol = [d in hset for d in self.dates]
            self.group_is_holiday.append(is_hol)
            self.group_is_natural_off.append(
                [w or h for w, h in zip(self.is_weekend, is_hol, strict=True)]
            )
            self.group_budgets.append(g.pto_budget + g.floating_holidays)

        # Day-level: True when *every* group is naturally off
        self.all_natural_off: list[bool] = [
            all(self.group_is_natural_off[g][d] for g in range(self.num_groups))
            for d in range(self.num_days)
        ]

    # ------------------------------------------------------------------
    # Core DP solver (multi-group)
    # ------------------------------------------------------------------

    def _solve_dp(
        self,
        value_fn: ValueFn,
        budget_overrides: list[int] | None = None,
    ) -> list[list[int]]:
        """Find optimal shared PTO placement for all groups.

        Parameters
        ----------
        value_fn : (day_index, streak_position) -> float
            Incremental reward for having a shared off-day.
        budget_overrides : list[int], optional
            Override the per-group total budgets (PTO + floating combined).

        Returns
        -------
        per_group_pto_days : list of list of day-indices
            ``per_group_pto_days[g]`` contains the day indices where group *g*
            must spend PTO (or floating holiday).
        """
        num_days = self.num_days
        num_groups = self.num_groups
        all_nat = self.all_natural_off
        g_nat = self.group_is_natural_off
        budgets_init = tuple(budget_overrides) if budget_overrides else tuple(self.group_budgets)

        @cache
        def dp(day: int, budgets: tuple[int, ...], streak: int) -> float:
            if day >= num_days:
                return 0.0

            if all_nat[day]:
                ns = streak + 1
                return value_fn(day, ns) + dp(day + 1, budgets, ns)

            # Not all naturally off — choose: work or take off
            best = dp(day + 1, budgets, 0)  # work

            # Cost: each group not naturally off must spend 1
            new_b = list(budgets)
            can_afford = True
            for g in range(num_groups):
                if not g_nat[g][day]:
                    if new_b[g] > 0:
                        new_b[g] -= 1
                    else:
                        can_afford = False
                        break

            if can_afford:
                ns = streak + 1
                v = value_fn(day, ns) + dp(day + 1, tuple(new_b), ns)
                if v > best:
                    best = v

            return best

        # Forward pass
        dp(0, budgets_init, 0)

        # Backtrack
        per_group: list[list[int]] = [[] for _ in range(num_groups)]
        day, budgets_live, streak = 0, list(budgets_init), 0

        while day < num_days:
            if all_nat[day]:
                streak += 1
                day += 1
                continue

            work_val = dp(day + 1, tuple(budgets_live), 0)
            best_val = work_val
            action = "work"

            new_b = list(budgets_live)
            can_afford = True
            for g in range(num_groups):
                if not g_nat[g][day]:
                    if new_b[g] > 0:
                        new_b[g] -= 1
                    else:
                        can_afford = False
                        break

            if can_afford:
                ns = streak + 1
                v = value_fn(day, ns) + dp(day + 1, tuple(new_b), ns)
                if v > best_val:
                    best_val = v
                    action = "off"

            if action == "off":
                for g in range(num_groups):
                    if not g_nat[g][day]:
                        per_group[g].append(day)
                        budgets_live[g] -= 1
                streak += 1
            else:
                streak = 0

            day += 1

        dp.cache_clear()
        return per_group

    # ------------------------------------------------------------------
    # Block extraction (multi-group)
    # ------------------------------------------------------------------

    def _make_plan(
        self,
        name: str,
        description: str,
        per_group_pto: list[list[int]],
    ) -> MultiGroupPlan:
        # All days that are off for everyone
        off_set: set[int] = set()
        for d in range(self.num_days):
            if self.all_natural_off[d]:
                off_set.add(d)
        all_pto_set: set[int] = set()
        for g_days in per_group_pto:
            all_pto_set.update(g_days)
        off_set.update(all_pto_set)

        blocks = self._extract_blocks(off_set, all_pto_set)

        # Split per-group days into floating then PTO
        allocations: list[GroupAllocation] = []
        for g in range(self.num_groups):
            indices = per_group_pto[g]
            fl_count = self.groups[g].floating_holidays
            float_idx = indices[:fl_count]
            pto_idx = indices[fl_count:]
            allocations.append(
                GroupAllocation(
                    group_name=self.groups[g].name,
                    pto_dates=[self.dates[i] for i in pto_idx],
                    floating_dates=[self.dates[i] for i in float_idx],
                )
            )

        return MultiGroupPlan(
            name=name,
            description=description,
            blocks=blocks,
            group_allocations=allocations,
        )

    def _extract_blocks(self, off_set: set[int], pto_set: set[int]) -> list[VacationBlock]:
        if not off_set:
            return []

        sorted_off = sorted(off_set)
        blocks: list[VacationBlock] = []
        start = prev = sorted_off[0]

        for d in sorted_off[1:]:
            if d == prev + 1:
                prev = d
            else:
                blk = self._make_block(start, prev, pto_set)
                if blk.pto_days > 0:
                    blocks.append(blk)
                start = prev = d

        blk = self._make_block(start, prev, pto_set)
        if blk.pto_days > 0:
            blocks.append(blk)

        return blocks

    def _make_block(self, start: int, end: int, pto_set: set[int]) -> VacationBlock:
        rng = range(start, end + 1)
        # "Shared holidays" = days that are a holiday for ALL groups (not weekend)
        shared_holidays = sum(
            1
            for d in rng
            if not self.is_weekend[d]
            and all(self.group_is_holiday[g][d] for g in range(self.num_groups))
        )
        return VacationBlock(
            start_date=self.dates[start],
            end_date=self.dates[end],
            total_days=end - start + 1,
            pto_days=sum(1 for d in rng if d in pto_set),
            holidays=shared_holidays,
            weekend_days=sum(1 for d in rng if self.is_weekend[d]),
        )

    # ------------------------------------------------------------------
    # Strategies
    # ------------------------------------------------------------------

    def optimize_max_bridges(self) -> MultiGroupPlan:
        """Maximize total shared vacation by bridging gaps."""
        per_group = self._solve_dp(value_fn=lambda _d, s: s)
        return self._make_plan(
            "Bridge Optimizer (Multi-Group)",
            "Maximizes shared vacation days by bridging gaps between "
            "weekends and holidays across all groups.",
            per_group,
        )

    def optimize_longest_vacation(self) -> MultiGroupPlan:
        """Concentrate PTO to create the single longest shared vacation."""
        # Sliding window: find longest window where the *most constrained*
        # group can still afford it.  For each group, count the workdays
        # that are NOT natural off for that group within the window.
        best_start = best_end = 0
        best_len = 0

        # Per-group workday counters in the sliding window
        g_work = [0] * self.num_groups
        left = 0

        for right in range(self.num_days):
            for g in range(self.num_groups):
                if not self.group_is_natural_off[g][right]:
                    g_work[g] += 1

            # Shrink until all groups can afford the window
            while any(g_work[g] > self.group_budgets[g] for g in range(self.num_groups)):
                for g in range(self.num_groups):
                    if not self.group_is_natural_off[g][left]:
                        g_work[g] -= 1
                left += 1

            if right - left + 1 > best_len:
                best_len = right - left + 1
                best_start = left
                best_end = right

        window = set(range(best_start, best_end + 1))

        def value_fn(_d: int, s: int) -> float:
            if _d in window:
                return 1000 + s
            return s

        per_group = self._solve_dp(value_fn=value_fn)
        return self._make_plan(
            "Longest Shared Vacation",
            "Concentrates PTO to create the single longest shared vacation "
            "block, with remaining days used for bridges elsewhere.",
            per_group,
        )

    def optimize_extended_weekends(self) -> MultiGroupPlan:
        """Spread PTO across many short shared getaways."""

        def value_fn(_d: int, s: int) -> float:
            if s <= 4:
                return float(s)
            return s - 10.0 * (s - 4)

        per_group = self._solve_dp(value_fn=value_fn)
        return self._make_plan(
            "Extended Weekends (Multi-Group)",
            "Spreads PTO across many 3-4 day shared weekends throughout "
            "the year for regular short getaways together.",
            per_group,
        )

    def optimize_quarterly(self) -> MultiGroupPlan:
        """Distribute shared PTO across quarters for year-round breaks."""
        quarter_bounds = [
            (datetime.date(self.year, 1, 1), datetime.date(self.year, 3, 31)),
            (datetime.date(self.year, 4, 1), datetime.date(self.year, 6, 30)),
            (datetime.date(self.year, 7, 1), datetime.date(self.year, 9, 30)),
            (datetime.date(self.year, 10, 1), datetime.date(self.year, 12, 31)),
        ]

        # Per-group quarterly budget allocation
        quarter_budgets: list[list[int]] = []  # [quarter][group]
        for _qi, (_qs, _qe) in enumerate(quarter_bounds):
            quarter_budgets.append([0] * self.num_groups)

        for g in range(self.num_groups):
            total = self.group_budgets[g]
            base = total // 4
            remainder = total % 4

            # Count holidays per quarter to decide where to allocate extras
            q_hol = []
            for qs, qe in quarter_bounds:
                count = sum(1 for h in self.groups[g].holidays if qs <= h <= qe)
                q_hol.append(count)
            ranked = sorted(range(4), key=lambda i: -q_hol[i])

            for qi in range(4):
                quarter_budgets[qi][g] = base
            for i in range(remainder):
                quarter_budgets[ranked[i]][g] += 1

        all_per_group: list[list[int]] = [[] for _ in range(self.num_groups)]

        for qi, (qs, qe) in enumerate(quarter_bounds):
            q_start_idx = (qs - self.start_date).days
            q_end_idx = (qe - self.start_date).days

            budgets_for_q = quarter_budgets[qi]
            if all(b == 0 for b in budgets_for_q):
                continue

            def make_value_fn(start: int, end: int) -> ValueFn:
                def vfn(d: int, s: int) -> float:
                    if start <= d <= end:
                        return float(s)
                    return 0.0

                return vfn

            per_group = self._solve_dp(
                value_fn=make_value_fn(q_start_idx, q_end_idx),
                budget_overrides=budgets_for_q,
            )
            for g in range(self.num_groups):
                all_per_group[g].extend(per_group[g])

        for g in range(self.num_groups):
            all_per_group[g].sort()

        return self._make_plan(
            "Quarterly Balance (Multi-Group)",
            "Distributes shared PTO across all four quarters for regular "
            "breaks year-round, with bridges optimised within each quarter.",
            all_per_group,
        )

    # ------------------------------------------------------------------
    # Generate all plans
    # ------------------------------------------------------------------

    def generate_all_plans(self) -> list[MultiGroupPlan]:
        strategies = [
            ("optimize_max_bridges", self.optimize_max_bridges),
            ("optimize_longest_vacation", self.optimize_longest_vacation),
            ("optimize_extended_weekends", self.optimize_extended_weekends),
            ("optimize_quarterly", self.optimize_quarterly),
        ]
        plans: list[MultiGroupPlan] = []
        for name, func in strategies:
            try:
                plans.append(func())
            except Exception as e:
                print(f"  [Warning] Strategy '{name}' failed: {e}")
        return plans


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def format_plan(plan: Plan, optimizer: PTOOptimizer) -> str:
    """Return a human-readable summary of a vacation plan."""
    lines: list[str] = []
    w = 64

    lines.append("")
    lines.append("=" * w)
    lines.append(f"  OPTION: {plan.name}")
    lines.append(f"  {plan.description}")
    lines.append("=" * w)

    total_vacation = sum(b.total_days for b in plan.blocks)
    total_pto = len(plan.pto_dates) + len(plan.floating_dates)

    budget_label = f"{optimizer.pto_budget}"
    if optimizer.floating_holidays:
        budget_label += f" + {optimizer.floating_holidays} floating"

    lines.append(f"  PTO days used: {total_pto} / {budget_label}")
    lines.append(f"  Total vacation days: {total_vacation}")
    if total_pto > 0:
        lines.append(
            f"  Efficiency: {total_vacation / total_pto:.1f}x (vacation days per PTO day)"
        )
    lines.append("")

    # Vacation blocks
    lines.append("  Vacation Blocks:")
    lines.append("  " + "-" * (w - 4))

    for i, block in enumerate(plan.blocks, 1):
        n = block.total_days
        day_word = "day" if n == 1 else "days"
        if block.start_date == block.end_date:
            dr = block.start_date.strftime("%a, %b %d")
        else:
            dr = (
                f"{block.start_date.strftime('%a, %b %d')} -> "
                f"{block.end_date.strftime('%a, %b %d')}"
            )
        lines.append(f"  {i:>2}. {dr}  ({n} {day_word})")

        parts: list[str] = []
        if block.pto_days:
            parts.append(f"{block.pto_days} PTO")
        if block.holidays:
            parts.append(f"{block.holidays} holiday{'s' if block.holidays > 1 else ''}")
        if block.weekend_days:
            parts.append(f"{block.weekend_days} weekend")
        lines.append(f"      {' + '.join(parts)}")
        lines.append("")

    # Days to request off
    lines.append("  Days to request off:")
    for d in plan.pto_dates:
        lines.append(f"    -> {d.strftime('%A, %B %d, %Y')}")
    if plan.floating_dates:
        lines.append("")
        lines.append("  Floating holiday(s):")
        for d in plan.floating_dates:
            lines.append(f"    -> {d.strftime('%A, %B %d, %Y')}")

    return "\n".join(lines)


def format_calendar_view(plan: Plan, optimizer: PTOOptimizer) -> str:
    """Return a month-by-month calendar highlighting PTO and holidays."""
    pto_set = set(plan.pto_dates)
    floating_set = set(plan.floating_dates)
    holiday_set = optimizer.holidays
    year = optimizer.year

    # Determine which months to show (those with PTO or holidays)
    active_months: set[int] = set()
    for d in plan.pto_dates:
        active_months.add(d.month)
    for d in plan.floating_dates:
        active_months.add(d.month)
    for d in holiday_set:
        active_months.add(d.month)

    if not active_months:
        return ""

    lines: list[str] = [
        "",
        f"  Calendar View {year}",
        "  Legend: P=PTO  F=Floating  H=Holiday  (bold = vacation block)",
        "",
    ]

    cal = calendar.Calendar(firstweekday=0)

    for month in range(1, 13):
        if month not in active_months:
            continue

        lines.append(f"  {calendar.month_name[month]} {year}")
        lines.append("  Mo  Tu  We  Th  Fr  Sa  Su")

        row = ""
        for day_num, weekday in cal.itermonthdays2(year, month):
            if day_num == 0:
                row += "    "
            else:
                d = datetime.date(year, month, day_num)
                if d in pto_set:
                    cell = f" {day_num:>2}P"
                elif d in floating_set:
                    cell = f" {day_num:>2}F"
                elif d in holiday_set:
                    cell = f" {day_num:>2}H"
                else:
                    cell = f"  {day_num:>2}"
                row += cell

            if weekday == 6:
                lines.append(row)
                row = ""

        if row.strip():
            lines.append(row)
        lines.append("")

    return "\n".join(lines)


def format_multi_group_plan(plan: MultiGroupPlan, optimizer: MultiGroupOptimizer) -> str:
    """Return a human-readable summary of a multi-group vacation plan."""
    lines: list[str] = []
    w = 64

    lines.append("")
    lines.append("=" * w)
    lines.append(f"  OPTION: {plan.name}")
    lines.append(f"  {plan.description}")
    lines.append("=" * w)

    # Groups summary
    lines.append("")
    lines.append("  Groups:")
    for g, grp in enumerate(optimizer.groups):
        alloc = plan.group_allocations[g]
        used = len(alloc.pto_dates) + len(alloc.floating_dates)
        budget_label = f"{grp.pto_budget}"
        if grp.floating_holidays:
            budget_label += f" + {grp.floating_holidays} floating"
        lines.append(f"    {grp.name}: {used} / {budget_label} PTO used")

    total_vacation = sum(b.total_days for b in plan.blocks)
    total_pto = sum(len(a.pto_dates) + len(a.floating_dates) for a in plan.group_allocations)
    lines.append("")
    lines.append(f"  Total shared vacation days: {total_vacation}")
    lines.append(f"  Total PTO spent (all groups): {total_pto}")
    if total_pto > 0:
        lines.append(
            f"  Efficiency: {total_vacation * len(optimizer.groups) / total_pto:.1f}x"
            " (shared vacation-days per PTO day)"
        )
    lines.append("")

    # Vacation blocks
    lines.append("  Vacation Blocks:")
    lines.append("  " + "-" * (w - 4))

    for i, block in enumerate(plan.blocks, 1):
        n = block.total_days
        day_word = "day" if n == 1 else "days"
        if block.start_date == block.end_date:
            dr = block.start_date.strftime("%a, %b %d")
        else:
            dr = (
                f"{block.start_date.strftime('%a, %b %d')} -> "
                f"{block.end_date.strftime('%a, %b %d')}"
            )
        lines.append(f"  {i:>2}. {dr}  ({n} {day_word})")

        parts: list[str] = []
        if block.pto_days:
            parts.append(f"{block.pto_days} PTO")
        if block.holidays:
            parts.append(f"{block.holidays} shared holiday{'s' if block.holidays > 1 else ''}")
        if block.weekend_days:
            parts.append(f"{block.weekend_days} weekend")
        lines.append(f"      {' + '.join(parts)}")
        lines.append("")

    # Per-group days to request off
    for g, alloc in enumerate(plan.group_allocations):
        grp = optimizer.groups[g]
        lines.append(f"  Days to request off — {grp.name}:")
        if alloc.pto_dates:
            for d in alloc.pto_dates:
                lines.append(f"    -> {d.strftime('%A, %B %d, %Y')}")
        if alloc.floating_dates:
            lines.append("    Floating holiday(s):")
            for d in alloc.floating_dates:
                lines.append(f"      -> {d.strftime('%A, %B %d, %Y')}")
        if not alloc.pto_dates and not alloc.floating_dates:
            lines.append("    (no PTO needed)")
        lines.append("")

    return "\n".join(lines)


def format_multi_group_calendar_view(plan: MultiGroupPlan, optimizer: MultiGroupOptimizer) -> str:
    """Return a month-by-month calendar for a multi-group plan."""
    year = optimizer.year

    # Collect all notable dates
    all_pto: set[datetime.date] = set()
    all_floating: set[datetime.date] = set()
    all_holidays: set[datetime.date] = set()
    for alloc in plan.group_allocations:
        all_pto.update(alloc.pto_dates)
        all_floating.update(alloc.floating_dates)
    for hset in optimizer.group_holiday_sets:
        all_holidays.update(hset)

    active_months: set[int] = set()
    for d in all_pto:
        active_months.add(d.month)
    for d in all_floating:
        active_months.add(d.month)
    for d in all_holidays:
        active_months.add(d.month)

    if not active_months:
        return ""

    lines: list[str] = [
        "",
        f"  Calendar View {year}",
        "  Legend: P=PTO  F=Floating  H=Holiday  (across all groups)",
        "",
    ]

    cal = calendar.Calendar(firstweekday=0)

    for month in range(1, 13):
        if month not in active_months:
            continue

        lines.append(f"  {calendar.month_name[month]} {year}")
        lines.append("  Mo  Tu  We  Th  Fr  Sa  Su")

        row = ""
        for day_num, weekday in cal.itermonthdays2(year, month):
            if day_num == 0:
                row += "    "
            else:
                d = datetime.date(year, month, day_num)
                if d in all_pto:
                    cell = f" {day_num:>2}P"
                elif d in all_floating:
                    cell = f" {day_num:>2}F"
                elif d in all_holidays:
                    cell = f" {day_num:>2}H"
                else:
                    cell = f"  {day_num:>2}"
                row += cell

            if weekday == 6:
                lines.append(row)
                row = ""

        if row.strip():
            lines.append(row)
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    # =====================================================================
    #  CONFIGURATION — edit these values for your situation
    # =====================================================================
    year = 2025
    pto_budget = 15
    floating_holidays = 1

    # 2025 US Federal Holidays (observed dates)
    holidays = [
        datetime.date(2025, 1, 1),  # New Year's Day
        datetime.date(2025, 1, 20),  # Martin Luther King Jr. Day
        datetime.date(2025, 2, 17),  # Presidents' Day
        datetime.date(2025, 5, 26),  # Memorial Day
        datetime.date(2025, 6, 19),  # Juneteenth
        datetime.date(2025, 7, 4),  # Independence Day
        datetime.date(2025, 9, 1),  # Labor Day
        datetime.date(2025, 11, 27),  # Thanksgiving
        datetime.date(2025, 12, 25),  # Christmas Day
    ]

    holiday_names = {
        (1, 1): "New Year's Day",
        (1, 20): "Martin Luther King Jr. Day",
        (2, 17): "Presidents' Day",
        (5, 26): "Memorial Day",
        (6, 19): "Juneteenth",
        (7, 4): "Independence Day",
        (9, 1): "Labor Day",
        (11, 27): "Thanksgiving",
        (12, 25): "Christmas Day",
    }
    # =====================================================================

    w = 64
    print("=" * w)
    print("  PTO VACATION OPTIMIZER")
    print("=" * w)
    print(f"  Year:              {year}")
    print(f"  PTO budget:        {pto_budget} days")
    print(f"  Floating holidays: {floating_holidays}")
    print(f"  Company holidays:  {len(holidays)}")
    print()
    for h in holidays:
        name = holiday_names.get((h.month, h.day), "Holiday")
        print(f"    {h.strftime('%a, %b %d'):>12}  {name}")

    optimizer = PTOOptimizer(year, pto_budget, holidays, floating_holidays)
    plans = optimizer.generate_all_plans()

    for plan in plans:
        print(format_plan(plan, optimizer))
        print(format_calendar_view(plan, optimizer))

    print()
    print("=" * w)
    print(f"  Generated {len(plans)} vacation plan options.")
    print("=" * w)


if __name__ == "__main__":
    main()
