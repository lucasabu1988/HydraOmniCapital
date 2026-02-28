"""
Script para actualizar el dashboard con datos honestos de Experiment 41
Cambia 13.90% → 11.31%, añade warnings, y actualiza todas las métricas
"""
import re
from pathlib import Path

# Métricas honestas de Experiment 41 (30 años, 1996-2026)
EXP41_CAGR = "11.31"
EXP41_SHARPE = "0.528"
EXP41_MAX_DD = "-63.4"
EXP41_YEARS = "30"

def update_dashboard_html():
    """Actualiza el dashboard.html con métricas honestas"""

    html_path = Path('templates/dashboard.html')

    if not html_path.exists():
        print(f"❌ No se encontró {html_path}")
        return False

    print(f"📖 Leyendo {html_path}...")
    content = html_path.read_text(encoding='utf-8')
    original_content = content

    changes = []

    # 1. Cambiar CAGR: 13.90% → 11.31%
    content, n = re.subn(r'13\.90%', f'{EXP41_CAGR}%', content)
    if n > 0:
        changes.append(f"✅ CAGR actualizado: 13.90% → {EXP41_CAGR}% ({n} ocurrencias)")

    # 2. Cambiar Sharpe: 0.646 → 0.528
    content, n = re.subn(r'0\.646', EXP41_SHARPE, content)
    if n > 0:
        changes.append(f"✅ Sharpe actualizado: 0.646 → {EXP41_SHARPE} ({n} ocurrencias)")

    # 3. Cambiar Max DD: -66.3% → -63.4%
    content, n = re.subn(r'-66\.3%', f'{EXP41_MAX_DD}%', content)
    if n > 0:
        changes.append(f"✅ Max DD actualizado: -66.3% → {EXP41_MAX_DD}% ({n} ocurrencias)")

    # 4. Actualizar años: 26 years → 30 years
    content, n = re.subn(r'26 years', f'{EXP41_YEARS} years', content)
    if n > 0:
        changes.append(f"✅ Años actualizados: 26 → {EXP41_YEARS} ({n} ocurrencias)")

    # 5. Actualizar experimentos: 40 → 41
    content, n = re.subn(r'40 experiments', '41 experiments', content)
    if n > 0:
        changes.append(f"✅ Experimentos actualizados: 40 → 41 ({n} ocurrencias)")

    # 6. Cambiar referencias Exp40 → Exp41 en comentarios
    content, n = re.subn(r'Exp40', 'Exp41', content, flags=re.IGNORECASE)
    if n > 0:
        changes.append(f"✅ Referencias Exp40 → Exp41 ({n} ocurrencias)")

    # 7. Actualizar sub-textos para ser más honestos
    content = content.replace(
        'Bias-corrected (Exp40)',
        '30-year backtest (Exp41)'
    )
    changes.append("✅ Subtextos actualizados a 30-year backtest")

    # 8. Actualizar meta description
    old_desc = 'Cross-sectional momentum on S&amp;P 500. 13.90% CAGR (Bias-Corrected) | 0.646 Sharpe | No Leverage. 26 years backtested, 40 experiments validated.'
    new_desc = f'Cross-sectional momentum on S&amp;P 500. {EXP41_CAGR}% CAGR (30-year backtest) | {EXP41_SHARPE} Sharpe | No Leverage. {EXP41_YEARS} years backtested, 41 experiments validated.'

    if old_desc in content:
        content = content.replace(old_desc, new_desc)
        changes.append("✅ Meta description actualizada")

    # Guardar si hubo cambios
    if content != original_content:
        # Backup
        backup_path = html_path.with_suffix('.html.backup')
        backup_path.write_text(original_content, encoding='utf-8')
        print(f"💾 Backup guardado en {backup_path}")

        # Guardar
        html_path.write_text(content, encoding='utf-8')
        print(f"\n{'='*60}")
        print("✅ DASHBOARD ACTUALIZADO EXITOSAMENTE")
        print(f"{'='*60}\n")

        for change in changes:
            print(change)

        print(f"\n📊 Métricas finales:")
        print(f"  CAGR: {EXP41_CAGR}%")
        print(f"  Sharpe: {EXP41_SHARPE}")
        print(f"  Max DD: {EXP41_MAX_DD}%")
        print(f"  Período: {EXP41_YEARS} años (1996-2026)")

        return True
    else:
        print("⚠️  No se encontraron cambios necesarios")
        return False


def create_drawdown_chart_snippet():
    """Genera el código HTML/JS para el gráfico de drawdown"""

    snippet = '''
<!-- UNDERWATER/DRAWDOWN CHART -->
<div class="chart-container" style="margin-top: 40px;">
    <div class="chart-header">
        <h3 class="chart-title">📉 Underwater Chart (Drawdown from Peak)</h3>
        <p class="chart-subtitle">
            Shows % decline from all-time high. Color zones:
            <span style="color: var(--green);">Green (0 to -10%)</span>,
            <span style="color: #FFA500;">Yellow (-10% to -25%)</span>,
            <span style="color: #FF6B6B;">Orange (-25% to -50%)</span>,
            <span style="color: var(--red);">Red (-50%+)</span>
        </p>
    </div>
    <canvas id="drawdownChart" style="max-height: 350px;"></canvas>
</div>

<script>
// Underwater/Drawdown Chart
function initDrawdownChart(equityData) {
    const ctx = document.getElementById('drawdownChart');
    if (!ctx || !equityData || equityData.length === 0) return;

    // Calcular drawdown desde peak
    let peak = -Infinity;
    const drawdownData = equityData.map(point => {
        const value = point.y;
        peak = Math.max(peak, value);
        const dd = ((value / peak) - 1) * 100; // Porcentaje
        return {
            x: point.x,
            y: dd,
            peak: peak
        };
    });

    // Zonas de color
    const getColor = (dd) => {
        if (dd >= -10) return 'rgba(34, 197, 94, 0.6)';      // Green
        if (dd >= -25) return 'rgba(255, 165, 0, 0.6)';      // Yellow
        if (dd >= -50) return 'rgba(255, 107, 107, 0.6)';    // Orange
        return 'rgba(239, 68, 68, 0.8)';                      // Red
    };

    new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [{
                label: 'Drawdown from Peak',
                data: drawdownData,
                borderColor: 'rgba(239, 68, 68, 0.8)',
                backgroundColor: (context) => {
                    const dd = context.raw?.y || 0;
                    return getColor(dd);
                },
                fill: true,
                tension: 0.1,
                pointRadius: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            interaction: {
                intersect: false,
                mode: 'index'
            },
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return `Drawdown: ${context.parsed.y.toFixed(2)}%`;
                        }
                    }
                },
                annotation: {
                    annotations: {
                        line1: {
                            type: 'line',
                            yMin: -10,
                            yMax: -10,
                            borderColor: '#FFA500',
                            borderWidth: 1,
                            borderDash: [5, 5]
                        },
                        line2: {
                            type: 'line',
                            yMin: -25,
                            yMax: -25,
                            borderColor: '#FF6B6B',
                            borderWidth: 1,
                            borderDash: [5, 5]
                        },
                        line3: {
                            type: 'line',
                            yMin: -50,
                            yMax: -50,
                            borderColor: '#EF4444',
                            borderWidth: 2,
                            borderDash: [5, 5]
                        }
                    }
                }
            },
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'year',
                        displayFormats: { year: 'yyyy' }
                    },
                    grid: { color: 'rgba(255,255,255,0.05)' }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Drawdown %'
                    },
                    ticks: {
                        callback: function(value) {
                            return value.toFixed(0) + '%';
                        }
                    },
                    max: 0,
                    grid: { color: 'rgba(255,255,255,0.05)' }
                }
            }
        }
    });
}

// Llamar después de cargar equity data
fetchEquityData().then(data => {
    if (data && data.equity) {
        initDrawdownChart(data.equity);
    }
});
</script>
'''

    Path('drawdown_chart_snippet.html').write_text(snippet, encoding='utf-8')
    print("\n📊 Snippet de drawdown chart guardado en drawdown_chart_snippet.html")
    print("   Puedes insertarlo después de la línea 2850 (después del comparison chart)")


def create_warning_banner_snippet():
    """Genera el warning banner estadístico"""

    snippet = '''
<!-- STATISTICAL UNCERTAINTY WARNING BANNER -->
<div class="statistical-warning-banner" style="
    background: linear-gradient(135deg, rgba(239, 68, 68, 0.1), rgba(251, 146, 60, 0.1));
    border-left: 4px solid var(--red);
    padding: 20px 24px;
    margin: 32px 0;
    border-radius: 8px;
">
    <div style="display: flex; align-items: flex-start; gap: 16px;">
        <div style="font-size: 32px; line-height: 1;">⚠️</div>
        <div style="flex: 1;">
            <h3 style="
                margin: 0 0 12px 0;
                font-size: 18px;
                font-weight: 600;
                color: var(--red);
            ">PERFORMANCE UNCERTAINTY</h3>

            <ul style="
                margin: 0;
                padding-left: 20px;
                list-style-type: disc;
                color: var(--text-secondary);
                line-height: 1.8;
            ">
                <li><strong style="color: var(--text-primary);">Sharpe ratio NOT statistically significant</strong> after multiple testing adjustment (DSR p-value = 0.30)</li>
                <li>37 experiments tested over 18 months — high multiple testing penalty applied</li>
                <li>Residual survivorship bias may overstate returns by 1.5-4.0% CAGR</li>
                <li>Alpha declining over time: <strong style="color: var(--green);">+27% (2000s)</strong> → <strong style="color: var(--yellow);">+5.1% (2020s)</strong></li>
                <li>90% confidence interval for expected returns: <strong style="color: var(--accent);">6.5% - 15.5%</strong> annually</li>
                <li>Expected forward CAGR likely <strong style="color: var(--text-primary);">10-13%</strong> (conservative estimate)</li>
            </ul>

            <p style="
                margin: 16px 0 0 0;
                font-size: 13px;
                color: var(--text-tertiary);
                font-style: italic;
            ">
                ℹ️ This warning reflects rigorous statistical analysis, not marketing spin.
                Position sizing should account for this uncertainty.
            </p>
        </div>
    </div>
</div>
'''

    Path('warning_banner_snippet.html').write_text(snippet, encoding='utf-8')
    print("\n⚠️  Warning banner guardado en warning_banner_snippet.html")
    print("   Puedes insertarlo después de la línea 2600 (después del landing hero)")


if __name__ == '__main__':
    print("\n" + "="*60)
    print("🔧 ACTUALIZANDO DASHBOARD CON EXPERIMENT 41 DATA")
    print("="*60 + "\n")

    # 1. Actualizar métricas en HTML
    if update_dashboard_html():
        print("\n✅ Paso 1/3 completo: Métricas actualizadas")

    # 2. Crear snippet de drawdown chart
    create_drawdown_chart_snippet()
    print("✅ Paso 2/3 completo: Drawdown chart generado")

    # 3. Crear warning banner
    create_warning_banner_snippet()
    print("✅ Paso 3/3 completo: Warning banner generado")

    print("\n" + "="*60)
    print("🎉 ACTUALIZACIÓN COMPLETA")
    print("="*60)
    print("\n📝 Próximos pasos manuales:")
    print("   1. Revisar templates/dashboard.html.backup si algo salió mal")
    print("   2. Insertar drawdown_chart_snippet.html después de línea 2850")
    print("   3. Insertar warning_banner_snippet.html después de línea 2600")
    print("   4. Commit los cambios")
    print("\n")
