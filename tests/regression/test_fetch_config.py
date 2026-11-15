from selenium_to_html.core.types.fetch_config import FetchConfig, ResourceRef


def test_fetch_config_defaults_match_implementation():
    cfg = FetchConfig()
    assert cfg.max_concurrency == 8
    assert cfg.request_timeout == 15.0
    assert cfg.total_timeout == 60.0
    assert cfg.attempts_per_approach == 2
    assert cfg.standby_idle_base == 0.5
    assert cfg.standby_idle_max == 8.0
    assert cfg.max_redirects == 5
    assert cfg.success_statuses == frozenset({200})
    assert cfg.redirect_statuses == frozenset({302})
    assert cfg.terminal_statuses == frozenset({404, 410})
    assert cfg.retryable_statuses == frozenset({408, 425, 429, 500, 502, 503, 504})
    assert cfg.same_origin_only is False
    assert cfg.include_media is False
    assert cfg.embed_media is False
    assert cfg.embed_max_bytes == 2 * 1024 * 1024
    assert cfg.use_browser_fallback is True
    assert cfg.verify_tls is True
    assert cfg.max_bytes == 25 * 1024 * 1024
    assert cfg.page_ready_timeout == 15.0
    assert cfg.page_source_attempts == 3
    assert cfg.browser_script_timeout == 20.0


def test_fetch_config_custom_overrides_propagate():
    cfg = FetchConfig(
        max_concurrency=3,
        request_timeout=1.5,
        total_timeout=2.5,
        attempts_per_approach=4,
        standby_idle_base=0.25,
        standby_idle_max=3.0,
        max_redirects=7,
        success_statuses=frozenset({200, 201}),
        redirect_statuses=frozenset({301, 302}),
        terminal_statuses=frozenset({410}),
        retryable_statuses=frozenset({503}),
        same_origin_only=True,
        include_media=True,
        embed_media=True,
        embed_max_bytes=10,
        use_browser_fallback=False,
        verify_tls=False,
        max_bytes=99,
        page_ready_timeout=1.0,
        page_source_attempts=5,
        browser_script_timeout=7.0,
    )
    assert cfg.max_concurrency == 3
    assert cfg.request_timeout == 1.5
    assert cfg.total_timeout == 2.5
    assert cfg.attempts_per_approach == 4
    assert cfg.standby_idle_base == 0.25
    assert cfg.standby_idle_max == 3.0
    assert cfg.max_redirects == 7
    assert cfg.success_statuses == frozenset({200, 201})
    assert cfg.redirect_statuses == frozenset({301, 302})
    assert cfg.terminal_statuses == frozenset({410})
    assert cfg.retryable_statuses == frozenset({503})
    assert cfg.same_origin_only is True
    assert cfg.include_media is True
    assert cfg.embed_media is True
    assert cfg.embed_max_bytes == 10
    assert cfg.use_browser_fallback is False
    assert cfg.verify_tls is False
    assert cfg.max_bytes == 99
    assert cfg.page_ready_timeout == 1.0
    assert cfg.page_source_attempts == 5
    assert cfg.browser_script_timeout == 7.0


def test_resource_ref_defaults():
    ref = ResourceRef(url="https://e.test/a", tag="img", attr="src", kind="media")
    assert ref.occurrences == 1
    assert ref.tag_texts == []
