from __future__ import annotations

import datetime
import json

from typer.testing import CliRunner

from pto.cli import app
from pto.holidays import get_holidays, us_holidays

runner = CliRunner()


class TestOptimizeCommand:
    def test_optimize_basic(self) -> None:
        result = runner.invoke(
            app, ["optimize", "--budget", "10", "--year", "2025", "--no-calendar"]
        )
        assert result.exit_code == 0
        assert "PTO VACATION OPTIMIZER" in result.output
        assert "Bridge Optimizer" in result.output

    def test_optimize_single_strategy(self) -> None:
        result = runner.invoke(
            app,
            [
                "optimize",
                "--budget",
                "5",
                "--year",
                "2025",
                "--strategy",
                "bridges",
                "--no-calendar",
            ],
        )
        assert result.exit_code == 0
        assert "Bridge Optimizer" in result.output
        assert "Generated 1 vacation plan option." in result.output

    def test_optimize_json_output(self) -> None:
        result = runner.invoke(
            app, ["optimize", "--budget", "5", "--year", "2025", "--strategy", "bridges", "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["year"] == 2025
        assert data["pto_budget"] == 5
        assert len(data["plans"]) == 1
        assert data["plans"][0]["name"] == "Bridge Optimizer"

    def test_optimize_all_strategies(self) -> None:
        result = runner.invoke(
            app, ["optimize", "--budget", "10", "--year", "2025", "--no-calendar"]
        )
        assert result.exit_code == 0
        assert "Generated 4 vacation plan options." in result.output

    def test_optimize_with_calendar(self) -> None:
        result = runner.invoke(
            app,
            ["optimize", "--budget", "5", "--year", "2025", "--strategy", "bridges", "--calendar"],
        )
        assert result.exit_code == 0
        assert "Calendar View" in result.output

    def test_optimize_invalid_strategy(self) -> None:
        result = runner.invoke(app, ["optimize", "--budget", "5", "--strategy", "bogus"])
        assert result.exit_code == 1
        assert "Invalid strategy" in result.output

    def test_optimize_no_country(self) -> None:
        result = runner.invoke(
            app,
            [
                "optimize",
                "--budget",
                "5",
                "--year",
                "2025",
                "--country",
                "none",
                "--holiday",
                "2025-12-25",
                "--no-calendar",
            ],
        )
        assert result.exit_code == 0
        assert "Company holidays:  1" in result.output

    def test_optimize_custom_holiday(self) -> None:
        result = runner.invoke(
            app,
            [
                "optimize",
                "--budget",
                "5",
                "--year",
                "2025",
                "--holiday",
                "2025-03-17",
                "--no-calendar",
            ],
        )
        assert result.exit_code == 0
        # 9 US holidays + 1 custom = 10
        assert "Company holidays:  10" in result.output

    def test_optimize_invalid_country(self) -> None:
        result = runner.invoke(app, ["optimize", "--budget", "5", "--country", "zz"])
        assert result.exit_code == 1
        assert "Unknown country preset" in result.output

    def test_optimize_budget_required(self) -> None:
        result = runner.invoke(app, ["optimize"])
        assert result.exit_code != 0

    def test_optimize_floating_holidays(self) -> None:
        result = runner.invoke(
            app, ["optimize", "--budget", "5", "--floating", "2", "--year", "2025", "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["floating_holidays"] == 2

    def test_optimize_zero_budget(self) -> None:
        result = runner.invoke(
            app, ["optimize", "--budget", "0", "--year", "2025", "--strategy", "bridges", "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["plans"][0]["pto_dates"] == []


class TestHolidaysCommand:
    def test_holidays_default(self) -> None:
        result = runner.invoke(app, ["holidays", "--year", "2025"])
        assert result.exit_code == 0
        assert "United States federal holidays" in result.output
        assert "New Year" in result.output
        assert "Christmas" in result.output

    def test_holidays_invalid_country(self) -> None:
        result = runner.invoke(app, ["holidays", "--country", "zz"])
        assert result.exit_code == 1
        assert "Unknown country preset" in result.output


class TestHolidayPresets:
    def test_us_holidays_count(self) -> None:
        holidays = us_holidays(2025)
        assert len(holidays) == 9

    def test_us_holidays_sorted(self) -> None:
        holidays = us_holidays(2025)
        dates = [d for d, _ in holidays]
        assert dates == sorted(dates)

    def test_us_holidays_observed_saturday(self) -> None:
        # July 4, 2026 falls on Saturday -> observed Friday July 3
        holidays = us_holidays(2026)
        dates = {d: n for d, n in holidays}
        assert datetime.date(2026, 7, 3) in dates

    def test_us_holidays_observed_sunday(self) -> None:
        # July 4, 2021 falls on Sunday -> observed Monday July 5
        holidays = us_holidays(2021)
        dates = {d: n for d, n in holidays}
        assert datetime.date(2021, 7, 5) in dates

    def test_get_holidays_unknown_country(self) -> None:
        import pytest

        with pytest.raises(KeyError):
            get_holidays("xx", 2025)

    def test_get_holidays_us(self) -> None:
        holidays = get_holidays("us", 2025)
        assert len(holidays) == 9
