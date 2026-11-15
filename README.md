# selenium_to_html

A hardened replacement for Selenium's `driver.page_source` inspired by zebbern's [website-clone](https://github.com/zebbern/website-clone/tree/main). 

`selenium_to_html` is a 1:1 hardened replacement for Selenium's `driver.page_source`. It starts by retrieving the raw page source (much like Selenium does already) but with added hardening. Once retrieved, the source is parsed using the stdlib `html.parser` for tag name tokens containing externally linked resources. Every resource is fetched in parallel with socketed requests. Each request goes through a layered fallback approach, which maintains a full stacktrace upon failure. 

Media embedding is opt-in by default, as it will produce differing output when compared to Selenium's `driver.page_source`. 

When enabled, all media (both local and remote resources) will be embedded as base64 `data:` URIs in the outputted HTML.

## Requirements
- Python 3.11+. 
- Selenium >=4.0 

## Installation

Note: If `pip` is not recognized, try `pip3`, or `uv pip install`

```bash
pip install git+https://github.com/static-codes/selenium_to_html.git
```

## Usage

### Synchronous (Blocking) context
```py
import logging
from selenium_to_html import FetchConfig, capture_page_sync

# All failures are logged under "selenium_to_html.*"
logging.basicConfig(level=logging.INFO)   

# driver should be an instance of Selenium Webdriver that had already navigated to the desired url.
# Works with ChromeDriver, GeckoDriver, and SafariDriver
snapshot = capture_page_sync(driver, FetchConfig(max_concurrency=12))

print(snapshot.page_url, len(snapshot.succeeded), "ok,", len(snapshot.failures), "failed")
for failure in snapshot.failure_report():
    print(failure["url"], failure["attempts"][-1]["error"])
```

### Asynchronous (Non-Blocking) context 

```py
import logging
from selenium_to_html import FetchConfig, capture_page

# All failures are logged under "selenium_to_html.*"
logging.basicConfig(level=logging.INFO)   

# driver should be an instance of Selenium Webdriver that had already navigated to the desired url.
# Works with ChromeDriver, GeckoDriver, and SafariDriver
snapshot = await capture_page(driver, FetchConfig(max_concurrency=12))

print(snapshot.page_url, len(snapshot.succeeded), "ok,", len(snapshot.failures), "failed")
for failure in snapshot.failure_report():
    print(failure["url"], failure["attempts"][-1]["error"])
```

### Embedding media as base64:

To embed media, simply pass `embed_media=True` to `FetchConfig` then pass the created `FetchConfig` to `capture_page_sync` or to `capture_page_async` for asynchronous requests.

**Syntax**: 
- *Synchronous* (Blocking): 
  `capture_page_sync(driver, FetchConfig(..., embed_media=True)`

- *Asynchronous* (Non-Blocking):
  1. Inside an async context/function:
    ```python
    await capture_page(driver, FetchConfig(..., embed_media=True))
    ```
    
  2. Inside a sync context/function:
    ```py
    import asyncio
    
    # If you're using windows, uncomment this next line:
    # asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(
       capture_page(driver, FetchConfig(...,
       embed_media=True)
    ))
    ```

Once `capture_page`/`capture_page_sync` have been called, the following fields and functions are available from the initialized variable:

- `embedded_source` will contain the requested page's source with all located `src=*` attributes being replaced for all [supported](selenium_to_html/core/types/resource_parsing.py#L13) media types.
- `embedded_count` will contain the number of sources that were modified during the embed process.
- `page_source` will contain same raw page source returned by Selenium's `driver.page_source`.
- `failure_report()` will generate a report on any failures encountered, along with their associated stacktrace.

```py
snapshot = capture_page_sync(driver, FetchConfig(embed_media=True))
html = snapshot.embedded_source
print(snapshot.embedded_count)
```

## Known Limitations

- Media embedding does not currently support `srcset=.*`, `<video poster>`, or CSS `url(...)` references.

- Request headers (including `Cookies` and `Referer`) are computed once per attempt and reused across redirected requests.

## FetchConfig API

The following are the parameter names and associated types supported by the `FetchConfig` constructor. For more information, please reference the [source](./selenium_to_html/core/types/fetch_config.py#L9-L73) comments.

- Concurrency and timing: 
    - `max_concurrency`: `int` 
    - `request_timeout`: `float` 
    - `total_timeout`: `float`
    - `attempts_per_approach`: `int`
    - `standby_idle_base`: `float`
    - `standby_idle_max`: `float`

- Status policy: 
    - `max_redirects`: `int`
    - `success_statuses`: `frozenset[int]` 
    - `redirect_statuses`: `frozenset[int]` 
    - `terminal_statuses`: `frozenset[int]` 
    - `retryable_statuses`: `frozenset[int]`

- Scope: 
    - `same_origin_only`: `bool`
    - `include_media`: `bool`

- Embedding: 
    - `embed_media`: `bool`
    - `embed_max_bytes`: `int` (per-resource cap, defaults to 2 MiB)

- Safety: 
    - `use_browser_fallback`: `bool`
    - `verify_tls`: `bool`
    - `max_bytes`: `int`

- Page source: 
    - `page_ready_timeout`: `int`
    - `page_source_attempts`: `int`
    - `browser_script_timeout`: `int`


## Fetch approaches

The fetch approaches are attemped on a per-resource basis in the following order:

1. `generic_minimal`: Uses a Windows 10 Chrome User Agent and sends a generic `Accept-Encoding` header value, without explicitly specifying `Cookies` or a `Referer`.
2. `browser_headers`: Routes the request through `urllib.request` using the provided `driver`'s user agent/cookies, with the `Referer` header set to the using `driver.current_url`.
3. `origin_referer`: The same as `browser_headers` except `Referer` is set to the page's origin; this may cause some leakage during stealth operations. 
4. `browser_fetch`: Executes `fetch()` inside the provided `driver`'s session. This may fail for a variety of reasons stemming from a rejected CORS header, it is treated as the last resort.

Each approach adheres to `attempts_per_approach` tries and uses an exponentially-increasing [standby idle time](./selenium_to_html/core/runner.py#L47).

## Status Codes

| HTTP Status Code | Result | Notes |
| :--- | :--- | :--- |
| `200` | **Success** | N/A. |
| `302` ending in `200` | **Success** | Redirects are followed, every chain member is validated then recorded. |
| `201-206`, `301`, `307`, and `308` | **Failure** | Reports as a failure, unless included in `redirect_status` (Which currently only includes `302`). |
| `404`, `410` | **Fatal Failure** | Reports as a non recoverable failure; All subsequent retries are cancelled and the lock is released to the next socketed request. |
| All others | **Failure** | Reports as a generic failure. |


## Notes:

- A driver instance must have already been navigated to the target page and cannot be called from another thread during a capture; An exception is raised if this is attempted. 

- Browser-side fetches are serialized via a lock.




## FAQ:

- Q: I'm receiving a `NullHandler` exception:
    - A: Insert the following code before calling any imported functions from `selenium_to_html`:
        ```py
        import logging
        logging.basicConfig(level=logging.INFO)   
        ```
