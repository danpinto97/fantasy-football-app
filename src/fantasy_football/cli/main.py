"""CLI: league info and draft grades (process vs outcome)."""

from typing import Tuple

import click
from rich.console import Console
from rich.table import Table

from fantasy_football.draft_accuracy.grader import DraftGrader, merge_pool_with_draft
from fantasy_football.espn.client import ESPNClient
from fantasy_football.models.league import LeagueSettings


console = Console()


@click.group()
def cli() -> None:
    """Fantasy football draft tracking (ESPN)."""
    pass


def _load_grader(league_id: str, season: int) -> Tuple[LeagueSettings, DraftGrader]:
    client = ESPNClient()
    try:
        settings = client.get_league_settings(league_id, season)
    except Exception as e:
        console.print(f"[red]Failed to load league settings:[/red] {e}")
        raise click.Abort()
    try:
        draft = client.get_draft(league_id, season)
    except Exception as e:
        console.print(f"[red]Failed to load draft:[/red] {e}")
        raise click.Abort()
    if not draft or not draft.picks:
        console.print("[yellow]No draft data for this league/season.[/yellow]")
        raise click.Abort()
    try:
        pool = client.get_player_pool(league_id, season)
    except Exception as e:
        console.print(f"[yellow]Could not load full player pool:[/yellow] {e}")
        pool = []
    pool = merge_pool_with_draft(pool, draft)
    if settings.num_teams <= 0:
        settings = LeagueSettings(
            league_id=settings.league_id,
            season=settings.season,
            name=settings.name,
            roster_slots=settings.roster_slots,
            num_teams=len({p.team_id for p in draft.picks}),
        )
    return settings, DraftGrader(draft, settings, pool)


def _player_label(player, *, injury: bool = False) -> str:
    label = player.name
    if player.position:
        label += f" ({player.position})"
    if injury and getattr(player, "injury_status", None):
        label += f" [red][{player.injury_status}][/red]"
    return label


@cli.command("draft-accuracy")
@click.option("--league-id", default="96876878", show_default=True, help="ESPN league ID.")
@click.option("--season", type=int, default=2024, show_default=True, help="Season year.")
@click.option(
    "--team-id",
    default=None,
    help="Team ID to analyze. Omit with --leaderboard to grade every team.",
)
@click.option("--max-round", type=int, default=11, show_default=True, help="Last round to include.")
@click.option(
    "--leaderboard/--no-leaderboard",
    default=False,
    help="Print process/outcome ranks for every team.",
)
def draft_accuracy(
    league_id: str,
    season: int,
    team_id: str,
    max_round: int,
    leaderboard: bool,
) -> None:
    """Grade a draft: process (ADP vs pick) and outcome (VBD vs slot)."""
    settings, grader = _load_grader(league_id, season)
    console.print(
        f"[bold]{settings.name or 'League'}[/bold] {league_id}  "
        f"Season {season}  Teams {settings.num_teams}"
    )

    if leaderboard or not team_id:
        if not team_id and not leaderboard:
            console.print("[red]Pass --team-id or --leaderboard.[/red]")
            raise click.Abort()
        grades = grader.grade_league(max_round=max_round)
        table = Table(title="Draft grades")
        table.add_column("Team", style="white")
        table.add_column("Process", justify="right")
        table.add_column("Outcome", justify="right")
        table.add_column("Early K/DST", justify="right")
        by_process = sorted(grades, key=lambda g: -g.process_score)
        for g in by_process:
            table.add_row(
                f"{g.team_name} ({g.team_id})",
                f"{g.process_score:+.1f}",
                f"{g.outcome_score:+.1f}",
                str(g.early_streamable_picks) if g.early_streamable_picks else "—",
            )
        console.print(table)
        console.print(
            "[dim]Process = picks of ADP value (positive = player fell to you), rounds 1–10. "
            "Outcome = VBD minus expected VBD of that slot. "
            "Early K/DST subtracts from process.[/dim]"
        )
        if not team_id:
            return

    team_ids = {p.team_id for p in grader.draft.picks}
    if team_id not in team_ids:
        valid = ", ".join(sorted(team_ids, key=lambda x: int(x) if x.isdigit() else 0))
        console.print(f"[red]Team ID {team_id} not in this draft. Valid IDs: {valid}[/red]")
        raise click.Abort()

    grade = grader.grade_team(team_id, max_round=max_round)
    console.print(
        f"[bold]Process[/bold] {grade.process_score:+.1f}   "
        f"[bold]Outcome[/bold] {grade.outcome_score:+.1f}"
    )
    table = Table(title=f"Draft — {grade.team_name} (Team {grade.team_id})")
    table.add_column("Rd", justify="right", style="cyan")
    table.add_column("Pick", justify="right")
    table.add_column("Your pick", style="white")
    table.add_column("ADP", justify="right")
    table.add_column("Process", justify="right")
    table.add_column("VBD", justify="right")
    table.add_column("Slot exp", justify="right")
    table.add_column("Outcome", justify="right")
    table.add_column("Best available", style="green")
    table.add_column("Best VBD", justify="right")

    for g in grade.picks:
        process_str = f"{g.process_value:+.1f}"
        if g.process_value > 0:
            process_str = f"[green]{process_str}[/green]"
        elif g.process_value < 0:
            process_str = f"[red]{process_str}[/red]"
        outcome_str = f"{g.outcome_value:+.1f}"
        if g.outcome_value > 0:
            outcome_str = f"[green]{outcome_str}[/green]"
        elif g.outcome_value < 0:
            outcome_str = f"[red]{outcome_str}[/red]"
        adp_str = f"{g.actual_adp:.1f}" if g.actual_adp is not None else "—"
        best_label = _player_label(g.best) if g.best else "—"
        best_vbd = f"{g.best_vbd:+.1f}" if g.best_vbd is not None else "—"
        table.add_row(
            str(g.round_num),
            str(g.overall_pick),
            _player_label(g.actual, injury=True),
            adp_str,
            process_str,
            f"{g.actual_vbd:+.1f}",
            f"{g.expected_slot_vbd:+.1f}",
            outcome_str,
            best_label,
            best_vbd,
        )
    console.print(table)
    console.print(
        "[dim]Best available = still undrafted, ADP no more than 0.5 rounds later than this "
        "pick (fallers always count), ranked by FLEX-aware VBD. K/DST only in the last two "
        "rounds. Process = pick# − ADP (positive = steal). Outcome = VBD − slot expected VBD.[/dim]"
    )


@cli.command("league")
@click.option("--league-id", default="96876878", show_default=True, help="ESPN league ID.")
@click.option("--season", type=int, default=2024, show_default=True, help="Season year.")
def league_info(league_id: str, season: int) -> None:
    """Print league settings and basic info."""
    client = ESPNClient()
    try:
        settings = client.get_league_settings(league_id, season)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise click.Abort()

    console.print(f"[bold]{settings.name}[/bold] (ID: {settings.league_id}, Season: {settings.season})")
    console.print(f"Teams: {settings.num_teams}")
    for slot in settings.roster_slots:
        console.print(f"  {slot.position}: {slot.count}" + (" (flex)" if slot.is_flex else ""))


if __name__ == "__main__":
    cli()
