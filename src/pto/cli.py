"""Typer CLI for the PTO Vacation Optimizer."""

from __future__ import annotations

import datetime
import json
import pathlib
import sys

import typer

from pto.holidays import PRESETS, get_holidays
from pto.optimizer import (
    HolidayGroup,
    MultiGroupOptimizer,
    MultiGroupPlan,
    Plan,
    PTOOptimizer,
    format_calendar_view,
    format_multi_group_calendar_view,
    format_multi_group_plan,
    format_plan,
)

app = typer.Typer(
    name="pto",
    help="PTO Vacation Optimizer — maximize your time off by strategically "
    "placing PTO days to bridge weekends and holidays.",
    add_completion=False,
)

STRATEGY_CHOICES = ["all", "bridges", "longest", "weekends", "quarterly"]


def _parse_date(value: str) -> datetime.date:
    """Parse a YYYY-MM-DD date string."""
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise typer.BadParameter(f"Invalid date format {value!r}. Use YYYY-MM-DD.") from None


def _current_year() -> int:
    return datetime.date.today().year


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def optimize(
    year: int = typer.Option(
        None,
        "--year",
        "-y",
        help="Target year. Defaults to the current year.",
    ),
    budget: int = typer.Option(
        None,
        "--budget",
        "-b",
        help="Number of PTO days available (single-group mode).",
        min=0,
    ),
    floating: int = typer.Option(
        0,
        "--floating",
        "-f",
        help="Number of floating holidays available.",
        min=0,
    ),
    country: str | None = typer.Option(
        "us",
        "--country",
        "-c",
        help=f"Holiday preset ({', '.join(sorted(PRESETS))}). Use 'none' to skip.",
    ),
    holiday: list[str] | None = typer.Option(  # noqa: B008
        None,
        "--holiday",
        "-H",
        help="Additional holiday date (YYYY-MM-DD). Repeatable.",
    ),
    strategy: str = typer.Option(
        "all",
        "--strategy",
        "-s",
        help="Strategy to run: all, bridges, longest, weekends, quarterly.",
    ),
    calendar: bool = typer.Option(
        True,
        "--calendar/--no-calendar",
        help="Show month-by-month calendar view.",
    ),
    output_json: bool = typer.Option(
        False,
        "--json",
        help="Output results as JSON.",
    ),
    config: str | None = typer.Option(
        None,
        "--config",
        help="Path to JSON config file for multi-group optimization.",
    ),
) -> None:
    """Optimize your PTO placement for maximum time off.

    Use --budget for single-person mode, or --config for multi-group
    (family / friends) mode.
    """
    # --- Multi-group mode ---
    if config is not None:
        _run_multi_group(config, year, strategy, calendar, output_json)
        return

    # --- Single-group mode (original behaviour) ---
    if budget is None:
        typer.echo("Error: --budget is required (or use --config for multi-group mode).", err=True)
        raise typer.Exit(code=1)

    resolved_year = year if year is not None else _current_year()

    if strategy not in STRATEGY_CHOICES:
        typer.echo(
            f"Error: Invalid strategy {strategy!r}. Choose from: {', '.join(STRATEGY_CHOICES)}",
            err=True,
        )
        raise typer.Exit(code=1)

    # Collect holidays
    holidays: list[datetime.date] = []
    holiday_names: dict[tuple[int, int], str] = {}

    if country and country != "none":
        try:
            preset = get_holidays(country, resolved_year)
        except KeyError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from None
        for d, name in preset:
            holidays.append(d)
            holiday_names[(d.month, d.day)] = name

    if holiday:
        for h in holiday:
            d = _parse_date(h)
            holidays.append(d)

    # Deduplicate and sort
    holidays = sorted(set(holidays))

    # Build optimizer
    optimizer = PTOOptimizer(
        year=resolved_year,
        pto_budget=budget,
        holidays=holidays,
        floating_holidays=floating,
    )

    # Run strategies
    strategy_map = {
        "bridges": optimizer.optimize_max_bridges,
        "longest": optimizer.optimize_longest_vacation,
        "weekends": optimizer.optimize_extended_weekends,
        "quarterly": optimizer.optimize_quarterly,
    }

    plans = optimizer.generate_all_plans() if strategy == "all" else [strategy_map[strategy]()]

    # Output
    if output_json:
        _print_json(plans, optimizer)
    else:
        _print_text(
            plans, optimizer, holidays, holiday_names, resolved_year, budget, floating, calendar
        )


def _print_text(
    plans: list[Plan],
    optimizer: PTOOptimizer,
    holidays: list[datetime.date],
    holiday_names: dict[tuple[int, int], str],
    year: int,
    budget: int,
    floating: int,
    show_calendar: bool,
) -> None:
    w = 64
    typer.echo("=" * w)
    typer.echo("  PTO VACATION OPTIMIZER")
    typer.echo("=" * w)
    typer.echo(f"  Year:              {year}")
    typer.echo(f"  PTO budget:        {budget} days")
    typer.echo(f"  Floating holidays: {floating}")
    typer.echo(f"  Company holidays:  {len(holidays)}")
    typer.echo()
    for h in holidays:
        name = holiday_names.get((h.month, h.day), h.strftime("%b %d"))
        typer.echo(f"    {h.strftime('%a, %b %d'):>12}  {name}")

    for plan in plans:
        typer.echo(format_plan(plan, optimizer))
        if show_calendar:
            typer.echo(format_calendar_view(plan, optimizer))

    typer.echo()
    typer.echo("=" * w)
    typer.echo(f"  Generated {len(plans)} vacation plan option{'s' if len(plans) != 1 else ''}.")
    typer.echo("=" * w)


def _print_json(plans: list[Plan], optimizer: PTOOptimizer) -> None:
    def _serialize_plan(plan: Plan) -> dict[str, object]:
        return {
            "name": plan.name,
            "description": plan.description,
            "pto_dates": [d.isoformat() for d in plan.pto_dates],
            "floating_dates": [d.isoformat() for d in plan.floating_dates],
            "blocks": [
                {
                    "start_date": b.start_date.isoformat(),
                    "end_date": b.end_date.isoformat(),
                    "total_days": b.total_days,
                    "pto_days": b.pto_days,
                    "holidays": b.holidays,
                    "weekend_days": b.weekend_days,
                }
                for b in plan.blocks
            ],
            "summary": {
                "total_vacation_days": sum(b.total_days for b in plan.blocks),
                "total_pto_used": len(plan.pto_dates) + len(plan.floating_dates),
            },
        }

    output = {
        "year": optimizer.year,
        "pto_budget": optimizer.pto_budget,
        "floating_holidays": optimizer.floating_holidays,
        "plans": [_serialize_plan(p) for p in plans],
    }
    json.dump(output, sys.stdout, indent=2)
    typer.echo()


# ---------------------------------------------------------------------------
# Multi-group helpers
# ---------------------------------------------------------------------------


def _load_config(path: str) -> dict[str, object]:
    """Load and validate a multi-group JSON config file."""
    p = pathlib.Path(path)
    if not p.exists():
        typer.echo(f"Error: Config file not found: {path}", err=True)
        raise typer.Exit(code=1)

    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        typer.echo(f"Error: Invalid JSON in config file: {exc}", err=True)
        raise typer.Exit(code=1) from None

    if not isinstance(data, dict) or "groups" not in data:
        typer.echo("Error: Config file must contain a 'groups' key.", err=True)
        raise typer.Exit(code=1)

    return data  # type: ignore[return-value]


def _build_groups(data: dict[str, object], resolved_year: int) -> list[HolidayGroup]:
    """Build HolidayGroup list from parsed config data."""
    groups: list[HolidayGroup] = []
    raw_groups = data["groups"]
    if not isinstance(raw_groups, list) or len(raw_groups) == 0:
        typer.echo("Error: 'groups' must be a non-empty list.", err=True)
        raise typer.Exit(code=1)

    for i, raw in enumerate(raw_groups):
        name = raw.get("name", f"Group {i + 1}")
        pto_budget = int(raw.get("pto_budget", 0))
        floating = int(raw.get("floating_holidays", 0))

        holidays: list[datetime.date] = []

        # Load preset holidays for this group
        country = raw.get("country", None)
        if country and country != "none":
            try:
                preset = get_holidays(country, resolved_year)
            except KeyError as exc:
                typer.echo(f"Error in group {name!r}: {exc}", err=True)
                raise typer.Exit(code=1) from None
            holidays.extend(d for d, _n in preset)

        # Extra custom holidays
        for h in raw.get("holidays", []):
            holidays.append(_parse_date(h))

        holidays = sorted(set(holidays))

        groups.append(
            HolidayGroup(
                name=name,
                holidays=holidays,
                pto_budget=pto_budget,
                floating_holidays=floating,
            )
        )

    return groups


def _run_multi_group(
    config_path: str,
    year_override: int | None,
    strategy: str,
    show_calendar: bool,
    output_json: bool,
) -> None:
    """Execute multi-group optimization from a config file."""
    if strategy not in STRATEGY_CHOICES:
        typer.echo(
            f"Error: Invalid strategy {strategy!r}. Choose from: {', '.join(STRATEGY_CHOICES)}",
            err=True,
        )
        raise typer.Exit(code=1)

    data = _load_config(config_path)
    resolved_year = year_override if year_override is not None else int(data.get("year", _current_year()))  # type: ignore[arg-type]

    groups = _build_groups(data, resolved_year)
    optimizer = MultiGroupOptimizer(year=resolved_year, groups=groups)

    strategy_map = {
        "bridges": optimizer.optimize_max_bridges,
        "longest": optimizer.optimize_longest_vacation,
        "weekends": optimizer.optimize_extended_weekends,
        "quarterly": optimizer.optimize_quarterly,
    }

    plans = (
        optimizer.generate_all_plans()
        if strategy == "all"
        else [strategy_map[strategy]()]
    )

    if output_json:
        _print_multi_group_json(plans, optimizer)
    else:
        _print_multi_group_text(plans, optimizer, resolved_year, show_calendar)


def _print_multi_group_text(
    plans: list[MultiGroupPlan],
    optimizer: MultiGroupOptimizer,
    year: int,
    show_calendar: bool,
) -> None:
    w = 64
    typer.echo("=" * w)
    typer.echo("  PTO VACATION OPTIMIZER (Multi-Group)")
    typer.echo("=" * w)
    typer.echo(f"  Year: {year}")
    typer.echo(f"  Groups: {len(optimizer.groups)}")
    typer.echo()

    for g in optimizer.groups:
        budget_label = f"{g.pto_budget} PTO"
        if g.floating_holidays:
            budget_label += f" + {g.floating_holidays} floating"
        typer.echo(f"    {g.name}: {budget_label}, {len(g.holidays)} holidays")

    for plan in plans:
        typer.echo(format_multi_group_plan(plan, optimizer))
        if show_calendar:
            typer.echo(format_multi_group_calendar_view(plan, optimizer))

    typer.echo()
    typer.echo("=" * w)
    typer.echo(f"  Generated {len(plans)} vacation plan option{'s' if len(plans) != 1 else ''}.")
    typer.echo("=" * w)


def _print_multi_group_json(
    plans: list[MultiGroupPlan], optimizer: MultiGroupOptimizer
) -> None:
    def _serialize(plan: MultiGroupPlan) -> dict[str, object]:
        return {
            "name": plan.name,
            "description": plan.description,
            "blocks": [
                {
                    "start_date": b.start_date.isoformat(),
                    "end_date": b.end_date.isoformat(),
                    "total_days": b.total_days,
                    "pto_days": b.pto_days,
                    "holidays": b.holidays,
                    "weekend_days": b.weekend_days,
                }
                for b in plan.blocks
            ],
            "group_allocations": [
                {
                    "group_name": a.group_name,
                    "pto_dates": [d.isoformat() for d in a.pto_dates],
                    "floating_dates": [d.isoformat() for d in a.floating_dates],
                    "total_used": len(a.pto_dates) + len(a.floating_dates),
                }
                for a in plan.group_allocations
            ],
            "summary": {
                "total_shared_vacation_days": sum(b.total_days for b in plan.blocks),
                "total_pto_across_groups": sum(
                    len(a.pto_dates) + len(a.floating_dates)
                    for a in plan.group_allocations
                ),
            },
        }

    output: dict[str, object] = {
        "year": optimizer.year,
        "groups": [
            {
                "name": g.name,
                "pto_budget": g.pto_budget,
                "floating_holidays": g.floating_holidays,
                "holiday_count": len(g.holidays),
            }
            for g in optimizer.groups
        ],
        "plans": [_serialize(p) for p in plans],
    }
    json.dump(output, sys.stdout, indent=2)
    typer.echo()


@app.command()
def holidays(
    country: str = typer.Option(
        "us",
        "--country",
        "-c",
        help=f"Country preset ({', '.join(sorted(PRESETS))}).",
    ),
    year: int = typer.Option(
        None,
        "--year",
        "-y",
        help="Year to list holidays for. Defaults to the current year.",
    ),
) -> None:
    """List holidays for a country preset."""
    resolved_year = year if year is not None else _current_year()

    try:
        preset = get_holidays(country, resolved_year)
    except KeyError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"  {PRESETS[country]} — {resolved_year}")
    typer.echo()
    for d, name in preset:
        typer.echo(f"    {d.strftime('%a, %b %d'):>12}  {name}")


def main() -> None:
    """Entry point for the CLI."""
    app()
