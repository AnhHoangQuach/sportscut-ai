import inspect
import numpy as np
import pytest
import re

import sportscut.detect as detect
from sportscut.detect import SAMPLE_RATE, find_highlights
from sportscut.media import extract_audio, probe_duration


def test_public_detector_contract() -> None:
    assert inspect.signature(find_highlights).parameters == {
        "video": inspect.Parameter("video", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str),
        "top": inspect.Parameter("top", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=10, annotation=int | None),
        "min_len": inspect.Parameter("min_len", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=10, annotation=float),
        "max_len": inspect.Parameter("max_len", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=30, annotation=float),
    }
    assert inspect.signature(find_highlights).return_annotation == list[detect.Segment]
    assert (detect.PRE_SEC, detect.POST_SEC, detect.BASELINE_SEC) == (8.0, 4.0, 120)
    assert (detect.MIN_Z, detect.MIN_SCALE_DB) == (3.0, 1.0)
    assert detect.extract_audio is extract_audio
    assert detect.probe_duration is probe_duration


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"top": 0}, "top must be >= 1"),
        ({"min_len": 0}, "min_len must be > 0"),
        ({"min_len": 20, "max_len": 10}, "min_len must be <= max_len"),
    ],
)
def test_rejects_invalid_options(options: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=f"^{message}$"):
        find_highlights("missing.mp4", **options)


@pytest.mark.parametrize("sample_count", [60 * SAMPLE_RATE, SAMPLE_RATE // 2])
def test_silence_and_sub_second_audio_give_no_segments(
    monkeypatch: pytest.MonkeyPatch, sample_count: int
) -> None:
    monkeypatch.setattr("sportscut.detect.probe_duration", lambda _video: 60.0)
    monkeypatch.setattr(
        "sportscut.detect.extract_audio",
        lambda _video: np.zeros(sample_count, dtype=np.float32),
    )

    assert find_highlights("x.mp4") == []


def test_every_burst_covered_once_and_quiet_parts_untouched(burst_video) -> None:
    segments = find_highlights(burst_video)

    assert len(segments) == 3
    assert segments == sorted(segments, key=lambda segment: segment.start)
    for burst_start in (20, 50, 75):
        covering = [
            segment
            for segment in segments
            if segment.start <= burst_start and segment.end >= burst_start + 1
        ]
        assert len(covering) == 1
    for quiet_start, quiet_end in ((0, 10), (28, 40), (58, 65), (82, 90)):
        assert all(
            not (segment.start < quiet_end and quiet_start < segment.end)
            for segment in segments
        )
    for segment in segments:
        assert segment.end - segment.start == pytest.approx(12, abs=0.01)
        assert re.fullmatch(r"audio peak z=\d+\.\d", segment.reason)
        assert type(segment.score) is float
        assert segment.score >= 3.0
        assert segment.score == pytest.approx(float(segment.reason.rsplit("=", 1)[1]), abs=0.05)


def _contains(segment, start: float, end: float) -> bool:
    return segment.start <= start and segment.end >= end


def test_top_keeps_highest_scores_sorted_by_time(burst_video) -> None:
    top_two = find_highlights(burst_video, top=2)
    assert len(top_two) == 2
    assert _contains(top_two[0], 20, 21)
    assert _contains(top_two[1], 75, 76)

    top_one = find_highlights(burst_video, top=1)
    assert len(top_one) == 1
    assert _contains(top_one[0], 75, 76)


def test_top_none_returns_all_candidates_and_preserves_capped_result(burst_video) -> None:
    all_segments = find_highlights(burst_video, top=None)
    assert len(all_segments) >= 3
    ranked = sorted(all_segments, key=lambda item: (-item.score, item.start))[:2]
    assert find_highlights(burst_video, top=2) == sorted(ranked, key=lambda item: item.start)


def test_min_len_extends_segments(burst_video) -> None:
    segments = find_highlights(burst_video, min_len=20, max_len=30)
    assert len(segments) == 3
    assert all(segment.end - segment.start == pytest.approx(20, abs=0.01) for segment in segments)
    assert all(_contains(segment, burst, burst + 1) for segment, burst in zip(segments, (20, 50, 75)))


def test_max_len_shortens_segments(burst_video) -> None:
    segments = find_highlights(burst_video, min_len=4, max_len=6)
    assert len(segments) == 3
    assert all(segment.end - segment.start == pytest.approx(6, abs=0.01) for segment in segments)
    assert all(_contains(segment, burst, burst + 1) for segment, burst in zip(segments, (20, 50, 75)))


def test_overlapping_windows_are_suppressed(burst_video) -> None:
    segments = find_highlights(burst_video, min_len=60, max_len=60)
    assert len(segments) == 1
    assert segments[0].start == pytest.approx(30.0, abs=0.2)
    assert segments[0].end == pytest.approx(probe_duration(burst_video), abs=0.01)
    assert _contains(segments[0], 75, 76)


def test_short_clip_is_clamped_to_duration(synthetic_video) -> None:
    segments = find_highlights(synthetic_video)
    assert len(segments) == 1
    assert segments[0].start == 0.0
    assert segments[0].end == pytest.approx(probe_duration(synthetic_video))
