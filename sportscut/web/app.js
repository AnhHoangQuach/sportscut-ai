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
