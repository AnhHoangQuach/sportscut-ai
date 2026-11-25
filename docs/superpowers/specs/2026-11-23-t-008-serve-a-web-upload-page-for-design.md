# T-008: Serve a web upload page for video files and YouTube links

Request R-002. Plan: `docs/superpowers/plans/2026-11-23-t-008-serve-a-web-upload-page-for.md`.

## Product Owner request

API + web upload: POST /highlights nhận video hoặc link YouTube, trả về danh sách đoạn highlight, có trang xem trước và chỉnh mốc cắt bằng tay.

## Goal

Add `sportscut/web/` as package data (index.html, app.js, style.css, no build step, no CDN) and serve it from the FastAPI app at `GET /` plus `/static/...`. The page has a file picker and a YouTube URL field (one or the other), optional top/min_len/max_len inputs, a busy indicator while the synchronous request runs, readable display of 400/413/422 errors, and on success navigates to `/jobs/{job_id}`. Tests: TestClient `GET /` returns 200 text/html containing the form with `file` and `url` inputs; static assets are served with correct content types; the packaged files are included by `pip install` (check via importlib.resources). Assumptions: plain HTML/vanilla JS, Vietnamese UI labels, no auth (local tool bound to 127.0.0.1 as in R-001).

## Acceptance criteria

- AC1: `GET /` through FastAPI TestClient returns 200 with a `Content-Type` beginning `text/html`; the response is a complete HTML document containing `form#highlights-form`, a `type=file` input named `file`, a `type=url` input named `url`, and optional number inputs named `top`, `min_len`, and `max_len`.
- AC2: The HTML has Vietnamese labels associated with every input, states that a file or YouTube URL must be supplied exclusively, references only `/static/style.css` and `/static/app.js`, and contains initially hidden `#busy[role=status]` and `#error[role=alert]` regions.
- AC3: `GET /static/app.js` and `GET /static/style.css` return 200. The JavaScript response content type is JavaScript (`text/javascript` or `application/javascript`, with an optional charset), and the stylesheet response content type begins `text/css`. Requests for a nonexistent `/static/...` file return 404.
- AC4: The frontend submit handler rejects both-source and no-source submissions before `fetch`, showing `Hãy chọn một tệp video hoặc nhập một liên kết YouTube.`; it creates `FormData` manually and sends exactly one of `file` or trimmed `url`.
- AC5: Blank `top`, `min_len`, and `max_len` fields are not appended to `FormData`; nonblank values are appended under those exact names. The request is `fetch('/highlights', {method: 'POST', body: formData})` without manually setting `Content-Type`.
- AC6: While the request is pending, the submit button is disabled, the form has `aria-busy=true`, and the Vietnamese busy indicator is visible. A `finally` path restores the button, removes the busy attribute, and hides the indicator.
- AC7: Non-OK JSON responses display `Lỗi <status>: <message>` in the alert. String `detail` values are displayed readably, FastAPI validation arrays are reduced to their `msg` strings rather than raw JSON, and fallback/network/invalid-response errors use a readable Vietnamese message. Thus API responses with status 400, 413, and 422 are supported.
- AC8: An OK JSON response containing a non-empty string `job_id` invokes `window.location.assign('/jobs/' + encodeURIComponent(job_id))`. This task does not require `GET /jobs/{job_id}` to exist.
- AC9: `pyproject.toml` declares the three `sportscut/web` file patterns as package data. A wheel built with `python -m pip wheel --no-deps` and installed into an isolated target contains non-empty UTF-8 `index.html`, `app.js`, and `style.css`, each discoverable with `importlib.resources.files('sportscut').joinpath('web', name)`.
- AC10: The page and assets make no external HTTP(S) references and require no CDN, JavaScript framework, Node package, build command, template engine, or added runtime dependency.
- AC11: Existing `POST /highlights`, clip download, CLI, upload, and YouTube tests remain unchanged in behavior; `.venv/bin/python -m pytest -q` reports 0 failures.
- AC12: `.venv/bin/python -m pytest -q tests/test_web.py tests/test_t008_acceptance.py -rs` reports 0 failed and 0 skipped. No code under `agent-office/`, and no detection, pipeline, export, media, source-download, CLI, or existing test file is changed.

## Out of scope

- Implementing `GET /jobs/{job_id}`, a preview player, displaying detected segments, or manually editing start/end marks; those require later R-002 tasks.
- Re-cut/edit API endpoints or changes to the POST `/highlights` response.
- Asynchronous jobs, progress polling, cancellation, upload progress, WebSockets, or background workers.
- Authentication, authorization, CORS, HTTPS, deployment, or changing the localhost default.
- Drag-and-drop upload, multiple files, YouTube metadata preview, client-side video validation, or client-side size limits.
- React, Vue, Svelte, TypeScript, npm, bundlers, CDN assets, remote fonts, or template engines.
- Changes to detection, evaluation, pipeline, clip export, source downloading, job layout, retention, or cleanup.

## Decisions

- T-008 serves one plain HTML/vanilla-JS page from the existing FastAPI process; there is no frontend build step or external asset dependency.
- Static files live as data under `sportscut/web/` without `__init__.py` and are included explicitly using setuptools package-data patterns.
- FastAPI resolves the resource directory with `importlib.resources.files('sportscut')`, serves `/` with `FileResponse`, and mounts the same directory at `/static`.
- The browser constructs FormData manually because native `FormData(form)` would include blank optional numeric fields and cause 422 instead of allowing API defaults.
- The page performs a client-side exactly-one-source check, while the API remains authoritative and unchanged.
- The synchronous POST keeps the page busy until completion; this task adds no progress reporting.
- API errors retain their server-provided string detail, prefixed with the status; FastAPI validation arrays are converted to joined human-readable messages.
- Success always navigates to `/jobs/{encoded job_id}` even though that destination is implemented by a later task. T-008 tests navigation intent, not the destination page.
- Packaging is proven from a built and isolated installed wheel, not merely from the source checkout.
- UI text and control labels are Vietnamese; existing API error detail may remain English.
- No existing design decision is reversed: T-005 synchronous/local/no-auth behavior and T-006 exactly-one file-or-URL behavior remain authoritative.

## Existing specs this task changes

- (none)

## Updated by T-034

- T-034 (built as T-041 / T-034B) adds a `Theo dõi cầu thủ` section (`#player-section`, `#player-form`) after `#highlights-form`, with a player-reel video, a touch list that seeks the source video, and its JS appended to the end of app.js. The `#highlights-form` behaviour is unchanged; the earlier 'no preview player' exclusion applies only to that original form. The page still references only `/static/style.css` and `/static/app.js`.
