import json
import re
import unicodedata
from pathlib import Path
from typing import NamedTuple

from sportscut.commentary import meta as meta_module
from sportscut.commentary.facts import ClipFacts
from sportscut.commentary.meta import EVENT_LABELS, ClipMeta

VI_CHARS = "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
FACT_FIELDS = ("minute", "score", "home", "away", "competition")
SCRIPT_CLIP_LENS = (10.0, 30.0)


class MetaCase(NamedTuple):
    id: str
    facts: ClipFacts
    must_mention: list[list[str]]
    forbidden: list[str]


def _normalise(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _facts_text(facts: ClipFacts) -> str:
    return "\n".join(str(value) for field in FACT_FIELDS if (value := getattr(facts, field)) is not None)


def _output_text(meta: ClipMeta) -> str:
    return _normalise(meta.title + "\n" + meta.caption + "\n" + " ".join(meta.hashtags))


def _met_groups(case: MetaCase, output: str) -> int:
    return sum(any(_normalise(needle) in output for needle in group) for group in case.must_mention)


def load_cases(path) -> list[MetaCase]:
    case_path = Path(path)
    try:
        data = json.loads(case_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"{case_path}: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"{case_path}: top level must be a list")
    if not data:
        raise ValueError(f"{case_path}: no eval cases")

    result = []
    ids = set()
    fact_keys = set(ClipFacts.__dataclass_fields__)
    for index, item in enumerate(data):
        where = f"{case_path}: [{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where}: must be an object")
        case_id = item.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"{where}: id must be a non-empty string")
        if case_id in ids:
            raise ValueError(f"{where}: duplicate id {case_id}")
        ids.add(case_id)

        facts_data = item.get("facts")
        if not isinstance(facts_data, dict):
            raise ValueError(f"{where}: facts must be an object")
        unknown = set(facts_data) - fact_keys
        if unknown:
            raise ValueError(f"{where}: unknown facts key: {sorted(unknown)[0]}")
        try:
            facts = ClipFacts(**facts_data)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{where}: invalid facts: {exc}") from exc

        must_mention = item.get("must_mention")
        if not isinstance(must_mention, list) or not must_mention:
            raise ValueError(f"{where}: must_mention must be a non-empty list")
        if any(
            not isinstance(group, list) or not group
            or any(not isinstance(needle, str) or not needle for needle in group)
            for group in must_mention
        ):
            raise ValueError(f"{where}: must_mention groups must contain non-empty strings")

        forbidden = item.get("forbidden")
        if not isinstance(forbidden, list) or any(
            not isinstance(needle, str) or not needle for needle in forbidden
        ):
            raise ValueError(f"{where}: forbidden must be a list of non-empty strings")
        facts_normalised = _normalise(_facts_text(facts))
        for needle in forbidden:
            if _normalise(needle) in facts_normalised:
                raise ValueError(f"{where}: forbidden {needle} appears in facts")
        result.append(MetaCase(case_id, facts, must_mention, forbidden))
    return result


def format_problems(meta: ClipMeta) -> list[str]:
    problems = []
    if not 10 <= len(meta.title) <= 80 or meta.title != meta.title.strip():
        problems.append(f"title length {len(meta.title)}")
    if not 1 <= len(meta.caption) <= 300:
        problems.append(f"caption length {len(meta.caption)}")
    if not 3 <= len(meta.hashtags) <= 8:
        problems.append(f"hashtag count {len(meta.hashtags)}")
    seen_tags = set()
    for tag in meta.hashtags:
        if not isinstance(tag, str) or re.fullmatch(r"#[A-Za-z0-9_]+", tag) is None:
            problems.append(f"bad hashtag {tag}")
        key = tag.casefold() if isinstance(tag, str) else str(tag).casefold()
        if key in seen_tags:
            problems.append(f"duplicate hashtag {tag}")
        seen_tags.add(key)
    return problems


def _unexpected_numbers(facts: ClipFacts, output: str) -> list[str]:
    facts_text = _normalise(_facts_text(facts))
    fact_numbers = set(re.findall(r"\d+", facts_text))
    unexpected = []
    for number in re.findall(r"\d+", output):
        if number not in fact_numbers and number not in unexpected:
            unexpected.append(number)
    return unexpected


def _name_tokens(facts: ClipFacts) -> set[str]:
    names = " ".join(value for value in (facts.home, facts.away, facts.competition) if value)
    return set(re.findall(r"[^\W\d_]+", _normalise(names)))


def _is_vi_text(facts: ClipFacts, text: str) -> bool:
    excluded = _name_tokens(facts)
    tokens = [t for t in re.findall(r"[^\W\d_]+", _normalise(text)) if t not in excluded]
    return bool(tokens) and sum(any(char in VI_CHARS for char in token) for token in tokens) / len(tokens) >= 0.3


def _is_vi(facts: ClipFacts, meta: ClipMeta) -> bool:
    return _is_vi_text(facts, meta.title + " " + meta.caption)


def _unknown_names(facts: ClipFacts, texts: list[str]) -> list[str]:
    segments = [seg for text in texts for seg in re.split(r"[.!?:|]\s+", text)]
    tokens = [t for seg in segments for t in re.findall(r"[^\W\d_]+", unicodedata.normalize("NFC", seg))[1:]]
    allowed = _name_tokens(facts)
    return [t for t in dict.fromkeys(tokens) if t[0].isupper() and t.casefold() not in allowed]


def validate_meta(facts: ClipFacts, meta: ClipMeta) -> list[str]:
    problems = format_problems(meta)
    problems += [f"number {n} not in facts" for n in _unexpected_numbers(facts, _output_text(meta))]
    problems += [f"name {t} not in facts" for t in _unknown_names(facts, [meta.title, meta.caption])]
    body = _normalise(meta.title + "\n" + meta.caption)
    minute = f"phút {facts.minute}" if facts.minute is not None else None
    needed = (EVENT_LABELS[facts.event], facts.home, facts.away, facts.competition, minute, facts.score)
    problems += [f"missing {text}" for text in needed if text is not None and _normalise(text) not in body]
    return problems + ([] if _is_vi(facts, meta) else ["not vietnamese"])


def score_case(case: MetaCase, meta: ClipMeta) -> dict:
    problems = format_problems(meta)
    format_ok = not problems

    output = _output_text(meta)
    met = _met_groups(case, output)
    fact_recall = met / len(case.must_mention)
    unexpected = _unexpected_numbers(case.facts, output)
    problems += [f"number {number} not in facts" for number in unexpected]
    found_forbidden = []
    for needle in case.forbidden:
        if _normalise(needle) in output:
            found_forbidden.append(needle)
            problems.append(f"forbidden {needle}")
    hallucinated = bool(unexpected or found_forbidden)

    vi = _is_vi(case.facts, meta)
    if not vi:
        problems.append("not vietnamese")

    score = fact_recall if format_ok and not hallucinated and vi else 0.0
    return {
        "id": case.id,
        "score": round(score, 4),
        "format_ok": format_ok,
        "fact_recall": round(fact_recall, 4),
        "hallucinated": hallucinated,
        "vi": vi,
        "problems": problems,
        "title": meta.title,
        "caption": meta.caption,
        "hashtags": list(meta.hashtags),
    }


def score_script_case(case: MetaCase, clip_len: float, lines) -> dict:
    from sportscut.commentary import script  # a top-level import would be circular
    texts = [text for _, text in lines]
    text = "\n".join(texts)
    output = _normalise(text)
    problems = script.fit_problems(lines, clip_len)
    script_fits = not problems
    fact_recall = _met_groups(case, output) / len(case.must_mention)
    unexpected = _unexpected_numbers(case.facts, output)
    problems += [f"number {number} not in facts" for number in unexpected]
    found_forbidden = [needle for needle in case.forbidden if _normalise(needle) in output]
    problems += [f"forbidden {needle}" for needle in found_forbidden]
    hallucinated = bool(unexpected or found_forbidden)
    vi = _is_vi_text(case.facts, text)
    if not vi:
        problems.append("not vietnamese")
    score = fact_recall if script_fits and not hallucinated and vi else 0.0
    return {
        "id": case.id,
        "clip_len": clip_len,
        "score": round(score, 4),
        "script_fits": script_fits,
        "fact_recall": round(fact_recall, 4),
        "hallucinated": hallucinated,
        "vi": vi,
        "problems": problems,
        "lines": [{"start": start, "text": line} for start, line in lines],
    }


def _evaluate_scripts(cases: list[MetaCase], backend: str) -> dict:
    from sportscut.commentary import script  # a top-level import would be circular
    results, raw_scores, met_groups = [], [], 0
    for case in cases:
        for clip_len in SCRIPT_CLIP_LENS:
            lines = script.write_script(case.facts, clip_len, backend)
            result = score_script_case(case, clip_len, lines)
            met = _met_groups(case, _normalise("\n".join(text for _, text in lines)))
            met_groups += met
            ok = result["script_fits"] and not result["hallucinated"] and result["vi"]
            raw_scores.append(met / len(case.must_mention) if ok else 0.0)
            results.append(result)
    count = len(results)
    total_groups = sum(len(case.must_mention) for case in cases) * len(SCRIPT_CLIP_LENS)
    return {
        "score": round(sum(raw_scores) / count, 4),
        "script_fits": round(sum(item["script_fits"] for item in results) / count, 4),
        "fact_recall": round(met_groups / total_groups, 4),
        "hallucination_rate": round(sum(item["hallucinated"] for item in results) / count, 4),
        "vi_rate": round(sum(item["vi"] for item in results) / count, 4),
        "per_case": results,
    }


def evaluate_meta_dir(path, backend: str = "template", script: bool = False) -> dict:
    if backend not in ("template", "llm"):
        raise ValueError(f"unknown backend: {backend}")
    root = Path(path)
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    cases_path = root / "cases.json"
    if not cases_path.is_file():
        raise ValueError(f"missing cases.json in {root}")
    cases = load_cases(cases_path)
    if script:
        return _evaluate_scripts(cases, backend)
    if backend == "template":
        generated = [(case, meta_module.generate_meta(case.facts)) for case in cases]
    else:
        from sportscut.commentary import llm  # a top-level import would be circular
        generated = list(zip(cases, llm.generate_metas_llm([case.facts for case in cases])))
    results = [score_case(case, output) for case, output in generated]
    count = len(cases)
    total_groups = sum(len(case.must_mention) for case in cases)
    met_counts = [_met_groups(case, _output_text(output)) for case, output in generated]
    met_groups = sum(met_counts)
    raw_scores = [
        met / len(case.must_mention)
        if result["format_ok"] and not result["hallucinated"] and result["vi"] else 0.0
        for ((case, _), result, met) in zip(generated, results, met_counts)
    ]
    return {
        "score": round(sum(raw_scores) / count, 4),
        "format_ok": round(sum(item["format_ok"] for item in results) / count, 4),
        "fact_recall": round(met_groups / total_groups, 4),
        "hallucination_rate": round(sum(item["hallucinated"] for item in results) / count, 4),
        "vi_rate": round(sum(item["vi"] for item in results) / count, 4),
        "per_case": results,
    }
