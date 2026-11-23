# Plan T-008: Serve a web upload page for video files and YouTube links

Design: `docs/superpowers/specs/2026-11-23-t-008-serve-a-web-upload-page-for-design.md`.

## Implementation plan

# T-008: Serve a web upload page for video files and YouTube links

## Context

T-005/T-006 provide a module-level FastAPI `app` in `sportscut/api.py`. `POST /highlights` is synchronous and accepts exactly one multipart `file` or form `url`, plus optional `top`, `min_len`, and `max_len`. Success returns `{"job_id": ..., "highlights": [...]}`; expected client errors use FastAPI JSON with `detail` and status 400, 413, or 422. This task adds the first browser page only. It does not add the later job preview/editor page.

## Design

### Package data

Create `sportscut/web/index.html`, `sportscut/web/app.js`, and `sportscut/web/style.css`. They are plain UTF-8 files with no generated bundle, external CDN, remote font, framework, or Node build.

In `pyproject.toml`, add:

```toml
[tool.setuptools.package-data]
sportscut = ["web/*.html", "web/*.js", "web/*.css"]
```

Do not add `sportscut/web/__init__.py`: `web/` is static package data under the existing `sportscut` package, not a Python subpackage.

### FastAPI routes

In `sportscut/api.py`:

- Import `resources` from `importlib` and `StaticFiles` from `fastapi.staticfiles`.
- Define `WEB_DIR = resources.files("sportscut").joinpath("web")`.
- Mount `app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")`.
- Add the exact route:

```python
@app.get("/", include_in_schema=False)
def get_web_app() -> FileResponse:
    return FileResponse(WEB_DIR.joinpath("index.html"), media_type="text/html")
```

The existing POST and clip routes, their validation order, response schemas, status mappings, storage, and synchronous execution remain unchanged.

### HTML contract

`index.html` is a complete Vietnamese HTML5 document. It links only `/static/style.css` and `/static/app.js` (with `defer`). It contains:

- `<form id="highlights-form">`.
- A file input with `id="file"`, `name="file"`, `type="file"`, and `accept="video/*"`.
- A YouTube input with `id="url"`, `name="url"`, and `type="url"`.
- Clear Vietnamese text stating that exactly one of file or YouTube URL must be supplied.
- Optional number inputs named and identified as `top`, `min_len`, and `max_len`. `top` uses `min="1"` and `step="1"`; duration inputs use a positive minimum and `step="any"`. They are not `required`.
- A submit button with `id="submit"`.
- A busy element with `id="busy"`, Vietnamese processing text, `role="status"`, and initially `hidden`.
- An error element with `id="error"`, `role="alert"`, `aria-live="assertive"`, and initially `hidden`.
- Vietnamese labels for all controls, associated through `for` attributes.

### JavaScript behavior

`app.js` uses vanilla browser APIs and registers a submit handler on `#highlights-form`.

On submit:

1. Prevent the normal form submission and clear/hide the previous error.
2. Read `file.files[0]` and `url.value.trim()`. If both or neither are present, show the Vietnamese message `Hãy chọn một tệp video hoặc nhập một liên kết YouTube.` and do not call `fetch`.
3. Construct a new `FormData`; append only the selected source. Append each of `top`, `min_len`, and `max_len` only when its trimmed value is non-empty, so blank optional fields allow the API defaults instead of producing empty form values.
4. Before `fetch`, disable the submit button, set `aria-busy="true"` on the form, and reveal `#busy`.
5. Call `fetch("/highlights", {method: "POST", body: formData})`. Do not set `Content-Type`; the browser supplies the multipart boundary.
6. Parse the response as JSON. For a non-OK response, display a readable error in `#error`: use a string `detail` directly; for FastAPI validation arrays, join each item's `msg` with `; `; otherwise use `Không thể xử lý video.`. Include the HTTP status in the rendered text, for example `Lỗi 413: upload exceeds ...`. This covers 400, 413, and 422 without exposing raw JSON.
7. On an OK response with a non-empty string `job_id`, call `window.location.assign(`/jobs/${encodeURIComponent(job_id)}`)`.
8. Treat a network failure, invalid JSON, or an OK response without `job_id` as `Không thể kết nối hoặc phản hồi từ máy chủ không hợp lệ.`.
9. In `finally`, re-enable the submit button, remove `aria-busy`, and hide the busy element. Navigation may occur before the restored state is visible.

`style.css` provides a usable single-column local-tool layout, visible focus styles, readable error and busy states, and responsive sizing. Visual branding, animation, and a design system are not required.

## Ordered implementation plan (TDD)

1. Add `tests/test_web.py::test_root_serves_upload_form`. Assert `GET /` is 200, content type starts with `text/html`, and parse/inspect the body for the form plus inputs named `file`, `url`, `top`, `min_len`, and `max_len`. Assert the file and URL types, optional numeric fields, Vietnamese labels, busy/error regions, and `/static/app.js` and `/static/style.css` references. Run it and observe the expected 404 failure.
2. Add `tests/test_web.py::test_static_assets_have_expected_content_types`. Assert `GET /static/app.js` and `GET /static/style.css` return 200; JavaScript content type is `text/javascript` or `application/javascript` (optional charset allowed), and CSS starts with `text/css`. Run it and observe the expected 404 failures.
3. Add `tests/test_web.py::test_frontend_submission_contract`. Inspect the served JavaScript and HTML to verify the source exclusivity check, manual `FormData` construction, omission of blank optional fields, POST to `/highlights`, busy/error state handling, response `detail` handling, and navigation to `/jobs/` using the returned `job_id`. This is a static contract test; no browser or Node dependency is introduced. Run it before implementation and observe failure.
4. Implement the three static files and the root/static routes in `sportscut/api.py`. Run the three tests until green. Do not alter `create_highlights` or `get_clip` behavior.
5. Add the package-data declaration to `pyproject.toml`.
6. Add `tests/test_web.py::test_wheel_install_contains_web_resources`. In a temporary directory, build a wheel using `python -m pip wheel --no-deps --wheel-dir <wheel-dir> .`, install that wheel using `python -m pip install --no-deps --target <target> <wheel>`, then run a subprocess from outside the repository with `PYTHONPATH=<target>`. The subprocess uses `importlib.resources.files("sportscut").joinpath("web", name)` for all three filenames and asserts each is a file with non-empty UTF-8 content. It must import the installed copy, not the source checkout. Run it before the package-data change to demonstrate the missing-resource failure, then after the change to pass.
7. Run the focused and full verification commands. The Tester independently adds `tests/test_t008_acceptance.py`, covering the HTTP, resource-installation, and frontend source-contract criteria without copying Developer test helpers. The Tester must demonstrate at least one acceptance test fails when the `/` route is temporarily removed or redirected, then restore the implementation. Neither test suite reads git history.

## Verification

```bash
.venv/bin/python -m pytest -q tests/test_web.py tests/test_t008_acceptance.py -rs
.venv/bin/python -m pytest -q
```

Both commands must report 0 failed and 0 skipped. No eval command or F1 threshold applies because detection and highlight output are unchanged.

## Test plan

- Developer integration test `tests/test_web.py::test_root_serves_upload_form`: TestClient checks status/content type and the complete form, control, label, busy, error, and asset-link contract.
- Developer integration test `tests/test_web.py::test_static_assets_have_expected_content_types`: TestClient checks JavaScript, CSS, and missing-static responses.
- Developer static frontend contract test `tests/test_web.py::test_frontend_submission_contract`: verifies exclusivity validation, manual FormData population, optional-field omission, synchronous-request busy state, readable error handling, and success navigation without adding a browser dependency.
- Developer packaging test `tests/test_web.py::test_wheel_install_contains_web_resources`: builds and installs the wheel in temporary directories and verifies all three assets through importlib.resources from the isolated installed package.
- Tester acceptance file `tests/test_t008_acceptance.py`: independently covers AC1-AC10 and performs a mutation check proving the root-route test fails when the route is absent, then restores it.
- Regression: run `.venv/bin/python -m pytest -q`; no eval is required because the task does not touch detection accuracy.
