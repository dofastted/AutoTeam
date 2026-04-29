import pytest

from autoteam.browser_runtime import BrowserLeaseError, acquire_browser_lease


class FakeBrowser:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakePlaywright:
    def __init__(self):
        self.chromium = self
        self.browser = FakeBrowser()
        self.stopped = False

    def launch(self, **_kwargs):
        return self.browser

    def stop(self):
        self.stopped = True


class FakeSyncPlaywright:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
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
