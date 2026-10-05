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

# The CLI body face is the real bitmap terminal font from the x0rzavi reference,
# gohufont-uni-14.pil, not a TrueType substitute. It is a PIL bitmap font, so
# gifos loads it with ImageFont.load() and FONT_SIZE is IGNORED entirely - the
# cell is whatever the font itself declares.
#
# Both files were obtained from x0rzavi/x0rzavi and verified by sha256 against
# the git-lfs oids in that repo's fonts/*.pil pointers, so they are byte-identical
# to the reference rather than merely similar:
#   gohufont-uni-14.pil  40c5ad80...b3208b7 (5143 bytes)
#   gohufont-uni-14.pbm  4aa30368...60f5618 (1283 bytes)  <- glyph data, required
# The .pil cannot be loaded without its .pbm sibling; both are installed.
FONT_FILE = HERE / "fonts" / "gohufont-uni-14.pil"
FONT_DATA = HERE / "fonts" / "gohufont-uni-14.pbm"

# The ASHER mark face, also from the reference repo. In x0rzavi/main.py this is
# FONT_FILE_LOGO, used at size 66 for the "GIF OS" wordmark, so it is the
# reference's display/logo face and the correct choice for a vertical mark.
#   vtks-blocketo.regular.ttf  560a9d8c...3208b8 (17800 bytes)
FONT_MARK = HERE / "fonts" / "vtks-blocketo.regular.ttf"
MARK_SIZE = 47

# Not used, and deliberately absent:
#   IosevkaTermNerdFont-Bold.ttf is defined as FONT_FILE_TRUETYPE in the
#     reference but never passed to set_font - it is dead there too.
#   Inversionz.otf is FONT_FILE_MONA, used only for the white-on-light ASCII
#     "mona" art block, which is explicitly out of scope here.
CACHE_FILE = HERE / ".stats_cache.json"

# Geometry. gohufont is a bitmap font measured at an 8x14 cell (monospaced,
# A-Z all 8px wide; tallest glyphs 14px). At 6px leading the row pitch is 20,
# so 900x640 resolves to 108x30 cells - far roomier than the previous 86x23.
# Every layout constant below is derived from that measured cell, not assumed.
# gohufont's 8px cell is much narrower than the 10px face it replaced, so the
# same content is ~496px wide instead of ~620px. On a 900px canvas that left a
# 203px dead margin on the right and broke the balance, so the canvas is
# narrowed to 780. That also sits closer to the reference's own 750x500, which
# is the size gohufont was designed for.
WIDTH, HEIGHT = 780, 640
XPAD, YPAD = 18, 16
FONT_SIZE, LINE_SPACING = 16, 6
BODY_CELL_W = 8
BODY_CELL_H = 14 + LINE_SPACING

USER = "Delebayo Asher"
HANDLE = "AsherJD-io"
FETCH_USER = "asher"

# The real prompt, in the hierarchy a stock bash PS1 produces:
#   PS1='\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
# i.e. user@host accented, then the path accented, then a plain $. The stock
# green and blue are re-pointed onto the approved slate/blue axis (no new
# colours), keeping the same three-part structure so it reads as a shell prompt
# rather than a graphic:
#   user@host -> #60a5fa light blue
#   :~        -> #3b82f6 bright blue
#   $         -> #f8fafc foreground
PROMPT = (
    "\x1b[95masher@ASHER-SGNL7CR\x1b[0m"   # #60a5fa light blue - identity
    "\x1b[90m:\x1b[0m"                     # #64748b muted      - path sep
    "\x1b[37m~\x1b[0m"                     # #cbd5e1 secondary  - cwd
    "\x1b[97m$ \x1b[0m"                    # #f8fafc primary    - the $
)

# Left column: the ASHER mark, drawn with the reference logo face
# vtks-blocketo.regular.ttf at MARK_SIZE, one letter per row via the library's
# own gen_text(). Five letters stacked vertically: A S H E R.
#
# Superseded approach: the mark was once composed from explicit square-block
# geometry and pasted with paste_image(), which gave exact square blocks but was
# not the reference typography. It now uses the reference's own display face.
#
# Size, measured rather than guessed - the stack is 24x231px against the 39x299
# of the block version and the 90x480 of the original oversized one, so it is
# the smallest of the three while staying legible: at MARK_SIZE the letter ink
# is 24px wide, and all five glyphs are pairwise distinct with no clipping.
# vtks-blocketo is NOT monospaced (A-Z widths range 5..17 at size 47), but
# A, S, H, E and R specifically share one width, so the stack stays aligned.
#
# Placement is centre-left. The profile block starts at INFO_ROW and the mark is
# centred against it rather than hanging from the top edge.
# The mark face has a very different cell from the body face (~25x47 against
# 8x14), so MARK_ROW/MARK_COL are columns of the MARK grid, not the body grid.
MARK_ROW = 3
MARK_COL = 4
# Row pitch between stacked letters, as a fraction of the mark face's line
# height, so the letters sit close without touching.
MARK_PITCH = 50

# Profile block origin. The 8px cell is much narrower than the previous 10px
# face, so this column sits further right in pixels while the mark keeps a
# generous gutter on its left.
INFO_COL, INFO_ROW = 24, 3


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
    padded to a fixed width so values line up, which is how a utility like
    neofetch prints: dim label, readable value, nothing decorative.

    Colour follows the x0rzavi reference's ROLE hierarchy, with its hues swapped
    for the Ordaciti palette rather than copied. Measured from the reference GIF,
    its settled profile frame uses: neutral body #b3b9b8 1.97%, label colour
    #67cbe7 0.63%, value colour #f4d67a 0.97%, a tiny inline highlight #71baf2
    0.05%, and a #2d3437 badge background at 4.84%.

    The roles are kept; the reds, yellows and greens are not. The badge
    background is deliberately NOT reproduced - there is no filled panel here.
    Translated onto the approved palette:
      labels    #60a5fa light blue - mirrors the reference's single label colour
      values    #cbd5e1 secondary - the dominant ink, as in the reference
      name      #f8fafc primary   - the identity line, the one brightest value
      counters  #60a5fa accent    - numbers only, mirroring #71baf2's tiny share
      header    #60a5fa accent    - the single accent header line
      qualifier #64748b muted     - "fetch profile", separators
    Blue is foreground accent only and stays a minority of the ink, because
    values dominate exactly as they do in the reference. No segment sets a
    background anywhere, so nothing can render as a panel, selection or badge.
    """
    rule = "\x1b[90m"    # #64748b muted      - ordinary separator
    dim = "\x1b[90m"     # #64748b muted      - qualifiers
    # Slot check, from config/ansi_escape_colors.toml bright_colors:
    #   90 #64748b   94 #3b82f6   95 #60a5fa   96 #f8fafc   97 #f8fafc
    # 96 is PRIMARY TEXT in this theme, not light blue. Using it for the labels
    # made every label render white, indistinguishable from the name value.
    #
    # ROLE SEPARATION, not one blue for everything. The previous revision gave
    # labels, counters and the header the SAME slot (95), so the frame read as
    # "blue labels on grey" and the reference's separate value, label and
    # inline-highlight roles collapsed into a single accent.
    #
    #   strongest accent  94 #3b82f6 - header identity line, inline numbers
    #   secondary accent  95 #60a5fa - PRIMARY labels, shell identity, ASHER mark
    #   neutral primary   97 #f8fafc - primary values, typed command, the $
    #   neutral secondary 37 #cbd5e1 - ordinary values, the dominant ink
    #   muted             90 #64748b - SECONDARY labels, separators, qualifiers
    #
    # Blue is now split across three visibly different roles rather than one,
    # and neutral ink still dominates the frame.
    key = "\x1b[95m"     # #60a5fa secondary accent - primary labels
    key2 = "\x1b[90m"    # #64748b muted          - continuation / secondary labels
    val = "\x1b[37m"     # #cbd5e1 neutral secondary - values
    name = "\x1b[97m"    # #f8fafc neutral primary   - primary value
    num = "\x1b[94m"     # #3b82f6 strongest accent - inline highlights only
    head = "\x1b[94m"    # #3b82f6 strongest accent - header identity line
    dot = f" {dim}\u00b7{val} "
    langs = ", ".join(stats["languages"])

    return "\n".join(
        [
            f"{head}{HANDLE}@github {dim}\u00b7 fetch profile\x1b[0m",
            f"{rule}{'-' * 47}\x1b[0m",
            f"{key}role   \x1b[0m{name}{USER}\x1b[0m",
            f"{key}title  \x1b[0m{val}Data Engineer\x1b[0m",
            f"{key}focus  \x1b[0m{val}Data Platforms{dot}Pipelines{dot}Decision Intelligence\x1b[0m",
            "",
            f"{key}stack  \x1b[0m{val}Python{dot}SQL{dot}TypeScript{dot}PostgreSQL{dot}BigQuery",
            f"{key2}       \x1b[0m{val}dbt{dot}Kestra{dot}PySpark{dot}Kafka/Redpanda{dot}Flink/PyFlink",
            f"{key2}       \x1b[0m{val}Docker{dot}Next.js\x1b[0m",
            "",
            f"{key}web    \x1b[0m{val}codered-azure.vercel.app",
            f"{key}in     \x1b[0m{val}linkedin.com/in/delebayo-joea",
            f"{key}mail   \x1b[0m{val}josephdelebayo@gmail.com",
            f"{key}social \x1b[0m{val}Twitter {dim}\u00b7 \x1b[0m{val}@23asher_io",
            "",
            f"{key}github \x1b[0m{num}{stats['commits']}{val} commits (1y)"
            f"{dot}{num}{stats['prs']}{val} PRs{dot}{num}{stats['merged']}{val} merged",
            f"{key2}       \x1b[0m{num}{stats['stars']}{val} stars{dot}{num}{stats['followers']}{val} followers"
            f"{dot}{val}rank {num}{stats['rank']}",
            f"{key2}       \x1b[0m{val}langs  {langs}",
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
    """Paint the ASHER mark in the left canvas using the reference logo face.

    Five letters, one per row, drawn with the library's own gen_text() so the
    animation path is unchanged. The face is switched in for the mark and the
    body face is restored immediately afterwards.

    Each row is emitted with an explicit row and column rather than relying on
    the cursor: set_font() recomputes the cell size (the mark face is ~38x43
    against the body's 8x14), so any cursor arithmetic would be measured in the
    wrong units.
    """
    from PIL import ImageFont

    face = ImageFont.truetype(str(FONT_MARK), MARK_SIZE)
    line_h = face.getbbox(r'|(/QMW"')[3]
    ink_w = max(face.getbbox(c)[2] for c in "ASHER")
    pitch = int(round(line_h * MARK_PITCH / 100))

    # Fit the stack inside the grid before touching the font, using pixels.
    need_rows = pitch * (len("ASHER") - 1) + line_h
    need_px_h = YPAD + (MARK_ROW - 1) * BODY_CELL_H + need_rows
    need_px_w = XPAD + (MARK_COL - 1) * BODY_CELL_W + ink_w
    if need_px_h > HEIGHT or need_px_w > WIDTH:
        raise SystemExit(
            f"ASHER mark needs {need_rows}px tall at row {MARK_ROW} "
            f"({need_px_h}px) and {ink_w}px wide at col {MARK_COL} "
            f"({need_px_w}px); canvas is {HEIGHT}x{WIDTH}"
        )

    t.set_font(str(FONT_MARK), MARK_SIZE, 0)
    for i, ch in enumerate("ASHER"):
        # #60a5fa light blue is slot 95 in this theme. Slot 94 is #3b82f6, which
        # made the mark the loudest element on the frame; slot 96 is #f8fafc,
        # which made it white. Neither is the intended accent.
        t.gen_text(f"\x1b[95m{ch}\x1b[0m", MARK_ROW + i, MARK_COL, contin=True)
    # Restore the body face so nothing after this point inherits the mark's cells.
    t.set_font(str(FONT_FILE), FONT_SIZE, LINE_SPACING)


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
    t.toggle_show_cursor(True)
    # Typed as plain foreground, the way a shell echoes what you type. An
    # earlier version repainted the command in an accent colour as a highlight;
    # that reads as decoration rather than as input, so it is dropped.
    t.gen_typing_text("\x1b[97mfetch.sh\x1b[0m", 1, contin=True, speed=1)
    t.gen_typing_text(f" -u {FETCH_USER}", 1, contin=True, speed=1)
    t.toggle_show_cursor(False)

    # --- resolve, then lay out the profile ----------------------------------
    # The command line is kept on screen and the output is drawn beneath it, so
    # the shell identity stays visible and it is obvious what produced the
    # block. An earlier version cleared the frame here, which threw away the
    # prompt and read as a cut rather than a fetch.
    # A short pause where the utility would be working. No decorative status
    # line and no invented commands (no cd/pwd/ls/echo): the transition is the
    # prompt, the typed command, and then its output.
    t.clone_frame(14)

    block = profile_block(stats)
    assert_fits(block, t.num_cols)
    t.gen_text(block, INFO_ROW, INFO_COL, count=4, contin=True)

    # Drawn last. draw_mark() switches to the mark face and back, and each
    # letter is written at an explicit row and column, so the profile block
    # above is unaffected by it.
    draw_mark(t)

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
