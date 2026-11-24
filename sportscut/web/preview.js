const T = globalThis.SportsCutTime
const F = globalThis.SportsCutFilter
const player = document.querySelector("#player")
const currentTime = document.querySelector("#current-time")
const segmentList = document.querySelector("#segments")
const rowTemplate = document.querySelector("#segment-row")
const addSegment = document.querySelector("#add-segment")
const save = document.querySelector("#save")
const status = document.querySelector("#status")
const error = document.querySelector("#error")
const jobTitle = document.querySelector("#job-title")
const filterAll = document.querySelector("#filter-all")
const eventChips = Array.from(document.querySelectorAll(".chip"))
const presetGoals = document.querySelector("#preset-goals")
const presetTop5 = document.querySelector("#preset-top5")
const filterCount = document.querySelector("#filter-count")
const pathMatch = location.pathname.match(/^\/jobs\/([^/]+)\/?$/)
save.disabled = true
addSegment.disabled = true

let jobId = null
let duration = 0
let segments = []
let playUntil = null
let selection = F.PRESETS.all

function showError(message) {
  error.textContent = message
  error.hidden = false
}

function responseMessage(data, fallback) {
  const detail = data?.detail
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => item.msg).filter(Boolean)
    if (messages.length) return messages.join("; ")
  }
  return fallback
}

function acceptResponse(data) {
  if (typeof data?.duration !== "number" || !Number.isFinite(data.duration)
      || !Array.isArray(data.highlights)) throw new Error("invalid response")
  duration = data.duration
  segments = data.highlights.map(
    ({ start, end, score, reason, event, clip_url }) => ({
      start, end, score, reason, event: F.normalizeEvent(event), clip_url,
    }),
  )
}

function editTime(input, seg, key) {
  input.addEventListener("change", () => {
    const value = T.parseTime(input.value)
    seg[key] = value === null ? NaN : value
    if (value === null) input.setAttribute("aria-invalid", "true")
    else input.removeAttribute("aria-invalid")
  })
}

function showTime(input, value) {
  if (Number.isFinite(value)) input.value = T.formatTime(value)
  else input.setAttribute("aria-invalid", "true")
}

function render() {
  const shown = new Set(F.selectIndices(segments, selection))
  segmentList.replaceChildren()
  eventChips.forEach((chip) => {
    chip.setAttribute(
      "aria-pressed", String(selection.events.includes(chip.dataset.event)),
    )
  })
  filterAll.setAttribute(
    "aria-pressed", String(F.sameSelection(selection, F.PRESETS.all)),
  )
  presetGoals.setAttribute(
    "aria-pressed", String(F.sameSelection(selection, F.PRESETS.goals)),
  )
  presetTop5.setAttribute(
    "aria-pressed", String(F.sameSelection(selection, F.PRESETS.top5)),
  )
  if (shown.size > 0) {
    filterCount.textContent = `Đang hiện ${shown.size}/${segments.length} đoạn`
  } else if (segments.length > 0) {
    filterCount.textContent = "Không có đoạn nào khớp bộ lọc."
  } else {
    filterCount.textContent = ""
  }
  segments.forEach((seg, index) => {
    if (!shown.has(index)) return
    const row = rowTemplate.content.firstElementChild.cloneNode(true)
    const play = row.querySelector(".play")
    const eventBadge = row.querySelector(".event-badge")
    const start = row.querySelector(".start")
    const end = row.querySelector(".end")
    play.textContent = `▶ Đoạn ${index + 1}`
    eventBadge.textContent = F.eventLabel(seg.event)
    eventBadge.dataset.event = seg.event
    showTime(start, seg.start)
    showTime(end, seg.end)
    editTime(start, seg, "start")
    editTime(end, seg, "end")

    play.addEventListener("click", () => {
      if (!Number.isFinite(seg.start) || !Number.isFinite(seg.end)) return
      player.currentTime = seg.start
      playUntil = seg.end
      player.play()
    })
    for (const [selector, key, delta] of [
      [".start-minus", "start", -0.5], [".start-plus", "start", 0.5],
      [".end-minus", "end", -0.5], [".end-plus", "end", 0.5],
    ]) {
      row.querySelector(selector).addEventListener("click", () => {
        if (!Number.isFinite(seg[key])) return
        seg[key] = T.clampTime(seg[key] + delta, duration)
        render()
      })
    }
    row.querySelector(".set-start").addEventListener("click", () => {
      seg.start = T.clampTime(player.currentTime, duration)
      render()
    })
    row.querySelector(".set-end").addEventListener("click", () => {
      seg.end = T.clampTime(player.currentTime, duration)
      render()
    })
    row.querySelector(".delete").addEventListener("click", () => {
      segments.splice(index, 1)
      render()
    })
    if (seg.clip_url) {
      const clip = row.querySelector(".clip")
      const clipPlayer = row.querySelector(".clip-player")
      clip.href = seg.clip_url
      clipPlayer.src = seg.clip_url
      clip.hidden = false
      clipPlayer.hidden = false
    }
    segmentList.append(row)
  })
}

player.addEventListener("timeupdate", () => {
  currentTime.textContent = T.formatTime(player.currentTime)
  if (playUntil !== null && player.currentTime >= playUntil) {
    player.pause()
    playUntil = null
  }
})

eventChips.forEach((chip) => {
  chip.addEventListener("click", () => {
    selection = F.toggleEvent(selection, chip.dataset.event)
    render()
  })
})

filterAll.addEventListener("click", () => {
  selection = F.PRESETS.all
  render()
})

presetGoals.addEventListener("click", () => {
  selection = F.PRESETS.goals
  render()
})

presetTop5.addEventListener("click", () => {
  selection = F.PRESETS.top5
  render()
})

addSegment.addEventListener("click", () => {
  segments.push({
    ...T.newSegmentAt(player.currentTime, duration),
    event: "other",
    score: null,
    clip_url: null,
  })
  selection = F.PRESETS.all
  render()
})

save.addEventListener("click", async () => {
  error.textContent = ""
  error.hidden = true
  const problems = T.validateSegments(segments, duration)
  if (problems.length) {
    showError(problems.join(" "))
    return
  }
  save.disabled = true
  status.textContent = "Đang cắt lại clip…"
  status.hidden = false
  try {
    const response = await fetch(`/highlights/${encodeURIComponent(jobId)}/segments`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        segments: segments.map(
          ({ start, end, reason, event }) => ({ start, end, reason, event }),
        ),
      }),
    })
    const data = await response.json()
    if (!response.ok) {
      const message = responseMessage(data, "Không thể lưu.")
      showError(`Lỗi ${response.status}: ${message}`)
      status.hidden = true
      return
    }
    acceptResponse(data)
    render()
    status.textContent = `Đã lưu ${segments.length} đoạn.`
  } catch (_exception) {
    showError("Không thể kết nối hoặc phản hồi từ máy chủ không hợp lệ.")
    status.hidden = true
  } finally {
    save.disabled = false
  }
})

async function loadJob() {
  try {
    const response = await fetch(`/highlights/${encodeURIComponent(jobId)}`)
    const data = await response.json()
    if (!response.ok) {
      const message = responseMessage(data, "Không thể tải job.")
      showError(`Lỗi ${response.status}: ${message}`)
      return
    }
    acceptResponse(data)
    save.disabled = false
    addSegment.disabled = false
    jobTitle.textContent = data.source_name ?? data.source_url
    player.src = `/highlights/${encodeURIComponent(jobId)}/source`
    render()
  } catch (_exception) {
    showError("Không thể kết nối hoặc phản hồi từ máy chủ không hợp lệ.")
  }
}

try {
  jobId = pathMatch ? decodeURIComponent(pathMatch[1]) : null
} catch (_exception) {
  jobId = null
}
if (jobId) loadJob()
else showError("Không tìm thấy job.")
