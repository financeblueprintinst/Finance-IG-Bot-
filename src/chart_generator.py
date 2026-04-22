"""Render branded 1080x1350 PNGs for each post type. Uses only matplotlib."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from config import BRAND_HANDLE, BRAND_NAME, COLORS, IMG_H, IMG_W, OUTPUT_DIR
from data_fetcher import NewsItem, Quote

# DPI math so figsize*dpi = 1080x1350
DPI = 150
FIGSIZE = (IMG_W / DPI, IMG_H / DPI)


def _base_fig():
    fig = plt.figure(figsize=FIGSIZE, dpi=DPI, facecolor=COLORS["bg"])
    return fig


def _draw_header(fig, title: str, subtitle: str | None = None):
    fig.text(0.06, 0.94, BRAND_NAME.upper(), color=COLORS["accent"],
             fontsize=12, fontweight="bold", family="DejaVu Sans")
    fig.text(0.06, 0.895, title, color=COLORS["fg"],
             fontsize=26, fontweight="bold", family="DejaVu Sans")
    if subtitle:
        fig.text(0.06, 0.865, subtitle, color=COLORS["muted"],
                 fontsize=13, family="DejaVu Sans")


def _draw_footer(fig):
    today = datetime.now().strftime("%b %d, %Y")
    fig.text(0.06, 0.04, today, color=COLORS["muted"], fontsize=11)
    fig.text(0.94, 0.04, BRAND_HANDLE, color=COLORS["muted"],
             fontsize=11, ha="right")
    fig.text(0.5, 0.015, "Not financial advice. For information only.",
             color=COLORS["muted"], fontsize=8, ha="center", alpha=0.7)


def _save(fig, name: str) -> Path:
    path = OUTPUT_DIR / f"{name}.png"
    fig.savefig(path, dpi=DPI, facecolor=fig.get_facecolor(),
                bbox_inches=None, pad_inches=0)
    plt.close(fig)
    return path


def _fmt_pct(p: float) -> str:
    sign = "+" if p >= 0 else ""
    return f"{sign}{p:.2f}%"


# ---------------------------------------------------------------------------
# Market recap: indices list + one highlighted chart (first ticker)
# ---------------------------------------------------------------------------
def render_market_recap(quotes: list[Quote]) -> Path:
    fig = _base_fig()
    _draw_header(fig, "Market Recap",
                 "Major indices — last close vs. previous day")

    # Main chart: first index history
    if quotes:
        ax = fig.add_axes([0.08, 0.48, 0.84, 0.32])
        hist = quotes[0].history
        color = COLORS["up"] if quotes[0].change_pct >= 0 else COLORS["down"]
        xs = mdates.date2num(hist.index.to_pydatetime())
        ax.plot(xs, hist.values, color=color, linewidth=2.4)
        ax.fill_between(xs, hist.values, hist.values.min(),
                        color=color, alpha=0.15)
        ax.xaxis_date()
        ax.set_facecolor(COLORS["panel"])
        for spine in ax.spines.values():
            spine.set_color(COLORS["grid"])
        ax.tick_params(colors=COLORS["muted"], labelsize=9)
        ax.grid(True, color=COLORS["grid"], linewidth=0.6, alpha=0.5)
        ax.set_title(f"{quotes[0].name}  {_fmt_pct(quotes[0].change_pct)}",
                     color=COLORS["fg"], fontsize=14, loc="left", pad=10)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
        # Pick ~5 evenly spaced ticks across the visible data range
        n = len(xs)
        if n > 1:
            idxs = [0, n // 4, n // 2, (3 * n) // 4, n - 1]
            ax.set_xticks([xs[i] for i in sorted(set(idxs))])
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))

    # Index list below
    y = 0.40
    for q in quotes:
        color = COLORS["up"] if q.change_pct >= 0 else COLORS["down"]
        fig.text(0.08, y, q.name, color=COLORS["fg"], fontsize=16, fontweight="bold")
        fig.text(0.55, y, f"{q.price:,.2f}", color=COLORS["fg"], fontsize=16)
        fig.text(0.82, y, _fmt_pct(q.change_pct), color=color,
                 fontsize=16, fontweight="bold")
        y -= 0.055

    _draw_footer(fig)
    return _save(fig, f"market_recap_{datetime.now():%Y%m%d}")


# ---------------------------------------------------------------------------
# Gainers / Losers
# ---------------------------------------------------------------------------
def render_gainers_losers(gainers: list[Quote], losers: list[Quote]) -> Path:
    fig = _base_fig()
    _draw_header(fig, "Top Movers", "S&P 500 large caps — today's session")

    def _block(y_top: float, title: str, rows: list[Quote], color: str):
        fig.text(0.08, y_top, title, color=color, fontsize=18, fontweight="bold")
        y = y_top - 0.05
        for q in rows:
            fig.text(0.08, y, q.ticker, color=COLORS["fg"],
                     fontsize=17, fontweight="bold")
            fig.text(0.40, y, f"${q.price:,.2f}", color=COLORS["muted"], fontsize=15)
            fig.text(0.82, y, _fmt_pct(q.change_pct), color=color,
                     fontsize=17, fontweight="bold")
            y -= 0.055

    _block(0.80, "GAINERS", gainers, COLORS["up"])
    _block(0.44, "LOSERS", losers, COLORS["down"])
    _draw_footer(fig)
    return _save(fig, f"gainers_losers_{datetime.now():%Y%m%d}")


# ---------------------------------------------------------------------------
# Commodities & Forex combined board
# ---------------------------------------------------------------------------
def render_commodities_forex(commodities: list[Quote], forex: list[Quote]) -> Path:
    fig = _base_fig()
    _draw_header(fig, "Commodities & FX",
                 "Spot prices — last close vs. previous day")

    def _block(y_top: float, title: str, rows: list[Quote]):
        fig.text(0.08, y_top, title, color=COLORS["accent"],
                 fontsize=18, fontweight="bold")
        y = y_top - 0.05
        for q in rows:
            color = COLORS["up"] if q.change_pct >= 0 else COLORS["down"]
            fig.text(0.08, y, q.name, color=COLORS["fg"],
                     fontsize=16, fontweight="bold")
            price_fmt = f"{q.price:,.4f}" if q.price < 10 else f"{q.price:,.2f}"
            fig.text(0.50, y, price_fmt, color=COLORS["fg"], fontsize=15)
            fig.text(0.82, y, _fmt_pct(q.change_pct), color=color,
                     fontsize=16, fontweight="bold")
            y -= 0.05

    _block(0.82, "COMMODITIES", commodities)
    _block(0.48, "FOREX", forex)
    _draw_footer(fig)
    return _save(fig, f"commodities_forex_{datetime.now():%Y%m%d}")


# ---------------------------------------------------------------------------
# Weekly recap (Saturday)
# ---------------------------------------------------------------------------
def render_weekly_recap(quotes: list[Quote]) -> Path:
    fig = _base_fig()
    _draw_header(fig, "Weekly Recap", "Indices — last 20 trading days")

    ax = fig.add_axes([0.08, 0.20, 0.84, 0.62])
    ax.set_facecolor(COLORS["panel"])
    for spine in ax.spines.values():
        spine.set_color(COLORS["grid"])
    ax.tick_params(colors=COLORS["muted"], labelsize=9)
    ax.grid(True, color=COLORS["grid"], linewidth=0.6, alpha=0.5)

    palette = [COLORS["accent"], COLORS["up"], COLORS["down"], "#F5A524", "#A78BFA"]
    for q, c in zip(quotes, palette):
        base = q.history.iloc[0]
        norm = (q.history / base - 1) * 100
        xs = mdates.date2num(norm.index.to_pydatetime())
        ax.plot(xs, norm.values, color=c, linewidth=2.2,
                label=f"{q.name}  {_fmt_pct(q.change_pct)}")
    ax.xaxis_date()

    ax.axhline(0, color=COLORS["muted"], linewidth=0.7, alpha=0.6)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:+.1f}%"))
    # ~5 ticks from the longest series we plotted
    if quotes:
        ref = mdates.date2num(quotes[0].history.index.to_pydatetime())
        if len(ref) > 1:
            n = len(ref)
            idxs = [0, n // 4, n // 2, (3 * n) // 4, n - 1]
            ax.set_xticks([ref[i] for i in sorted(set(idxs))])
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.legend(loc="upper left", facecolor=COLORS["panel"],
              edgecolor=COLORS["grid"], labelcolor=COLORS["fg"], fontsize=10)

    _draw_footer(fig)
    return _save(fig, f"weekly_recap_{datetime.now():%Y%m%d}")


# ---------------------------------------------------------------------------
# News digest (Sunday)
# ---------------------------------------------------------------------------
def render_news_digest(items: list[NewsItem]) -> Path:
    fig = _base_fig()
    _draw_header(fig, "News Digest", "Top finance headlines — last 24h")

    y = 0.82
    for i, n in enumerate(items[:5], start=1):
        title = n.title if len(n.title) <= 90 else n.title[:87] + "…"
        fig.text(0.08, y, f"{i}.", color=COLORS["accent"],
                 fontsize=20, fontweight="bold")
        fig.text(0.14, y, title, color=COLORS["fg"], fontsize=13,
                 wrap=True)
        fig.text(0.14, y - 0.035, n.source, color=COLORS["muted"], fontsize=10)
        y -= 0.14

    _draw_footer(fig)
    return _save(fig, f"news_digest_{datetime.now():%Y%m%d}")
