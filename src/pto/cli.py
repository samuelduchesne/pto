"""Typer CLI for the PTO Vacation Optimizer."""

from __future__ import annotations

import datetime
import json
import sys

import typer

from pto.holidays import PRESETS, get_holidays
from pto.optimizer import Plan, PTOOptimizer, format_calendar_view, format_plan

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
        ...,
        "--budget",
        "-b",
        help="Number of PTO days available.",
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
) -> None:
    """Optimize your PTO placement for maximum time off."""
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
