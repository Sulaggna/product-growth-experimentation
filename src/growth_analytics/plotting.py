"""Shared chart style for all figures.

Categories use a fixed colour order and each entity keeps its colour across charts
(organic is always blue, paid social always orange). Magnitudes use a single blue
ramp, and signed values use blue and red around a grey midpoint. Text stays in the
ink colours.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from . import config as C  # noqa: E402

# tokens
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
NEUTRAL = "#f0efec"

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
BLUE = {100: "#cde2fb", 150: "#b7d3f6", 200: "#9ec5f4", 250: "#86b6ef", 300: "#6da7ec", 350: "#5598e7",
        400: "#3987e5", 450: "#2a78d6", 500: "#256abf", 550: "#1c5cab", 600: "#184f95", 650: "#104281",
        700: "#0d366b"}
POS, NEG = BLUE[500], "#e34948"  # diverging poles
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}

CHANNEL_COLOR = {"organic": SERIES[0], "paid_social": SERIES[1], "search": SERIES[2],
                 "referral": SERIES[3], "influencer": SERIES[4]}
PLATFORM_COLOR = {"ios": SERIES[0], "android": SERIES[1], "web": SERIES[2]}
MODEL_COLOR = {"Logistic regression": SERIES[0], "Gradient boosting": SERIES[1]}
LABEL = {"organic": "Organic", "paid_social": "Paid social", "search": "Search", "referral": "Referral",
         "influencer": "Influencer", "ios": "iOS", "android": "Android", "web": "Web",
         "acquisition_channel": "Channel", "platform": "Platform"}

SEQ_CMAP = LinearSegmentedColormap.from_list("seq_blue", [BLUE[100], BLUE[300], BLUE[500], BLUE[700]])


def use_style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 10, "text.color": INK,
        "axes.edgecolor": BASELINE, "axes.linewidth": 0.8, "axes.labelcolor": INK_2, "axes.labelsize": 9.5,
        "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.titlepad": 10,
        "axes.titlecolor": INK,
        "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
        "axes.grid": True, "axes.grid.axis": "y", "axes.axisbelow": True,
        "grid.color": GRID, "grid.linewidth": 0.7, "grid.linestyle": "-",
        "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK_2, "ytick.labelcolor": INK_2,
        "xtick.labelsize": 9, "ytick.labelsize": 9, "ytick.left": False, "xtick.major.size": 3,
        "lines.linewidth": 2.0, "lines.solid_capstyle": "round", "lines.markersize": 6,
        "legend.frameon": False, "legend.fontsize": 9, "legend.labelcolor": INK_2,
        "savefig.dpi": 150, "figure.dpi": 100,
        "text.parse_math": False,  # "$" in titles is currency, not TeX
    })


def figure(nrows: int = 1, ncols: int = 1, w: float = 10, h: float = 4.6, **kw):
    use_style()
    fig, axes = plt.subplots(nrows, ncols, figsize=(w, h), **kw)
    return fig, axes


def headline(fig, title: str, subtitle: str | None = None) -> None:
    fig.text(0.012, 0.985, title, ha="left", va="top", fontsize=14, fontweight="bold", color=INK)
    if subtitle:
        fig.text(0.012, 0.915, subtitle, ha="left", va="top", fontsize=10.5, color=INK_2)
    fig._has_subtitle = bool(subtitle)  # used by save()


def save(fig, name: str, out_dir: Path | None = None) -> Path:
    out = Path(out_dir or C.FIGURES_DIR)
    out.mkdir(parents=True, exist_ok=True)
    top = 0.84 if getattr(fig, "_has_subtitle", False) else 0.9
    fig.tight_layout(rect=(0, 0, 1, top))
    path = out / f"{name}.png"
    fig.savefig(path, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    return path


# formatters
def pct(decimals: int = 0):
    return FuncFormatter(lambda v, _: f"{v * 100:.{decimals}f}%")


def pp(decimals: int = 1):
    return FuncFormatter(lambda v, _: f"{v * 100:+.{decimals}f} pp" if abs(v) > 1e-12 else "0")


def thousands():
    return FuncFormatter(lambda v, _: f"{v / 1000:g}k" if abs(v) >= 1000 else f"{v:.0f}")


def usd(decimals: int = 0):
    return FuncFormatter(lambda v, _: f"${v:,.{decimals}f}")


# composite marks
def forest(ax, labels, est, lo, hi, colors=None, ref: float = 0.0, fmt=None, value_fmt=None, truth=None):
    """Horizontal point-and-interval chart (top row first)."""
    n = len(labels)
    y = list(range(n))[::-1]
    colors = colors or [SERIES[0]] * n
    ax.axvline(ref, color=BASELINE, lw=1.0, zorder=1)
    for yi, e, l_, h_, c in zip(y, est, lo, hi, colors):
        ax.plot([l_, h_], [yi, yi], color=c, lw=2.0, solid_capstyle="round", zorder=2)
        ax.plot([e], [yi], "o", ms=8, color=c, mec=SURFACE, mew=2, zorder=3)
        if value_fmt:
            ax.text(h_, yi + 0.18, "  " + value_fmt(e, l_, h_), va="bottom", ha="left", fontsize=8.5, color=INK_2)
    if truth is not None:
        for yi, t in zip(y, truth):
            if t is not None:
                ax.plot([t], [yi], marker="D", ms=6, mfc=SURFACE, mec=INK, mew=1.2, zorder=4, ls="none")
        ax.plot([], [], marker="D", ms=6, mfc=SURFACE, mec=INK, mew=1.2, ls="none", label="simulated ground truth")
        ax.legend(loc="lower right")
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.set_ylim(-0.7, n - 0.3)
    if fmt is not None:
        ax.xaxis.set_major_formatter(fmt)
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(axis="x", length=0)


def end_label(ax, x, y, text: str, dy: float = 0.0) -> None:
    ax.annotate(text, (x, y), xytext=(6, dy), textcoords="offset points", va="center", ha="left",
                fontsize=9, color=INK_2)


def end_labels(ax, items: list[tuple], min_gap_frac: float = 0.055) -> None:
    """Direct labels at line ends, nudged apart vertically so they never collide.

    ``items`` = [(x, y, text), ...] in data coordinates (x already offset past the line end).
    """
    lo, hi = ax.get_ylim()
    gap = (hi - lo) * min_gap_frac
    placed: list[float] = []
    for x, y, text in sorted(items, key=lambda t: t[1]):
        y_new = y if not placed else max(y, placed[-1] + gap)
        placed.append(y_new)
        ax.text(x, y_new, text, va="center", ha="left", fontsize=9, color=INK_2, clip_on=False)
