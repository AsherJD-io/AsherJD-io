#!/usr/bin/env python3
"""Generate the animated terminal header for the AsherJD-io profile README.

Engine
------
Every frame is produced by `github-readme-terminal` (the `gifos` package):
`gifos.Terminal`, its text and typing generators, its cursor handling, its ANSI
colour table, `gifos.utils.fetch_github_stats` for the counters, and its own
`gen_gif()`, which shells out to ffmpeg. Nothing here draws a frame by hand.

The composition follows the reference at https://github.com/x0rzavi/x0rzavi:
prompt, typed fetch command, identity mark on the left, profile block on the
right, closing prompt. All content, artwork, wording and colour are Asher's.

Identity
--------
The prompt is this machine's real WSL prompt, read from the live environment
rather than assumed:

    $ whoami      -> asher
    $ hostname    -> ASHER-SGNL7CR
    PS1 ~/.bashrc -> '\\[\\033[01;32m\\]\\u@\\h\\[\\033[00m\\]:\\
                     \\[\\033[01;34m\\]\\w\\[\\033[00m\\]\\$ '

which renders as `asher@ASHER-SGNL7CR:~$`. The stock prompt colours user green
and path blue; both are re-pointed onto the local slate/blue axis so the frame
reads as one colour system rather than a stock Ubuntu terminal.

Palette
-------
config/ansi_escape_colors.toml holds one `ordaciti` scheme built only from
#0f172a #2563eb #3b82f6 #60a5fa #f8fafc #cbd5e1 #64748b.

Usage
-----
    pip install -r requirements.txt
    GITHUB_TOKEN=... python main.py     # token needed for the stats fetch

Without a token the render falls back to a cached snapshot, so the GIF is still
reproducible offline. The token is read from the environment only and is never
written to disk.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

# gifos is deliberately NOT imported at module scope: it resolves its TOML and
# creates its frame folder at import time, so it must come after sync_config().
# See load_gifos().

HERE = Path(__file__).resolve().parent
CONFIG_DIR = HERE / "config"
FONT_FILE = HERE / "fonts" / "JetBrainsMono-Bold.ttf"
CACHE_FILE = HERE / ".stats_cache.json"

# Geometry. At a 16px monospace face the cell is 10x20 with 6px leading, so
# 900x640 resolves to an 86x22 grid. The two-column layout is built on those
# numbers, and the row budget is asserted at draw time rather than discovered.
WIDTH, HEIGHT = 900, 640
XPAD, YPAD = 18, 16
FONT_SIZE, LINE_SPACING = 16, 6

USER = "Delebayo Asher"
HANDLE = "AsherJD-io"
FETCH_USER = "asher"

# The real prompt, split so the slate/blue axis can replace the stock green.
PROMPT = (
    "\x1b[95masher@ASHER-SGNL7CR\x1b[0m"
    ":"
    "\x1b[96m~\x1b[0m"
    "\x1b[97m$ \x1b[0m"
)

# Left column. There is no block-art mark: an earlier geometric A built from
# block glyphs read as a smudge rather than an identity, so the area is left
# empty and the profile block starts closer to the left edge. Marking the
# column as intentional keeps it from looking like an oversight.
#
#   ┌───┐
#   │ A │
#   └───┘
#
# A single glyph in a much larger face, vertically centred against the profile
# block. Restrained enough to read as a character rather than a logo.
# set_font() recomputes the grid, so these are MARK-grid coordinates (10 rows at
# 44px), not body-grid ones. Row 5 lands the glyph near the vertical middle of
# the profile block, which spans body rows 3-20.
MARK_SIZE = 44
MARK_ROW = 5
MARK_COL = 2

# Profile block origin. Indented past the mark so the two never collide; the
# widest line still ends well inside the grid at this column.
INFO_COL, INFO_ROW = 8, 3


def sync_config() -> None:
    """Install config/ into the user config dir the library actually reads.

    gifos resolves its TOML from its own package directory and then overlays
    ~/.config/gifos/. Copying here is the documented override path, which keeps
    the palette a file in this repo rather than a constant buried in code.
    """
    dest = Path.home() / ".config" / "gifos"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("gifos_settings.toml", "ansi_escape_colors.toml"):
        shutil.copyfile(CONFIG_DIR / name, dest / name)
    print(f"INFO: synced config -> {dest}")


def load_gifos():
    """Import gifos only after sync_config() has run.

    The package resolves its TOML -- including files.output_gif_name -- at import
    time, and it creates the frame folder then too. Importing it before the
    config is in place silently picks up stale defaults, which is how the GIF
    ended up written to the repo root instead of assets/.
    """
    import gifos as _gifos

    return _gifos


def fetch_stats() -> dict:
    """Public GitHub counters, via the package's own stats helper.

    fetch_github_stats() calls sys.exit() when GITHUB_TOKEN is missing, so the
    token is checked here first and a snapshot keeps the render reproducible
    offline. Every value is public profile data; nothing private is requested
    and the token is never persisted.
    """
    if not os.getenv("GITHUB_TOKEN"):
        print("WARN: GITHUB_TOKEN unset")
        if CACHE_FILE.exists():
            print("INFO: using cached stats")
            return json.loads(CACHE_FILE.read_text())
        print("INFO: using verified snapshot")
        return {
            "stars": 9,
            "followers": 1,
            "commits": 207,
            "prs": 10,
            "merged": 8,
            "rank": "C+",
            "languages": ["Python", "TypeScript", "JavaScript"],
        }

    from gifos.utils.fetch_github_stats import fetch_github_stats

    s = fetch_github_stats(HANDLE, [], include_all_commits=False)
    if s is None:
        print("WARN: stats fetch failed")
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text())
        raise SystemExit("no stats and no cache")

    stats = {
        "stars": s.total_stargazers,
        "followers": s.total_followers,
        "commits": s.total_commits_last_year,
        "prs": s.total_pull_requests_made,
        "merged": s.total_pull_requests_merged,
        "rank": s.user_rank.level,
        "languages": [name for name, _ in s.languages_sorted[:3]],
    }
    print(f"INFO: stats {stats}")
    CACHE_FILE.write_text(json.dumps(stats, indent=2))
    return stats


def profile_block(stats: dict) -> str:
    """The right-hand column: who, what, stack, contact, counters.

    Emitted as one multiline string so the library does the row layout. Keys are
    padded to a fixed width so values line up, which reads as a fetch screen
    rather than a list. Every colour segment resets, and separators use only the
    dim tone so the bright values carry the meaning.

    Palette mapping: mid #3b82f6 for the header, light #60a5fa for values,
    fg #f8fafc for counters, muted #cbd5e1 for the name, dim #64748b for rules
    and separators. Blue is foreground accent only; no segment sets a
    background, so nothing renders as a filled panel.
    """
    dim, key, val, num = "\x1b[90m", "\x1b[96m", "\x1b[93m", "\x1b[97m"
    # Foreground only. An earlier header used \x1b[30;101m, which in this scheme
    # is fg #64748b on bg #64748b and painted a solid filled rectangle behind
    # the command line. Blue is an accent here, never a panel.
    head = "\x1b[94m"
    dot = f" {dim}\u00b7{val} "
    langs = ", ".join(stats["languages"])

    return "\n".join(
        [
            f"{head}{HANDLE}@github {dim}\u00b7 fetch profile\x1b[0m",
            f"{dim}{'-' * 47}\x1b[0m",
            f"{key}role   \x1b[0m\x1b[37m{USER}\x1b[0m",
            f"{key}title  \x1b[0m{val}Data Engineer\x1b[0m",
            f"{key}focus  \x1b[0m{val}Data Platforms{dot}Pipelines{dot}Decision Intelligence\x1b[0m",
            dim,
            f"{key}stack  \x1b[0m{val}Python{dot}SQL{dot}TypeScript{dot}PostgreSQL{dot}BigQuery",
            f"{dim}       \x1b[0m{val}dbt{dot}Kestra{dot}PySpark{dot}Kafka/Redpanda{dot}Flink/PyFlink",
            f"{dim}       \x1b[0m{val}Docker{dot}Next.js\x1b[0m",
            dim,
            f"{key}web    \x1b[0m{val}codered-azure.vercel.app",
            f"{key}in     \x1b[0m{val}linkedin.com/in/delebayo-joea",
            f"{key}mail   \x1b[0m{val}josephdelebayo@gmail.com",
            f"{key}social \x1b[0m{val}Twitter {dim}\u00b7 \x1b[0m{val}@23asher_io",
            dim,
            f"{key}github \x1b[0m{num}{stats['commits']}{val} commits (1y)"
            f"{dot}{num}{stats['prs']}{val} PRs{dot}{num}{stats['merged']}{val} merged",
            f"{dim}       \x1b[0m{num}{stats['stars']}{val} stars{dot}{num}{stats['followers']}{val} followers"
            f"{dot}{val}rank {num}{stats['rank']}",
            f"{dim}       \x1b[0m{val}langs  {langs}",
        ]
    )


def assert_fits(block: str, cols: int) -> None:
    """Fail loudly if any rendered line runs past the right edge.

    The library clips silently at the grid boundary, so an over-long line looks
    merely truncated rather than broken. Checked before any frames are made.
    """
    for i, line in enumerate(block.split("\n")):
        plain = re.sub(r"\x1b\[[0-9;]*m", "", line)
        end = INFO_COL + len(plain) - 1
        if end > cols:
            raise SystemExit(
                f"profile line {i} ends at col {end}, grid has {cols}: {plain!r}"
            )


def draw_mark(t) -> None:
    """Paint a single large 'A' in the left gutter.

    One glyph in a bigger face, not block art: an earlier attempt assembled the
    letter from block characters and read as a smudge at profile size. This is
    set in the same family at a larger point size, so it stays obviously a
    character rather than becoming a logo.

    Drawn through gen_text like everything else. The library's set_font() also
    recomputes num_rows/num_cols, so the profile size is restored immediately
    afterwards and the grid is asserted to be unchanged.
    """
    rows_before, cols_before = t.num_rows, t.num_cols
    t.set_font(str(FONT_FILE), MARK_SIZE, LINE_SPACING)
    if (t.num_rows, t.num_cols) == (rows_before, cols_before):
        raise SystemExit(
            f"mark font size {MARK_SIZE} did not change the grid; "
            "the mark would be indistinguishable from body text"
        )
    t.gen_text("\x1b[96mA\x1b[0m", MARK_ROW, MARK_COL, contin=True)
    t.set_font(str(FONT_FILE), FONT_SIZE, LINE_SPACING)
    if (t.num_rows, t.num_cols) != (rows_before, cols_before):
        raise SystemExit("failed to restore body font size after drawing the mark")


def main() -> None:
    sync_config()
    stats = fetch_stats()

    gifos = load_gifos()
    t = gifos.Terminal(
        WIDTH, HEIGHT, XPAD, YPAD, str(FONT_FILE), FONT_SIZE, LINE_SPACING
    )
    print(f"INFO: grid {t.num_cols} cols x {t.num_rows} rows")
    t.set_prompt(PROMPT)

    # --- prompt, then the fetch command typed out ----------------------------
    t.toggle_show_cursor(False)
    t.gen_text("", 1, count=18)
    t.gen_prompt(1, count=6)
    start_col = t.curr_col
    t.toggle_show_cursor(True)
    t.gen_typing_text("\x1b[94mfetch", 1, contin=True, speed=1)
    # Repaint the command in the brighter tone. This is the library's own
    # syntax-highlighting trick, and the reason delete_row takes a column.
    t.delete_row(1, start_col)
    t.gen_text("\x1b[96mfetch.sh\x1b[0m", 1, contin=True)
    t.gen_typing_text(f" -u {FETCH_USER}", 1, contin=True, speed=1)
    t.toggle_show_cursor(False)

    # --- resolve, then lay out the profile ----------------------------------
    # The command line is kept on screen and the output is drawn beneath it, so
    # the shell identity stays visible and it is obvious what produced the
    # block. An earlier version cleared the frame here, which threw away the
    # prompt and read as a cut rather than a fetch.
    t.clone_frame(8)
    t.gen_text("\x1b[90m[ resolving profile ]\x1b[0m", 2, 1, count=10, contin=True)
    t.toggle_show_cursor(False)
    t.delete_row(2)
    draw_mark(t)

    block = profile_block(stats)
    assert_fits(block, t.num_cols)
    t.gen_text(block, INFO_ROW, INFO_COL, count=4, contin=True)

    # --- closing prompt ------------------------------------------------------
    # Pinned to an explicit row: gen_prompt() writes non-continuing, and the
    # library scrolls when the target row is at or above the blank frontier, so
    # letting it follow curr_row shifted the finished layout up by one.
    close_row = INFO_ROW + len(block.split("\n")) + 1
    if close_row > t.num_rows:
        raise SystemExit(f"closing prompt overflows grid: row {close_row} of {t.num_rows}")
    t.clone_frame(24)
    t.toggle_show_cursor(True)
    t.gen_prompt(close_row, count=4)
    t.gen_typing_text(
        "\x1b[90m# thanks for stopping by\x1b[0m", close_row, contin=True, speed=1
    )
    t.toggle_show_cursor(False)
    t.gen_text("", close_row, count=150, contin=True)

    t.gen_gif()
    write_readme()


def write_readme() -> None:
    """Stage the profile README.

    The GIF carries the content, so the README is the image plus a compact
    contact row. The image is deliberately NOT wrapped in an <a>: the header
    must be completely non-clickable, with the contact links below it as the
    only clickable elements.
    """
    badge = "https://img.shields.io/badge"
    (HERE / "README.md").write_text(
        '<img src="./assets/header.gif" alt="Delebayo Asher - Data Engineer" width="100%">\n\n'
        f"[![Portfolio]({badge}/Portfolio-0f172a?style=flat-square)]"
        "(https://codered-azure.vercel.app/)\n"
        f"[![LinkedIn]({badge}/LinkedIn-0A66C2?style=flat-square&logo=linkedin&logoColor=white)]"
        "(https://www.linkedin.com/in/delebayo-joea/)\n"
        f"[![Twitter]({badge}/Twitter-1DA1F2?style=flat-square&logo=twitter&logoColor=white)]"
        "(https://x.com/23asher_io/)\n"
        f"[![Email]({badge}/Email-EA4335?style=flat-square&logo=gmail&logoColor=white)]"
        "(mailto:josephdelebayo@gmail.com)\n"
    )
    print("INFO: README.md written")


if __name__ == "__main__":
    main()
