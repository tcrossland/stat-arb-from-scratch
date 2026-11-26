"""Ledger explorer: the forward runs' ledgers, locally. See docs/plans/ledger-explorer.md.

    uv run --group explore marimo run notebooks/ledger.py -- --root <checkout> --ledger <name>

`--root` is the checkout whose ledgers to read, by default this one. `--ledger` is the ledger to open first: `reversal`,
the default, or a momentum path by its name in config/momentum_forward.toml; a selector on the page switches between
them. The views are in `statarb.paper.views`; this file only lays them out, with its theme in `ledger.css` beside it. It runs on the local machine only: decision record
0003 forbids redistributing the data the ledger derives from, so nothing it shows is committed or published.
"""

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="Ledger explorer", css_file="ledger.css")


@app.cell
def _():
    import base64
    import datetime as dt
    import io
    from html import escape
    from pathlib import Path

    import marimo as mo
    import matplotlib.pyplot as plt
    import pandas as pd
    from matplotlib.ticker import FuncFormatter

    from statarb.config import repo_root
    from statarb.data.schema import TICKER
    from statarb.paper import views

    return FuncFormatter, Path, TICKER, base64, dt, escape, io, mo, pd, plt, repo_root, views


@app.cell
def _(FuncFormatter, base64, escape, io, mo, plt):
    # Chart style. Long and short, and the lines of one chart, take fixed colours in a fixed order; text stays in
    # ink, never in a series colour. The palette is chosen for the page's theme, not flipped.
    _dark = mo.app_meta().theme == "dark"
    INK = (
        {"surface": "#1a1a19", "primary": "#f0efec", "secondary": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a", "axis": "#383835", "quiet": "#52514e"}
        if _dark
        else {"surface": "#fcfcfb", "primary": "#0b0b0b", "secondary": "#52514e", "muted": "#898781", "grid": "#e1e0d9", "axis": "#c3c2b7", "quiet": "#c3c2b7"}
    )
    SERIES = ("#3987e5", "#d95926", "#199e70") if _dark else ("#2a78d6", "#eb6834", "#1baf7a")
    WIDE = 10.8                                                   # inches; the page shows a figure at 100 pixels an inch
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Helvetica Neue", "Arial", "DejaVu Sans"]

    def canvas(width: float, height: float, rows: int = 1, grid: str = "y"):
        """A figure on the chart surface with quiet axes: hairline grid, no frame, muted ticks."""
        fig, axes = plt.subplots(rows, 1, figsize=(width, height), dpi=160, facecolor=INK["surface"])
        for ax in [axes] if rows == 1 else axes:
            ax.set_facecolor(INK["surface"])
            for side in ("top", "right", "left", "bottom"):
                ax.spines[side].set_visible(False)
            ax.tick_params(colors=INK["muted"], length=0, labelsize=8)
            ax.grid(axis=grid, color=INK["grid"], linewidth=0.6)
            ax.set_axisbelow(True)
        return fig, axes

    def title(ax, text: str) -> None:
        ax.set_title(text, loc="left", fontsize=9.5, fontweight="bold", color=INK["primary"], pad=10)

    def legend(ax) -> None:
        ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.0), ncols=4, frameon=False, fontsize=8, labelcolor=INK["secondary"],
                  handlelength=1.2, columnspacing=1.2, borderaxespad=0.3)

    def zero(ax, axis: str = "y") -> None:
        (ax.axhline if axis == "y" else ax.axvline)(0, color=INK["axis"], linewidth=1.0, zorder=1)

    def money(value: float, signed: bool = False) -> str:
        sign = "−" if value < 0 else "+" if signed and value > 0 else ""
        return f"{sign}${abs(value):,.0f}"

    def signed(value: float) -> str:
        """A weight as a signed percentage; a value that rounds to nothing has no sign."""
        return "0.00%" if abs(value) < 5e-5 else f"{value:+.2%}".replace("-", "−")

    def compact(value: float, _=None) -> str:
        size, sign = abs(value), "−" if value < 0 else ""
        if size >= 1e6:
            return f"{sign}${size / 1e6:.1f}M"
        return f"{sign}${size / 1e3:.0f}K" if size >= 1e4 else f"{sign}${size:,.0f}"

    def money_axis(ax, axis: str, largest: float) -> None:
        """Dollar ticks in one style along the axis: in full under $10,000, else in thousands or millions."""
        unit, suffix = (1e6, "M") if largest >= 1e6 else (1e3, "K") if largest >= 1e4 else (1.0, "")
        label = (lambda v, _: f"{'−' if v < 0 else ''}${abs(v) / unit:g}{suffix}") if suffix else (lambda v, _: compact(v))
        getattr(ax, f"{axis}axis").set_major_formatter(FuncFormatter(label))

    def percent_axis(ax, axis: str) -> None:
        """Percent ticks on steps of 1, 2 or 5, with the decimal places the ticks themselves need, so no label is a
        rounded tick: a step of 2.5 points labelled in whole percents reads 2%, 5%, 8%."""
        ax.locator_params(axis=axis, steps=[1, 2, 5, 10])
        target = getattr(ax, f"{axis}axis")

        def label(value, _):
            ticks = target.get_majorticklocs() * 100
            places = next((p for p in range(3) if abs(ticks - ticks.round(p)).max() < 1e-9), 3)
            return f"{value:.{places}%}".replace("-", "−")

        target.set_major_formatter(FuncFormatter(label))

    def day_axis(ax, dates) -> None:
        """Trading days evenly spaced, so weekends leave no gap; at most eight date labels."""
        step = max(1, -(-len(dates) // 8))
        ticks = list(range(0, len(dates), step))
        ax.set_xticks(ticks, [f"{dates[i]:%d %b}" for i in ticks])
        ax.set_xlim(-0.6, len(dates) - 0.4)

    def bar_width(days: int, width: float) -> float:
        """A bar width in day steps that stays thin: at most 24 pixels at the size the page shows the chart."""
        return min(0.6, 24 * days / (width * 100))

    LEAST = 720                                                   # pixels: the narrowest a WIDE chart is drawn

    def chart(fig, alt: str, least: int | None = None):
        """The figure as an image at its own size, 100 pixels an inch, shrinking to fit the page. With `least` it
        shrinks no further than `least` pixels, in a box that scrolls sideways, so its text stays legible on a phone."""
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=200, facecolor=fig.get_facecolor(), metadata={"Software": None})
        plt.close(fig)
        width = round(fig.get_figwidth() * 100)
        src = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        floor = f"min-width:{min(least, width)}px;" if least else ""
        hint = '<p class="lx-scroll-hint">Scroll sideways for the whole chart.</p>' if least else ""
        return mo.Html(f'<div class="lx-chart"><img src="{src}" alt="{escape(alt)}" style="width:{width}px;{floor}"></div>{hint}')

    return INK, LEAST, SERIES, WIDE, bar_width, canvas, chart, compact, day_axis, legend, money, money_axis, percent_axis, signed, title, zero


@app.cell
def _(Path, escape, mo, repo_root, views):
    # The ledger to open: the reversal run's, or a momentum path by the name config/momentum_forward.toml gives it.
    root = Path(mo.cli_args().get("root") or repo_root()).resolve()
    _names = views.ledgers(root)
    _labels = {("Reversal" if n == views.REVERSAL else f"Momentum: {n}"): n for n in _names}
    _asked = mo.cli_args().get("ledger") or views.REVERSAL
    mo.stop(_asked not in _names, mo.callout(mo.md(f"No ledger `{_asked}` under `{root}`. The ledgers are "
                                                   + ", ".join(f"`{n}`" for n in _names) + "."), kind="danger"))
    which = mo.ui.dropdown(_labels, value=next(k for k, v in _labels.items() if v == _asked), label="Ledger")
    mo.hstack([mo.Html('<div class="lx-header"><h1>Ledger explorer</h1></div>'), which], justify="space-between", align="center", wrap=True)
    return root, which


@app.cell
def _(mo, root, views, which):
    loaded = views.load(root, which.value)
    frame, sectors = loaded.frame, loaded.sectors
    all_days = views.days(frame)
    mo.stop(not all_days, mo.callout(mo.md(f"No ledger days in `{loaded.folder}`."), kind="warn"))
    book_size = float(frame["book_size"].iloc[0])
    # The decile sort of the momentum paths ranks its signal itself: no slope, and expected moves that are NaN for
    # stocks and zero for the hedges. Those columns are left out rather than shown blank or as zeros.
    moves = views.calibrated(frame)
    return all_days, book_size, frame, loaded, moves, sectors


@app.cell
def _(escape, mo, pd):
    def tiles(*items):
        """A row of stat tiles from (label, value, caption) or (label, value, caption, bad)."""
        cells = "".join(
            f'<div class="lx-tile{" lx-bad" if len(item) > 3 and item[3] else ""}"><div class="lx-label">{escape(item[0])}</div>'
            f'<div class="lx-value">{escape(item[1])}</div><div class="lx-caption">{escape(item[2])}</div></div>'
            for item in items
        )
        return mo.Html(f'<div class="lx-tiles">{cells}</div>')

    def heading(text: str):
        return mo.Html(f'<div class="lx-h">{escape(text)}</div>')

    def note(text: str):
        return mo.Html(f'<p class="lx-note">{escape(text)}</p>')

    def plural(count: int, word: str) -> str:
        return f"{count:,} {word}{'' if count == 1 else 's'}"

    _WEIGHTS = {"held", "drifted", "trade", "holding", "target", "long", "short", "gross", "net", "turnover"}
    _BASIS_POINTS = {"expected_move", "prior_expected_move", "pnl", "borrow"}
    _LABELS = {
        "date": "Date", "ticker": "Ticker", "sector": "Sector", "side": "Side", "action": "Action", "names": "Names",
        "held": "Carried in", "ret": "Return, open to open", "pnl": "P&L (bp)", "borrow": "Borrow (bp)", "drifted": "Before trade",
        "trade": "Trade", "holding": "Holding", "target": "Target", "expected_move": "Expected move (bp)",
        "prior_expected_move": "Expected move, prior close (bp)",
        "holding_usd": "Holding ($)", "trade_usd": "Trade ($)", "gross_usd": "Gross P&L ($)", "borrow_usd": "Borrow ($)",
        "cost_spread_usd": "Spread ($)", "cost_impact_usd": "Impact ($)", "cost_commission_usd": "Commission ($)",
        "net_usd": "Net ($)", "cumulative_net_usd": "Cumulative net ($)", "pnl_usd": "P&L ($)", "turnover": "Turnover",
        "days": "Days", "entry": "Entry", "exit": "Exit", "status": "Solver status",
        "slope": "Slope", "git_commit": "Commit", "git_dirty": "Tree", "snapshot": "Snapshot",
    }

    def _formatter(pattern: str):
        def text(value) -> str:
            if pd.isna(value):
                return ""
            out = pattern.format(value)
            return out.replace("-", "−" if any(digit in out for digit in "123456789") else "")   # no sign on a zero

        return text

    def show(table: pd.DataFrame, index: bool = False, page_size: int = 15):
        """A read-only table for reading: named columns, dates as dates, weights in percent, small moves in basis
        points, dollars whole, numbers right-aligned."""
        out = table.reset_index() if index else table.copy()
        formats, justify, names = {}, {}, {}
        for column in out.columns:
            label = _LABELS.get(column, column.replace("_", " ").capitalize())
            values = out[column]
            names[column] = label
            if pd.api.types.is_datetime64_any_dtype(values):
                out[column] = values.dt.strftime("%Y-%m-%d").fillna("open" if column == "exit" else "")
            elif pd.api.types.is_float_dtype(values):
                if column.endswith("_usd"):
                    formats[label] = _formatter("{:,.0f}")
                elif column in _WEIGHTS:
                    formats[label] = _formatter("{:.2%}")
                elif column in _BASIS_POINTS:
                    out[column] = values * 1e4
                    formats[label] = _formatter("{:.1f}")
                else:
                    formats[label] = _formatter("{:.2%}" if column == "ret" else "{:.3f}")
                justify[label] = "right"
            elif pd.api.types.is_integer_dtype(values):
                justify[label] = "right"
        return mo.ui.table(
            out.rename(columns=names), selection=None, page_size=page_size, format_mapping=formats, text_justify_columns=justify,
            show_data_types=False, show_column_summaries=False, show_download=False,
            show_search=len(out) > page_size,   # a table that fits on one page needs no search
        )

    return heading, note, plural, show, tiles


@app.cell
def _(all_days, dt, escape, frame, loaded, mo, money, plural, signed, tiles, views):
    _last = views.exposure(frame).iloc[-1]
    _net = views.pnl(frame)["net_usd"].sum()
    _problems = len(loaded.problems)
    # What the daily job would process if it ran now, by its own rule. One session due is the usual state between the
    # run time and the scheduler's; more than one means a run was missed.
    _due = views.due(loaded.run, all_days[-1], dt.datetime.now(dt.UTC))
    _state = "" if _due is None else ", up to date" if not len(_due) else f", {plural(len(_due), 'session')} due"
    mo.vstack([
        mo.Html(
            f'<p class="lx-sub">{all_days[0]:%Y-%m-%d} to {all_days[-1]:%Y-%m-%d} · sectors from snapshot '
            f"{escape(str(loaded.snapshot))} · <code>{escape(str(loaded.folder))}</code></p>"
        ),
        tiles(
            ("Last ledger day", f"{all_days[-1]:%Y-%m-%d}", f"day {len(all_days)} of the run{_state}", _due is not None and len(_due) > 1),
            ("Gross exposure", f"{_last['gross']:.1%}", "after the last open"),
            ("Net exposure", signed(_last["net"]), "after the last open"),
            ("Names long / short", f"{int(_last['names_long'])} / {int(_last['names_short'])}", "after the last open"),
            ("Net P&L to date", money(_net, signed=True), "after costs and borrow"),
            ("Ledger check", "✓ Intact" if not _problems else f"! {_problems} problem{'s' if _problems > 1 else ''}",
             "chain, first day, metadata", bool(_problems)),
        ),
        *([mo.callout(mo.md("**The ledger failed its check:**\n\n" + "\n".join(f"- {p}" for p in loaded.problems)), kind="danger")]
          if _problems else []),
    ])


@app.cell
def _(TICKER, all_days, frame, mo, pd, sectors, views):
    # Dates are picked from the ledger's own days, written as ISO 8601: a calendar picker follows the browser's
    # locale, and offers days the ledger does not have.
    _days = {f"{d:%Y-%m-%d}": d for d in all_days}
    _latest = next(reversed(_days))
    day = mo.ui.dropdown(_days, value=_latest, searchable=True, label="Day")
    _month_back = next(label for label, d in _days.items() if d >= all_days[-1] - pd.Timedelta(days=30))
    since = mo.ui.dropdown(_days, value=_month_back, searchable=True, label="From")
    until = mo.ui.dropdown(_days, value=_latest, searchable=True, label="to")
    window = mo.hstack([since, until], justify="start", gap=0.75)
    _largest = views.book(frame, sectors, all_days[-1])[TICKER]                 # start on the largest position, if any
    ticker = mo.ui.dropdown(sorted(frame[TICKER].unique()), value=_largest.iloc[0] if len(_largest) else None, searchable=True, label="Ticker")
    by = mo.ui.dropdown({"Sector": "sector", "Ticker": "ticker", "Side": "side"}, value="Sector", label="By")
    return by, day, since, ticker, until, window


@app.cell
def _(frame, since, until, views):
    in_window = views.between(frame, min(since.value, until.value), max(since.value, until.value))   # either order
    return (in_window,)


@app.cell
def _(SERIES, canvas, chart, day, frame, heading, legend, mo, moves, percent_axis, plural, sectors, show, signed, tiles, title, views,
      zero):
    _held = views.book(frame, sectors, day.value)
    _sectors = views.sector_exposure(_held)
    _exp = views.exposure(frame).loc[day.value]
    _rows = list(range(len(_sectors)))[::-1]                       # largest gross at the top
    _fig, _ax = canvas(4.4, 0.9 + 0.34 * max(len(_sectors), 1), grid="x")
    _ax.barh(_rows, _sectors["long"], height=0.5, color=SERIES[0], label="Long")
    _ax.barh(_rows, _sectors["short"], height=0.5, color=SERIES[1], label="Short")
    _ax.set_yticks(_rows, list(_sectors.index))
    zero(_ax, "x")
    percent_axis(_ax, "x")
    title(_ax, "By sector, % of capital")
    legend(_ax)
    _fig.tight_layout()
    book_tab = mo.vstack([
        day,
        tiles(
            ("Gross exposure", f"{_exp['gross']:.1%}", f"after the open of {day.value:%Y-%m-%d}"),
            ("Net exposure", signed(_exp["net"]), "long plus short"),
            ("Long", f"{_exp['long']:.1%}", plural(int(_exp["names_long"]), "name")),
            ("Short", f"{_exp['short']:.1%}".replace("-", "−"), plural(int(_exp["names_short"]), "name")),
        ),
        # The chart keeps its own width and the table takes the rest, side by side where both fit, else stacked.
        mo.Html('<div class="lx-pair">' + chart(_fig, "Long and short weight by sector").text
                + f"<div>{show(_sectors, index=True).text}</div></div>"),
        heading(f"Positions, largest first ({len(_held)})"),
        show(_held if moves else _held.drop(columns="prior_expected_move")),
    ])
    return (book_tab,)


@app.cell
def _(TICKER, heading, in_window, mo, money, plural, show, tiles, views, window):
    _trades = views.trades(in_window)
    trades_tab = mo.vstack([
        window,
        tiles(
            ("Trades", f"{len(_trades):,}", f"on {plural(_trades['date'].nunique(), 'day')}"),
            ("Names traded", f"{_trades[TICKER].nunique():,}", "in the window"),
            ("Traded", money(_trades["trade_usd"].abs().sum()), "buys plus sells"),
            ("Opens / closes", f"{(_trades['action'] == 'open').sum()} / {(_trades['action'] == 'close').sum()}", "flips count as neither"),
        ),
        heading("Trades at each open, latest day first"),
        show(_trades),
    ])
    return (trades_tab,)


@app.cell
def _(INK, LEAST, SERIES, WIDE, bar_width, book_size, canvas, chart, compact, day_axis, frame, heading, in_window, legend, mo, money,
      money_axis, percent_axis, plural, show, tiles, title, views, window, zero):
    _pnl = views.pnl(in_window)
    _exp = views.exposure(frame).loc[_pnl.index]
    _x, _dates = list(range(len(_pnl))), list(_pnl.index)
    _costs = _pnl[["cost_spread_usd", "cost_impact_usd", "cost_commission_usd"]].sum(axis=1).sum()
    _traded = float(_pnl["turnover"].sum()) * book_size            # dollars bought plus sold over the window
    _fig, (_top, _bottom) = canvas(WIDE, 5.8, rows=2)
    _top.bar(_x, _pnl["net_usd"], width=bar_width(len(_x), WIDE), color=INK["quiet"], label="Daily net", zorder=2)
    _top.plot(_x, _pnl["cumulative_net_usd"], color=SERIES[0], linewidth=2, solid_capstyle="round", label="Cumulative net", zorder=3)
    if _x:
        _top.plot(_x[-1], _pnl["cumulative_net_usd"].iloc[-1], "o", color=SERIES[0], markersize=6, markeredgecolor=INK["surface"],
                  markeredgewidth=1.5, zorder=4)
        _top.annotate(compact(_pnl["cumulative_net_usd"].iloc[-1]), (_x[-1], _pnl["cumulative_net_usd"].iloc[-1]),
                      xytext=(8, 0), textcoords="offset points", va="center", fontsize=8, color=INK["secondary"])
    zero(_top)
    money_axis(_top, "y", float(_pnl[["net_usd", "cumulative_net_usd"]].abs().max().max()) if _x else 0.0)
    day_axis(_top, _dates)
    title(_top, "Net P&L after costs and borrow, dollars")
    legend(_top)
    # Turnover is what each open traded and exposure what it left, so turnover is bars, as daily net is above, and the
    # two exposures are lines: opening a book from flat trades exactly its gross, and one line would cover the other.
    _bottom.bar(_x, _pnl["turnover"], width=bar_width(len(_x), WIDE), color=INK["quiet"], label="Turnover", zorder=2)
    for _name, _values, _colour in (("Gross", _exp["gross"], SERIES[0]), ("Net", _exp["net"], SERIES[1])):
        _bottom.plot(_x, _values, color=_colour, linewidth=2, solid_capstyle="round", label=_name, zorder=3)
    zero(_bottom)
    percent_axis(_bottom, "y")
    day_axis(_bottom, _dates)
    title(_bottom, "Exposure after each open and turnover, % of capital")
    legend(_bottom)
    _fig.tight_layout(h_pad=2.0)
    pnl_tab = mo.vstack([
        window,
        tiles(
            ("Net P&L", money(_pnl["net_usd"].sum(), signed=True), f"over {plural(len(_pnl), 'day')}"),
            ("Gross P&L", money(_pnl["gross_usd"].sum(), signed=True), "before costs and borrow"),
            ("Trading costs", money(_costs), "spread, impact, commission"),
            ("Cost of trading", f"{_costs / _traded * 1e4:.1f} bp" if _traded else "n/a", "of each dollar traded"),
            ("Borrow", money(_pnl["borrow_usd"].sum()), "on shorts carried in"),
            ("Turnover", f"{_pnl['turnover'].mean():.1%}", "of capital a day, mean"),
        ),
        chart(_fig, "Net P&L, exposure and turnover by day", LEAST),
        heading("By day"),
        show(_pnl, index=True),
    ])
    return (pnl_tab,)


@app.cell
def _(LEAST, SERIES, WIDE, by, canvas, chart, heading, in_window, mo, money_axis, note, sectors, show, since, title, until, views, zero):
    _table = views.attribution(in_window, sectors, by.value)
    _top = _table.head(15)
    _rows = list(range(len(_top)))[::-1]
    _fig, _ax = canvas(WIDE, 0.9 + 0.3 * max(len(_top), 1), grid="x")
    _ax.barh(_rows, _top["net_usd"], height=0.5, color=SERIES[0])
    _ax.set_yticks(_rows, [str(k) for k in _top.index])
    zero(_ax, "x")
    money_axis(_ax, "x", float(_top["net_usd"].abs().max()) if len(_top) else 0.0)
    title(_ax, f"P&L net of borrow by {by.value}, dollars" + (f": the {len(_top)} largest of {len(_table)}" if len(_table) > len(_top) else ""))
    _fig.tight_layout()
    attribution_tab = mo.vstack([
        mo.hstack([since, until, by], justify="start", gap=0.75, wrap=True),   # flat: a nested row would push `by` to the far side
        note("P&L and borrow belong to the holding carried into each day. Trading costs are charged by day, not by name, "
             "so they are in the P&L tab and not here."),
        *([chart(_fig, f"P&L net of borrow by {by.value}", LEAST), heading(f"By {by.value}"), show(_table, index=True)] if len(_table)
          else [note("Nothing was carried in over this window, so there is nothing to attribute yet.")]),
    ])
    return (attribution_tab,)


@app.cell
def _(frame, heading, mo, note, plural, show, tiles, views):
    _spells = views.spells(frame)
    _open = _spells["exit"].isna()
    _closed = _spells.loc[~_open, "days"]
    spells_tab = mo.vstack([
        note("A spell is a run of days a name is held on one side, from the open that fills it to the open that closes "
             "or flips it. Adding to it or reducing it keeps the spell."),
        tiles(
            ("Open spells", f"{int(_open.sum()):,}", "held after the last open"),
            ("Closed spells", f"{int((~_open).sum()):,}", "since the run began"),
            ("Median length", plural(round(_closed.median()), "day") if len(_closed) else "n/a", "closed spells"),
        ),
        heading("Spells, latest entry first"),
        show(_spells),
    ])
    return (spells_tab,)


@app.cell
def _(LEAST, SERIES, WIDE, book_size, canvas, chart, day_axis, frame, heading, mo, money, moves, note, percent_axis, show, signed, ticker,
      tiles, title, views, zero):
    if ticker.value is None:
        ticker_tab = mo.vstack([ticker, note("Pick a ticker to see its holding, trades and P&L day by day.")])
    else:
        _h = views.history(frame, ticker.value)
        _x = list(range(len(_h)))
        _fig, _ax = canvas(WIDE, 2.8)
        # A holding lasts from its open to the next, so the last one is drawn a day wide: a step that ended at the
        # last open would give the holding now no width at all.
        _edges, _levels = [*_x, len(_x)], [*_h["holding"], *_h["holding"].iloc[-1:]]
        _ax.step(_edges, _levels, where="post", color=SERIES[0], linewidth=2)
        _ax.fill_between(_edges, _levels, step="post", color=SERIES[0], alpha=0.10, linewidth=0)
        zero(_ax)
        percent_axis(_ax, "y")
        day_axis(_ax, list(_h["date"]))
        _ax.set_xlim(-0.6, len(_x) + 0.4)
        title(_ax, f"{ticker.value}: holding after each open, % of capital")
        _fig.tight_layout()
        ticker_tab = mo.vstack([
            ticker,
            tiles(
                ("Holding now", signed(_h["holding"].iloc[-1]), money(_h["holding"].iloc[-1] * book_size, signed=True)),
                ("Days held", f"{int((_h['holding'] != 0).sum())}", f"of {len(_h)} on the grid"),
                ("P&L to date", money(_h["pnl"].sum() * book_size, signed=True), "before borrow and costs"),
                ("Borrow to date", money(_h["borrow"].sum() * book_size), "on days carried short"),
            ),
            chart(_fig, f"{ticker.value}: holding after each open", LEAST),
            heading("By day"),
            # No target is recorded under the optimiser, and no expected move under the decile sort.
            show(_h.drop(columns=[c for c, gone in (("target", _h["target"].isna().all()), ("expected_move", not moves)) if gone])),
        ])
    return (ticker_tab,)


@app.cell
def _(all_days, frame, heading, mo, moves, note, show, views):
    _next = views.next_open(frame)
    _decided = f"The decision made at the close of {all_days[-1]:%Y-%m-%d}, for the next open. "
    if moves:
        _solved_later = bool(_next["target"].isna().all())         # the optimiser: no target is recorded
        _shown = _next.drop(columns="target") if _solved_later else _next
        _move = _shown["expected_move"]
        _parts = [
            (f"Expected to rise, largest first ({(_move > 0).sum()})", _shown.loc[_move > 0]),
            (f"Expected to fall, largest first ({(_move < 0).sum()})", _shown.loc[_move < 0].iloc[::-1]),
            (f"No expected move ({(~(_move > 0) & ~(_move < 0)).sum()})", _shown.loc[~(_move > 0) & ~(_move < 0)]),   # or a zero
        ]
        _text = _decided + ("The optimiser solves on these expected moves at that open, so the ledger records no target and "
                            "its trades appear only in the next ledger day." if _solved_later else "Target is the book the rule set for that open.")
    else:
        _shown = _next.drop(columns="expected_move")
        _target = _shown["target"]
        _parts = [
            (f"Long at the next open, largest first ({(_target > 0).sum()})", _shown.loc[_target > 0]),
            (f"Short at the next open, largest first ({(_target < 0).sum()})", _shown.loc[_target < 0].iloc[::-1]),
            (f"Closed at the next open ({(_target == 0).sum()})", _shown.loc[_target == 0]),
        ]
        _text = _decided + ("The decile sort ranks the signal itself, so the ledger records no expected move. Target is the "
                            "book the sort set for that open.")
    next_tab = mo.vstack([
        note(_text),
        # Side by side where both fit, else stacked: an `hstack` of equal widths never wraps, and overlapped on a phone.
        mo.Html('<div class="lx-pair">' + "".join(f"<div>{mo.vstack([heading(h), show(t)]).text}</div>" for h, t in _parts[:2]) + "</div>"),
        *([heading(_parts[2][0]), show(_parts[2][1])] if len(_parts[2][1]) else []),
    ])
    return (next_tab,)


@app.cell
def _(frame, heading, mo, note, show, views):
    # Short headers and hashes, so the ten columns fit the page: the note under the tabs says what each count is.
    _health = views.health(frame).rename(columns={"names": "on_grid", "held": "carried_in", "missing_returns": "no_return"})
    _health = _health.assign(
        git_commit=_health["git_commit"].str[:7], config_hash=_health["config_hash"].str[:8],
        git_dirty=_health["git_dirty"].map({False: "clean", True: "dirty"}),
    ).iloc[::-1]
    # The decile sort records neither a solver status nor a slope: those columns go rather than show blanks.
    _empty = [c for c in ("status", "slope") if _health[c].isna().all() or (_health[c] == "").all()]
    _health = _health.drop(columns=_empty)
    _recorded = {(): "how the optimiser finished, the calibration slope, ", ("slope",): "how the optimiser finished, ",
                 ("status",): "the calibration slope, "}.get(tuple(_empty), "")
    health_tab = mo.vstack([
        note("One row per ledger day, latest first: the names on the grid, the names carried in and those of them with no "
             f"return, {_recorded}and the code, snapshot and config the day ran on."),
        heading("Run health"),
        show(_health, index=True),
    ])
    return (health_tab,)


@app.cell
def _(attribution_tab, book_tab, health_tab, mo, next_tab, pnl_tab, spells_tab, ticker_tab, trades_tab):
    mo.ui.tabs({
        "Book": book_tab,
        "Trades": trades_tab,
        "P&L": pnl_tab,
        "Attribution": attribution_tab,
        "Spells": spells_tab,
        "Ticker": ticker_tab,
        "Next open": next_tab,
        "Health": health_tab,
    }, lazy=True)


if __name__ == "__main__":
    app.run()
