"""Timed Vietnamese commentary script for one clip (text and timing only)."""
import logging
import math
import re
import unicodedata

import numpy as np

from sportscut.commentary import eval_meta
from sportscut.detect import POST_SEC, PRE_SEC
from sportscut.media import SAMPLE_RATE

logger = logging.getLogger(__name__)

SYLLABLES_PER_SEC = 3.5
PAD = 0.25        # silence kept at the clip start and end (s)
GAP = 0.25        # pause between lines when placing (s)
MAX_LINES = 3
MAX_TEXT = 200    # characters per line
EPS = 1e-6
MOMENT_LINES = {
    "goal": "Vào! Bàn thắng!",
    "save": "Pha cứu thua tuyệt vời!",
    "red_card": "Trọng tài rút thẻ đỏ!",
    "controversy": "Tình huống gây tranh cãi!",
    "other": "Khoảnh khắc đáng chú ý!",
}


def syllables(text: str) -> int:
    text = unicodedata.normalize("NFC", text)
    return len(re.findall(r"[^\W\d_]+", text)) + sum(char.isdecimal() for char in text)


def speech_seconds(text: str) -> float:
    return syllables(text) / SYLLABLES_PER_SEC


def default_peak(clip_len: float) -> float:
    return clip_len * PRE_SEC / (PRE_SEC + POST_SEC)


def audio_peak(samples: np.ndarray, clip_len: float) -> float | None:
    n = min(len(samples) // SAMPLE_RATE, math.floor(clip_len))
    if n <= 0:
        return None
    frames = np.asarray(samples[: n * SAMPLE_RATE], dtype=np.float64).reshape(n, SAMPLE_RATE)
    return float(np.argmax(np.sqrt(np.mean(frames ** 2, axis=1)))) + 0.5


def fit_problems(lines, clip_len) -> list[str]:
    problems = [] if 1 <= len(lines) <= MAX_LINES else [f"line count {len(lines)}"]
    prev_end = None
    for i, (start, text) in enumerate(lines, 1):
        end = start + speech_seconds(text)
        if not math.isfinite(start) or start < PAD - EPS:
            problems.append(f"line {i} starts before the window")
        if end > clip_len - PAD + EPS:
            problems.append(f"line {i} overruns the clip")
        if prev_end is not None and start < prev_end - EPS:
            problems.append(f"line {i} overlaps line {i - 1}")
        prev_end = end
    return problems


def script_fits(lines, clip_len) -> bool:
    return not fit_problems(lines, clip_len)


def validate_script(facts, lines, clip_len) -> list[str]:
    texts = [text for _, text in lines]
    problems = fit_problems([(s, t if isinstance(t, str) else "") for s, t in lines], clip_len)
    problems += [
        f"line {i} text" for i, text in enumerate(texts, 1)
        if not isinstance(text, str) or not text or text != text.strip() or len(text) > MAX_TEXT
    ]
    texts = [text for text in texts if isinstance(text, str)]
    joined = "\n".join(texts)
    problems += [f"number {n} not in facts" for n in eval_meta._unexpected_numbers(facts, joined)]
    problems += [f"name {t} not in facts" for t in eval_meta._unknown_names(facts, texts)]
    return problems + ([] if eval_meta._is_vi_text(facts, joined) else ["not vietnamese"])


def _place(before, at, after, clip_len, peak) -> list[tuple[float, str]]:
    s_at = max(PAD, min(peak, clip_len - PAD - speech_seconds(at)))
    result = [(s_at - GAP - speech_seconds(before), before)] if before else []
    result.append((s_at, at))
    if after:
        result.append((s_at + speech_seconds(at) + GAP, after))
    return result


def _before_variants(facts) -> list[str | None]:
    if facts.minute is None and not (facts.home or facts.away or facts.competition):
        return [None]
    if facts.home and facts.away:
        teams = f"{facts.home} gặp {facts.away}"
    elif facts.home or facts.away:
        teams = f"trận đấu của {facts.home or facts.away}"
    else:
        teams = "trận đấu"
    comp = f" tại {facts.competition}" if facts.competition else ""

    def sentence(body: str) -> str:
        text = f"Phút {facts.minute}, {body}." if facts.minute is not None else body + "."
        return text[0].upper() + text[1:]

    variants = [sentence(teams + comp), sentence(teams)]
    if facts.minute is not None:
        variants.append(f"Phút {facts.minute}.")
    return list(dict.fromkeys(variants)) + [None]


def _template(facts, clip_len, peak) -> list[tuple[float, str]]:
    at = MOMENT_LINES[facts.event]
    after = f"Tỉ số {facts.score}." if facts.score else None
    afters = [after, None] if after else [None]
    for before in _before_variants(facts):
        for tail in afters:
            lines = _place(before, at, tail, clip_len, peak)
            if not validate_script(facts, lines, clip_len):
                return lines
    return []


def _is_number(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def write_script(facts, clip_len, backend="template", *, peak=None, client=None) -> list[tuple[float, str]]:
    if not _is_number(clip_len) or clip_len <= 0:
        raise ValueError("clip_len must be a finite number > 0")
    if peak is not None and (not _is_number(peak) or not 0 <= peak < clip_len):
        raise ValueError("peak must be a finite number in [0, clip_len)")
    if backend not in ("template", "llm"):
        raise ValueError(f"unknown backend: {backend}")
    clip_len = float(clip_len)
    peak = default_peak(clip_len) if peak is None else float(peak)
    if backend == "template":
        return _template(facts, clip_len, peak)

    from sportscut.commentary import llm  # lazy: llm imports eval_meta, which imports this module lazily
    limits = {
        "clip_len": clip_len,
        "peak": peak,
        "before_max_syllables": max(0, math.floor(SYLLABLES_PER_SEC * (peak - PAD - GAP))),
        "at_after_max_syllables": max(0, math.floor(SYLLABLES_PER_SEC * (clip_len - PAD - max(peak, PAD)))),
    }
    roles = llm.script_roles_llm(facts, limits, client=client)
    if roles is None:
        return _template(facts, clip_len, peak)
    lines = _place(roles["before"], roles["at"], roles["after"], clip_len, peak)
    if problems := validate_script(facts, lines, clip_len):
        logger.warning("rejected LLM script (%s); template fallback", "; ".join(problems))
        return _template(facts, clip_len, peak)
    return lines
