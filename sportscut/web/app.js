const form = document.querySelector("#highlights-form")
const fileInput = document.querySelector("#file")
const urlInput = document.querySelector("#url")
const submit = document.querySelector("#submit")
const busy = document.querySelector("#busy")
const error = document.querySelector("#error")

function showError(message) {
  error.textContent = message
  error.hidden = false
}

form.addEventListener("submit", async (event) => {
  event.preventDefault()
  error.textContent = ""
  error.hidden = true

  const file = fileInput.files[0]
  const url = urlInput.value.trim()
  if ((file && url) || (!file && !url)) {
    showError("Hãy chọn một tệp video hoặc nhập một liên kết YouTube.")
    return
  }

  const formData = new FormData()
  if (file) {
    formData.append("file", file)
  } else {
    formData.append("url", url)
  }
  const top = document.querySelector("#top").value.trim()
  const min_len = document.querySelector("#min_len").value.trim()
  const max_len = document.querySelector("#max_len").value.trim()
  const events = Array.from(
    document.querySelectorAll('input[name="events"]:checked'),
    (input) => input.value,
  ).join(",")
  if (top) formData.append("top", top)
  if (min_len) formData.append("min_len", min_len)
  if (max_len) formData.append("max_len", max_len)
  if (events) formData.append("events", events)

  submit.disabled = true
  form.setAttribute("aria-busy", "true")
  busy.hidden = false
  try {
    const response = await fetch("/highlights", {
      method: "POST",
      body: formData,
    })
    const data = await response.json()
    if (!response.ok) {
      let message = "Không thể xử lý video."
      const detail = data?.detail
      if (typeof detail === "string") {
        message = detail
      } else if (Array.isArray(detail)) {
        const messages = detail.map((item) => item.msg).filter(Boolean)
        if (messages.length) message = messages.join("; ")
      }
      showError(`Lỗi ${response.status}: ${message}`)
      return
    }
    if (typeof data.job_id !== "string" || !data.job_id) {
      throw new Error("invalid response")
    }
    window.location.assign(`/jobs/${encodeURIComponent(data.job_id)}`)
  } catch (_exception) {
    showError("Không thể kết nối hoặc phản hồi từ máy chủ không hợp lệ.")
  } finally {
    submit.disabled = false
    form.removeAttribute("aria-busy")
    busy.hidden = true
  }
})

const playerForm = document.querySelector("#player-form")
const playerSubmit = document.querySelector("#player-submit")
const playerBusy = document.querySelector("#player-busy")
const playerError = document.querySelector("#player-error")
const playerResult = document.querySelector("#player-result")
const playerReel = document.querySelector("#player-reel")
const playerEmpty = document.querySelector("#player-empty")
const playerTouches = document.querySelector("#player-touches")
const playerSource = document.querySelector("#player-source")

function showPlayerError(message) {
  playerError.textContent = message
  playerError.hidden = false
}

playerForm.addEventListener("submit", async (event) => {
  event.preventDefault()
  playerError.textContent = ""
  playerError.hidden = true
  playerResult.hidden = true
  const playerFile = document.querySelector("#player-file").files[0]
  const playerJobId = document.querySelector("#player-job-id").value.trim()
  if ((playerFile && playerJobId) || (!playerFile && !playerJobId)) {
    showPlayerError("Hãy chọn một tệp video hoặc nhập mã công việc.")
    return
  }
  const team = document.querySelector("#player-team-name").value.trim()
    || document.querySelector("#player-team-color").value
  const number = document.querySelector("#player-number").value.trim()
  const playerData = new FormData()
  if (playerFile) playerData.append("file", playerFile)
  else playerData.append("job_id", playerJobId)
  playerData.append("team", team)
  playerData.append("number", number)

  playerSubmit.disabled = true
  playerForm.setAttribute("aria-busy", "true")
  playerBusy.hidden = false
  try {
    const response = await fetch("/players", { method: "POST", body: playerData })
    const data = await response.json()
    if (!response.ok) {
      let message = data?.detail
      if (Array.isArray(message)) message = message.map((item) => item.msg).filter(Boolean).join("; ")
      if (typeof message !== "string" || !message) message = "Không thể tạo video cầu thủ."
      showPlayerError(`Lỗi ${response.status}: ${message}`)
      return
    }
    playerSource.src = `/highlights/${encodeURIComponent(data.job_id)}/source`
    if (data.reel_url) {
      playerReel.src = data.reel_url
      playerReel.hidden = false
      playerEmpty.hidden = true
    } else {
      playerReel.removeAttribute("src")
      playerReel.hidden = true
      playerEmpty.hidden = false
    }
    playerTouches.replaceChildren()
    for (const touch of data.touches) {
      const item = document.createElement("li")
      const seek = document.createElement("button")
      seek.type = "button"
      seek.textContent = `${touch.t.toFixed(1)} s`
      seek.addEventListener("click", () => {
        playerSource.currentTime = touch.t
      })
      item.append(seek)
      playerTouches.append(item)
    }
    playerResult.hidden = false
  } catch (_exception) {
    showPlayerError("Không thể kết nối hoặc phản hồi từ máy chủ không hợp lệ.")
  } finally {
    playerSubmit.disabled = false
    playerForm.removeAttribute("aria-busy")
    playerBusy.hidden = true
  }
})
