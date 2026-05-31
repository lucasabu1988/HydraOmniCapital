"""
Salida bonita con Rich para el Screener HYDRA Local.
"""
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
import pandas as pd
from datetime import datetime

console = Console()


def print_header():
    console.print(Panel.fit(
        "[bold cyan]HYDRA SCREENER LOCAL[/bold cyan]\n"
        f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M')} | Modo Manual[/dim]",
        border_style="cyan"
    ))


def print_candidates_table(df: pd.DataFrame, top_n: int = 15):
    """Muestra la tabla principal de candidatos."""
    table = Table(
        title=f"Top {top_n} Candidatos del Día",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta"
    )
    
    table.add_column("Rank", justify="center", style="cyan")
    table.add_column("Ticker", style="bold white")
    table.add_column("Momentum", justify="right", style="green")
    table.add_column("Régimen", justify="center")
    table.add_column("Recomendado", justify="center")
    table.add_column("Nota", style="dim")
    
    for _, row in df.head(top_n).iterrows():
        regime_color = "green" if row['regime_score'] >= 0.5 else "yellow" if row['regime_score'] >= 0.35 else "red"
        
        rec = "✅" if row['recommended'] else "❌"
        rec_style = "green" if row['recommended'] else "red"
        
        table.add_row(
            str(int(row['rank'])),
            row['ticker'],
            f"{row['momentum_score']:.3f}",
            f"[{regime_color}]{row['regime_score']:.2f}[/{regime_color}]",
            f"[{rec_style}]{rec}[/{rec_style}]",
            row['reason']
        )
    
    console.print(table)


def print_summary(regime_score: float, total_candidates: int):
    """Resumen rápido."""
    color = "green" if regime_score >= 0.5 else "yellow" if regime_score >= 0.35 else "red"
    
    console.print(Panel.fit(
        f"[bold]Régimen Score:[/bold] [{color}]{regime_score:.2f}[/{color}]\n"
        f"[bold]Candidatos analizados:[/bold] {total_candidates}\n"
        f"[bold]Top recomendados:[/bold] {min(15, total_candidates)}",
        title="Resumen del Día",
        border_style="blue"
    ))


def print_footer():
    console.print("\n[dim]Ejecuta de nuevo cuando quieras. Los datos son de Yahoo Finance.[/dim]")