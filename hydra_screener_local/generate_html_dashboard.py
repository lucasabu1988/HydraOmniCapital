import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
#!/usr/bin/env python
"""
Static HTML Dashboard Generator for HYDRA (D3)

Generates a self-contained, nice-looking HTML file from the latest
hydra_last_summary.json (or a history JSON) that can be opened in any browser
without needing TradingView.

Usage:
    python generate_html_dashboard.py
    python generate_html_dashboard.py --json pine/hydra_last_summary.json --output dashboard.html

The output is a single .html file with embedded CSS/JS for the table, regime pills, etc.
Useful as "TV-only" alternative or for sharing.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path
import html

ROOT = Path(__file__).parent

def load_latest_summary(json_path: str = None):
    if json_path:
        p = Path(json_path)
    else:
        candidates = [
            ROOT / "pine" / "hydra_last_summary.json",
            ROOT / "history" / "20260601.json",
            ROOT / "history" / "20260531.json",
        ]
        p = next((c for c in candidates if c.exists()), None)
    if not p or not p.exists():
        raise FileNotFoundError("No summary JSON found. Run the screener first or provide --json.")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f), p

def generate_html(data: dict, source_path: Path) -> str:
    date = data.get("date", "unknown")
    regime = data.get("regime", {})
    pillars = data.get("pillars", {})
    rationale = html.escape(data.get("rationale", ""))
    recs = data.get("recommended_tickers", [])
    top_details = data.get("top_details", [])

    # Regime color
    rtype = regime.get("type", "MODERATE")
    rcolor = {"STRONG": "#22c55e", "MODERATE": "#eab308", "CAUTIOUS": "#f97316", "WEAK": "#ef4444"}.get(rtype, "#64748b")

    # Build table rows
    rows_html = ""
    for d in top_details:
        rec_badge = '<span style="color:#22c55e;font-weight:600">✓</span>' if d.get("ticker") in recs else "—"
        strict_badge = '<span style="color:#22c55e">✓</span>' if d.get("passes_strict") else "—"
        rows_html += f"""
        <tr>
            <td>{d.get('rank', '')}</td>
            <td><strong>{d.get('ticker', '')}</strong></td>
            <td>{d.get('composite', 0):.4f}</td>
            <td>{d.get('momentum', 0):.4f}</td>
            <td>{strict_badge}</td>
            <td>{html.escape(str(d.get('special_modes', '')))}</td>
            <td>{rec_badge}</td>
        </tr>
        """

    pillars_html = ""
    for k, v in pillars.items():
        color = "#22c55e" if v >= 1.0 else "#f97316"
        pillars_html += f'<span style="margin-right:12px"><strong>{k}</strong>: <span style="color:{color}">{v:.2f}</span></span>'

    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>HYDRA Dashboard - {date}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 20px; background: #0f172a; color: #e2e8f0; }}
h1 {{ color: #60a5fa; }}
.card {{ background: #1e2937; padding: 16px; border-radius: 8px; margin-bottom: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.3); }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #334155; }}
th {{ background: #334155; }}
.regime {{ display: inline-block; padding: 4px 12px; border-radius: 9999px; color: white; font-weight: 600; background: {rcolor}; }}
.footer {{ font-size: 12px; color: #64748b; margin-top: 20px; }}
</style>
</head>
<body>
<h1>HYDRA Dashboard — {date}</h1>

<div class="card">
  <h2>Regime <span class="regime">{rtype}</span> (score: {regime.get('score', 0):.3f})</h2>
  <p><strong>Special Modes:</strong> {', '.join(regime.get('special_modes', [])) or '—'}</p>
  <p><strong>Rationale:</strong> {rationale}</p>
</div>

<div class="card">
  <h2>Pillars</h2>
  <p>{pillars_html}</p>
</div>

<div class="card">
  <h2>Recommended ({len(recs)})</h2>
  <p style="font-family: monospace;">{', '.join(recs)}</p>
</div>

<div class="card">
  <h2>Top Details</h2>
  <table>
    <thead>
      <tr><th>Rank</th><th>Ticker</th><th>Composite</th><th>Momentum</th><th>Strict</th><th>Special</th><th>Rec</th></tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</div>

<div class="footer">
  Generated: {datetime.now().isoformat(timespec='seconds')}<br>
  Source: {source_path}<br>
  Open this file in any browser. For live use, re-generate after each screener run or use the Pine dashboard.
</div>
</body>
</html>"""
    return html_content

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=None, help="Path to summary JSON")
    parser.add_argument("--output", default="output/hydra_dashboard.html", help="Output HTML path")
    args = parser.parse_args()

    data, source = load_latest_summary(args.json)
    html = generate_html(data, source)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"[OK] Dashboard written to {out_path}")
    print("Open it in your browser (no internet or TV required).")

if __name__ == "__main__":
    main()
