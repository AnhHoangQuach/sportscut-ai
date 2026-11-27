import hashlib
import json
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
# Index 0 is always the T-023 phrasing; one entry is picked per clip by _pick.
TITLE_LEADS = {
    "goal": ("Bàn thắng", "Siêu phẩm", "Pha lập công", "Khoảnh khắc ghi bàn"),
    "save": ("Pha cứu thua", "Cứu thua xuất thần", "Pha cản phá đẳng cấp"),
    "red_card": ("Thẻ đỏ", "Tấm thẻ đỏ", "Pha nhận thẻ đỏ"),
    "controversy": ("Tình huống gây tranh cãi", "Pha bóng gây tranh cãi", "Khoảnh khắc gây tranh cãi"),
    "other": ("Khoảnh khắc đáng chú ý", "Pha bóng đáng xem", "Khoảnh khắc ấn tượng"),
}
CAPTION_STYLES = {  # (opener, closer)
    "goal": (("Bàn thắng", "Cùng xem lại khoảnh khắc này!"),
             ("Bàn thắng đẹp mắt", "Xem ngay pha lập công này!"),
             ("Một bàn thắng đáng nhớ", "Hãy cùng xem lại nhé!")),
    "save": (("Pha cứu thua", "Cùng xem lại khoảnh khắc này!"),
             ("Pha cứu thua xuất thần", "Đừng bỏ lỡ pha bóng này!"),
             ("Một pha cứu thua đẳng cấp", "Hãy cùng xem lại nhé!")),
    "red_card": (("Thẻ đỏ", "Cùng xem lại khoảnh khắc này!"),
                 ("Tấm thẻ đỏ", "Đừng bỏ lỡ tình huống này!"),
                 ("Chiếc thẻ đỏ được rút ra", "Hãy cùng xem lại nhé!")),
    "controversy": (("Tình huống gây tranh cãi", "Cùng xem lại khoảnh khắc này!"),
                    ("Tình huống gây tranh cãi lớn", "Bạn nghĩ sao về tình huống này?"),
                    ("Một tình huống gây tranh cãi", "Hãy cùng xem lại nhé!")),
    "other": (("Khoảnh khắc đáng chú ý", "Cùng xem lại khoảnh khắc này!"),
              ("Một khoảnh khắc đáng chú ý", "Đừng bỏ lỡ pha bóng này!"),
              ("Khoảnh khắc đáng chú ý không thể bỏ lỡ", "Hãy cùng xem lại nhé!")),
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


def _pick(part: str, facts: ClipFacts, clip: int | None, count: int) -> int:
    # SHA-256, never hash(): the choice must not change with PYTHONHASHSEED.
    key = json.dumps([part, facts.event, facts.minute, facts.home, facts.away, clip], ensure_ascii=False)
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") % count


def generate_meta(facts: ClipFacts, backend: str = "template", clip: int | None = None) -> ClipMeta:
    if backend != "template":
        raise ValueError(f"unknown backend: {backend}")
    if clip is not None and (isinstance(clip, bool) or not isinstance(clip, int) or clip < 0):
        raise ValueError("clip must be a non-negative integer")

    leads = TITLE_LEADS[facts.event]
    lead = leads[_pick("title", facts, clip, len(leads))]
    teams = (
        f"{facts.home} vs {facts.away}" if facts.home and facts.away
        else facts.home or facts.away
    )
    minute = f"phút {facts.minute}" if facts.minute is not None else None
    candidates = []
    if teams and minute:
        candidates.append(f"{lead}: {teams}, {minute}")
    if teams:
        candidates.append(f"{lead}: {teams}")
    if minute:
        candidates.append(f"{lead}, {minute}")
    candidates.append(f"{lead} trong trận đấu")
    title = next(candidate for candidate in candidates if 10 <= len(candidate) <= 80)

    if facts.home and facts.away:
        match_text = f" trong trận {facts.home} gặp {facts.away}"
    elif facts.home or facts.away:
        match_text = f" trong trận đấu của {facts.home or facts.away}"
    else:
        match_text = " trong trận đấu"
    styles = CAPTION_STYLES[facts.event]
    opener, closer = styles[_pick("caption", facts, clip, len(styles))]
    caption = opener + match_text
    if facts.minute is not None:
        caption += f" ở phút {facts.minute}"
    if facts.competition:
        caption += f" tại {facts.competition}"
    caption += "."
    if facts.score:
        caption += f" Tỉ số: {facts.score}."
    caption += f" {closer}"

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
