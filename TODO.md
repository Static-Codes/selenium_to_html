# selenium_to_html Unit Test Suite Planning Doc

## Requirements
- Python 3.11+, Selenium 4.0+, unittest, the rest stdlib-only; no external packages.
- Cross platform (Windows, macOS, Linux)
    - Chrome Tests - All Platforms
    - Firefox Tests - All Platforms
    - Safari Tests - macOS Only
- CI/CD Friendly handling both interactive and non-interactive tty
- UV-first design with considerations to backwards compatibility with Python 3.11+


## Test Details:
The following details define the scope for the Unit Test:

Network required to perform I/O.

Should ensure that the API does not introduce regressions in feature support or break backwards-compatiblity with Selenium's `driver.page_source`. 

This should include negative tests that properly guard all exceptions from regressions that would otherwise degrade the package's error logging. This cannot be understated, a failure to do so will result in blanketed blindspots in code coverage, which itself will lead to unvetted functionality. The regression coverage is a must, it needs to be robust enough to support the claim "backwards-compatible with selenium's `page_source`" This will involve serving local data to http.server (using the methodology outlined in **Data Practices**) that will be probed by a driver instance. This instance should be shared across calls to the base `driver.page_source` and `capture_page`/`capture_page_sync`. Additional areas to include are: 

- The override implementation of `html.parser.HTMLParser` (selenium_to_html/core/types/resource_parsing.py) and using `urlib.request` to validate both fetched contents and the failure log compared to expected status codes as defined by the README.

- Documentation, specifically ensuring function names and default values remain updated, throwing a failure name if either of these checks fail, with an accompanying error message. This message should detail the steps required for a developer to remedy the situation.

### Methodologies

* **Data Practices**
All test data should be fabricated to ensure coverage for all media tags **(both supported and unsupported)** to prevent regressions and bolster the claims made by the project in the root README file. It should be served locally over a simple `http.server` running on the first open tcp port that is not otherwise reserved for system operations. Served data should categorized into one of the following:
    - **Malformed Data** The data should be intentionally malformed to expose any bugs or implementation flaws that would prevent proper error handling.
    - **Unsanitized Data** This data should be provided without prior escaping to test the robustness of `selenium_to_html`'s sanitization.
    - **Sanitized Data** This data should be escaped prior to being provided as a negative test for the same code covered by **Unsanitized Data**

### General Practices

Following PEP standards for naming conventions on Python 3.11+; Do not abbreviate variables (outside of method signatures) and those that are already shortened in the existing codebase.

Do not document any current bugs or flaws in implementation unless it prevents the test suite from being completed as expected.

Provide a comprehensive github flavored markdown document that is not overtly scholarly, but maintains a level of knowledge that would indicate proficency with the problem domain.

Do not use emdashes, do not refer to personal pronouns, (We, I, me, you, us, etc/) They, them, their's, etc are acceptable.

Do not leave overtly verbose comments, ensure any provided comments follow the linguistic quirks of the developer.

---

## Addendum: Remaining Coverage

This section extends the plan above. Where it conflicts with earlier text (category names in particular), this section wins.

### Resolved Decisions

| Topic | Decision |
| :--- | :--- |
| Network | Required only for TLS and certificate validation checks. Every other test runs against loopback servers and must pass with the network disabled. |
| `page_source` compatibility | Output must produce the same element tree as `driver.page_source`. Formatting quirks are excluded from the comparison (see **Page Source Compatibility**). |
| Data categories | Renamed to **Unescaped Data**, **Escaped Data** and **Malformed Data**. The package does not sanitize HTML, so the old names described behavior that is not under test. |
| Non-interactive tty | Covers both the test runner's own output and unattended CI/CD execution. |
| "Local" and "remote" resources | Local means same-origin as the page. Remote means cross-origin. Both are served from loopback by two `http.server` instances on different ports. `file:` URLs are out of scope. |

### Data Practices (Revised)

- **Unescaped Data** is raw and unescaped on purpose: bare `&` in query strings, quote characters inside attribute values, backslashes and replacement-style sequences (`\1`, `\g<0>`) inside URLs and tag text, spaces, non-ASCII characters, `</script>` inside attributes, CR/LF and NUL bytes inside URLs, and attribute values far past a sensible length.
- **Escaped Data** carries the same payloads as above but entity-encoded (`&amp;`, `&quot;`, `&#x27;`) or percent-encoded. It is the negative control. Both categories must resolve to the same intended URL, and an embed must rewrite exactly the intended attribute and nothing else in the tag.
- **Malformed Data** covers two layers:
    - *Markup:* unclosed tags, unclosed or mismatched quotes, truncated documents that end mid-tag, duplicate attributes, empty documents, a BOM, invalid UTF-8 bytes, a declared charset that does not match the bytes, and a URL that makes `urlsplit` raise (an unbalanced `[` in the host).
    - *Transport:* a `Content-Length` that lies in either direction, a body cut short by a closed socket, a connection reset mid-body, a bad status line, a missing `Content-Type`, an unsupported or corrupt `Content-Encoding`, and a redirect with a missing or garbage `Location`. These require writing raw bytes to `wfile`, so the handler must not rely on `send_response` alone.

### Suite Layout

```
tests/
    __init__.py
    support/
        loopback_server.py     # threaded server, route table, request log
        port_selection.py
        fake_driver.py         # scripted driver for failure injection
        browser_factory.py     # chrome, firefox, safari construction and skips
        tree_compare.py        # normalized element tree builder and differ
        fixtures.py            # generated pages for each data category
    test_page_source_compatibility.py
    test_resource_parser.py
    test_fetch_status_policy.py
    test_fetch_approaches.py
    test_body_and_limits.py
    test_timeouts.py
    test_embedding.py
    test_entry_points.py
    test_logging_contract.py
    test_tls_validation.py
    test_documentation.py
    test_failure_path_inventory.py
    test_runner_output.py
```

Fixtures are generated in code rather than stored as files, so each category can be parametrized with `subTest` and every case reports under its own name.

### Shared Infrastructure

**Loopback server**
- Built on `ThreadingHTTPServer` with daemon threads. The single-threaded `HTTPServer` would serialize the browser and `urllib` against each other and make concurrency impossible to measure.
- Binds `127.0.0.1` explicitly. `localhost` can resolve to IPv6 first on macOS and Windows and add connection delays.
- Keeps a request log (path, headers, arrival time) and a live in-flight counter with a recorded peak. Header, retry count and concurrency assertions read from this log rather than from package internals.
- Routes are declared per test, with configurable delay, status, headers, body, and raw-byte mode.
- A second instance on another port provides the cross-origin case, with optional `Access-Control-Allow-Origin` headers for the browser fetch path.

**Port selection**
- Scan upward from 1024 and bind directly, keeping the bound socket. Probing then rebinding invites a race, and two suite runs on one machine would collide.
- Skip ports on the browser restricted lists. Chromium refuses a set of ports outright (for example 2049, 3659, 4045, 5060, 5061, 6000, 6566, 6665 to 6669, 10080) and Firefox keeps a similar list. The list lives in one constant so it can be updated.

**Fake driver**
- A scripted object exposing `page_source`, `current_url`, `execute_script`, `execute_async_script`, `get_cookies` and `set_script_timeout`, where each call can return a value or raise on a given invocation number.
- Used wherever a real browser cannot fail on demand: page source retries, `readyState` timeouts, the `outerHTML` fallback, missing cookies, and every malformed `browser_fetch` payload (non-dict result, `error` key, non-success status, redirect flag, oversize body, invalid base64, raised exception).
- Real browsers remain the source of truth for `document.baseURI` with `<base>`, cookie and user agent retrieval, native redirect following, and CORS.

**Browser lifecycle**
- One driver per browser per module, created in `setUpModule` and released through `addModuleCleanup`, so a failed setup still shuts down the driver and the servers.
- Between tests: delete cookies and navigate to `about:blank`.
- Chrome and Firefox run headless in CI. Chrome adds `--no-sandbox` when running inside a container. Safari has no headless mode.
- Driver binaries come from environment variables when set, and from Selenium Manager otherwise. Selenium 4.0 predates Selenium Manager, so the lowest-version run must supply driver paths explicitly.
- A missing browser skips its test class with a message naming what was missing. Safari uses `skipUnless(sys.platform == "darwin")` and additionally skips with a message about `safaridriver --enable` when remote automation is off.
- `SELENIUM_TO_HTML_TEST_BROWSERS` selects browsers. `SELENIUM_TO_HTML_REQUIRE_BROWSERS` turns a skip into a failure for the listed browsers, so a CI job cannot go green by silently skipping everything.

### Page Source Compatibility

Compared on every browser, using the shared driver for both `driver.page_source` and `capture_page`/`capture_page_sync`, on pages that are frozen (no timers, no late script mutation) plus one page whose scripts mutate the DOM before `load` finishes.

**Comparison method.** Both strings are parsed into a normalized tree by `support/tree_compare.py` (stdlib `html.parser`) and the trees are diffed.

Ignored as formatting quirks:
- Whitespace between tags, and runs of whitespace inside text (collapsed)
- Attribute order and attribute quoting style
- The self-closing slash on void elements
- Entity form versus literal character form
- Tag name, attribute name and doctype casing

Never ignored: element order, element count, attribute names and values after normalization, text content after collapsing, and comments.

**Assertions**
- With `embed_media=False`, `snapshot.page_source` yields a tree equal to `driver.page_source`, for every data category.
- With `embed_media=True`, `embedded_source` differs from `page_source` only on media tags whose only differing attribute is `src`, and each data URI decodes to exactly the bytes the server delivered.
- Reading `driver.page_source` before and after a capture yields equal trees, so a capture does not alter the document.
- Driver state before and after a capture is compared: current URL, window handles, cookies, and script timeout.
- Fallbacks: blank `page_source` falls through to `outerHTML`, both blank raises `RuntimeError` carrying the last exception, and `page_source_attempts` is honored exactly.
- A closed or crashed driver, and a driver that has no cookie support, produce the documented outcome.

### Parser Coverage

**Supported (discovered and, where applicable, embedded)**

| Tag | Attribute | Kind |
| :--- | :--- | :--- |
| `script` | `src` | `script` |
| `link` | `href`, when `rel` has a token from `RELATIVE_LINK_TOKENS` | `stylesheet` or `link` |
| `img`, `video`, `audio`, `source`, `track`, `embed` | `src` | `media` |
| `base` | `href` | affects resolution only |

**Unsupported (must not be fetched, must not be rewritten)**

`img srcset`, `source srcset`, `video poster`, CSS `url(...)` in `<style>` and in `style=` attributes, `picture`, `object data`, `iframe src`, `input type=image`, `svg image href`, `data-src` and `lazy-src` attributes, `link rel` values outside the token set (`alternate`, `canonical`, `dns-prefetch`), `a href`, and `form action`. The assertion is two-sided: the resource is absent from `snapshot.resources`, and the request log shows zero hits for it.

**Edge cases**
- Self-closing tags, mixed-case tag and attribute names, duplicate attributes, unquoted attributes, and whitespace around values
- `&amp;` in URLs (parser decodes, raw tag text does not)
- Empty `src`, every entry in the skip scheme list (`data:`, `javascript:`, `blob:`, `about:`, `mailto:`, `tel:`), `ftp:` and `file:`
- Protocol-relative URLs, fragment stripping, relative paths against a nested base
- First `<base>` wins, and `document.baseURI` takes precedence when the browser supplies it
- Tags inside `<script>` bodies, comments, `<noscript>` and `<template>`
- Deduplication: `occurrences` counts repeats and `tag_texts` holds each distinct raw tag once
- The parser raising mid-feed keeps partial results (triggered with `unittest.mock.patch`)

**Flag matrix.** `include_media` x `embed_media` x `same_origin_only` (eight combinations) against one canonical page with local and remote copies of each supported tag. The expected resource set for each combination is written out in the test as a literal table rather than computed.

### Fetch Policy Coverage

Status assertions run with `use_browser_fallback=False` so results reflect the `urllib` policy alone. A second pass with fallback enabled asserts `browser_fetch` separately, since a browser follows redirects natively and can resolve responses the `urllib` path rejects. Both passes are checked against the README Status Codes table.

Attempt counts use `A` for the number of enabled approaches (4, or 3 without fallback) and `N` for `attempts_per_approach`.

| Server behavior | Expected result | Expected attempts |
| :--- | :--- | :--- |
| `200` | success, first approach | 1 |
| `302` to `200`, single hop and chain | success, every hop recorded in `redirects` | 1 |
| `302` chain longer than `max_redirects` | failure, "too many redirects" | A |
| `302` loop | failure | A |
| `302` with no `Location` | failure, non-retryable | A |
| `302` to `ftp:` or `file:` | failure, unsupported scheme | A |
| `301`, `307`, `308` | failure | A |
| `201` to `206` | failure | A |
| `404`, `410` | fatal failure, remaining attempts cancelled | 1 |
| `408`, `425`, `429`, `500`, `502`, `503`, `504` | failure after retries | A x N |
| `400`, `401`, `403`, `418` | generic failure | A |

Additional checks:
- Overridden `success_statuses`, `redirect_statuses`, `fatal_statuses` and `retryable_statuses`, including empty sets and sets that overlap.
- A flaky endpoint that fails once then succeeds proves the retry path and the "retrieved via fallback" log line.
- Per-approach header assertions from the request log, using gated endpoints that reject earlier approaches so each approach is reached for real:
    - `generic_minimal`: the generic Windows Chrome user agent, `Accept-Encoding: identity`, no `Cookie`, no `Referer`
    - `browser_headers`: the driver's user agent, `Referer` equal to the page URL, matching cookies
    - `origin_referer`: `Referer` equal to the page origin
    - `browser_fetch`: reached last, serialized by the driver lock (in-flight peak of 1)
- Cookie filtering through `_cookie_header` called directly with fabricated cookies: domain, subdomain, path prefix, `secure` over `http` versus `https`, empty names, and `None` values. No network is needed for this.
- Concurrency: with `3 x max_concurrency` slow resources, the in-flight peak equals `max_concurrency`. `max_concurrency` of `0` or a negative value behaves as `1`.
- `_standby_idle`: tested separately with `random` patched, checking the floor, the 1.1x minimum raise, doubling per attempt, and the `standby_idle_max` ceiling. Every other test patches the idle function to return immediately so the suite stays fast.
- `asyncio.gather` returning an exception for one resource yields a failed `ResourceResult` for it and leaves the others intact.

### Body, Size and Timeout Coverage

**Bodies**
- `gzip`, `deflate` (zlib-wrapped and raw), and `identity`, with the server both honoring `Accept-Encoding` and forcing an encoding regardless of it
- `br` and an unknown encoding (non-retryable failure), and a corrupt gzip stream (retryable failure)
- `ResourceResult.text()`: declared charset, unknown charset falling back to UTF-8, quoted charset values, and undecodable bytes with each `errors` mode
- MIME resolution for embedding: declared type, `application/octet-stream` resolved by extension, no type and no known extension, and a declared type that contradicts the extension

**Limits (each tested at the boundary: exactly at the limit passes, one byte over fails)**
- `max_resource_bytes` on both the `urllib` path and the `browser_fetch` path
- `embed_max_bytes` (over the limit is skipped with a warning and the attribute stays untouched)
- Zero-byte media is never embedded

**Timeouts (small values, delays on the server)**
- `request_timeout`: first-byte delay past the limit
- `total_timeout`: a body that drips slowly past the limit
- `page_ready_timeout`: a page holding a connection open so `readyState` never completes, expecting the warning and a continued capture
- `browser_script_timeout`: a slow endpoint fetched through the browser path

### Embedding Coverage

- Each supported media tag is embedded, and the replaced attribute is only `src`, never `data-src` or `lazy-src`.
- Replacement text containing backslashes or group-reference sequences survives intact.
- Duplicate identical tags, the same URL in differently written tags, and the same tag text appearing twice in one document.
- Failed or oversize resources leave their tags untouched while the rest of the page is still embedded.
- `embedded_count` agrees with the number of rewritten tags, and `embedded_source` is `None` when `embed_media` is off.
- Embedding raising internally is logged and leaves `embedded_source` as `None` (triggered by patching `_embed_media`).

### Entry Points

- `capture_page` awaited from `IsolatedAsyncioTestCase`.
- `capture_page_sync` from a plain `TestCase` (the `asyncio.run` path) and from inside a running loop (the thread pool path).
- Both entry points return equivalent snapshots for the same page.
- Cancelling a `capture_page` task mid-fetch propagates `CancelledError`, the driver lock is released, and a following capture on the same driver succeeds.
- On Windows, the README's `WindowsSelectorEventLoopPolicy` snippet and the default policy are both exercised.
- Default `FetchConfig()` is used when `None` is passed.

### Logging Contract

Every failure path is checked with `assertLogs` on the named logger, asserting level and the stable parts of the message (not the full text). The `failure_report()` structure is asserted key by key and must survive `json.dumps`.

| Logger | Level | Trigger |
| :--- | :--- | :--- |
| `selenium_to_html.runner` | `INFO` | discovery count, fallback success, embed count, capture summary |
| `selenium_to_html.runner` | `WARNING` | each failed attempt |
| `selenium_to_html.runner` | `ERROR` | fatal status, exhausted attempts, unhandled gather exception |
| `selenium_to_html.runner` | `ERROR` with traceback | embedding failure |
| `selenium_to_html.browser_helper` | `WARNING` | `readyState` timeout, `page_source` attempt failure, `outerHTML` fallback failure |
| `selenium_to_html.browser_helper` | `DEBUG` | unresolved `readyState`, failed state lookups |
| `selenium_to_html.resource_helper` | `ERROR` with traceback | parser raised |
| `selenium_to_html.resource_helper` | `WARNING` | unparseable URL, resource over `embed_max_bytes` |

Also covered:
- The `NullHandler` default (no output and no exception when logging is unconfigured, matching the README FAQ entry).
- Logger names stay under the `selenium_to_html.` prefix.
- Log output contains no ANSI codes and does not change between a tty and a non-tty stream.

### TLS Validation

This is the only network-dependent group. It targets a public TLS test host (for example badssl.com) and lives in `test_tls_validation.py`.

- **Baseline first:** a valid-certificate fetch must succeed. If it fails, every dependent negative test skips with a message naming the likely cause (missing system roots, for example a python.org build on macOS that never ran its certificate install step). This stops an environment problem from being reported as a regression.
- **With `verify_tls=True`:** expired, self-signed, wrong-host and untrusted-root certificates each fail, and the recorded error mentions `SSLCertVerificationError`. Failures appear in `failure_report()` for every approach attempted.
- **With `verify_tls=False`:** the same hosts succeed on the `urllib` approaches.
- `verify_tls` does not leak between captures (each capture builds its own context).
- `secure` cookies are sent over `https` only. The filtering itself is covered offline through `_cookie_header`, and the real exchange is covered here.
- Preflight is a short TCP connect to the host. An unreachable host skips with a message. `SELENIUM_TO_HTML_REQUIRE_NETWORK=1` turns that skip into a failure for CI jobs that are expected to have network access. `SELENIUM_TO_HTML_TEST_OFFLINE=1` skips the group deliberately.

### Documentation Checks

Each check is its own test method, so a failure names exactly what drifted (for example `test_readme_default_matches_source_for_max_concurrency`). README content is read with `re` and source values with `dataclasses.fields`.

- Every `FetchConfig` parameter named in the README exists, and none are missing from it.
- Type and default match for each parameter. Floats documented as `int` are a mismatch.
- Public names in `__all__`, the module docstring, and the README usage examples agree. A function named in the README that is not importable fails.
- The README Status Codes table matches the default status sets in `FetchConfig`, and the Fetch approaches list matches `_APPROACHES` in name and order.
- The supported media tags link resolves to `MEDIA_TAG_TOKENS`.
- Every README link that carries a line anchor lands on the symbol it names, with a tolerance of zero lines.
- Fenced Python blocks in the README parse with `ast.parse`.
- Version in `__init__.py` equals `pyproject.toml`, and the README requirements match `requires-python` and the Selenium specifier.
- Every behavioral claim in the README maps to a named test in a claims table kept in the test module. A claim without a test fails the check.

**Failure message format.** Each assertion message states what drifted, the expected and actual values, the file to edit, and the remedy:

```
Documentation drift: default for FetchConfig.max_concurrency
    README.md says:   8
    fetch_config.py:  16
Remedy:
    1. Decide which side is correct.
    2. Update the "FetchConfig API" section of README.md, or the default in
       selenium_to_html/core/types/fetch_config.py.
    3. Re-run: uv run python -m unittest tests.test_documentation
```

The suite's own markdown (not this planning doc) is also linted for the style rules: no em dashes anywhere, and no first or second person pronouns in prose outside fenced code.

### Coverage Enforcement

`coverage.py` would break the stdlib-only rule, so two stdlib mechanisms are used instead.

- **Line report:** a report-only step using the stdlib `trace` module. No threshold is enforced until a baseline exists.
- **Failure path inventory** (`test_failure_path_inventory.py`): walks the package with `ast` and lists every `raise _AttemptError(...)` site and every `logger` call. Each one must appear in a registry that names the test covering it. A new raise or log site with no registry entry fails with a message naming the file, line and the registry to update. This is what keeps error handling and logging from regressing into untested territory.

### CI/CD and Runner Output

- `sys.stdout.isatty()` selects the output style. A tty gets color and in-place progress. A non-tty gets plain, line-oriented output with no escape codes. `NO_COLOR` and the `CI` variable force plain output.
- Nothing in the suite prompts for input, and every wait has an upper bound.
- Skip reasons are printed in the summary so a skipped browser or network group is visible in CI logs.
- Exit code is non-zero on any failure or error, and on any skip that was promoted by a `REQUIRE` variable.
- Package log output is routed to stderr so the runner's own output stays clean.
- A JUnit XML file is optional. If a CI needs one, a small writer on `xml.etree` keeps the suite stdlib-only.
- `test_runner_output.py` checks the tty and non-tty paths with a fake stream object, including that `NO_COLOR` wins.

### Commands

```bash
# Primary, UV-first
uv sync
uv run python -m unittest discover -s tests -t . -v

# Version matrix
uv run --python 3.11 python -m unittest discover -s tests -t .
uv run --python 3.12 python -m unittest discover -s tests -t .
uv run --python 3.13 python -m unittest discover -s tests -t .

# Lowest supported Selenium
uv run --resolution lowest-direct python -m unittest discover -s tests -t .

# Without uv
python -m venv .venv
python -m pip install -e .
python -m unittest discover -s tests -t . -v
```

### Deliverable

The comprehensive GFM document lives at `tests/README.md`. It covers how to run the suite, how browsers and drivers are provisioned, the environment variables above, how each data category is used, and how to read a documentation drift failure. It follows the style rules in **General Practices**.
