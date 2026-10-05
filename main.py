#!/usr/bin/env python3
"""Generate the animated terminal header for the AsherJD-io profile README.

Engine
------
Every frame is produced by the `gifos` package (installed from PyPI as
`github-readme-terminal`): `gifos.Terminal`, its text and typing generators, its
cursor handling, its ANSI colour table, `gifos.utils.fetch_github_stats` for the
counters, and its own `gen_gif()`, which shells out to ffmpeg. Nothing here draws
a frame by hand.

Composition
-----------
Boot-style terminal sequence: prompt, a typed fetch command, an identity mark on
the left, a profile block on the right, then a closing prompt. All content,
artwork, wording and colour are Asher's.

Identity
--------
The prompt is this machine's real WSL prompt:

    $ whoami      -> asher
    $ hostname    -> ASHER-SGNL7CR

which renders as `asher@ASHER-SGNL7CR:~$`. The stock PS1 colours the user green
and the path blue; both are re-pointed onto the palette below so the frame reads
as one colour system rather than a stock Ubuntu terminal.

Palette
-------
config/ansi_escape_colors.toml holds one `ordaciti` scheme. Colour is assigned
by ROLE, and each role owns one ANSI slot:

    90  #64748b muted    separator rule, qualifiers
    91  #ef7e7e warm     prompt identity, typed command, header backing (101)
    92  #96d988 green    resolved command, closing message
    93  #f4d67a gold     path component, profile values
    94  #60a5fa blue     inline highlights only
    96  #67cbe7 cyan     labels
    37  #b3b9b8 neutral  shell symbols, ASHER mark
    30  #0f172a dark     section-header text, knocked out of the 101 backing

Blue is deliberately the rarest role on the frame: the inline counters only.

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

# The CLI body face: a real bitmap terminal font, not a TrueType substitute.
# gohufont-uni-14.pil is a PIL bitmap font, so gifos loads it with
# ImageFont.load() and FONT_SIZE is IGNORED entirely - the cell is whatever the
# font itself declares. It needs its .pbm sibling to load at all; both are
# installed.
#   gohufont-uni-14.pil  (5143 bytes)
#   gohufont-uni-14.pbm  (1283 bytes)  <- glyph data, required
FONT_FILE = HERE / "fonts" / "gohufont-uni-14.pil"
FONT_DATA = HERE / "fonts" / "gohufont-uni-14.pbm"

# The ASHER mark face: a display/logo face, which is the correct choice for a
# large vertical mark rather than the body face.
#   vtks-blocketo.regular.ttf  (17800 bytes)
FONT_MARK = HERE / "fonts" / "vtks-blocketo.regular.ttf"
MARK_SIZE = 47

CACHE_FILE = HERE / ".stats_cache.json"

# Geometry. The body font is a bitmap font measured at an 8x14 cell
# (monospaced, A-Z all 8px wide; tallest glyphs 14px). At 6px leading the row
# pitch is 20. Every layout constant below is derived from that measured cell,
# not assumed.
#
# The 8px cell is narrow, so the same content is ~496px wide. On a 900px canvas
# that would leave a 203px dead margin on the right and break the balance, so
# the canvas is narrowed to 780.
#
# HEIGHT IS NOT a constant. It is computed from the actual content bounds by
# required_height() once the stats and therefore the profile block are known, so
# the panel cannot drift out of sync with its contents. A hardcoded height left
# a large dead region under the closing prompt; recomputing means adding or
# removing a line changes the panel automatically.
WIDTH = 780
XPAD, YPAD = 18, 16
FONT_SIZE, LINE_SPACING = 16, 6
BODY_CELL_W = 8
BODY_CELL_H = 14 + LINE_SPACING
# Breathing room below the last content row, in pixels. Deliberately the same as
# the side/top padding so the closing prompt sits symmetrically in the frame.
BOTTOM_PAD = YPAD

USER = "Delebayo Asher"
HANDLE = "AsherJD-io"
FETCH_USER = "asher"

# Programming languages already named in the stack field below. They are
# suppressed in the langs row so the profile does not print the same technology
# twice: stack is curated intent, langs is GitHub-derived signal, and the two
# are only interesting when they differ. Keys are compared case-sensitively
# because GitHub reports canonical names ("TypeScript", not "typescript").
STACK_LANGUAGES = frozenset({"TypeScript"})

# Last verified public counters, used when GitHub cannot be reached at all and
# no usable cache exists. Same schema as the live path so profile_block() is
# schema-agnostic. Only a floor for offline reproducibility - it is never
# preferred over live data, and it is not a source of truth about the account.
VERIFIED_SNAPSHOT = {
    "stars": 9,
    "repos": 12,
    "prs": 14,
    "merged": 13,
    "rank": "C+",
    "languages": ["Python", "TypeScript", "JavaScript"],
}

# The prompt, in three parts: warm identity, a gold path component, and neutral
# shell symbols between them.
#   asher@ASHER-SGNL7CR -> 91 #ef7e7e warm    - identity
#   @                   -> 37 #b3b9b8 neutral - shell symbol
#   :                   -> 37 #b3b9b8 neutral - shell symbol
#   ~                   -> 93 #f4d67a gold    - path component
#   $                   -> 37 #b3b9b8 neutral - shell symbol
#
# Nothing in the prompt is blue. Blue is the inline-highlight role only, and
# putting it on the prompt makes the line read as a graphic rather than a shell.
PROMPT = (
    "\x1b[91masher@ASHER-SGNL7CR\x1b[0m"   # 91 #ef7e7e warm    - identity
    "\x1b[37m@\x1b[0m"                     # 37 #b3b9b8 neutral - shell symbol
    "\x1b[37m:\x1b[0m"                     # 37 #b3b9b8 neutral - shell symbol
    "\x1b[93m~\x1b[0m"                     # 93 #f4d67a gold    - path component
    "\x1b[37m$ \x1b[0m"                    # 37 #b3b9b8 neutral - shell symbol
)

# Left column: the ASHER mark, drawn with the display face vtks-blocketo at
# MARK_SIZE, one letter per row via the library's own gen_text(). Five letters
# stacked vertically: A S H E R.
#
# Size, measured rather than guessed - at MARK_SIZE the letter ink is 24px wide
# and all five glyphs are pairwise distinct with no clipping.
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


def fetch_repo_count() -> int | None:
    """Number of repositories the account owns, straight from the GraphQL API.

    The package's stats helper has no repository count: it exposes
    `total_repo_contributions`, which is repositoriesContributedTo - a different
    field that includes repositories owned by other people. The only honest
    source for "my repos" is repositories(ownerAffiliations: OWNER), so this
    asks for it directly using the same token and endpoint the helper uses.

    Returns None on any failure. The caller must handle that: a None rendered
    into the profile would print the literal text "None repos".
    """
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        return None
    try:
        import requests

        query = """
        query userInfo($user_name: String!) {
            user(login: $user_name) {
                repositories(first: 1, ownerAffiliations: [OWNER]) {
                    totalCount
                }
            }
        }
        """
        r = requests.post(
            "https://api.github.com/graphql",
            json={"query": query, "variables": {"user_name": HANDLE}},
            headers={"Authorization": f"bearer {token}"},
            timeout=30,
        )
        if r.status_code != 200:
            print(f"WARN: repo count HTTP {r.status_code}")
            return None
        payload = r.json()
        if "errors" in payload:
            print(f"WARN: repo count GraphQL error: {payload['errors']}")
            return None
        count = payload["data"]["user"]["repositories"]["totalCount"]
        if not isinstance(count, int):
            print(f"WARN: repo count not an int: {count!r}")
            return None
        return count
    except Exception as exc:  # network/JSON surprises must not kill the render
        print(f"WARN: repo count failed: {exc}")
        return None


# The stats keys profile_block() reads. A cached snapshot written by an older
# schema (it used to carry "commits" and "followers") must not be fed straight
# to profile_block(), or the render dies on KeyError before any frame is drawn.
# This is the contract both the cache reader and the live path are held to.
STATS_SCHEMA = ("stars", "repos", "prs", "merged", "rank", "languages")


def stats_are_valid(stats: object) -> bool:
    """True when stats carries exactly the current schema, with usable values.

    Checked rather than trusted, because the cache is untracked and can hold
    whatever the last successful run wrote - including output from an older
    schema after the fields change.
    """
    if not isinstance(stats, dict) or set(stats) != set(STATS_SCHEMA):
        return False
    if any(not isinstance(stats[k], int) for k in ("stars", "repos", "prs", "merged")):
        return False
    if not isinstance(stats["rank"], str) or not stats["rank"]:
        return False
    langs = stats["languages"]
    return isinstance(langs, list) and all(isinstance(name, str) for name in langs)


def read_cached_stats() -> dict | None:
    """Load the last verified snapshot, or None if it is absent or unusable.

    An unusable cache is reported and discarded rather than returned: falling
    back to the built-in snapshot keeps the render reproducible offline, which
    is the whole point of the cache existing.
    """
    if not CACHE_FILE.exists():
        return None
    try:
        cached = json.loads(CACHE_FILE.read_text())
    except (OSError, ValueError) as exc:
        print(f"WARN: cache unreadable ({exc}); discarding")
        return None
    if not stats_are_valid(cached):
        print(
            f"WARN: cache schema is {sorted(cached) if isinstance(cached, dict) else 'not an object'}, "
            f"expected {sorted(STATS_SCHEMA)}; discarding"
        )
        return None
    return cached


def fetch_stats() -> dict:
    """Public GitHub counters, via the package's own stats helper.

    fetch_github_stats() calls sys.exit() when GITHUB_TOKEN is missing, so the
    token is checked here first and the cached snapshot keeps the render
    reproducible offline. Every value is public profile data; nothing private is
    requested and the token is never persisted.

    Both exit paths return the same schema (STATS_SCHEMA), so profile_block()
    never has to care which one produced the dict.
    """
    # Offline: cache first, then the built-in snapshot. Both are schema-checked.
    if not os.getenv("GITHUB_TOKEN"):
        print("WARN: GITHUB_TOKEN unset")
        cached = read_cached_stats()
        if cached is not None:
            print("INFO: using cached stats")
            return cached
        print("INFO: using verified snapshot")
        return dict(VERIFIED_SNAPSHOT)

    from gifos.utils.fetch_github_stats import fetch_github_stats

    s = fetch_github_stats(HANDLE, [], include_all_commits=False)
    if s is None:
        print("WARN: stats fetch failed")
        cached = read_cached_stats()
        if cached is not None:
            return cached
        raise SystemExit("no stats and no cache")

    stats = {
        "stars": s.total_stargazers,
        "repos": fetch_repo_count(),
        "prs": s.total_pull_requests_made,
        "merged": s.total_pull_requests_merged,
        "rank": s.user_rank.level,
        # Fetched wider than it is displayed. The package hands back the top 6;
        # taking 3 here would truncate before the TypeScript filter runs in
        # profile_block(), leaving the langs row short. profile_block() applies
        # the cap after filtering, so the row still shows at most 3.
        "languages": [name for name, _ in s.languages_sorted],
    }

    # The repo count is a separate request from the package's helper, so it is
    # the one field that can come back empty. Prefer the cached count, then the
    # verified snapshot, over rendering a literal "None" into the profile.
    if stats["repos"] is None:
        fallback = read_cached_stats() or VERIFIED_SNAPSHOT
        stats["repos"] = fallback["repos"]
        print(f"WARN: repo count unavailable; using {stats['repos']} from snapshot")

    assert stats_are_valid(stats), f"live stats off-schema: {stats}"
    print(f"INFO: stats {stats}")
    CACHE_FILE.write_text(json.dumps(stats, indent=2))
    return stats


def profile_block(stats: dict) -> str:
    """The right-hand column: who, what, stack, contact, counters.

    Emitted as one multiline string so the library does the row layout. Keys are
    padded to a fixed width so values line up, which is how a utility like
    neofetch prints: dim label, readable value, nothing decorative.

    Colour is assigned by ROLE rather than by decoration, and each role owns one
    ANSI slot. The roles are what make the frame legible as a terminal: a reader
    should be able to tell a label from a value from an inline highlight without
    reading the text.

        \\x1b[30;101m  section header  dark text on a warm filled backing
        \\x1b[96m      labels          cyan
        \\x1b[93m      values          gold
        \\x1b[94m      inline tags     blue, used sparingly on the counters

    Blue is reserved for that last role and nothing else. It is the rarest
    colour on the frame by design, so the inline numbers read as highlights
    rather than as a second label colour.

    Measured ink shares for this frame, for comparison:
        gold 1.17%  warm 0.50%  neutral 0.44%  cyan 0.14%  green 0.12%  blue 0.03%
    """
    # Slot check, from config/ansi_escape_colors.toml bright_colors:
    #   90 #64748b muted   91 #ef7e7e warm   92 #96d988 green  93 #f4d67a gold
    #   94 #60a5fa blue    96 #67cbe7 cyan   97 #f8fafc neutral
    rule = "\x1b[90m"     # 90 #64748b muted - the ---------- separator
    dim = "\x1b[90m"      # 90 #64748b muted - qualifiers, "fetch profile"
    key = "\x1b[96m"      # 96 #67cbe7 cyan  - every label
    val = "\x1b[93m"      # 93 #f4d67a gold  - every value
    num = "\x1b[94m"      # 94 #60a5fa blue  - inline highlights ONLY
    dot = f" {dim}\u00b7{val} "

    # stack is the technologies field - what Asher works with, curated.
    # langs is GitHub-derived signal. TypeScript appears in both, so it is
    # filtered out of langs to avoid saying the same thing twice on one screen.
    # The list stays dynamic: it is still whatever GitHub reports, minus the
    # duplicates, never a hand-written list. Filtering happens here, at render
    # time, so the same rule applies to the live, cached and snapshot paths -
    # filtering earlier would leave an already-written cache unfiltered.
    # Displayed in descending GitHub share order, capped at 3.
    langs = ", ".join(
        [name for name in stats["languages"] if name not in STACK_LANGUAGES][:3]
    )

    # The header is the 30;101 pair: 30 is the dark text, 101 the warm filled
    # backing. "fetch profile" sits OUTSIDE the backing as a separate muted
    # qualifier rather than part of the header - which is why the reset precedes
    # it.
    return "\n".join(
        [
            f"\x1b[30;101m{HANDLE}@github\x1b[0m {dim}\u00b7 fetch profile",
            f"{rule}{'-' * 47}\x1b[0m",
            f"{key}role   \x1b[0m{val}{USER}",
            f"{key}title  \x1b[0m{val}Data Engineer",
            f"{key}focus  \x1b[0m{val}Data Platforms{dot}Pipelines{dot}Decision Intelligence",
            "",
            f"{key}stack  \x1b[0m{val}Python{dot}SQL{dot}TypeScript{dot}PostgreSQL{dot}BigQuery",
            f"{key}       \x1b[0m{val}dbt{dot}Kestra{dot}PySpark{dot}Kafka/Redpanda{dot}Flink/PyFlink",
            f"{key}       \x1b[0m{val}Docker{dot}Next.js",
            "",
            f"{key}web    \x1b[0m{val}codered-azure.vercel.app",
            f"{key}in     \x1b[0m{val}linkedin.com/in/delebayo-joea",
            f"{key}mail   \x1b[0m{val}josephdelebayo@gmail.com",
            f"{key}social \x1b[0m{val}Twitter {dim}\u00b7 {val}@23asher_io",
            "",
            # The counters carry the inline-highlight role, which is the only
            # place blue appears in the block.
            f"{key}github \x1b[0m{num}{stats['repos']}{val} repos"
            f"{dot}{num}{stats['prs']}{val} PRs{dot}{num}{stats['merged']}{val} merged",
            f"{key}       \x1b[0m{num}{stats['stars']}{val} stars"
            f"{dot}{val}rank {num}{stats['rank']}",
            # langs is a first-class field label on its own row, in the same label
            # column as the rest - not a continuation of the value above it.
            f"{key}langs  \x1b[0m{val}{langs}",
        ]
    )


def required_height(block: str) -> int:
    """Panel height needed for the settled frame, in pixels.

    Derived from the content, not guessed. The bottom-most occupied row is the
    closing prompt, which sits one row below the last line of the profile block
    (close_row in main()). The library computes its row count as
    (height - 2*ypad) // pitch, so the height that yields exactly that many rows
    is the inverse of that expression:

        height = 2*ypad + rows*pitch + bottom_pad

    with rows = close_row. BOTTOM_PAD then adds the bottom breathing room. Both
    the profile block length and the closing-prompt offset are read from the
    same values main() uses, so gaining or losing a line moves the panel edge
    automatically.
    """
    block_rows = len(block.split("\n"))
    close_row = INFO_ROW + block_rows + 1
    return 2 * YPAD + close_row * BODY_CELL_H + BOTTOM_PAD


def assert_only_warm_background(block: str) -> None:
    """Fail if any block text can paint a background other than the 101 header.

    gifos maps background slots 40-47 and 100-107 off the same normal_colors and
    bright_colors tables the foreground slots use, and 104 resolves to #60a5fa -
    a bright blue box. Note the ranges are NOT 40..107: 48-99 are foreground
    codes that merely sit inside that span (90 muted, 93 gold, 94 blue, 96 cyan),
    so a bare range test rejects the whole profile block. Only 40-47 and 100-107
    set a background. Nothing here should set one at all except the single 101
    that forms the section header, so this is checked rather than assumed.
    """
    allowed = {"101"}
    codes = {
        c
        for group in re.findall(r"\x1b\[([0-9;]*)m", block)
        for c in group.split(";")
        if c.isdigit()
    }
    bg = {
        c
        for c in codes
        if 40 <= int(c) <= 47 or 100 <= int(c) <= 107
    }
    if bg - allowed:
        raise SystemExit(f"profile block sets unexpected background slots: {bg - allowed}")


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


def draw_mark(t, height: int) -> None:
    """Paint the ASHER mark in the left canvas using the display logo face.

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
    if need_px_h > height or need_px_w > WIDTH:
        raise SystemExit(
            f"ASHER mark needs {need_rows}px tall at row {MARK_ROW} "
            f"({need_px_h}px) and {ink_w}px wide at col {MARK_COL} "
            f"({need_px_w}px); canvas is {height}x{WIDTH}"
        )

    t.set_font(str(FONT_MARK), MARK_SIZE, 0)
    for i, ch in enumerate("ASHER"):
        # 37 neutral terminal ink #b3b9b8 - a supporting role, deliberately not
        # an accent. It must not share the muted separator slot, or the mark
        # reads as furniture rather than terminal art, and a cold dark slate here
        # reads as dull blue-grey beside the warm roles. The mark stays secondary
        # because it is neutral and small, not because it is dim.
        t.gen_text(f"\x1b[37m{ch}\x1b[0m", MARK_ROW + i, MARK_COL, contin=True)
    # Restore the body face so nothing after this point inherits the mark's cells.
    t.set_font(str(FONT_FILE), FONT_SIZE, LINE_SPACING)


def main() -> None:
    sync_config()
    stats = fetch_stats()

    # The block is built before the Terminal exists because it determines how
    # tall the panel needs to be. Everything below then draws into a frame sized
    # to the content rather than the other way round.
    block = profile_block(stats)
    assert_only_warm_background(block)
    height = required_height(block)

    gifos = load_gifos()
    t = gifos.Terminal(
        WIDTH, height, XPAD, YPAD, str(FONT_FILE), FONT_SIZE, LINE_SPACING
    )
    print(f"INFO: grid {t.num_cols} cols x {t.num_rows} rows")
    print(f"INFO: panel {WIDTH}x{height} from {len(block.split(chr(10)))} block lines")
    t.set_prompt(PROMPT)

    # --- prompt, then the fetch command typed out ----------------------------
    # The command is typed in 91 warm, then repainted in 92 green once it
    # "resolves". delete_row() erases back to the post-prompt column so the
    # recoloured text replaces the typed text in place:
    #     t.gen_typing_text("\x1b[91mfetch.sh", ...)   # typed, warm
    #     t.delete_row(1, prompt_col)                  # erase back
    #     t.gen_text("\x1b[92mfetch.sh\x1b[0m", ...)    # resolved, green
    # This is what stops the command reading as plain white body text.
    t.toggle_show_cursor(False)
    t.gen_text("", 1, count=18)
    t.gen_prompt(1, count=6)
    prompt_col = t.curr_col
    t.toggle_show_cursor(True)
    t.gen_typing_text(f"\x1b[91mfetch.sh", 1, contin=True, speed=1)
    t.delete_row(1, prompt_col)
    t.gen_text(f"\x1b[92mfetch.sh\x1b[0m", 1, count=3, contin=True)
    t.gen_typing_text(f"\x1b[92m -u {FETCH_USER}\x1b[0m", 1, contin=True, speed=1)
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

    assert_fits(block, t.num_cols)
    t.gen_text(block, INFO_ROW, INFO_COL, count=4, contin=True)

    # Drawn last. draw_mark() switches to the mark face and back, and each
    # letter is written at an explicit row and column, so the profile block
    # above is unaffected by it.
    draw_mark(t, height)

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
    # 92 green #96d988: the closing message keeps the resolved-command green
    # rather than dropping to muted grey, which would collapse it into the same
    # tone as the separator.
    t.gen_typing_text(
        "\x1b[92m# thanks for stopping by\x1b[0m", close_row, contin=True, speed=1
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
