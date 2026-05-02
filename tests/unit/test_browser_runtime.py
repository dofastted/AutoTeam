import pytest
import threading

import autoteam.browser_runtime as browser_runtime
from autoteam.browser_runtime import BrowserLeaseError, acquire_browser_lease, browser_parallel_limit


@pytest.fixture(autouse=True)
def clear_browser_runtime_env(monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_BROWSER_CDP_URL", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_BROWSER_CDP_COMMAND", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_USER_DATA_DIR", raising=False)
    browser_runtime._PERSISTENT_KEEPALIVE.clear()
    yield
    browser_runtime._PERSISTENT_KEEPALIVE.clear()


class FakeBrowser:
    def __init__(self):
        self.closed = False
        self.contexts = []

    def close(self):
        self.closed = True

    def is_connected(self):
        return not self.closed

    def new_context(self, **_kwargs):
        context = FakeContext(browser=self)
        self.contexts.append(context)
        return context


class FakeContext:
    def __init__(self, browser):
        self.browser = browser
        self.closed = False
        self.pages = []

    def new_page(self):
        page = object()
        self.pages.append(page)
        return page

    def close(self):
        self.closed = True


class ThreadBoundBrowser(FakeBrowser):
    def __init__(self):
        super().__init__()
        self.owner_thread_id = None

    def bind_current_thread(self):
        self.owner_thread_id = threading.get_ident()

    def _check_thread(self):
        if threading.get_ident() != self.owner_thread_id:
            raise RuntimeError("Cannot switch to a different thread started main")

    def is_connected(self):
        self._check_thread()
        return not self.closed

    def new_context(self, **_kwargs):
        self._check_thread()
        context = ThreadBoundContext(browser=self)
        self.contexts.append(context)
        return context


class ThreadBoundContext(FakeContext):
    @property
    def browser(self):
        self._check_thread()
        return self._browser

    @browser.setter
    def browser(self, value):
        self._browser = value

    def _check_thread(self):
        self._browser._check_thread()

    @property
    def pages(self):
        self._check_thread()
        return self._pages

    @pages.setter
    def pages(self, value):
        self._pages = value

    def new_page(self):
        self._check_thread()
        page = ThreadBoundPage(self)
        self._pages.append(page)
        return page

    def close(self):
        self._check_thread()
        self.closed = True


class ThreadBoundPage:
    def __init__(self, context):
        self.context = context
        self.url = ""
        self.filled_values = []

    def _check_thread(self):
        self.context._check_thread()

    def goto(self, url, **_kwargs):
        self._check_thread()
        self.url = url
        return "ok"

    def locator(self, selector):
        self._check_thread()
        return ThreadBoundLocator(self, selector)


class ThreadBoundLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector
        self.value = ""

    @property
    def first(self):
        self.page._check_thread()
        return self

    def fill(self, value):
        self.page._check_thread()
        self.value = value
        self.page.filled_values.append((self.selector, value))
        return None


class FakePlaywright:
    def __init__(self, browser=None):
        self.chromium = self
        self.browser = browser or FakeBrowser()
        self.persistent_context = None
        self.stopped = False
        self.launch_options = None
        self.persistent_options = None
        self.user_data_dir = None
        self.start_count = 0

    def launch(self, **_kwargs):
        self.launch_options = _kwargs
        return self.browser

    def launch_persistent_context(self, user_data_dir, **kwargs):
        self.user_data_dir = user_data_dir
        self.persistent_options = kwargs
        if isinstance(self.browser, ThreadBoundBrowser):
            self.browser.bind_current_thread()
        self.persistent_context = (
            ThreadBoundContext(browser=self.browser)
            if isinstance(self.browser, ThreadBoundBrowser)
            else FakeContext(browser=self.browser)
        )
        return self.persistent_context

    def connect_over_cdp(self, _url):
        return self.browser

    def stop(self):
        self.stopped = True


class FakeSyncPlaywright:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        self.playwright.start_count += 1
        return self.playwright


def test_browser_lease_allows_only_one_active_browser():
    fake = FakePlaywright()

    with acquire_browser_lease("first", sync_playwright_factory=lambda: FakeSyncPlaywright(fake)) as lease:
        lease.launch_chromium(headless=True)
        with pytest.raises(BrowserLeaseError, match="first"):
            with acquire_browser_lease("second", sync_playwright_factory=lambda: FakeSyncPlaywright(FakePlaywright())):
                pass

    assert fake.browser.closed is True
    assert fake.stopped is True


def test_browser_lease_releases_after_exception():
    fake = FakePlaywright()

    with pytest.raises(RuntimeError, match="boom"):
        with acquire_browser_lease("raises", sync_playwright_factory=lambda: FakeSyncPlaywright(fake)) as lease:
            lease.launch_chromium(headless=True)
            raise RuntimeError("boom")

    assert fake.browser.closed is True
    assert fake.stopped is True

    with acquire_browser_lease("next", sync_playwright_factory=lambda: FakeSyncPlaywright(FakePlaywright())):
        pass


def test_browser_lease_uses_cdp_url(monkeypatch):
    fake = FakePlaywright()
    monkeypatch.setenv("PLAYWRIGHT_BROWSER_CDP_URL", "http://127.0.0.1:9222")
    monkeypatch.setenv("PLAYWRIGHT_BROWSER_CDP_COMMAND", "")
    monkeypatch.setenv("PLAYWRIGHT_USER_DATA_DIR", "/tmp/autoteam-profile")

    with acquire_browser_lease("cdp", sync_playwright_factory=lambda: FakeSyncPlaywright(fake)) as lease:
        browser = lease.launch_chromium(headless=True)

    assert browser is fake.browser
    assert fake.browser.closed is True
    assert fake.persistent_context is None


def test_browser_lease_uses_persistent_profile_and_keeps_browser_alive(monkeypatch):
    fake = FakePlaywright()
    monkeypatch.setenv("PLAYWRIGHT_BROWSER_CDP_URL", "")
    monkeypatch.setenv("PLAYWRIGHT_BROWSER_CDP_COMMAND", "")
    monkeypatch.setenv("PLAYWRIGHT_USER_DATA_DIR", "/tmp/autoteam-profile")

    with acquire_browser_lease("persistent", sync_playwright_factory=lambda: FakeSyncPlaywright(fake)) as lease:
        browser = lease.launch_chromium(headless=True, args=["--no-sandbox"], unknown_option=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})

    assert fake.user_data_dir == "/tmp/autoteam-profile"
    assert fake.persistent_options["headless"] is True
    assert fake.persistent_options["args"] == ["--no-sandbox"]
    assert "unknown_option" not in fake.persistent_options
    assert fake.persistent_context.closed is False
    assert fake.persistent_context.pages
    assert context.closed is True
    assert fake.browser.closed is False
    assert fake.stopped is False


def test_browser_lease_reuses_persistent_playwright_without_restart(monkeypatch):
    fake = FakePlaywright()
    monkeypatch.setenv("PLAYWRIGHT_BROWSER_CDP_URL", "")
    monkeypatch.setenv("PLAYWRIGHT_BROWSER_CDP_COMMAND", "")
    monkeypatch.setenv("PLAYWRIGHT_USER_DATA_DIR", "/tmp/autoteam-profile")

    with acquire_browser_lease("persistent-1", sync_playwright_factory=lambda: FakeSyncPlaywright(fake)) as lease:
        lease.launch_chromium(headless=True)

    with acquire_browser_lease(
        "persistent-2",
        sync_playwright_factory=lambda: (_ for _ in ()).throw(AssertionError("should reuse persistent playwright")),
    ) as lease:
        browser = lease.launch_chromium(headless=True)
        context = browser.new_context()

    assert fake.start_count == 1
    assert context.closed is True
    assert fake.browser.closed is False
    assert fake.stopped is False


def test_persistent_playwright_restarts_across_threads(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSER_CDP_URL", "")
    monkeypatch.setenv("PLAYWRIGHT_BROWSER_CDP_COMMAND", "")
    monkeypatch.setenv("PLAYWRIGHT_USER_DATA_DIR", "/tmp/autoteam-profile")
    monkeypatch.setattr(browser_runtime, "_kill_chromium_processes_for_profile", lambda _user_data_dir: None)
    monkeypatch.setattr(browser_runtime, "_cleanup_persistent_profile_locks", lambda _user_data_dir: None)

    fakes = [FakePlaywright(), FakePlaywright()]
    thread_ids = []
    threads_seen = []
    errors = []

    def run_once(index):
        try:
            with acquire_browser_lease(
                f"persistent-thread-{index}",
                sync_playwright_factory=lambda: FakeSyncPlaywright(fakes[index]),
            ) as lease:
                lease.launch_chromium(headless=True)
                thread_ids.append(threading.get_ident())
                threads_seen.append(threading.current_thread())
        except Exception as exc:
            errors.append(exc)

    first = threading.Thread(target=run_once, args=(0,))
    first.start()
    first.join()
    assert not errors

    first_keepalive_thread_id = browser_runtime._PERSISTENT_KEEPALIVE.get("thread_id")
    first_keepalive_thread = browser_runtime._PERSISTENT_KEEPALIVE.get("thread")
    # 持久化 keepalive 在专用 worker 线程，不是调用方线程
    assert first_keepalive_thread_id is not None
    assert first_keepalive_thread_id != thread_ids[0]
    assert first_keepalive_thread is not threads_seen[0]
    assert browser_runtime._PERSISTENT_KEEPALIVE.get("worker") is not None

    second = threading.Thread(target=run_once, args=(1,))
    second.start()
    second.join()

    assert not errors
    # 持久化 worker 跨线程复用：第一次启动后保留，第二次调用不会重新 start playwright
    assert fakes[0].start_count == 1
    assert fakes[1].start_count == 0
    second_keepalive_thread_id = browser_runtime._PERSISTENT_KEEPALIVE.get("thread_id")
    second_keepalive_thread = browser_runtime._PERSISTENT_KEEPALIVE.get("thread")
    # worker 线程保持不变，跨调用线程仍使用同一 worker
    assert second_keepalive_thread_id == first_keepalive_thread_id
    assert second_keepalive_thread is first_keepalive_thread
    assert browser_runtime._PERSISTENT_KEEPALIVE.get("playwright") is fakes[0]
    assert browser_runtime._PERSISTENT_KEEPALIVE.get("context") is fakes[0].persistent_context


def test_persistent_objects_proxy_all_page_access_to_worker_thread(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSER_CDP_URL", "")
    monkeypatch.setenv("PLAYWRIGHT_BROWSER_CDP_COMMAND", "")
    monkeypatch.setenv("PLAYWRIGHT_USER_DATA_DIR", "/tmp/autoteam-profile")

    fake = FakePlaywright(browser=ThreadBoundBrowser())

    with acquire_browser_lease("persistent-proxy", sync_playwright_factory=lambda: FakeSyncPlaywright(fake)) as lease:
        browser = lease.launch_chromium(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        assert page.goto("https://example.com", wait_until="domcontentloaded") == "ok"
        locator = page.locator("input").first
        locator.fill("hello")

    real_context = fake.browser.contexts[0]
    real_page = real_context._pages[0]
    assert real_page.url == "https://example.com"
    assert real_page.filled_values == [("input", "hello")]
    assert real_context.closed is True


def test_browser_parallel_limit_allows_configured_slots():
    leases = []
    with browser_parallel_limit(3):
        for index in range(3):
            lease = acquire_browser_lease(
                f"worker-{index + 1}",
                sync_playwright_factory=lambda: FakeSyncPlaywright(FakePlaywright()),
            )
            leases.append(lease)
            lease.__enter__()

        with pytest.raises(BrowserLeaseError):
            with acquire_browser_lease(
                "worker-4", sync_playwright_factory=lambda: FakeSyncPlaywright(FakePlaywright())
            ):
                pass

    for lease in reversed(leases):
        lease.__exit__(None, None, None)
