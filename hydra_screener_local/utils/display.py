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
    """Muestra la tabla principal de candidatos (con ajustes de Meta-Layer)."""
    table = Table(
        title=f"Top {top_n} Candidatos del Día (con Meta-Layer)",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta"
    )
    
    table.add_column("Rank", justify="center", style="cyan")
    table.add_column("Ticker", style="bold white")
    table.add_column("Momentum", justify="right")
    table.add_column("Meta Score", justify="right", style="green")
    table.add_column("Régimen", justify="center")
    table.add_column("Recovery", justify="center")
    table.add_column("Agg", justify="center")
    table.add_column("Rec", justify="center")
    table.add_column("Razón", style="dim")
    
    for _, row in df.head(top_n).iterrows():
        regime_color = "green" if row.get('regime', 0) >= 0.5 else "yellow" if row.get('regime', 0) >= 0.35 else "red"
        
        rec = "✅" if row.get('recommended', False) else "❌"
        rec_style = "green" if row.get('recommended', False) else "red"
        
        recovery = f"{row.get('recovery_boost', 1.0):.2f}"
        
        table.add_row(
            str(int(row['rank'])),
            row['ticker'],
            f"{row.get('momentum', 0):.3f}",
            f"{row.get('meta_score', 0):.3f}",
            f"[{regime_color}]{row.get('regime', 0):.2f}[/{regime_color}]",
            recovery,
            f"{row.get('aggression', 1.0):.2f}",
            f"[{rec_style}]{rec}[/{rec_style}]",
            str(row.get('reason', ''))[:45]
        )
    
    console.print(table)


def print_summary(regime_score: float, total_candidates: int, meta_info: dict = None):
    """Resumen rápido con información de Meta-Layer."""
    color = "green" if regime_score >= 0.5 else "yellow" if regime_score >= 0.35 else "red"
    
    content = (
        f"[bold]Régimen Score:[/bold] [{color}]{regime_score:.2f}[/{color}]\n"
        f"[bold]Candidatos analizados:[/bold] {total_candidates}\n"
        f"[bold]Top recomendados:[/bold] {min(15, total_candidates)}"
    )
    
    if meta_info:
        content += f"\n[bold]Meta Aggression:[/bold] {meta_info.get('aggression', 1.0):.2f}"
        if meta_info.get('recovery_boost', 1.0) > 1.0:
            content += f"  [yellow]Recovery Boost: {meta_info['recovery_boost']:.2f}[/yellow]"
    
    console.print(Panel.fit(content, title="Resumen del Día", border_style="blue"))


def print_footer():
    console.print("\n[dim]Ejecuta de nuevo cuando quieras. Los datos son de Yahoo Finance.[/dim]")