from __future__ import annotations

import datetime

from pto.optimizer import PTOOptimizer, format_calendar_view, format_plan


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
