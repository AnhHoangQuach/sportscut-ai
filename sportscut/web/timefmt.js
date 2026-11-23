(function (root) {
  const MAX_SEGMENTS = 50
  const NEW_SEGMENT_SECONDS = 10

  function roundMs(value) {
    return Math.round(value * 1000) / 1000
  }

  function formatTime(seconds) {
    if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) {
      throw new RangeError("seconds must be finite and non-negative")
    }
    const tenths = Math.round(seconds * 10)
    const minutes = Math.floor(tenths / 600)
    const remaining = (tenths % 600) / 10
    return `${String(minutes).padStart(2, "0")}:${remaining.toFixed(1).padStart(4, "0")}`
  }

  function parseTime(text) {
    if (typeof text !== "string") return null
    const match = text.trim().match(/^(?:(\d+):)?(\d+(?:\.\d+)?)$/)
    if (!match) return null
    const minutes = match[1] === undefined ? 0 : Number(match[1])
    const seconds = Number(match[2])
    if (match[1] !== undefined && seconds >= 60) return null
    return roundMs(minutes * 60 + seconds)
  }

  function clampTime(seconds, duration) {
    return roundMs(Math.min(Math.max(seconds, 0), duration))
  }

  function newSegmentAt(time, duration) {
    let start = clampTime(time, duration)
    const end = clampTime(start + NEW_SEGMENT_SECONDS, duration)
    if (end <= start) start = clampTime(duration - NEW_SEGMENT_SECONDS, duration)
    return { start, end, reason: "manual" }
  }

  function validateSegments(segments, duration) {
    const problems = []
    if (segments.length > MAX_SEGMENTS) problems.push("Tối đa 50 đoạn.")
    segments.forEach(({ start, end }, index) => {
      const validNumbers = typeof start === "number" && Number.isFinite(start)
        && typeof end === "number" && Number.isFinite(end)
      if (!validNumbers) {
        problems.push(`Đoạn ${index + 1}: thời gian không hợp lệ.`)
      } else if (!(0 <= start && start < end && end <= duration)) {
        problems.push(`Đoạn ${index + 1}: cần 0 ≤ đầu < cuối ≤ ${formatTime(duration)}.`)
      }
    })
    return problems
  }

  const api = {
    MAX_SEGMENTS, NEW_SEGMENT_SECONDS, formatTime, parseTime,
    clampTime, newSegmentAt, validateSegments,
  }
  root.SportsCutTime = api
  if (typeof module === "object" && module.exports) module.exports = api
})(globalThis)
