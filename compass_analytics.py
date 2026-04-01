import logging
from pathlib import Path

import dash
from dash import dcc, html, Input, Output
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

DARK_BG = "#0f172a"
CARD_BG = "#1e293b"
ACCENT = "#0ea5e9"
TEXT = "#e2e8f0"
MUTED = "#94a3b8"

PLOTLY_TEMPLATE = "plotly_dark"


def create_analytics_app(flask_app):
    dash_app = dash.Dash(
        __name__,
        server=flask_app,
        url_base_pathname="/analytics/",
        suppress_callback_exceptions=True,
    )

    dash_app.layout = html.Div(
        style={"backgroundColor": DARK_BG, "minHeight": "100vh", "padding": "20px",
               "fontFamily": "'Inter', -apple-system, sans-serif", "color": TEXT},
        children=[
            html.H1("HYDRA Analytics", style={"color": ACCENT, "marginBottom": "20px"}),
            html.A("\u2190 Back to Dashboard", href="/",
                   style={"color": ACCENT, "textDecoration": "none", "marginBottom": "20px", "display": "block"}),
            dcc.Tabs(
                id="analytics-tabs",
                value="tearsheet",
                colors={"border": CARD_BG, "primary": ACCENT, "background": DARK_BG},
                style={"marginBottom": "20px"},
                children=[
                    dcc.Tab(label="Performance Tearsheet", value="tearsheet",
                            style={"backgroundColor": CARD_BG, "color": MUTED, "padding": "12px"},
                            selected_style={"backgroundColor": ACCENT, "color": "white", "padding": "12px"}),
                    dcc.Tab(label="Weight Analysis", value="weights",
                            style={"backgroundColor": CARD_BG, "color": MUTED, "padding": "12px"},
                            selected_style={"backgroundColor": ACCENT, "color": "white", "padding": "12px"}),
                    dcc.Tab(label="Risk Decomposition", value="risk",
                            style={"backgroundColor": CARD_BG, "color": MUTED, "padding": "12px"},
                            selected_style={"backgroundColor": ACCENT, "color": "white", "padding": "12px"}),
                    dcc.Tab(label="Live vs Backtest", value="comparison",
                            style={"backgroundColor": CARD_BG, "color": MUTED, "padding": "12px"},
                            selected_style={"backgroundColor": ACCENT, "color": "white", "padding": "12px"}),
                ],
            ),
            html.Div(id="tab-content"),
        ],
    )

    @dash_app.callback(Output("tab-content", "children"), Input("analytics-tabs", "value"))
    def render_tab(tab):
        if tab == "tearsheet":
            return _render_tearsheet_tab()
        elif tab == "weights":
            return _render_weights_tab()
        elif tab == "risk":
            return _render_risk_tab()
        elif tab == "comparison":
            return _render_comparison_tab()
        return html.Div("Unknown tab")

    return dash_app


def _card(title, children):
    return html.Div(
        style={"backgroundColor": CARD_BG, "borderRadius": "8px", "padding": "20px",
               "marginBottom": "16px", "border": f"1px solid {DARK_BG}"},
        children=[
            html.H3(title, style={"color": TEXT, "marginBottom": "12px", "fontSize": "16px"}),
            *children,
        ],
    )


def _render_tearsheet_tab():
    tearsheet_path = Path(__file__).parent / "static" / "reports" / "tearsheet.html"

    try:
        from compass_quantstats import load_returns, generate_tearsheet, compute_metrics
        returns = load_returns(source="backtest")
        generate_tearsheet(returns)
        metrics = compute_metrics(returns)
    except Exception as e:
        logger.warning(f"Failed to load metrics: {e}")
        metrics = {}

    children = []

    if metrics:
        metric_cards = []
        display_metrics = [
            ("CAGR", "cagr", "{:.2%}"), ("Sharpe", "sharpe", "{:.2f}"),
            ("Sortino", "sortino", "{:.2f}"), ("Max Drawdown", "max_drawdown", "{:.2%}"),
            ("Volatility", "volatility", "{:.2%}"), ("Calmar", "calmar", "{:.2f}"),
            ("Win Rate", "win_rate", "{:.2%}"), ("Profit Factor", "profit_factor", "{:.2f}"),
        ]
        for label, key, fmt in display_metrics:
            val = metrics.get(key)
            formatted = fmt.format(val) if val is not None else "N/A"
            metric_cards.append(
                html.Div(style={"textAlign": "center", "padding": "12px", "backgroundColor": DARK_BG,
                                "borderRadius": "6px", "minWidth": "120px"}, children=[
                    html.Div(label, style={"color": MUTED, "fontSize": "12px", "marginBottom": "4px"}),
                    html.Div(formatted, style={"color": ACCENT, "fontSize": "20px", "fontWeight": "bold"}),
                ])
            )
        children.append(_card("Key Metrics", [
            html.Div(style={"display": "flex", "gap": "12px", "flexWrap": "wrap"}, children=metric_cards)
        ]))

    if tearsheet_path.exists():
        children.append(_card("Full Tearsheet", [
            html.Iframe(
                src="/static/reports/tearsheet.html",
                style={"width": "100%", "height": "800px", "border": "none", "borderRadius": "4px"},
            )
        ]))
    else:
        children.append(_card("Tearsheet", [
            html.P("Tearsheet not yet generated. It will be created on first load.",
                   style={"color": MUTED})
        ]))

    return html.Div(children)


def _render_weights_tab():
    try:
        import json
        state_path = Path(__file__).parent / "state" / "compass_state_latest.json"
        with open(state_path) as f:
            state = json.load(f)

        positions = state.get("positions", {})
        position_meta = state.get("position_meta", {})
        if not positions:
            return _card("Weight Analysis", [html.P("No active positions", style={"color": MUTED})])

        symbols = list(positions.keys())
        weights_method = "unknown"
        for sym in symbols:
            meta = position_meta.get(sym, {})
            if "weights_method" in meta:
                weights_method = meta["weights_method"]
                break

        shares_data = {sym: pos.get("shares", 0) for sym, pos in positions.items()}
        costs = {sym: position_meta.get(sym, {}).get("entry_price", pos.get("avg_cost", 100)) for sym, pos in positions.items()}
        values = {sym: shares_data[sym] * costs[sym] for sym in symbols}
        total = sum(values.values()) or 1
        weight_pct = {sym: v / total for sym, v in values.items()}

        fig = go.Figure(data=[go.Pie(
            labels=list(weight_pct.keys()),
            values=list(weight_pct.values()),
            hole=0.4,
            marker=dict(colors=px.colors.qualitative.Set2),
            textinfo="label+percent",
        )])
        fig.update_layout(
            template=PLOTLY_TEMPLATE,
            paper_bgcolor=CARD_BG,
            plot_bgcolor=CARD_BG,
            title=f"Current Allocation (method: {weights_method})",
            font=dict(color=TEXT),
            height=400,
        )

        return html.Div([
            _card("Current Portfolio Weights", [dcc.Graph(figure=fig)]),
        ])

    except Exception as e:
        return _card("Weight Analysis", [html.P(f"Error loading data: {e}", style={"color": "#ef4444"})])


def _render_risk_tab():
    try:
        import json
        state_path = Path(__file__).parent / "state" / "compass_state_latest.json"
        with open(state_path) as f:
            state = json.load(f)

        positions = state.get("positions", {})
        position_meta = state.get("position_meta", {})
        if not positions:
            return _card("Risk Decomposition", [html.P("No active positions", style={"color": MUTED})])

        symbols = list(positions.keys())

        from compass_riskfolio import compute_risk_contribution
        costs = {sym: position_meta.get(sym, {}).get("entry_price", positions[sym].get("avg_cost", 100)) for sym in symbols}
        shares = {sym: positions[sym].get("shares", 0) for sym in symbols}
        values = {sym: shares[sym] * costs[sym] for sym in symbols}
        total = sum(values.values()) or 1
        current_weights = {sym: v / total for sym, v in values.items()}

        rc = compute_risk_contribution(symbols, current_weights)

        rc_symbols = list(rc.keys())
        rc_values = [rc[s]["risk_contribution"] for s in rc_symbols]
        weight_values = [rc[s]["weight"] for s in rc_symbols]

        fig = go.Figure(data=[
            go.Bar(name="Weight", x=rc_symbols, y=weight_values,
                   marker_color=ACCENT, opacity=0.6),
            go.Bar(name="Risk Contribution", x=rc_symbols, y=rc_values,
                   marker_color="#f59e0b"),
        ])
        fig.update_layout(
            template=PLOTLY_TEMPLATE, barmode="group",
            paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
            title="Weight vs Risk Contribution",
            font=dict(color=TEXT), height=400,
            yaxis=dict(tickformat=".0%"),
        )

        from compass_riskfolio import compute_correlation_matrix
        try:
            corr = compute_correlation_matrix(symbols)

            heatmap = go.Figure(data=go.Heatmap(
                z=corr.values, x=corr.columns.tolist(), y=corr.index.tolist(),
                colorscale="RdBu_r", zmin=-1, zmax=1,
                text=np.round(corr.values, 2), texttemplate="%{text}",
            ))
            heatmap.update_layout(
                template=PLOTLY_TEMPLATE, paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                title="Position Correlation Matrix (63d)",
                font=dict(color=TEXT), height=400,
            )
            return html.Div([
                _card("Risk Contribution", [dcc.Graph(figure=fig)]),
                _card("Correlation Matrix", [dcc.Graph(figure=heatmap)]),
            ])
        except Exception:
            return html.Div([_card("Risk Contribution", [dcc.Graph(figure=fig)])])

    except Exception as e:
        return _card("Risk Decomposition", [html.P(f"Error: {e}", style={"color": "#ef4444"})])


def _render_comparison_tab():
    try:
        from compass_quantstats import load_returns

        backtest_returns = load_returns(source="backtest")
        backtest_equity = (1 + backtest_returns).cumprod()

        try:
            live_returns = load_returns(source="live")
            live_equity = (1 + live_returns).cumprod()
            has_live = len(live_returns) > 0
        except Exception:
            has_live = False

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=backtest_equity.index, y=backtest_equity.values,
            name="Backtest", line=dict(color=MUTED, width=1),
        ))

        if has_live:
            fig.add_trace(go.Scatter(
                x=live_equity.index, y=live_equity.values,
                name="Live", line=dict(color=ACCENT, width=2),
            ))

            if len(live_returns) > 5:
                common = backtest_returns.index.intersection(live_returns.index)
                if len(common) > 5:
                    diff = live_returns.loc[common] - backtest_returns.loc[common]
                    tracking_error = diff.std() * np.sqrt(252)
                    fig.add_annotation(
                        x=0.02, y=0.98, xref="paper", yref="paper",
                        text=f"Tracking Error: {tracking_error:.2%}",
                        showarrow=False, font=dict(color=ACCENT, size=14),
                    )

        fig.update_layout(
            template=PLOTLY_TEMPLATE, paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
            title="Equity Curve: Backtest vs Live",
            font=dict(color=TEXT), height=500,
            xaxis=dict(title="Date"), yaxis=dict(title="Growth of $1"),
            legend=dict(x=0.02, y=0.95),
        )

        return _card("Live vs Backtest Comparison", [dcc.Graph(figure=fig)])

    except Exception as e:
        return _card("Comparison", [html.P(f"Error: {e}", style={"color": "#ef4444"})])
