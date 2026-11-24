import re
import unicodedata
from dataclasses import dataclass

from sportscut.commentary.facts import ClipFacts

EVENT_LABELS = {
    "goal": "Bàn thắng",
    "save": "Pha cứu thua",
    "red_card": "Thẻ đỏ",
    "controversy": "Tình huống gây tranh cãi",
    "other": "Khoảnh khắc đáng chú ý",
}
EVENT_TAGS = {
    "goal": "BanThang",
    "save": "CuuThua",
    "red_card": "TheDo",
    "controversy": "TranhCai",
    "other": "KhoanhKhac",
}


@dataclass(frozen=True)
class ClipMeta:
    title: str
    caption: str
    hashtags: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"title": self.title, "caption": self.caption, "hashtags": list(self.hashtags)}


def hashtag(text: str) -> str | None:
    text = text.replace("đ", "d").replace("Đ", "D")
    folded = "".join(
        char for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )
    result = "".join(part[0].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", folded) if part)
    return f"#{result}" if result else None


def generate_meta(facts: ClipFacts, backend: str = "template") -> ClipMeta:
    if backend != "template":
        raise ValueError(f"unknown backend: {backend}")

    label = EVENT_LABELS[facts.event]
    teams = (
        f"{facts.home} vs {facts.away}" if facts.home and facts.away
        else facts.home or facts.away
    )
    minute = f"phút {facts.minute}" if facts.minute is not None else None
    candidates = []
    if teams and minute:
        candidates.append(f"{label}: {teams}, {minute}")
    if teams:
        candidates.append(f"{label}: {teams}")
    if minute:
        candidates.append(f"{label}, {minute}")
    candidates.append(f"{label} trong trận đấu")
    title = next(candidate for candidate in candidates if 10 <= len(candidate) <= 80)

    if facts.home and facts.away:
        match_text = f" trong trận {facts.home} gặp {facts.away}"
    elif facts.home or facts.away:
        match_text = f" trong trận đấu của {facts.home or facts.away}"
    else:
        match_text = " trong trận đấu"
    caption = label + match_text
    if facts.minute is not None:
        caption += f" ở phút {facts.minute}"
    if facts.competition:
        caption += f" tại {facts.competition}"
    caption += "."
    if facts.score:
        caption += f" Tỉ số: {facts.score}."
    caption += " Cùng xem lại khoảnh khắc này!"

    tags = ["#BongDa", f"#{EVENT_TAGS[facts.event]}", "#Highlight"]
    tags.extend(filter(None, (hashtag(value) for value in (facts.home, facts.away, facts.competition) if value)))
    unique = []
    seen = set()
    for tag in tags:
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(tag)
    return ClipMeta(title, caption, tuple(unique))
