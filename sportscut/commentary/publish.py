import json
from pathlib import Path

from sportscut.commentary import llm
from sportscut.commentary.facts import ClipFacts, facts_from_entry
from sportscut.commentary.meta import EVENT_LABELS, EVENT_TAGS, ClipMeta, generate_meta, hashtag
from sportscut.export import MANIFEST_NAME
from sportscut.models import EVENT_TYPES

CAPTIONS_NAME = "captions.txt"
REEL_NAME = "reel.json"
META_KEYS = ("title", "caption", "hashtags")


def reel_meta(facts_list: list[ClipFacts]) -> ClipMeta:
    first = facts_list[0]
    home, away, competition, score = first.home, first.away, first.competition, first.score
    counts = [(e, n) for e in EVENT_TYPES if (n := sum(f.event == e for f in facts_list))]
    teams = f"{home} vs {away}" if home and away else home or away
    titles = ([f"Tổng hợp highlight: {teams}"] if teams else []) + ["Tổng hợp highlight trận đấu"]
    title = next(t for t in titles if 10 <= len(t) <= 80)
    match_text = (f" trong trận {home} gặp {away}" if home and away
                  else f" trong trận đấu của {home or away}" if home or away else " trong trận đấu")

    def caption(with_counts: bool) -> str:
        text = f"Tổng hợp {len(facts_list)} khoảnh khắc đáng chú ý" + match_text
        text += f" tại {competition}" if competition else ""
        text += (": " + ", ".join(f"{n} {EVENT_LABELS[e].lower()}" for e, n in counts)) if with_counts else ""
        return text + "." + (f" Tỉ số: {score}." if score else "") + " Cùng xem lại nhé!"

    text = caption(True)
    if len(text) > 300:
        text = caption(False)
    tags = ["#BongDa", "#Highlight", "#TongHop"]
    tags += [tag for value in (home, away, competition) if value and (tag := hashtag(value))]
    tags += [f"#{EVENT_TAGS[e]}" for e, _ in counts]
    unique = [tag for i, tag in enumerate(tags) if tag.casefold() not in {t.casefold() for t in tags[:i]}]
    return ClipMeta(title, text, tuple(unique[:8]))


def _load_facts(path: Path, match) -> tuple[list[dict], list[ClipFacts]]:
    facts_from_entry({"start": 0, "end": 1, "event": "other"}, match)  # match errors are raised as they are
    if not path.is_file():
        raise ValueError(f"missing {path}")
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: cannot read JSON: {exc}") from exc
    if not isinstance(entries, list):
        raise ValueError(f"{path}: expected a JSON list of clips")
    if not entries:
        raise ValueError(f"{path}: no clips")
    facts = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: [{i}]: entry must be an object")
        if not isinstance(entry.get("file"), str) or not entry["file"]:
            raise ValueError(f"{path}: [{i}]: file must be a non-empty string")
        event = entry.get("event") if entry.get("event") in EVENT_TYPES else "other"
        try:
            facts.append(facts_from_entry({**entry, "event": event}, match))
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"{path}: [{i}]: {exc}") from exc
    return entries, facts


def write_meta(out_dir, match=None, backend="template", client=None) -> list[dict]:
    if backend not in ("template", "llm"):
        raise ValueError(f"unknown backend: {backend}")
    out = Path(out_dir)
    entries, facts = _load_facts(out / MANIFEST_NAME, match)
    if backend == "template":
        metas = [generate_meta(f, clip=i) for i, f in enumerate(facts)]
    else:
        metas = llm.generate_metas_llm(facts, client=client)
    new_entries = [
        {**{k: v for k, v in entry.items() if k not in META_KEYS}, **meta.to_dict()}
        for entry, meta in zip(entries, metas)
    ]
    reel = reel_meta(facts)
    blocks = [f"{e['file']}\n{e['title']}\n{e['caption']}\n" + " ".join(e["hashtags"]) for e in new_entries]
    (out / MANIFEST_NAME).write_text(json.dumps(new_entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / CAPTIONS_NAME).write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    (out / REEL_NAME).write_text(json.dumps(reel.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return new_entries
