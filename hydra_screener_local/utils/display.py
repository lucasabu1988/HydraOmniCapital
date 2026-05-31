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
    table.add_column("Tipo", justify="center")
    table.add_column("Special Modes", style="yellow")
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
            str(row.get('regime_type', ''))[:7],
            str(row.get('special_modes', ''))[:22],
            f"{row.get('aggression', 1.0):.2f}",
            f"[{rec_style}]{rec}[/{rec_style}]",
            str(row.get('reason', ''))[:35]
        )
    
    console.print(table)


def print_summary(regime_score: float, total_candidates: int, meta_info: dict = None, pillar_mults: dict = None):
    """Resumen rápido con información de Meta-Layer + Pillar Multipliers."""
    color = "green" if regime_score >= 0.5 else "yellow" if regime_score >= 0.35 else "red"
    
    content = (
        f"[bold]Régimen Score:[/bold] [{color}]{regime_score:.2f}[/{color}]  "
        f"[bold]Tipo:[/bold] {meta_info.get('regime_type', 'N/A') if meta_info else 'N/A'}\n\n"
        f"[bold]Pillar Multipliers recomendados hoy:[/bold]\n"
    )
    
    if pillar_mults:
        for pillar, mult in pillar_mults.items():
            arrow = "↑" if mult > 1.05 else "↓" if mult < 0.95 else "→"
            content += f"  {pillar:12} {mult:.2f}x {arrow}\n"
    else:
        content += "  (No disponibles)\n"
    
    content += f"\n[bold]Candidatos analizados:[/bold] {total_candidates}\n"
    content += f"[bold]Top recomendados:[/bold] {min(15, total_candidates)}"
    
    console.print(Panel.fit(content, title="Resumen del Día - Meta-Layer + Pillars", border_style="blue"))


def print_footer():
    console.print("\n[dim]Ejecuta de nuevo cuando quieras. Los datos son de Yahoo Finance.[/dim]")