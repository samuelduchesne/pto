from __future__ import annotations

import datetime
import json
import os
import tempfile

from typer.testing import CliRunner

from pto.cli import app
from pto.holidays import get_holidays, us_holidays

runner = CliRunner()


def _write_config(data: dict[str, object]) -> str:
    """Write a JSON config to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    return path


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


# =========================================================================
# Multi-group CLI tests
# =========================================================================


class TestMultiGroupOptimize:
    def _basic_config(self) -> dict[str, object]:
        return {
            "year": 2025,
            "groups": [
                {
                    "name": "Alice",
                    "pto_budget": 10,
                    "floating_holidays": 1,
                    "country": "us",
                },
                {
                    "name": "Bob",
                    "pto_budget": 8,
                    "country": "us",
                    "holidays": ["2025-11-28"],
                },
            ],
        }

    def test_multi_group_text_output(self) -> None:
        path = _write_config(self._basic_config())
        try:
            result = runner.invoke(app, ["optimize", "--config", path, "--no-calendar"])
            assert result.exit_code == 0
            assert "Multi-Group" in result.output
            assert "Alice" in result.output
            assert "Bob" in result.output
            assert "Generated 4 vacation plan options." in result.output
        finally:
            os.unlink(path)

    def test_multi_group_json_output(self) -> None:
        path = _write_config(self._basic_config())
        try:
            result = runner.invoke(
                app,
                ["optimize", "--config", path, "--strategy", "bridges", "--json"],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["year"] == 2025
            assert len(data["groups"]) == 2
            assert data["groups"][0]["name"] == "Alice"
            assert len(data["plans"]) == 1
            plan = data["plans"][0]
            assert "group_allocations" in plan
            assert len(plan["group_allocations"]) == 2
        finally:
            os.unlink(path)

    def test_multi_group_single_strategy(self) -> None:
        path = _write_config(self._basic_config())
        try:
            result = runner.invoke(
                app,
                ["optimize", "--config", path, "--strategy", "longest", "--no-calendar"],
            )
            assert result.exit_code == 0
            assert "Generated 1 vacation plan option." in result.output
        finally:
            os.unlink(path)

    def test_multi_group_with_calendar(self) -> None:
        path = _write_config(self._basic_config())
        try:
            result = runner.invoke(
                app,
                ["optimize", "--config", path, "--strategy", "bridges", "--calendar"],
            )
            assert result.exit_code == 0
            assert "Calendar View" in result.output
        finally:
            os.unlink(path)

    def test_multi_group_year_override(self) -> None:
        path = _write_config(self._basic_config())
        try:
            result = runner.invoke(
                app,
                [
                    "optimize",
                    "--config",
                    path,
                    "--year",
                    "2026",
                    "--strategy",
                    "bridges",
                    "--json",
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["year"] == 2026
        finally:
            os.unlink(path)

    def test_config_file_not_found(self) -> None:
        result = runner.invoke(app, ["optimize", "--config", "/nonexistent/config.json"])
        assert result.exit_code == 1
        assert "Config file not found" in result.output

    def test_config_invalid_json(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write("not json{{{")
        try:
            result = runner.invoke(app, ["optimize", "--config", path])
            assert result.exit_code == 1
            assert "Invalid JSON" in result.output
        finally:
            os.unlink(path)

    def test_config_missing_groups_key(self) -> None:
        path = _write_config({"year": 2025})
        try:
            result = runner.invoke(app, ["optimize", "--config", path])
            assert result.exit_code == 1
            assert "groups" in result.output
        finally:
            os.unlink(path)

    def test_config_empty_groups(self) -> None:
        path = _write_config({"groups": []})
        try:
            result = runner.invoke(app, ["optimize", "--config", path])
            assert result.exit_code == 1
        finally:
            os.unlink(path)

    def test_config_no_country(self) -> None:
        """Groups can omit country to have no preset holidays."""
        cfg = {
            "year": 2025,
            "groups": [
                {"name": "Solo", "pto_budget": 5, "holidays": ["2025-12-25"]},
            ],
        }
        path = _write_config(cfg)
        try:
            result = runner.invoke(
                app,
                ["optimize", "--config", path, "--strategy", "bridges", "--json"],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["groups"][0]["holiday_count"] == 1
        finally:
            os.unlink(path)

    def test_budget_not_required_when_config(self) -> None:
        """--budget is not needed when --config is provided."""
        path = _write_config(self._basic_config())
        try:
            result = runner.invoke(
                app,
                ["optimize", "--config", path, "--strategy", "bridges", "--no-calendar"],
            )
            assert result.exit_code == 0
        finally:
            os.unlink(path)
