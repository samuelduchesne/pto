from __future__ import annotations

import datetime

from pto.optimizer import (
    HolidayGroup,
    MultiGroupOptimizer,
    PTOOptimizer,
    format_calendar_view,
    format_multi_group_calendar_view,
    format_multi_group_plan,
    format_plan,
)


def _us_holidays_2025() -> list[datetime.date]:
    return [
        datetime.date(2025, 1, 1),
        datetime.date(2025, 1, 20),
        datetime.date(2025, 2, 17),
        datetime.date(2025, 5, 26),
        datetime.date(2025, 6, 19),
        datetime.date(2025, 7, 4),
        datetime.date(2025, 9, 1),
        datetime.date(2025, 11, 27),
        datetime.date(2025, 12, 25),
    ]


def _make_optimizer(
    pto_budget: int = 15,
    floating_holidays: int = 1,
) -> PTOOptimizer:
    return PTOOptimizer(
        year=2025,
        pto_budget=pto_budget,
        holidays=_us_holidays_2025(),
        floating_holidays=floating_holidays,
    )


class TestPTOOptimizerInit:
    def test_dates_span_full_year(self) -> None:
        opt = _make_optimizer()
        assert opt.dates[0] == datetime.date(2025, 1, 1)
        assert opt.dates[-1] == datetime.date(2025, 12, 31)
        assert len(opt.dates) == 365

    def test_weekends_detected(self) -> None:
        opt = _make_optimizer()
        # Jan 4 2025 is a Saturday
        idx = (datetime.date(2025, 1, 4) - opt.start_date).days
        assert opt.is_weekend[idx] is True
        # Jan 6 2025 is a Monday
        idx = (datetime.date(2025, 1, 6) - opt.start_date).days
        assert opt.is_weekend[idx] is False

    def test_holidays_detected(self) -> None:
        opt = _make_optimizer()
        idx = (datetime.date(2025, 7, 4) - opt.start_date).days
        assert opt.is_holiday[idx] is True

    def test_natural_off_combines_weekends_and_holidays(self) -> None:
        opt = _make_optimizer()
        # Saturday
        sat_idx = (datetime.date(2025, 1, 4) - opt.start_date).days
        assert opt.is_natural_off[sat_idx] is True
        # Holiday on a weekday
        mlk_idx = (datetime.date(2025, 1, 20) - opt.start_date).days
        assert opt.is_natural_off[mlk_idx] is True


class TestStrategies:
    def test_bridge_optimizer_uses_all_pto(self) -> None:
        opt = _make_optimizer(pto_budget=10, floating_holidays=0)
        plan = opt.optimize_max_bridges()
        assert len(plan.pto_dates) == 10
        assert plan.name == "Bridge Optimizer"

    def test_longest_vacation_uses_all_pto(self) -> None:
        opt = _make_optimizer(pto_budget=10, floating_holidays=0)
        plan = opt.optimize_longest_vacation()
        assert len(plan.pto_dates) == 10

    def test_extended_weekends_uses_all_pto(self) -> None:
        opt = _make_optimizer(pto_budget=10, floating_holidays=0)
        plan = opt.optimize_extended_weekends()
        assert len(plan.pto_dates) == 10

    def test_quarterly_uses_all_budget(self) -> None:
        opt = _make_optimizer(pto_budget=8, floating_holidays=0)
        plan = opt.optimize_quarterly()
        total = len(plan.pto_dates) + len(plan.floating_dates)
        assert total == 8

    def test_bridge_optimizer_vacation_exceeds_pto(self) -> None:
        """Total vacation days should exceed PTO days used (bridging effect)."""
        opt = _make_optimizer(pto_budget=10, floating_holidays=0)
        plan = opt.optimize_max_bridges()
        total_vacation = sum(b.total_days for b in plan.blocks)
        assert total_vacation > 10

    def test_floating_holidays_assigned(self) -> None:
        opt = _make_optimizer(pto_budget=5, floating_holidays=2)
        plan = opt.optimize_max_bridges()
        total = len(plan.pto_dates) + len(plan.floating_dates)
        assert total == 7

    def test_generate_all_plans_returns_four(self) -> None:
        opt = _make_optimizer()
        plans = opt.generate_all_plans()
        assert len(plans) == 4


class TestVacationBlocks:
    def test_blocks_are_contiguous(self) -> None:
        opt = _make_optimizer()
        plan = opt.optimize_max_bridges()
        for block in plan.blocks:
            expected = (block.end_date - block.start_date).days + 1
            assert block.total_days == expected

    def test_block_day_counts_add_up(self) -> None:
        opt = _make_optimizer()
        plan = opt.optimize_max_bridges()
        for block in plan.blocks:
            assert block.pto_days + block.holidays + block.weekend_days <= block.total_days


class TestFormatting:
    def test_format_plan_contains_name(self) -> None:
        opt = _make_optimizer()
        plan = opt.optimize_max_bridges()
        output = format_plan(plan, opt)
        assert "Bridge Optimizer" in output

    def test_format_calendar_view_returns_string(self) -> None:
        opt = _make_optimizer()
        plan = opt.optimize_max_bridges()
        output = format_calendar_view(plan, opt)
        assert isinstance(output, str)
        assert "Calendar View" in output


class TestEdgeCases:
    def test_zero_pto_budget(self) -> None:
        opt = _make_optimizer(pto_budget=0, floating_holidays=0)
        plan = opt.optimize_max_bridges()
        assert len(plan.pto_dates) == 0
        assert len(plan.blocks) == 0

    def test_no_holidays(self) -> None:
        opt = PTOOptimizer(year=2025, pto_budget=5, holidays=[])
        plan = opt.optimize_max_bridges()
        assert len(plan.pto_dates) == 5


# =========================================================================
# Heuristics
# =========================================================================


class TestPinnedDates:
    def test_pinned_date_appears_in_output(self) -> None:
        pin = datetime.date(2025, 8, 15)  # A Friday
        opt = PTOOptimizer(
            year=2025,
            pto_budget=10,
            holidays=_us_holidays_2025(),
            pinned_dates=[pin],
        )
        plan = opt.optimize_max_bridges()
        all_off = set(plan.pto_dates) | set(plan.floating_dates)
        assert pin in all_off

    def test_multiple_pinned_dates(self) -> None:
        pins = [datetime.date(2025, 3, 14), datetime.date(2025, 9, 12)]
        opt = PTOOptimizer(
            year=2025,
            pto_budget=10,
            holidays=_us_holidays_2025(),
            pinned_dates=pins,
        )
        plan = opt.optimize_max_bridges()
        all_off = set(plan.pto_dates) | set(plan.floating_dates)
        for p in pins:
            assert p in all_off

    def test_pinned_uses_budget(self) -> None:
        pins = [datetime.date(2025, 8, 15)]
        opt = PTOOptimizer(
            year=2025,
            pto_budget=5,
            holidays=_us_holidays_2025(),
            pinned_dates=pins,
        )
        plan = opt.optimize_max_bridges()
        total = len(plan.pto_dates) + len(plan.floating_dates)
        assert total <= 5


class TestBlackoutDates:
    def test_blackout_date_excluded(self) -> None:
        # Blackout Jan 2 and Jan 3 — the prime bridging days
        blackouts = [datetime.date(2025, 1, 2), datetime.date(2025, 1, 3)]
        opt = PTOOptimizer(
            year=2025,
            pto_budget=10,
            holidays=_us_holidays_2025(),
            blackout_dates=blackouts,
        )
        plan = opt.optimize_max_bridges()
        all_off = set(plan.pto_dates) | set(plan.floating_dates)
        for b in blackouts:
            assert b not in all_off

    def test_blackout_still_uses_full_budget(self) -> None:
        blackouts = [datetime.date(2025, 1, 2)]
        opt = PTOOptimizer(
            year=2025,
            pto_budget=10,
            holidays=_us_holidays_2025(),
            blackout_dates=blackouts,
        )
        plan = opt.optimize_max_bridges()
        total = len(plan.pto_dates) + len(plan.floating_dates)
        assert total == 10


class TestMaxBlockDays:
    def test_blocks_respect_soft_cap(self) -> None:
        opt = PTOOptimizer(
            year=2025,
            pto_budget=15,
            holidays=_us_holidays_2025(),
            max_block_days=7,
        )
        plan = opt.optimize_max_bridges()
        # With soft cap at 7, we should see multiple shorter blocks
        # instead of one mega-block
        assert len(plan.blocks) >= 2

    def test_no_cap_allows_long_blocks(self) -> None:
        opt = PTOOptimizer(
            year=2025,
            pto_budget=15,
            holidays=_us_holidays_2025(),
        )
        plan = opt.optimize_max_bridges()
        longest = max(b.total_days for b in plan.blocks)
        assert longest >= 7  # unrestricted should produce long blocks

    def test_uses_full_budget(self) -> None:
        opt = PTOOptimizer(
            year=2025,
            pto_budget=10,
            holidays=_us_holidays_2025(),
            max_block_days=5,
        )
        plan = opt.optimize_max_bridges()
        total = len(plan.pto_dates) + len(plan.floating_dates)
        assert total == 10


class TestMinGapDays:
    def test_gap_between_blocks(self) -> None:
        opt = PTOOptimizer(
            year=2025,
            pto_budget=10,
            holidays=_us_holidays_2025(),
            min_gap_days=5,
        )
        plan = opt.optimize_max_bridges()
        # Verify at least 5 workdays between consecutive blocks
        for i in range(len(plan.blocks) - 1):
            end_of_block = plan.blocks[i].end_date
            start_of_next = plan.blocks[i + 1].start_date
            gap_days = 0
            d = end_of_block + datetime.timedelta(days=1)
            while d < start_of_next:
                if d.weekday() < 5:  # workday
                    gap_days += 1
                d += datetime.timedelta(days=1)
            assert gap_days >= 5, (
                f"Gap between block ending {end_of_block} and block "
                f"starting {start_of_next} is only {gap_days} workdays"
            )


class TestMonthlyCap:
    def test_monthly_cap_limits_pto_per_month(self) -> None:
        opt = PTOOptimizer(
            year=2025,
            pto_budget=15,
            holidays=_us_holidays_2025(),
            monthly_pto_cap=3,
        )
        plan = opt.optimize_max_bridges()
        # Count PTO per month
        from collections import Counter

        month_counts: Counter[int] = Counter()
        for d in plan.pto_dates:
            month_counts[d.month] += 1
        for d in plan.floating_dates:
            month_counts[d.month] += 1
        for m, count in month_counts.items():
            assert count <= 3, f"Month {m} has {count} PTO days, exceeds cap of 3"

    def test_monthly_cap_distributes_pto(self) -> None:
        opt = PTOOptimizer(
            year=2025,
            pto_budget=12,
            holidays=_us_holidays_2025(),
            monthly_pto_cap=2,
        )
        plan = opt.optimize_max_bridges()
        # With cap=2, 12 days should spread across at least 6 months
        months_used = set()
        for d in plan.pto_dates:
            months_used.add(d.month)
        for d in plan.floating_dates:
            months_used.add(d.month)
        assert len(months_used) >= 6


class TestSeasonalWeights:
    def test_prefer_summer_shifts_pto(self) -> None:
        opt_default = PTOOptimizer(
            year=2025,
            pto_budget=10,
            holidays=_us_holidays_2025(),
        )
        plan_default = opt_default.optimize_max_bridges()

        opt_summer = PTOOptimizer(
            year=2025,
            pto_budget=10,
            holidays=_us_holidays_2025(),
            seasonal_weights={6: 1.5, 7: 1.5, 8: 1.5},
        )
        plan_summer = opt_summer.optimize_max_bridges()

        def summer_days(plan):
            count = 0
            for d in plan.pto_dates:
                if d.month in (6, 7, 8):
                    count += 1
            for d in plan.floating_dates:
                if d.month in (6, 7, 8):
                    count += 1
            return count

        # Summer-weighted plan should have more summer PTO
        assert summer_days(plan_summer) >= summer_days(plan_default)


class TestCombinedHeuristics:
    def test_pinned_and_blackout_together(self) -> None:
        pin = datetime.date(2025, 7, 3)
        blackout = datetime.date(2025, 1, 2)
        opt = PTOOptimizer(
            year=2025,
            pto_budget=10,
            holidays=_us_holidays_2025(),
            pinned_dates=[pin],
            blackout_dates=[blackout],
        )
        plan = opt.optimize_max_bridges()
        all_off = set(plan.pto_dates) | set(plan.floating_dates)
        assert pin in all_off
        assert blackout not in all_off

    def test_max_block_and_monthly_cap(self) -> None:
        opt = PTOOptimizer(
            year=2025,
            pto_budget=12,
            holidays=_us_holidays_2025(),
            max_block_days=5,
            monthly_pto_cap=3,
        )
        plan = opt.optimize_max_bridges()
        total = len(plan.pto_dates) + len(plan.floating_dates)
        assert total <= 12
        # Verify monthly cap
        from collections import Counter

        month_counts: Counter[int] = Counter()
        for d in plan.pto_dates:
            month_counts[d.month] += 1
        for d in plan.floating_dates:
            month_counts[d.month] += 1
        for _m, count in month_counts.items():
            assert count <= 3

    def test_all_strategies_work_with_heuristics(self) -> None:
        """All four strategies should work when heuristics are enabled."""
        opt = PTOOptimizer(
            year=2025,
            pto_budget=10,
            holidays=_us_holidays_2025(),
            max_block_days=7,
            min_gap_days=3,
            monthly_pto_cap=4,
            seasonal_weights={6: 1.5, 7: 1.5, 8: 1.5},
            pinned_dates=[datetime.date(2025, 7, 3)],
            blackout_dates=[datetime.date(2025, 1, 2)],
        )
        plans = opt.generate_all_plans()
        assert len(plans) == 4
        for plan in plans:
            total = len(plan.pto_dates) + len(plan.floating_dates)
            assert total <= 10


# =========================================================================
# Multi-Group Optimizer
# =========================================================================


def _us_holidays_2025_dates() -> list[datetime.date]:
    """Same list used by the single-group helper."""
    return _us_holidays_2025()


def _make_two_groups(
    budget_a: int = 15,
    budget_b: int = 12,
    floating_a: int = 0,
    floating_b: int = 0,
) -> MultiGroupOptimizer:
    """Two groups with US holidays; group B also gets day-after-Thanksgiving."""
    us = _us_holidays_2025()
    extra = [*us, datetime.date(2025, 11, 28)]  # Black Friday
    return MultiGroupOptimizer(
        year=2025,
        groups=[
            HolidayGroup("Alice", us, budget_a, floating_a),
            HolidayGroup("Bob", extra, budget_b, floating_b),
        ],
    )


class TestMultiGroupInit:
    def test_dates_span_full_year(self) -> None:
        opt = _make_two_groups()
        assert opt.dates[0] == datetime.date(2025, 1, 1)
        assert opt.dates[-1] == datetime.date(2025, 12, 31)
        assert len(opt.dates) == 365

    def test_num_groups(self) -> None:
        opt = _make_two_groups()
        assert opt.num_groups == 2

    def test_all_natural_off_respects_both_groups(self) -> None:
        """A day is all-natural-off only if EVERY group has it off."""
        opt = _make_two_groups()
        # Thanksgiving 2025 is Nov 27 — both groups have it
        idx = (datetime.date(2025, 11, 27) - opt.start_date).days
        assert opt.all_natural_off[idx] is True
        # Black Friday Nov 28 — only Bob has it, Alice doesn't
        idx = (datetime.date(2025, 11, 28) - opt.start_date).days
        assert opt.all_natural_off[idx] is False

    def test_requires_at_least_one_group(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="At least one group"):
            MultiGroupOptimizer(year=2025, groups=[])


class TestMultiGroupStrategies:
    def test_bridge_uses_available_budget(self) -> None:
        opt = _make_two_groups(budget_a=5, budget_b=5)
        plan = opt.optimize_max_bridges()
        for alloc in plan.group_allocations:
            used = len(alloc.pto_dates) + len(alloc.floating_dates)
            assert used <= 5

    def test_bridge_vacation_exceeds_pto(self) -> None:
        opt = _make_two_groups(budget_a=10, budget_b=10)
        plan = opt.optimize_max_bridges()
        total_vacation = sum(b.total_days for b in plan.blocks)
        # Should leverage bridging effect
        assert total_vacation > 10

    def test_longest_vacation_produces_long_block(self) -> None:
        opt = _make_two_groups(budget_a=10, budget_b=10)
        plan = opt.optimize_longest_vacation()
        assert len(plan.blocks) >= 1
        longest = max(b.total_days for b in plan.blocks)
        assert longest >= 10

    def test_extended_weekends_no_very_long_blocks(self) -> None:
        opt = _make_two_groups(budget_a=8, budget_b=8)
        plan = opt.optimize_extended_weekends()
        for block in plan.blocks:
            assert block.total_days <= 7

    def test_quarterly_distributes_across_quarters(self) -> None:
        opt = _make_two_groups(budget_a=8, budget_b=8)
        plan = opt.optimize_quarterly()
        # Check blocks span multiple quarters
        if plan.blocks:
            quarters = {(b.start_date.month - 1) // 3 for b in plan.blocks}
            assert len(quarters) >= 2

    def test_generate_all_plans_returns_four(self) -> None:
        opt = _make_two_groups(budget_a=8, budget_b=8)
        plans = opt.generate_all_plans()
        assert len(plans) == 4

    def test_floating_holidays_assigned(self) -> None:
        opt = _make_two_groups(budget_a=5, budget_b=5, floating_a=2, floating_b=1)
        plan = opt.optimize_max_bridges()
        alice = plan.group_allocations[0]
        bob = plan.group_allocations[1]
        assert len(alice.floating_dates) <= 2
        assert len(bob.floating_dates) <= 1
        assert len(alice.pto_dates) + len(alice.floating_dates) <= 7
        assert len(bob.pto_dates) + len(bob.floating_dates) <= 6

    def test_zero_budget_group_constrains_output(self) -> None:
        """A group with 0 PTO can only be off on weekends + its holidays."""
        us = _us_holidays_2025()
        opt = MultiGroupOptimizer(
            year=2025,
            groups=[
                HolidayGroup("Worker", us, pto_budget=10),
                HolidayGroup("Daycare", us, pto_budget=0),
            ],
        )
        plan = opt.optimize_max_bridges()
        daycare = plan.group_allocations[1]
        # Daycare should have no PTO assigned
        assert len(daycare.pto_dates) == 0
        assert len(daycare.floating_dates) == 0

    def test_different_holidays_cost_more_pto(self) -> None:
        """When groups have different holidays, bridging costs more PTO."""
        us = _us_holidays_2025()
        # Same holidays — single group equivalent
        same = MultiGroupOptimizer(
            year=2025,
            groups=[
                HolidayGroup("A", us, pto_budget=10),
                HolidayGroup("B", us, pto_budget=10),
            ],
        )
        same_plan = same.optimize_max_bridges()
        same_vac = sum(b.total_days for b in same_plan.blocks)

        # Different holidays — harder to align
        diff = MultiGroupOptimizer(
            year=2025,
            groups=[
                HolidayGroup("A", us, pto_budget=10),
                HolidayGroup("B", [], pto_budget=10),  # no holidays at all
            ],
        )
        diff_plan = diff.optimize_max_bridges()
        diff_vac = sum(b.total_days for b in diff_plan.blocks)

        # With no holidays for B, shared vacation should be ≤ same-holiday case
        assert diff_vac <= same_vac


class TestMultiGroupBlocks:
    def test_blocks_are_contiguous(self) -> None:
        opt = _make_two_groups()
        plan = opt.optimize_max_bridges()
        for block in plan.blocks:
            expected = (block.end_date - block.start_date).days + 1
            assert block.total_days == expected

    def test_block_day_counts_add_up(self) -> None:
        opt = _make_two_groups()
        plan = opt.optimize_max_bridges()
        for block in plan.blocks:
            assert block.pto_days + block.holidays + block.weekend_days <= block.total_days


class TestMultiGroupFormatting:
    def test_format_plan_contains_group_names(self) -> None:
        opt = _make_two_groups()
        plan = opt.optimize_max_bridges()
        output = format_multi_group_plan(plan, opt)
        assert "Alice" in output
        assert "Bob" in output
        assert "Multi-Group" in output

    def test_format_calendar_view_returns_string(self) -> None:
        opt = _make_two_groups()
        plan = opt.optimize_max_bridges()
        output = format_multi_group_calendar_view(plan, opt)
        assert isinstance(output, str)
        assert "Calendar View" in output
