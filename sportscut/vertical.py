"""Render vertical 9:16 clips by following a crop path."""

import math
from numbers import Real
from pathlib import Path

from sportscut import media, reframe
from sportscut.events import scoreboard

OUT_WIDTH = 1080
OUT_HEIGHT = 1920
MAX_EXPRESSION = 100_000
GRID_W, GRID_H = 160, 90          # sample_top_band scale grid
SCORE_MAX_W, SCORE_MAX_H = 1000, 160
SCORE_TOP = 40                    # y of the scoreboard overlay in the 1080x1920 frame
CAPTION_Y = 240
SUB_FONTSIZE = 56
SUB_LAST_Y = 1600                 # top y of the last subtitle line (lower third)
SUB_LINE_H = 80
CAPTION_LABELS = {
    "goal": "BÀN THẮNG",
    "save": "CỨU THUA",
    "red_card": "THẺ ĐỎ",
    "controversy": "TRANH CÃI",
}


def _is_number(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, Real)
        and math.isfinite(value)
    )


def _validate(crop_path) -> list[tuple[float, float]]:
    try:
        items = list(crop_path)
    except TypeError:
        raise ValueError("invalid crop path: not a sequence") from None
    if not items:
        raise ValueError("invalid crop path: empty")
    keyframes: list[tuple[float, float]] = []
    for index, item in enumerate(items):
        try:
            pair = tuple(item)
        except TypeError:
            raise ValueError(f"invalid crop path: item {index} is not a pair") from None
        if len(pair) != 2 or not all(_is_number(value) for value in pair):
            raise ValueError(
                f"invalid crop path: item {index} is not a pair of finite numbers"
            )
        t, x = float(pair[0]), float(pair[1])
        if index == 0 and t < 0:
            raise ValueError("invalid crop path: first t is negative")
        if keyframes and t <= keyframes[-1][0]:
            raise ValueError(f"invalid crop path: t is not strictly increasing at item {index}")
        keyframes.append((t, x))
    return keyframes


def crop_x_expression(crop_path, width: int, crop_w: int) -> str:
    """Return a flat ffmpeg expression in t for the crop's left edge."""
    keyframes = _validate(crop_path)
    half = crop_w / 2
    lefts = [
        (t, min(max(x, half), width - half) - half) for t, x in keyframes
    ]
    parts = [f"{lefts[0][1]:.4f}"]
    for (t0, l0), (t1, l1) in zip(lefts, lefts[1:]):
        slope = (l1 - l0) / (t1 - t0)
        if abs(slope) < 1e-9:
            continue
        sign = "+" if slope > 0 else "-"
        parts.append(f"{sign}{abs(slope):.6f}*(clip(t,{t0:.4f},{t1:.4f})-{t0:.4f})")
    expr = "".join(parts)
    if len(expr) > MAX_EXPRESSION:
        raise ValueError(f"crop path too long: {len(keyframes)} keyframes")
    return expr


def caption_text(event: str, start: float, end: float) -> str | None:
    """Return the caption for an event segment, e.g. "BÀN THẮNG · 34'"."""
    label = CAPTION_LABELS.get(event)
    if label is None:
        return None
    minute = math.floor((start + end) / 2 / 60) + 1
    return f"{label} \u00b7 {minute}'"


def check_score_box(box, width: int, height: int) -> tuple[int, int, int, int]:
    """Return box as four ints, or raise ValueError if it is not inside the frame."""
    try:
        values = tuple(box)
    except TypeError:
        values = ()
    if isinstance(box, str) or len(values) != 4 or not all(
        isinstance(v, int) and not isinstance(v, bool) for v in values
    ):
        raise ValueError("invalid score box: expected four integers x,y,w,h")
    x, y, w, h = values
    if x < 0 or y < 0 or w < 2 or h < 2:
        raise ValueError("invalid score box: x,y must be >= 0 and w,h >= 2")
    if x + w > width or y + h > height:
        raise ValueError(
            f"invalid score box: {x},{y},{w},{h} does not fit the {width}x{height} frame"
        )
    return values


def band_box_to_source(box, width: int, height: int) -> tuple[int, int, int, int]:
    """Map a find_box result in the 160x90 grid to padded, even source pixels."""
    x, y, w, h = box
    bx0, by0 = max(0, x - 1), max(0, y - 1)
    bx1, by1 = min(GRID_W, x + w + 1), min(media.BAND_H, y + h + 1)
    sx0, sy0 = bx0 * width // GRID_W, by0 * height // GRID_H
    sx1 = min(width, -(-bx1 * width // GRID_W))
    sy1 = min(height, -(-by1 * height // GRID_H))
    sx0 -= sx0 % 2
    sy0 -= sy0 % 2
    sx1 = min(width - width % 2, sx1 + sx1 % 2)
    sy1 = min(height - height % 2, sy1 + sy1 % 2)
    return (sx0, sy0, sx1 - sx0, sy1 - sy0)


def find_score_box(clip) -> tuple[int, int, int, int] | None:
    """Return the static broadcast scoreboard box in source pixels, or None."""
    band = scoreboard.find_box(media.sample_top_band(clip))
    if band is None:
        return None
    width, height = media.probe_size(clip)
    return band_box_to_source(band, width, height)


def score_overlay_geometry(box) -> tuple[int, int, int, int]:
    """Return (scaled w, scaled h, x, y) of the scoreboard overlay."""
    _, _, w, h = box
    f = min(SCORE_MAX_W / w, SCORE_MAX_H / h)
    sw = max(2, 2 * round(w * f / 2))
    sh = max(2, 2 * round(h * f / 2))
    return (sw, sh, (OUT_WIDTH - sw) // 2, SCORE_TOP)


def _escape(value: str) -> str:
    """Escape a filter option value at ffmpeg's two filtergraph levels."""
    for old, new in (("\\", "\\\\"), ("'", "\\'"), (":", "\\:")):
        value = value.replace(old, new)
    for old, new in (
        ("\\", "\\\\"), ("'", "\\'"), ("[", "\\["), ("]", "\\]"),
        (",", "\\,"), (";", "\\;"),
    ):
        value = value.replace(old, new)
    return value


def drawtext_filter(caption: str, fontfile) -> str:
    """Return the drawtext filter that writes caption below the scoreboard."""
    return (
        f"drawtext=fontfile={_escape(str(fontfile))}:text={_escape(caption)}:"
        "expansion=none:fontsize=64:fontcolor=white:box=1:boxcolor=black@0.6:"
        f"boxborderw=16:x=(w-text_w)/2:y={CAPTION_Y}"
    )


def subtitle_filters(cues, fontfile) -> str:
    """Return one drawtext per subtitle line, shown only during its cue, in the lower third."""
    filters = []
    for start, end, text in cues:
        lines = text.split("\n")
        n = len(lines)
        for j, line in enumerate(lines):
            y = SUB_LAST_Y - (n - 1 - j) * SUB_LINE_H
            filters.append(
                f"drawtext=fontfile={_escape(str(fontfile))}:text={_escape(line)}:expansion=none:"
                f"fontsize={SUB_FONTSIZE}:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=12:"
                f"x=(w-text_w)/2:y={y}:enable='between(t,{start:.3f},{end:.3f})'"
            )
    return ",".join(filters)


def vertical_filter(
    crop_path, width: int, height: int, score_box=None, caption=None, fontfile=None,
    subtitles=None,
) -> str:
    """Return the ffmpeg -vf filter that crops along the path and scales to 9:16.

    With score_box, the box is cropped from the source on every frame and
    overlaid in the top band; with caption, a drawtext line is added; with
    subtitles (layout cues), their lines are drawn in the lower third.
    """
    crop_w = reframe.crop_width(width, height)
    expr = crop_x_expression(crop_path, width, crop_w)
    base = (
        f"crop=w={crop_w}:h={height}:x='{expr}':y=0,"
        f"scale={OUT_WIDTH}:{OUT_HEIGHT},setsar=1"
    )
    if score_box is None and caption is None and not subtitles:
        return base
    if caption is not None and fontfile is None:
        raise ValueError("caption needs a fontfile")
    if subtitles and fontfile is None:
        raise ValueError("subtitles need a fontfile")
    graph = base
    if score_box is not None:
        bx, by, bw, bh = check_score_box(score_box, width, height)
        sw, sh, ox, oy = score_overlay_geometry((bx, by, bw, bh))
        graph = (
            f"split=2[sc_main][sc_box];[sc_main]{base}[sc_v];"
            f"[sc_box]crop=w={bw}:h={bh}:x={bx}:y={by},scale={sw}:{sh},setsar=1[sc_b];"
            f"[sc_v][sc_b]overlay=x={ox}:y={oy}"
        )
    if caption is not None:
        graph = graph + "," + drawtext_filter(caption, fontfile)
    if subtitles:
        graph = graph + "," + subtitle_filters(subtitles, fontfile)
    return graph


def render_vertical(clip, crop_path, out, score_box=None, caption=None, subtitles=None) -> Path:
    """Render a 1080x1920 H.264 copy of clip that follows crop_path."""
    _validate(crop_path)
    width, height = media.probe_size(clip)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    fontfile = media.find_font() if caption is not None or subtitles else None
    return media.filter_video(
        clip,
        vertical_filter(crop_path, width, height, score_box, caption, fontfile, subtitles),
        out,
    )
