import json
import logging
import os
import re
import unicodedata
from functools import partial

from sportscut.commentary import meta
from sportscut.commentary.eval_meta import validate_meta
from sportscut.commentary.meta import EVENT_LABELS, ClipMeta

DEFAULT_MODEL = "claude-haiku-5-5"
MODEL_ENV = "SPORTSCUT_LLM_MODEL"
KEY_ENV = "ANTHROPIC_API_KEY"
MAX_TOKENS = 4096
TIMEOUT_SEC = 60.0
SYSTEM_PROMPT = """You write Vietnamese social-media metadata for football highlight clips.
The input JSON has "clips", each with id, event, label and optional minute, home, away, competition and score.
Reply with JSON only (no prose, no code fence): {"clips": [{"id": ..., "title": ..., "caption": ..., \
"hashtags": [...]}]}, one object per input clip, with the same id.
Rules for every clip:
- Write Vietnamese with diacritics.
- The title is 10-80 characters and the caption 1-300 characters.
- Give 3-8 unique hashtags, each matching #[A-Za-z0-9_]+ (no diacritics, no spaces).
- The title or caption must contain the label verbatim, every given name (home, away, competition) verbatim, \
"phút <minute>" when a minute is given, and the score verbatim when it is given.
- Use no number that is not in that clip's facts.
- Name no player, team, coach, referee or competition that is not in the facts.
- Never say who scored.
- Capitalise only the first word of a sentence and the given names."""
logger = logging.getLogger(__name__)
_nfc = partial(unicodedata.normalize, "NFC")


def model_name() -> str:
    return os.environ.get(MODEL_ENV, "").strip() or DEFAULT_MODEL


def build_request(facts_list) -> dict:
    clips = [{"id": i, "label": EVENT_LABELS[f.event], **{k: v for k, v in vars(f).items() if v is not None}}
             for i, f in enumerate(facts_list)]
    content = json.dumps({"clips": clips}, ensure_ascii=False)
    return {"model": model_name(), "max_tokens": MAX_TOKENS, "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": content}]}


def parse_response(text: str, count: int) -> list[ClipMeta | None] | None:
    text = text.strip()
    if fenced := re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL):
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("clips"), list):
        return None
    result = [None] * count
    for item in (item for item in data["clips"] if isinstance(item, dict)):
        clip_id, title, caption, tags = (item.get(key) for key in ("id", "title", "caption", "hashtags"))
        if (
            isinstance(clip_id, int) and not isinstance(clip_id, bool) and 0 <= clip_id < count
            and result[clip_id] is None and isinstance(title, str) and isinstance(caption, str)
            and isinstance(tags, list) and all(isinstance(tag, str) for tag in tags)
        ):
            result[clip_id] = ClipMeta(_nfc(title), _nfc(caption), tuple(_nfc(tag) for tag in tags))
    return result


def generate_metas_llm(facts_list, client=None) -> list[ClipMeta]:
    count = len(facts_list)
    if count == 0:
        return []
    def all_fallback(message: str, *args) -> list[ClipMeta]:
        logger.warning(message, *args, count)
        return [meta.generate_meta(facts) for facts in facts_list]

    if client is None:
        key = os.environ.get(KEY_ENV, "").strip()
        if not key:
            return all_fallback("ANTHROPIC_API_KEY is not set; template fallback for all %d clips")
        try:
            import anthropic
        except ImportError:
            return all_fallback("the llm backend needs the [llm] extra (pip install 'sportscut[llm]'); "
                                "template fallback for all %d clips")
    try:
        if client is None:
            client = anthropic.Anthropic(api_key=key, timeout=TIMEOUT_SEC)
        response = client.messages.create(**build_request(facts_list))
        text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    except Exception as exc:  # never log str(exc): it may echo request details
        return all_fallback("LLM request failed (%s); template fallback for all %d clips", type(exc).__name__)
    parsed = parse_response(text, count)
    if parsed is None:
        return all_fallback("LLM response is not valid JSON; template fallback for all %d clips")

    result = []
    for index, (facts, output) in enumerate(zip(facts_list, parsed)):
        if output is None:
            logger.warning("clip %d: missing or malformed in LLM response; template fallback", index)
        elif problems := validate_meta(facts, output):
            logger.warning("clip %d: rejected LLM metadata (%s); template fallback", index, "; ".join(problems))
        else:
            result.append(output)
            continue
        result.append(meta.generate_meta(facts))
    return result
