import json
import os
import pytest
import time
import random
import string
from typing import Optional
from urllib.parse import urlparse
import beartype  # to trigger the runtime typechecking
import requests
from karakeep_python_api import KarakeepAPI, datatypes


# --- Offline HTTP fake for unit tests (no live server required) ---

OFFLINE_ENDPOINT = "https://karakeep.test/api/v1/"


class FakeResponse:
    """Minimal stand-in for requests.Response used by the offline unit tests."""

    def __init__(self, status_code=200, json_data=None, content=None, headers=None):
        self.status_code = status_code
        if json_data is not None:
            self.content = json.dumps(json_data).encode("utf-8")
        elif isinstance(content, str):
            self.content = content.encode("utf-8")
        else:
            self.content = content or b""
        self.headers = headers or {}

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content.decode("utf-8"))

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"{self.status_code} Error", response=self
            )


class FakeHTTP:
    """Routes requests.request calls to canned FakeResponse objects and records them."""

    def __init__(self):
        self.routes = {}
        self.calls = []
        # KarakeepAPI.__init__ performs a connection check against users/me.
        self.add("GET", "users/me", FakeResponse(json_data={"id": "test-user"}))

    def add(self, method, path, response):
        """Register a response for a path relative to /api/v1/ (e.g. 'bookmarks')."""
        self.routes[(method.upper(), path.strip("/"))] = response

    def __call__(self, method, url, **kwargs):
        path = urlparse(url).path
        # Strip the /api/v1/ prefix so routes can be registered by relative path.
        rel_path = path.split("/api/v1/", 1)[-1].strip("/")
        self.calls.append(
            {"method": method.upper(), "url": url, "path": rel_path, **kwargs}
        )
        key = (method.upper(), rel_path)
        if key not in self.routes:
            raise AssertionError(f"FakeHTTP received an unrouted request: {key}")
        response = self.routes[key]
        if callable(response):
            return response(method, url, **kwargs)
        return response


@pytest.fixture
def fake_http(monkeypatch):
    """Patch requests.request with an in-memory router and isolate the env vars."""
    for var in (
        "KARAKEEP_PYTHON_API_KEY",
        "KARAKEEP_PYTHON_API_ENDPOINT",
        "KARAKEEP_PYTHON_API_VERBOSE",
        "KARAKEEP_PYTHON_API_RATE_LIMIT",
        "KARAKEEP_PYTHON_API_DISABLE_RESPONSE_VALIDATION",
        "KARAKEEP_PYTHON_API_VERIFY_SSL",
        "KARAKEEP_PYTHON_API_ENSURE_ASCII",
    ):
        monkeypatch.delenv(var, raising=False)
    fake = FakeHTTP()
    monkeypatch.setattr(requests, "request", fake)
    return fake


@pytest.fixture
def offline_client(fake_http):
    """A KarakeepAPI client whose HTTP layer is fully faked."""
    client = KarakeepAPI(
        api_key="test-key",
        api_endpoint=OFFLINE_ENDPOINT,
        verbose=False,
    )
    return client


@pytest.fixture
def karakeep_client():
    """
    Fixture that provides a configured Karakeep API client.

    Requires the following environment variables:
    - KARAKEEP_PYTHON_API_ENDPOINT
    - KARAKEEP_PYTHON_API_KEY
    - KARAKEEP_PYTHON_API_VERIFY_SSL (optional, defaults to true)
    """
    api_endpoint = os.environ.get("KARAKEEP_PYTHON_API_ENDPOINT")
    api_key = os.environ.get("KARAKEEP_PYTHON_API_KEY")
    verify_ssl_str = os.environ.get("KARAKEEP_PYTHON_API_VERIFY_SSL", "true")

    if not api_endpoint or not api_key:
        missing = []
        if not api_endpoint:
            missing.append("KARAKEEP_PYTHON_API_ENDPOINT")
        if not api_key:
            missing.append("KARAKEEP_PYTHON_API_KEY")
        pytest.skip(
            f"Missing required environment variables for Karakeep API tests: {', '.join(missing)}. Set these to run integration tests."
        )

    verify_ssl = verify_ssl_str.lower() in ("true", "1", "yes")

    # Instantiate the client using standard environment variables
    # KarakeepAPI constructor handles api_endpoint and api_key directly
    return KarakeepAPI(
        api_endpoint=api_endpoint,
        api_key=api_key,
        verify_ssl=verify_ssl,
        verbose=True,  # Enable verbose logging for tests
    )


@pytest.fixture
def managed_bookmark(karakeep_client: KarakeepAPI) -> datatypes.Bookmark:
    """
    Fixture to create a bookmark before a test and delete it afterwards.
    Yields the created bookmark object.
    """
    created_bookmark_id: Optional[str] = None
    # Generate unique URL and title to avoid collisions and aid debugging
    timestamp = int(time.time())
    random_suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    test_url = f"https://example.com/test_page_fixture_{timestamp}_{random_suffix}"
    original_title = f"Managed Fixture Bookmark {timestamp}-{random_suffix}"

    print(
        f"\n  FIXTURE SETUP: Attempting to create bookmark (URL: {test_url}, Title: '{original_title}')"
    )
    try:
        # Create the bookmark
        bookmark = karakeep_client.create_a_new_bookmark(
            type="link", url=test_url, title=original_title
        )
        assert isinstance(bookmark, datatypes.Bookmark), (
            "Fixture: create_a_new_bookmark should return a Bookmark model"
        )
        assert bookmark.id, "Fixture: Created bookmark must have an ID"
        created_bookmark_id = bookmark.id
        print(
            f"  FIXTURE SETUP: ✓ Successfully created bookmark with ID: {created_bookmark_id}"
        )

        yield bookmark  # Provide the bookmark to the test function

    finally:
        # Teardown: Delete the bookmark
        if created_bookmark_id:
            print(
                f"\n  FIXTURE TEARDOWN: Attempting to delete bookmark ID: {created_bookmark_id}"
            )
            try:
                karakeep_client.delete_a_bookmark(bookmark_id=created_bookmark_id)
                print(
                    f"  FIXTURE TEARDOWN: ✓ Successfully deleted bookmark ID: {created_bookmark_id}"
                )
            except Exception as e:
                # Log error during teardown but don't let it mask original test failure
                print(
                    f"  FIXTURE TEARDOWN: ERROR during bookmark deletion for ID {created_bookmark_id}: {e}"
                )
        else:
            print("\n  FIXTURE TEARDOWN: No bookmark ID recorded, skipping deletion.")
