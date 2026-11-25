# Plan T-041: Add the 'Theo dõi cầu thủ' section to the web page

Design: `docs/superpowers/specs/2026-11-24-t-041-add-the-theo-d-i-c-design.md`.

## Implementation plan

# T-041 (T-034B): Add the 'Theo dõi cầu thủ' section to the web page

Request R-006. This is the web half of T-034. It depends on T-040 (T-034A), which is merged on main as 0a9ca1c and provides `POST /players` -> `{job_id, touches, reel_url}`, `GET /players/{job_id}/reel/{name}` and `GET /highlights/{job_id}/source`.

## Goal
Users pick a player on the upload page: either a video file or an existing job id, plus a shirt colour (a picker, or a typed name that overrides it) and a shirt number. The page calls `POST /players`, then shows the player reel (or 'Không tìm thấy pha chạm bóng nào.'), a list of touch buttons and the source video. Clicking a touch moves the source video to that time. There is no backend change and no effect on the eval.

## Grounding (main @ 0a9ca1c)
- `sportscut/web/index.html` (55 lines) has one `<form id="highlights-form">` inside `<main>`, ending at line 51 with `</form>`. Its only href/src values are `/static/style.css` and `/static/app.js`.
- `sportscut/web/app.js` (75 lines) holds the /highlights submit handler. Its top-level names are `form, fileInput, urlInput, submit, busy, error, showError`. The new code must not reuse them.
- `sportscut/web/style.css` has `#busy {` (line 64) and `#error {` (line 68). It has no `video` rule. `#player` is the preview-page player, which is a different element.
- Guard tests that must stay green **unchanged**:
  - tests/test_web.py
  - tests/test_t008_acceptance.py: the href/src list in the HTML is exactly `["/static/style.css","/static/app.js"]`; no `https?://` in the HTML, app.js or style.css; no `content-type` (case-insensitive) in app.js; the *first* `fetch(` and the *first* `finally` in app.js are the /highlights ones; `.disabled = true`, `setAttribute("aria-busy", "true")` and `busy.hidden = false` occur before the first fetch.
  - tests/test_web_filters.py: the `(?:href|src)="..."` regex finds only the two assets.
  - tests/test_t016_acceptance.py
- `PlayerQuery` accepts a team name or `#rrggbb` (sportscut/player.py `normalize_team`), so the colour picker value is a valid team. Number must be 1..99.
- Manifest touches are dicts with a numeric `t` (seconds, rounded to 3 decimals).

## Files
- Modify `sportscut/web/index.html`: insert the block below right after the `</form>` of `#highlights-form` and before `</main>`. About 27 lines.
- Modify `sportscut/web/app.js`: append the code below at the END of the file. About 70 lines.
- Modify `sportscut/web/style.css`: change two selectors and append two rules. About 12 changed lines.
- Modify `docs/superpowers/specs/2026-11-23-t-008-serve-a-web-upload-page-for-design.md`: append the note.
- Create `tests/test_player_page.py` (Developer, <= 80 lines).
- Create `tests/test_t034b_acceptance.py` (Tester, <= 130 lines).
- docs/superpowers spec, plan and INDEX row (orchestrator).

## Exact HTML block (index.html, after `</form>`, indented to match)
```html
    <section id="player-section" aria-labelledby="player-title">
      <h2 id="player-title">Theo dõi cầu thủ</h2>
      <p>Chọn một tệp video hoặc nhập mã công việc đã có, rồi chọn màu áo và số áo.</p>
      <form id="player-form">
        <label for="player-file">Tệp video</label>
        <input id="player-file" name="file" type="file" accept="video/*">
        <label for="player-job-id">Mã công việc có sẵn</label>
        <input id="player-job-id" name="job_id" type="text">
        <label for="player-team-color">Màu áo</label>
        <input id="player-team-color" name="team_color" type="color" value="#ff0000">
        <label for="player-team-name">Hoặc tên màu áo (ví dụ: red, blue)</label>
        <input id="player-team-name" name="team_name" type="text">
        <label for="player-number">Số áo</label>
        <input id="player-number" name="number" type="number" min="1" max="99" step="1">
        <button id="player-submit" type="submit">Tạo video cầu thủ</button>
        <p id="player-busy" role="status" hidden>Đang tìm các pha chạm bóng, vui lòng chờ…</p>
        <p id="player-error" role="alert" aria-live="assertive" hidden></p>
      </form>
      <div id="player-result" hidden>
        <h3>Video tổng hợp</h3>
        <video id="player-reel" controls></video>
        <p id="player-empty" hidden>Không tìm thấy pha chạm bóng nào.</p>
        <h3>Các pha chạm bóng</h3>
        <ol id="player-touches"></ol>
        <video id="player-source" controls></video>
      </div>
    </section>
```
The HTML has no `src`/`href` attributes; both videos get `src` from JS.

## JS to append to the end of app.js
The names and strings are fixed because tests match them. Keep the formatting close to this.
```js
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
```

## CSS (style.css)
- `#busy {` becomes `#busy,\n#player-busy {`. `#error {` becomes `#error,\n#player-error {`. The rule bodies are unchanged.
- Append at the end of the file: `video {\n  width: 100%;\n}` and `#player-section {\n  margin-top: 2rem;\n}`.

## T-008 spec note (append at end of the file)
```
## Updated by T-034

- T-034 (built as T-041 / T-034B) adds a `Theo dõi cầu thủ` section (`#player-section`, `#player-form`) after `#highlights-form`, with a player-reel video, a touch list that seeks the source video, and its JS appended to the end of app.js. The `#highlights-form` behaviour is unchanged; the earlier 'no preview player' exclusion applies only to that original form. The page still references only `/static/style.css` and `/static/app.js`.
```

## Steps (test-first)
1. Write `tests/test_player_page.py` (<= 80 lines, `pytest.importorskip("fastapi")`, TestClient(app)). It contains:
   - `test_player_section_markup`: uses an `html.parser` (or regex) check on GET / for the AC1 ids, names, types, attributes and labels, and checks that `<section id="player-section"` comes after `<form id="highlights-form">`.
   - `test_player_js_contract`: checks the AC3 markers.
   - `test_player_css_and_spec_note`: checks AC6 and AC7.
   Run `python -m pytest -q tests/test_player_page.py`; it must FAIL on missing markup and markers.
2. Add the HTML block, then rerun the step-1 tests: the markup test passes.
3. Append the JS, then rerun: the JS test passes.
4. Make the CSS edits and append the T-008 spec note, then rerun: all three pass.
5. Run the guard tests: `python -m pytest -q tests/test_web.py tests/test_t008_acceptance.py tests/test_web_filters.py tests/test_t016_acceptance.py` gives 0 failed.
6. Run the full suite: `python -m pytest -q` gives 0 failed, 0 errors.
7. Run the size check: `git diff --numstat main...HEAD -- . ':(exclude)docs/superpowers'` sums to < 380.
8. Tester: write `tests/test_t034b_acceptance.py` (<= 130 lines) from the ACs, including the node behaviour tests AC4/AC5. Confirm they fail on main (for example, on a stash of the web changes), then pass.

## Verify
- `python -m pytest -q`: 0 failed, 0 errors (quote the summary line).
- `git diff --numstat main...HEAD -- . ':(exclude)docs/superpowers' | awk '{s+=$1+$2} END {print s}'` prints a number < 380.
- No eval command is needed (accuracy is untouched).

## Assumptions
- The team text field overrides the colour picker when it is non-blank. Otherwise the picker's `#rrggbb` is sent; the API normalises and validates it.
- The client only checks file XOR job id. The number and team are validated by the API, and its 422 detail is shown as `Lỗi 422: ...`.
- Touch buttons show `t` with one decimal plus ' s'. There is no mm:ss formatting (timefmt.js is not loaded on this page).
- Clicking a touch only sets `currentTime`. It does not auto-play, which avoids unhandled play() promise rejections.
- A new submit hides the previous result until the new response arrives.
- The page needs no README change. Docs for the player feature can come later.

## Test plan

- Developer, tests/test_player_page.py (<= 80 lines, pytest.importorskip('fastapi')): test_player_section_markup covers AC1 via html.parser on TestClient(app).get('/'), including the section coming after #highlights-form and no src on either video.
- Developer, tests/test_player_page.py: test_player_js_contract covers the AC3 markers and ordering, and checks there is no innerHTML, content-type or https?:// in app.js (AC2 part).
- Developer, tests/test_player_page.py: test_player_css_and_spec_note covers AC6 (whitespace-normalised CSS) and AC7.
- Tester, tests/test_t034b_acceptance.py (<= 130 lines), written from the ACs and not from the Developer tests: test_ac1_ac2_markup_and_assets parses GET / and checks the AC1 structure and the exact two-asset reference list.
- Tester: test_ac4_ac5_player_flow_in_node. It skips if shutil.which('node') is None. It writes a harness .js into tmp_path that defines a fake `document` (querySelector returns a cached fake element per selector with hidden/value/files/src/textContent/children, addEventListener storing listeners, setAttribute/removeAttribute, append/replaceChildren; querySelectorAll returns []; createElement returns a fresh fake element) and a scripted `fetch`. It loads sportscut/web/app.js with vm.runInThisContext, calls the stored 'submit' listener with {preventDefault(){}}, awaits it, and prints a JSON result per scenario (success with colour fallback, team-name override, reel null, 422 string, 422 array, both/neither, fetch rejection). The Python side asserts the AC4/AC5 values. Node >= 18 provides FormData.
- Tester: test_ac9_ac10_scope_and_size runs the git diff --exit-code and numstat commands (skip if git is missing) and asserts the file set and line totals.
- Tester: show that the acceptance tests fail without the change (for example, git stash the sportscut/web edits and run the file: AC1/AC3/AC4 fail), then pass with it.
- Regression: python -m pytest -q tests/test_web.py tests/test_t008_acceptance.py tests/test_web_filters.py tests/test_t016_acceptance.py, then the full python -m pytest -q, both 0 failed.
