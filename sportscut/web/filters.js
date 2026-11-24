(function (root) {
  const EVENT_TYPES = Object.freeze([
    "goal", "save", "red_card", "controversy", "other",
  ])
  const EVENT_LABELS = Object.freeze({
    goal: "Bàn thắng",
    save: "Cứu thua",
    red_card: "Thẻ đỏ",
    controversy: "Tranh cãi",
    other: "Khác",
  })
  const EVENT_PRIORITY = Object.freeze({
    goal: 5,
    red_card: 4,
    controversy: 3,
    save: 2,
    other: 1,
  })

  function preset(events, top) {
    return Object.freeze({ events: Object.freeze(events), top })
  }

  const PRESETS = Object.freeze({
    all: preset([], null),
    goals: preset(["goal"], null),
    top5: preset([], 5),
  })

  function normalizeEvent(event) {
    return EVENT_TYPES.includes(event) ? event : "other"
  }

  function eventLabel(event) {
    return EVENT_LABELS[normalizeEvent(event)]
  }

  function toggleEvent(selection, event) {
    const selected = new Set(selection.events)
    if (selected.has(event)) selected.delete(event)
    else selected.add(event)
    return {
      events: EVENT_TYPES.filter((eventType) => selected.has(eventType)),
      top: selection.top,
    }
  }

  function sameSelection(a, b) {
    if (a.top !== b.top) return false
    const left = new Set(a.events)
    const right = new Set(b.events)
    return left.size === right.size
      && Array.from(left).every((event) => right.has(event))
  }

  function selectIndices(segments, selection) {
    const active = selection ?? PRESETS.all
    const events = active.events
    const top = active.top
    if (top !== null && top !== undefined
        && (!Number.isInteger(top) || top < 1)) {
      throw new RangeError("top must be a positive integer")
    }

    const candidates = []
    segments.forEach((segment, index) => {
      const event = normalizeEvent(segment.event)
      if (events.length && !events.includes(event)) return
      const priority = EVENT_PRIORITY[event]
      const score = typeof segment.score === "number"
        && Number.isFinite(segment.score) ? segment.score : 0
      const start = typeof segment.start === "number"
        && Number.isFinite(segment.start) ? segment.start : Infinity
      const end = typeof segment.end === "number"
        && Number.isFinite(segment.end) ? segment.end : Infinity
      candidates.push({ index, rank: -(score * priority), priority, start, end })
    })
    if (top === null || top === undefined) {
      return candidates.map(({ index }) => index)
    }
    candidates.sort((a, b) => (
      a.rank - b.rank
      || b.priority - a.priority
      || a.start - b.start
      || a.end - b.end
      || a.index - b.index
    ))
    return candidates.slice(0, top)
      .map(({ index }) => index)
      .sort((a, b) => a - b)
  }

  const api = {
    EVENT_TYPES,
    EVENT_LABELS,
    EVENT_PRIORITY,
    PRESETS,
    normalizeEvent,
    eventLabel,
    toggleEvent,
    sameSelection,
    selectIndices,
  }
  root.SportsCutFilter = api
  if (typeof module === "object" && module.exports) module.exports = api
})(globalThis)
