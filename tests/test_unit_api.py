"""Offline unit tests for KarakeepAPI.

These tests fake the HTTP layer (see FakeHTTP in conftest.py) so they run
without a live Karakeep server, unlike the integration tests in
test_karakeep_api.py which require KARAKEEP_PYTHON_API_ENDPOINT/KEY.
"""

import json
import time

import pytest
import requests
from loguru import logger
from pydantic import ValidationError

from karakeep_python_api import KarakeepAPI, APIError, AuthenticationError, datatypes

# The tests directory is on sys.path under pytest's default import mode, both for
# `pytest` and `python -m pytest`, so the shared offline helpers import directly.
from conftest import OFFLINE_ENDPOINT, FakeResponse


@pytest.fixture(autouse=True)
def _quiet_logger():
    """Each KarakeepAPI() adds a loguru sink; drop them so they don't pile up."""
    yield
    logger.remove()


# --- Canned API payloads matching the Pydantic schemas ---

BOOKMARK = {
    "id": "bm123456",
    "createdAt": "2026-01-01T00:00:00.000Z",
    "modifiedAt": None,
    "title": "A bookmark",
    "archived": False,
    "favourited": False,
    "taggingStatus": "success",
    "summarizationStatus": None,
    "embeddingStatus": None,
    "userId": "u1",
    "tags": [],
    "content": {"type": "link", "url": "https://example.com"},
    "assets": [],
}
PAGINATED_BOOKMARKS = {"bookmarks": [BOOKMARK], "nextCursor": None}
LIST_MODEL = {
    "id": "list1",
    "name": "My List",
    "icon": "star",
    "parentId": None,
    "public": False,
    "hasCollaborators": False,
    "userRole": "owner",
}
TAG = {
    "id": "tag1",
    "name": "python",
    "numBookmarks": 1,
    "numBookmarksByAttachedType": {"ai": 0, "human": 1},
}
HIGHLIGHT = {
    "bookmarkId": "bm123456",
    "startOffset": 0,
    "endOffset": 5,
    "color": "yellow",
    "text": "hello",
    "note": None,
    "id": "hl1",
    "userId": "u1",
    "createdAt": "2026-01-01T00:00:00.000Z",
}
BACKUP = {
    "id": "backup1",
    "userId": "u1",
    "assetId": None,
    "createdAt": "2026-01-01T00:00:00.000Z",
    "size": 123.0,
    "bookmarkCount": 2,
    "status": "success",
}
FEED = {
    "id": "feed1",
    "name": "My Feed",
    "url": "https://example.com/rss.xml",
    "enabled": True,
    "importTags": False,
    "lastFetchedStatus": None,
    "lastFetchedAt": None,
    "lastSuccessfulFetchAt": None,
}
READABLE_CONTENT = {
    "bookmarkId": "bm123456",
    "bookmarkType": "link",
    "format": "markdown",
    "content": "hello",
    "contentVersion": "v1",
    "range": {"start": 0, "end": 5, "total": 5},
    "nextCursor": None,
    "truncated": False,
}
SIGNED_URL = {
    "assetId": "asset123",
    "signedUrl": "https://karakeep.test/signed?sig=abc",
    "expiresAt": "2026-01-01T01:00:00.000Z",
}
UPLOADED_ASSET = {
    "assetId": "asset123",
    "contentType": "application/pdf",
    "size": 100.0,
    "fileName": "doc.pdf",
}


# --- Exception classes ---


def test_api_error_str_with_and_without_status_code():
    assert str(APIError("boom")) == "boom"
    assert str(APIError("boom", status_code=500)) == "[Status Code: 500] boom"


def test_authentication_error_has_401_status():
    err = AuthenticationError("bad key")
    assert err.status_code == 401
    assert "bad key" in str(err)


# --- __init__ validation and configuration ---


def test_init_requires_api_key(fake_http):
    with pytest.raises(ValueError, match="API Key is required"):
        KarakeepAPI(api_endpoint=OFFLINE_ENDPOINT)


def test_init_requires_endpoint(fake_http):
    with pytest.raises(ValueError, match="API endpoint is required"):
        KarakeepAPI(api_key="k")


def test_init_reads_key_and_endpoint_from_env(fake_http, monkeypatch):
    monkeypatch.setenv("KARAKEEP_PYTHON_API_KEY", "env-key")
    monkeypatch.setenv("KARAKEEP_PYTHON_API_ENDPOINT", OFFLINE_ENDPOINT)
    client = KarakeepAPI()
    assert client.api_key == "env-key"
    assert client.api_endpoint == OFFLINE_ENDPOINT


@pytest.mark.parametrize(
    "given, expected",
    [
        ("https://karakeep.test/api/v1/", "https://karakeep.test/api/v1/"),
        ("https://karakeep.test/api/v1", "https://karakeep.test/api/v1/"),
        ("https://karakeep.test", "https://karakeep.test/api/v1/"),
        ("https://karakeep.test/", "https://karakeep.test/api/v1/"),
    ],
)
def test_init_normalizes_endpoint(fake_http, given, expected):
    client = KarakeepAPI(api_key="k", api_endpoint=given)
    assert client.api_endpoint == expected


def test_init_verbose_from_env(fake_http, monkeypatch):
    monkeypatch.setenv("KARAKEEP_PYTHON_API_VERBOSE", "true")
    client = KarakeepAPI(api_key="k", api_endpoint=OFFLINE_ENDPOINT)
    assert client.verbose is True


def test_init_rate_limit_from_argument_and_env(fake_http, monkeypatch):
    client = KarakeepAPI(api_key="k", api_endpoint=OFFLINE_ENDPOINT, rate_limit=2.5)
    assert client.rate_limit == 2.5

    monkeypatch.setenv("KARAKEEP_PYTHON_API_RATE_LIMIT", "1.5")
    client = KarakeepAPI(api_key="k", api_endpoint=OFFLINE_ENDPOINT)
    assert client.rate_limit == 1.5

    monkeypatch.setenv("KARAKEEP_PYTHON_API_RATE_LIMIT", "not-a-number")
    client = KarakeepAPI(api_key="k", api_endpoint=OFFLINE_ENDPOINT)
    assert client.rate_limit == 0.0


def test_init_disable_response_validation_from_env(fake_http, monkeypatch):
    monkeypatch.setenv("KARAKEEP_PYTHON_API_DISABLE_RESPONSE_VALIDATION", "true")
    client = KarakeepAPI(api_key="k", api_endpoint=OFFLINE_ENDPOINT)
    assert client.disable_response_validation is True


def test_init_loads_default_openapi_spec(offline_client):
    assert isinstance(offline_client.openapi_spec, dict)
    assert "openapi" in offline_client.openapi_spec


def test_init_missing_openapi_spec_is_not_fatal(fake_http, tmp_path):
    client = KarakeepAPI(
        api_key="k",
        api_endpoint=OFFLINE_ENDPOINT,
        openapi_spec_path=str(tmp_path / "does-not-exist.json"),
    )
    assert client.openapi_spec is None


def test_init_invalid_openapi_spec_is_not_fatal(fake_http, tmp_path):
    bad_spec = tmp_path / "bad.json"
    bad_spec.write_text("{ this is not json")
    client = KarakeepAPI(
        api_key="k", api_endpoint=OFFLINE_ENDPOINT, openapi_spec_path=str(bad_spec)
    )
    assert client.openapi_spec is None


def test_init_openapi_spec_path_is_a_directory(fake_http, tmp_path):
    # Reading a directory raises an OSError, which must not be fatal either.
    client = KarakeepAPI(
        api_key="k", api_endpoint=OFFLINE_ENDPOINT, openapi_spec_path=str(tmp_path)
    )
    assert client.openapi_spec is None


def test_init_connection_check_auth_failure(fake_http):
    fake_http.add(
        "GET", "users/me", FakeResponse(status_code=401, json_data={"message": "nope"})
    )
    with pytest.raises(AuthenticationError):
        KarakeepAPI(api_key="bad-key", api_endpoint=OFFLINE_ENDPOINT)


def test_init_connection_check_unexpected_error(fake_http, monkeypatch):
    def boom(self):
        raise RuntimeError("kaput")

    monkeypatch.setattr(KarakeepAPI, "get_current_user_info", boom)
    with pytest.raises(APIError, match="Unexpected error during client initialization"):
        KarakeepAPI(api_key="k", api_endpoint=OFFLINE_ENDPOINT)


# --- _enforce_rate_limit ---


def test_enforce_rate_limit_sleeps_when_calls_are_too_close(offline_client, monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    offline_client.rate_limit = 5.0
    offline_client.last_request_time = time.monotonic()
    offline_client._enforce_rate_limit()
    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= 5.0


def test_enforce_rate_limit_noop_when_disabled(offline_client, monkeypatch):
    monkeypatch.setattr(
        time, "sleep", lambda s: pytest.fail("sleep should not be called")
    )
    offline_client.rate_limit = 0.0
    offline_client._enforce_rate_limit()


# --- _call: request building ---


def test_call_filters_none_params_and_stringifies_booleans(offline_client, fake_http):
    fake_http.add("GET", "bookmarks", FakeResponse(json_data=PAGINATED_BOOKMARKS))
    offline_client.get_all_bookmarks(archived=True)
    request = fake_http.calls[-1]
    assert request["params"]["archived"] == "true"
    assert request["params"]["includeContent"] == "true"
    assert "favourited" not in request["params"]
    assert request["headers"]["Authorization"] == "Bearer test-key"


def test_call_serializes_pydantic_model_body(offline_client, fake_http):
    fake_http.add("POST", "echo", FakeResponse(json_data={"ok": True}))
    model = datatypes.CheckUrlResponse(bookmarkId="bm1")
    result = offline_client._call("POST", "echo", data=model)
    assert result == {"ok": True}
    request = fake_http.calls[-1]
    assert json.loads(request["data"]) == {"bookmarkId": "bm1"}
    assert request["headers"]["Content-Type"] == "application/json"


def test_call_serializes_dict_and_list_bodies(offline_client, fake_http):
    fake_http.add("POST", "echo", FakeResponse(json_data={"ok": True}))
    offline_client._call("POST", "echo", data={"a": 1})
    assert json.loads(fake_http.calls[-1]["data"]) == {"a": 1}
    offline_client._call("POST", "echo", data=[1, 2])
    assert json.loads(fake_http.calls[-1]["data"]) == [1, 2]


def test_call_rejects_unserializable_dict_body(offline_client, fake_http):
    fake_http.add("POST", "echo", FakeResponse(json_data={"ok": True}))
    with pytest.raises(APIError, match="Failed to JSON encode"):
        offline_client._call("POST", "echo", data={"bad": object()})


def test_call_passes_raw_str_and_bytes_bodies(offline_client, fake_http):
    fake_http.add("POST", "echo", FakeResponse(json_data={"ok": True}))
    offline_client._call("POST", "echo", data="raw text")
    assert fake_http.calls[-1]["data"] == "raw text"
    offline_client._call("POST", "echo", data=b"\x00\x01")
    assert fake_http.calls[-1]["data"] == b"\x00\x01"


def test_call_content_type_mismatch_warning_paths(offline_client, fake_http):
    # dict body with a non-JSON Content-Type, and str body with a JSON Content-Type:
    # both must still be sent (the client only warns).
    fake_http.add("POST", "echo", FakeResponse(json_data={"ok": True}))
    offline_client._call(
        "POST", "echo", data={"a": 1}, extra_headers={"Content-Type": "text/plain"}
    )
    assert fake_http.calls[-1]["headers"]["Content-Type"] == "text/plain"
    offline_client._call(
        "POST",
        "echo",
        data='{"a": 1}',
        extra_headers={"Content-Type": "application/json"},
    )
    assert fake_http.calls[-1]["data"] == '{"a": 1}'


def test_call_files_upload_drops_content_type_and_data(offline_client, fake_http):
    fake_http.add("POST", "assets", FakeResponse(json_data=UPLOADED_ASSET))
    files = {"file": ("doc.pdf", b"%PDF", "application/pdf")}
    offline_client._call(
        "POST",
        "assets",
        data={"ignored": True},
        files=files,
        extra_headers={"Content-Type": "application/json"},
    )
    request = fake_http.calls[-1]
    assert request["files"] == files
    assert request["data"] is None
    assert "Content-Type" not in request["headers"]


# --- _call: response handling and errors ---


def test_call_returns_none_for_204(offline_client, fake_http):
    fake_http.add("DELETE", "bookmarks/bm123456", FakeResponse(status_code=204))
    assert offline_client.delete_a_bookmark(bookmark_id="bm123456") is None


def test_call_returns_bytes_for_non_json_accept(offline_client, fake_http):
    fake_http.add(
        "GET",
        "raw-data",
        FakeResponse(content=b"\x89PNG", headers={"Content-Type": "image/png"}),
    )
    result = offline_client._call("GET", "raw-data", extra_headers={"Accept": "*/*"})
    assert result == b"\x89PNG"


def test_call_raises_authentication_error_on_401(offline_client, fake_http):
    fake_http.add(
        "GET", "whoami", FakeResponse(status_code=401, json_data={"message": "denied"})
    )
    with pytest.raises(AuthenticationError, match="Authentication failed"):
        offline_client._call("GET", "whoami")


def test_call_401_with_non_json_body(offline_client, fake_http):
    fake_http.add("GET", "whoami", FakeResponse(status_code=401, content=b"denied"))
    with pytest.raises(AuthenticationError):
        offline_client._call("GET", "whoami")


def test_call_raises_api_error_with_json_message(offline_client, fake_http):
    fake_http.add(
        "GET",
        "missing",
        FakeResponse(status_code=404, json_data={"message": "no such thing"}),
    )
    with pytest.raises(APIError, match="no such thing") as excinfo:
        offline_client._call("GET", "missing")
    assert excinfo.value.status_code == 404


def test_call_truncates_long_error_bodies(offline_client, fake_http):
    fake_http.add(
        "GET", "broken", FakeResponse(status_code=500, content=b"x" * 2000)
    )
    with pytest.raises(APIError) as excinfo:
        offline_client._call("GET", "broken")
    assert excinfo.value.status_code == 500
    assert "..." in excinfo.value.message


def test_call_html_error_body(offline_client, fake_http):
    html = "<html><body><h1>Service unavailable</h1></body></html>"
    fake_http.add("GET", "broken", FakeResponse(status_code=503, content=html))
    with pytest.raises(APIError) as excinfo:
        offline_client._call("GET", "broken")
    assert excinfo.value.status_code == 503


def test_call_invalid_json_on_success_raises(offline_client, fake_http):
    fake_http.add("GET", "garbled", FakeResponse(content=b"not json at all"))
    with pytest.raises(APIError, match="Failed to parse"):
        offline_client._call("GET", "garbled")


def test_call_timeout_raises_api_error(offline_client, fake_http):
    def raise_timeout(method, url, **kwargs):
        raise requests.exceptions.Timeout("too slow")

    fake_http.add("GET", "slow", raise_timeout)
    with pytest.raises(APIError, match="timed out"):
        offline_client._call("GET", "slow")


def test_call_connection_error_raises_api_error(offline_client, fake_http):
    def raise_conn(method, url, **kwargs):
        raise requests.exceptions.ConnectionError("refused")

    fake_http.add("GET", "down", raise_conn)
    with pytest.raises(APIError, match="Connection error"):
        offline_client._call("GET", "down")


def test_call_generic_request_exception_raises_api_error(offline_client, fake_http):
    def raise_generic(method, url, **kwargs):
        raise requests.exceptions.RequestException("weird failure")

    fake_http.add("GET", "odd", raise_generic)
    with pytest.raises(APIError, match="weird failure"):
        offline_client._call("GET", "odd")


def test_call_retries_on_max_retries_exceeded(offline_client, fake_http, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    attempts = {"n": 0}

    def flaky(method, url, **kwargs):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise requests.exceptions.ConnectionError("Max retries exceeded with url")
        return FakeResponse(json_data={"ok": True})

    fake_http.add("GET", "flaky", flaky)
    assert offline_client._call("GET", "flaky") == {"ok": True}
    assert attempts["n"] == 3


def test_call_gives_up_after_max_retries(offline_client, fake_http, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)

    def always_fail(method, url, **kwargs):
        raise requests.exceptions.ConnectionError("Max retries exceeded with url")

    fake_http.add("GET", "dead", always_fail)
    with pytest.raises(APIError):
        offline_client._call("GET", "dead")


# --- Endpoint wrappers: happy paths ---


@pytest.mark.parametrize(
    "method_name, kwargs, http_method, path, response, expected_type",
    [
        ("get_all_bookmarks", {}, "GET", "bookmarks", PAGINATED_BOOKMARKS, datatypes.PaginatedBookmarks),
        ("search_bookmarks", {"q": "test"}, "GET", "bookmarks/search", PAGINATED_BOOKMARKS, datatypes.PaginatedBookmarks),
        ("check_url", {"url": "https://example.com"}, "GET", "bookmarks/check-url", {"bookmarkId": None}, datatypes.CheckUrlResponse),
        ("get_a_single_bookmark", {"bookmark_id": "bm123456"}, "GET", "bookmarks/bm123456", BOOKMARK, datatypes.Bookmark),
        ("update_a_bookmark", {"bookmark_id": "bm123456", "update_data": {"title": "new"}}, "PATCH", "bookmarks/bm123456", {"id": "bm123456", "title": "new"}, dict),
        ("summarize_a_bookmark", {"bookmark_id": "bm123456"}, "POST", "bookmarks/bm123456/summarize", {"id": "bm123456", "summary": "s"}, dict),
        ("get_bookmark_readable_content", {"bookmark_id": "bm123456"}, "GET", "bookmarks/bm123456/content", READABLE_CONTENT, datatypes.BookmarkReadableContent),
        ("attach_tags_to_a_bookmark", {"bookmark_id": "bm123456", "tag_names": ["python"]}, "POST", "bookmarks/bm123456/tags", {"attached": ["tag1"]}, dict),
        ("detach_tags_from_a_bookmark", {"bookmark_id": "bm123456", "tag_ids": ["tag1"]}, "DELETE", "bookmarks/bm123456/tags", {"detached": ["tag1"]}, dict),
        ("get_lists_of_a_bookmark", {"bookmark_id": "bm123456"}, "GET", "bookmarks/bm123456/lists", {"lists": [LIST_MODEL]}, list),
        ("get_highlights_of_a_bookmark", {"bookmark_id": "bm123456"}, "GET", "bookmarks/bm123456/highlights", {"highlights": [HIGHLIGHT]}, list),
        ("attach_asset", {"bookmark_id": "bm123456", "asset_id": "a1", "asset_type": "pdf"}, "POST", "bookmarks/bm123456/assets", {"id": "a1", "assetType": "pdf"}, datatypes.BookmarkAsset),
        ("replace_asset", {"bookmark_id": "bm123456", "asset_id": "a1", "new_asset_id": "a2"}, "PUT", "bookmarks/bm123456/assets/a1", None, type(None)),
        ("detach_asset", {"bookmark_id": "bm123456", "asset_id": "a1"}, "DELETE", "bookmarks/bm123456/assets/a1", None, type(None)),
        ("get_all_lists", {}, "GET", "lists", {"lists": [LIST_MODEL]}, list),
        ("create_a_new_list", {"name": "My List", "icon": "star"}, "POST", "lists", LIST_MODEL, datatypes.ListModel),
        ("get_a_single_list", {"list_id": "list1"}, "GET", "lists/list1", LIST_MODEL, datatypes.ListModel),
        ("delete_a_list", {"list_id": "list1"}, "DELETE", "lists/list1", None, type(None)),
        ("update_a_list", {"list_id": "list1", "name": "Renamed"}, "PATCH", "lists/list1", LIST_MODEL, datatypes.ListModel),
        ("get_bookmarks_in_the_list", {"list_id": "list1"}, "GET", "lists/list1/bookmarks", PAGINATED_BOOKMARKS, datatypes.PaginatedBookmarks),
        ("add_a_bookmark_to_a_list", {"list_id": "list1", "bookmark_id": "bm123456"}, "PUT", "lists/list1/bookmarks/bm123456", None, type(None)),
        ("remove_a_bookmark_from_a_list", {"list_id": "list1", "bookmark_id": "bm123456"}, "DELETE", "lists/list1/bookmarks/bm123456", None, type(None)),
        ("get_all_tags", {}, "GET", "tags", {"tags": [TAG], "nextCursor": None}, datatypes.PaginatedTags),
        ("create_a_new_tag", {"name": " python "}, "POST", "tags", {"id": "tag1", "name": "python"}, dict),
        ("get_a_single_tag", {"tag_id": "tag1"}, "GET", "tags/tag1", TAG, datatypes.Tag),
        ("delete_a_tag", {"tag_id": "tag1"}, "DELETE", "tags/tag1", None, type(None)),
        ("update_a_tag", {"tag_id": "tag1", "update_data": {"name": "new"}}, "PATCH", "tags/tag1", {"id": "tag1", "name": "new"}, dict),
        ("get_bookmarks_with_the_tag", {"tag_id": "tag1"}, "GET", "tags/tag1/bookmarks", PAGINATED_BOOKMARKS, datatypes.PaginatedBookmarks),
        ("get_all_highlights", {}, "GET", "highlights", {"highlights": [HIGHLIGHT], "nextCursor": None}, datatypes.PaginatedHighlights),
        ("create_a_new_highlight", {"bookmark_id": "bm123456", "start_offset": 0, "end_offset": 5}, "POST", "highlights", HIGHLIGHT, datatypes.Highlight),
        ("get_a_single_highlight", {"highlight_id": "hl1"}, "GET", "highlights/hl1", HIGHLIGHT, datatypes.Highlight),
        ("delete_a_highlight", {"highlight_id": "hl1"}, "DELETE", "highlights/hl1", HIGHLIGHT, datatypes.Highlight),
        ("update_a_highlight", {"highlight_id": "hl1", "color": "red"}, "PATCH", "highlights/hl1", HIGHLIGHT, datatypes.Highlight),
        ("get_current_user_info", {}, "GET", "users/me", {"id": "test-user"}, dict),
        ("get_current_user_stats", {}, "GET", "users/me/stats", {"numBookmarks": 5}, dict),
        ("update_user", {"user_id": "u1", "role": "admin"}, "PUT", "admin/users/u1", {"success": True}, dict),
        ("get_all_backups", {}, "GET", "backups", {"backups": [BACKUP]}, list),
        ("trigger_a_new_backup", {}, "POST", "backups", BACKUP, datatypes.Backup),
        ("get_a_single_backup", {"backup_id": "backup1"}, "GET", "backups/backup1", BACKUP, datatypes.Backup),
        ("delete_a_backup", {"backup_id": "backup1"}, "DELETE", "backups/backup1", None, type(None)),
        ("get_asset_signed_url", {"asset_id": "asset123"}, "GET", "assets/asset123/signed-url", SIGNED_URL, datatypes.SignedAssetUrl),
        ("admin_trigger_recrawl", {}, "POST", "admin/jobs/trigger/recrawl", {"success": True}, dict),
        ("admin_trigger_reindex", {}, "POST", "admin/jobs/trigger/reindex", {"success": True}, dict),
        ("admin_trigger_inference", {"type": "tag"}, "POST", "admin/jobs/trigger/inference", {"success": True}, dict),
        ("get_all_feeds", {}, "GET", "feeds", {"feeds": [FEED]}, list),
        ("create_a_new_feed", {"name": "My Feed", "url": "https://example.com/rss.xml"}, "POST", "feeds", FEED, datatypes.Feed),
        ("get_a_single_feed", {"feed_id": "feed1"}, "GET", "feeds/feed1", FEED, datatypes.Feed),
        ("update_a_feed", {"feed_id": "feed1", "name": "Renamed"}, "PATCH", "feeds/feed1", FEED, datatypes.Feed),
        ("delete_a_feed", {"feed_id": "feed1"}, "DELETE", "feeds/feed1", None, type(None)),
        ("fetch_a_feed", {"feed_id": "feed1"}, "POST", "feeds/feed1/fetch", None, type(None)),
    ],
)
def test_endpoint_wrappers_happy_path(
    offline_client, fake_http, method_name, kwargs, http_method, path, response, expected_type
):
    if response is None:
        fake_http.add(http_method, path, FakeResponse(status_code=204))
    else:
        fake_http.add(http_method, path, FakeResponse(json_data=response))

    result = getattr(offline_client, method_name)(**kwargs)

    request = fake_http.calls[-1]
    assert request["method"] == http_method
    assert request["path"] == path
    assert isinstance(result, expected_type)
    if expected_type is list and result:
        # List endpoints must return validated models, not raw dicts.
        assert not isinstance(result[0], dict)


@pytest.mark.parametrize(
    "method_name, kwargs, path, response",
    [
        ("get_all_bookmarks", {}, "bookmarks", PAGINATED_BOOKMARKS),
        ("get_all_lists", {}, "lists", {"lists": [LIST_MODEL]}),
        ("get_all_feeds", {}, "feeds", {"feeds": [FEED]}),
    ],
)
def test_disable_response_validation_returns_raw_data(
    fake_http, method_name, kwargs, path, response
):
    client = KarakeepAPI(
        api_key="k", api_endpoint=OFFLINE_ENDPOINT, disable_response_validation=True
    )
    fake_http.add("GET", path, FakeResponse(json_data=response))
    result = getattr(client, method_name)(**kwargs)
    assert result == response


@pytest.mark.parametrize(
    "method_name, kwargs, path",
    [
        ("get_all_lists", {}, "lists"),
        ("get_all_backups", {}, "backups"),
        ("get_all_feeds", {}, "feeds"),
        ("get_lists_of_a_bookmark", {"bookmark_id": "bm123456"}, "bookmarks/bm123456/lists"),
        ("get_highlights_of_a_bookmark", {"bookmark_id": "bm123456"}, "bookmarks/bm123456/highlights"),
    ],
)
def test_list_endpoints_reject_unexpected_response_shape(
    offline_client, fake_http, method_name, kwargs, path
):
    fake_http.add("GET", path, FakeResponse(json_data={"unexpected": "shape"}))
    with pytest.raises(APIError, match="Unexpected response format"):
        getattr(offline_client, method_name)(**kwargs)


# --- Endpoint wrappers: argument validation (no HTTP involved) ---


@pytest.mark.parametrize(
    "method_name, kwargs, match",
    [
        ("create_a_new_bookmark", {"type": "link"}, "'url' is required"),
        ("create_a_new_bookmark", {"type": "text"}, "'text' is required"),
        ("create_a_new_bookmark", {"type": "asset", "assetId": "a1"}, "'asset_type'"),
        ("create_a_new_bookmark", {"type": "asset", "asset_type": "pdf"}, "'assetId' is required"),
        ("update_a_bookmark", {"bookmark_id": "b", "update_data": {}}, "at least one field"),
        ("attach_tags_to_a_bookmark", {"bookmark_id": "b"}, "At least one of"),
        ("attach_tags_to_a_bookmark", {"bookmark_id": "b", "tag_ids": ["  "]}, "non-empty string"),
        ("attach_tags_to_a_bookmark", {"bookmark_id": "b", "tag_names": [" "]}, "non-empty string"),
        ("detach_tags_from_a_bookmark", {"bookmark_id": "b"}, "At least one of"),
        ("detach_tags_from_a_bookmark", {"bookmark_id": "b", "tag_ids": [""]}, "non-empty string"),
        ("detach_tags_from_a_bookmark", {"bookmark_id": "b", "tag_names": [" "]}, "non-empty string"),
        ("create_a_new_list", {"name": "n", "icon": "i", "list_type": "smart"}, "'query' is required"),
        ("update_a_list", {"list_id": "l"}, "At least one field"),
        ("create_a_new_tag", {"name": "   "}, "cannot be empty"),
        ("update_a_tag", {"tag_id": "t", "update_data": {}}, "at least one field"),
        ("update_a_highlight", {"highlight_id": "h"}, "At least one field"),
        ("update_user", {"user_id": "u"}, "At least one field"),
        ("update_a_feed", {"feed_id": "f"}, "At least one field"),
        ("download_a_backup", {"backup_id": "   "}, "cannot be empty"),
        ("download_a_backup", {"backup_id": "abc"}, "invalid"),
        ("get_a_single_asset", {"asset_id": ""}, "cannot be empty"),
        ("get_a_single_asset", {"asset_id": "abc"}, "invalid"),
        ("get_asset_signed_url", {"asset_id": " "}, "cannot be empty"),
    ],
)
def test_wrapper_argument_validation(offline_client, method_name, kwargs, match):
    with pytest.raises(ValueError, match=match):
        getattr(offline_client, method_name)(**kwargs)


# --- create_a_new_bookmark request bodies ---


def test_create_bookmark_link_body(offline_client, fake_http):
    fake_http.add("POST", "bookmarks", FakeResponse(json_data=BOOKMARK))
    result = offline_client.create_a_new_bookmark(
        type="link",
        url="https://example.com",
        title="A bookmark",
        archived=False,
        favourited=True,
        note="a note",
        summary="a summary",
        createdAt="2026-01-01T00:00:00.000Z",
        crawlPriority="low",
        importSessionId="imp1",
        source="cli",
        precrawledArchiveId="arch1",
    )
    assert isinstance(result, datatypes.Bookmark)
    body = json.loads(fake_http.calls[-1]["data"])
    assert body["type"] == "link"
    assert body["url"] == "https://example.com"
    assert body["favourited"] is True
    assert body["crawlPriority"] == "low"
    assert body["source"] == "cli"
    assert body["precrawledArchiveId"] == "arch1"


def test_create_bookmark_text_and_asset_bodies(offline_client, fake_http):
    fake_http.add("POST", "bookmarks", FakeResponse(json_data=BOOKMARK))
    offline_client.create_a_new_bookmark(
        type="text", text="hello world", sourceUrl="https://src.example.com"
    )
    body = json.loads(fake_http.calls[-1]["data"])
    assert body == {
        "type": "text",
        "text": "hello world",
        "sourceUrl": "https://src.example.com",
    }

    offline_client.create_a_new_bookmark(
        type="asset",
        asset_type="pdf",
        assetId="asset123",
        fileName="doc.pdf",
        sourceUrl="https://src.example.com",
    )
    body = json.loads(fake_http.calls[-1]["data"])
    assert body["assetType"] == "pdf"
    assert body["assetId"] == "asset123"
    assert body["fileName"] == "doc.pdf"


# --- Tag attach/detach bodies ---


def test_attach_tags_builds_expected_body(offline_client, fake_http):
    fake_http.add(
        "POST", "bookmarks/bm123456/tags", FakeResponse(json_data={"attached": []})
    )
    offline_client.attach_tags_to_a_bookmark(
        bookmark_id="bm123456",
        tag_ids=[" tag1 "],
        tag_names=["python"],
        attached_by="ai",
    )
    body = json.loads(fake_http.calls[-1]["data"])
    assert body == {
        "tags": [
            {"tagId": "tag1", "attachedBy": "ai"},
            {"tagName": "python", "attachedBy": "ai"},
        ]
    }


def test_detach_tags_omits_attached_by_when_none(offline_client, fake_http):
    fake_http.add(
        "DELETE", "bookmarks/bm123456/tags", FakeResponse(json_data={"detached": []})
    )
    offline_client.detach_tags_from_a_bookmark(
        bookmark_id="bm123456", tag_names=["python"], attached_by=None
    )
    body = json.loads(fake_http.calls[-1]["data"])
    assert body == {"tags": [{"tagName": "python"}]}


def test_detach_tags_by_name_includes_attached_by(offline_client, fake_http):
    fake_http.add(
        "DELETE", "bookmarks/bm123456/tags", FakeResponse(json_data={"detached": []})
    )
    offline_client.detach_tags_from_a_bookmark(
        bookmark_id="bm123456", tag_names=["python"]
    )
    body = json.loads(fake_http.calls[-1]["data"])
    assert body == {"tags": [{"tagName": "python", "attachedBy": "human"}]}


# --- Binary endpoints ---


def test_download_a_backup_returns_bytes(offline_client, fake_http):
    fake_http.add(
        "GET",
        "backups/backup123/download",
        FakeResponse(content=b"PK\x03\x04zipdata", headers={"Content-Type": "application/zip"}),
    )
    data = offline_client.download_a_backup(backup_id="backup123")
    assert data == b"PK\x03\x04zipdata"
    assert fake_http.calls[-1]["headers"]["Accept"] == "application/zip"


def test_download_a_backup_empty_response(offline_client, fake_http):
    fake_http.add("GET", "backups/backup123/download", FakeResponse(status_code=204))
    assert offline_client.download_a_backup(backup_id="backup123") == b""


def test_download_a_backup_unexpected_json_raises(offline_client, monkeypatch):
    monkeypatch.setattr(
        offline_client, "_call", lambda *a, **k: {"error": "not bytes"}
    )
    with pytest.raises(APIError, match="Expected bytes"):
        offline_client.download_a_backup(backup_id="backup123")


def test_get_a_single_asset_returns_bytes(offline_client, fake_http):
    fake_http.add(
        "GET",
        "assets/asset123",
        FakeResponse(content=b"%PDF-1.4", headers={"Content-Type": "application/pdf"}),
    )
    data = offline_client.get_a_single_asset(asset_id="asset123")
    assert data == b"%PDF-1.4"
    assert fake_http.calls[-1]["headers"]["Accept"] == "*/*"


def test_get_a_single_asset_empty_response(offline_client, fake_http):
    fake_http.add("GET", "assets/asset123", FakeResponse(status_code=204))
    assert offline_client.get_a_single_asset(asset_id="asset123") == b""


def test_get_a_single_asset_unexpected_json_raises(offline_client, monkeypatch):
    monkeypatch.setattr(offline_client, "_call", lambda *a, **k: {"oops": 1})
    with pytest.raises(APIError, match="Expected bytes"):
        offline_client.get_a_single_asset(asset_id="asset123")


# --- upload_a_new_asset ---


def test_upload_a_new_asset(offline_client, fake_http, tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    fake_http.add("POST", "assets", FakeResponse(json_data=UPLOADED_ASSET))
    result = offline_client.upload_a_new_asset(file=str(f))
    assert isinstance(result, datatypes.UploadedAsset)
    files = fake_http.calls[-1]["files"]
    assert files["file"][0] == "doc.pdf"
    assert files["file"][1] == b"%PDF-1.4 fake"
    assert files["file"][2] == "application/pdf"


def test_upload_a_new_asset_missing_file(offline_client, tmp_path):
    with pytest.raises(FileNotFoundError):
        offline_client.upload_a_new_asset(file=str(tmp_path / "nope.pdf"))


def test_upload_a_new_asset_read_failure_raises_api_error(
    offline_client, fake_http, tmp_path, monkeypatch
):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF")

    def unreadable(*args, **kwargs):
        raise IOError("permission denied")

    monkeypatch.setattr("builtins.open", unreadable)
    with pytest.raises(APIError, match="Failed to read file"):
        offline_client.upload_a_new_asset(file=str(f))


def test_upload_a_new_asset_verbose(fake_http, tmp_path):
    client = KarakeepAPI(api_key="k", api_endpoint=OFFLINE_ENDPOINT, verbose=True)
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF")
    fake_http.add("POST", "assets", FakeResponse(json_data=UPLOADED_ASSET))
    assert isinstance(
        client.upload_a_new_asset(file=str(f)), datatypes.UploadedAsset
    )


def test_upload_a_new_asset_unknown_mime_type(offline_client, fake_http, tmp_path):
    f = tmp_path / "mystery.zzz-unknown"
    f.write_bytes(b"data")
    fake_http.add("POST", "assets", FakeResponse(json_data=UPLOADED_ASSET))
    offline_client.upload_a_new_asset(file=str(f))
    assert fake_http.calls[-1]["files"]["file"][2] == "application/octet-stream"


# --- get_bookmark_readable_content pagination ---


def test_readable_content_fetch_all_walks_cursors(offline_client, fake_http):
    pages = [
        {**READABLE_CONTENT, "content": "part1 ", "nextCursor": "c2", "truncated": True},
        {**READABLE_CONTENT, "content": "part2", "nextCursor": None},
    ]
    state = {"i": 0}

    def paged(method, url, **kwargs):
        page = pages[state["i"]]
        state["i"] += 1
        return FakeResponse(json_data=page)

    fake_http.add("GET", "bookmarks/bm123456/content", paged)
    result = offline_client.get_bookmark_readable_content(
        bookmark_id="bm123456", fetch_all=True
    )
    assert isinstance(result, datatypes.BookmarkReadableContent)
    assert result.content == "part1 part2"
    assert result.nextCursor is None
    assert result.truncated is False


def test_readable_content_fetch_all_rejects_non_dict(offline_client, fake_http):
    fake_http.add(
        "GET", "bookmarks/bm123456/content", FakeResponse(json_data=["not", "a", "dict"])
    )
    with pytest.raises(APIError, match="Unexpected response format"):
        offline_client.get_bookmark_readable_content(
            bookmark_id="bm123456", fetch_all=True
        )


def test_readable_content_fetch_all_rejects_non_dict_continuation(
    offline_client, fake_http
):
    pages = [
        FakeResponse(json_data={**READABLE_CONTENT, "nextCursor": "c2"}),
        FakeResponse(json_data=["still", "not", "a", "dict"]),
    ]
    state = {"i": 0}

    def paged(method, url, **kwargs):
        page = pages[state["i"]]
        state["i"] += 1
        return page

    fake_http.add("GET", "bookmarks/bm123456/content", paged)
    with pytest.raises(APIError, match="Unexpected response format"):
        offline_client.get_bookmark_readable_content(
            bookmark_id="bm123456", fetch_all=True
        )


# --- Response validation failures surface as ValidationError ---


def test_validation_error_on_bad_response_shape(offline_client, fake_http):
    fake_http.add(
        "GET", "bookmarks/bm123456", FakeResponse(json_data={"id": "bm123456"})
    )
    with pytest.raises(ValidationError):
        offline_client.get_a_single_bookmark(bookmark_id="bm123456")


@pytest.mark.parametrize(
    "method_name, kwargs, path, response",
    [
        ("get_all_lists", {}, "lists", {"lists": [{"bad": "shape"}]}),
        ("get_all_backups", {}, "backups", {"backups": [{"bad": "shape"}]}),
        (
            "get_highlights_of_a_bookmark",
            {"bookmark_id": "bm123456"},
            "bookmarks/bm123456/highlights",
            {"highlights": [{"bad": "shape"}]},
        ),
        (
            "get_lists_of_a_bookmark",
            {"bookmark_id": "bm123456"},
            "bookmarks/bm123456/lists",
            {"lists": [{"bad": "shape"}]},
        ),
    ],
)
def test_list_endpoints_reraise_element_validation_errors(
    offline_client, fake_http, method_name, kwargs, path, response
):
    fake_http.add("GET", path, FakeResponse(json_data=response))
    with pytest.raises(ValidationError):
        getattr(offline_client, method_name)(**kwargs)


# --- Verbose logging code paths ---


def test_verbose_client_exercises_debug_logging(fake_http, monkeypatch):
    client = KarakeepAPI(api_key="k", api_endpoint=OFFLINE_ENDPOINT, verbose=True)
    assert client.verbose is True

    # JSON request/response logging (with a long body to hit truncation).
    fake_http.add(
        "POST", "echo", FakeResponse(json_data={"data": "x" * 2000})
    )
    client._call("POST", "echo", data={"payload": "y" * 1000})

    # 204 logging.
    fake_http.add("DELETE", "gone", FakeResponse(status_code=204))
    client._call("DELETE", "gone")

    # Binary response logging.
    fake_http.add("GET", "backups/backup123/download", FakeResponse(content=b"zip"))
    assert client.download_a_backup(backup_id="backup123") == b"zip"

    # Binary asset retrieval logging.
    fake_http.add("GET", "assets/asset123", FakeResponse(content=b"img"))
    assert client.get_a_single_asset(asset_id="asset123") == b"img"

    # Empty binary responses log a dedicated message.
    fake_http.add("GET", "backups/backup123/download", FakeResponse(status_code=204))
    assert client.download_a_backup(backup_id="backup123") == b""
    fake_http.add("GET", "assets/asset123", FakeResponse(status_code=204))
    assert client.get_a_single_asset(asset_id="asset123") == b""

    # Verbose rate limit logging.
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    client.rate_limit = 5.0
    client.last_request_time = time.monotonic()
    client._enforce_rate_limit()
    assert sleeps


# --- Optional request-body fields ---


def test_create_a_new_list_with_all_optional_fields(offline_client, fake_http):
    fake_http.add("POST", "lists", FakeResponse(json_data=LIST_MODEL))
    offline_client.create_a_new_list(
        name="Smart",
        icon="star",
        description="a smart list",
        parent_id="parent1",
        list_type="smart",
        query="is:fav",
        public=True,
    )
    body = json.loads(fake_http.calls[-1]["data"])
    assert body["description"] == "a smart list"
    assert body["parentId"] == "parent1"
    assert body["type"] == "smart"
    assert body["query"] == "is:fav"
    assert body["public"] is True


def test_update_a_list_sends_all_provided_fields(offline_client, fake_http):
    fake_http.add("PATCH", "lists/list1", FakeResponse(json_data=LIST_MODEL))
    offline_client.update_a_list(
        list_id="list1",
        name="n",
        description="d",
        icon="i",
        parent_id="p",
        query="q",
        public=False,
    )
    body = json.loads(fake_http.calls[-1]["data"])
    assert body == {
        "name": "n",
        "description": "d",
        "icon": "i",
        "parentId": "p",
        "query": "q",
        "public": False,
    }


def test_update_a_feed_sends_all_provided_fields(offline_client, fake_http):
    fake_http.add("PATCH", "feeds/feed1", FakeResponse(json_data=FEED))
    offline_client.update_a_feed(
        feed_id="feed1",
        name="n",
        url="https://example.com/new.xml",
        enabled=False,
        import_tags=True,
    )
    body = json.loads(fake_http.calls[-1]["data"])
    assert body == {
        "name": "n",
        "url": "https://example.com/new.xml",
        "enabled": False,
        "importTags": True,
    }


def test_update_user_sends_all_provided_fields(offline_client, fake_http):
    fake_http.add("PUT", "admin/users/u1", FakeResponse(json_data={"success": True}))
    offline_client.update_user(
        user_id="u1",
        role="user",
        bookmark_quota=10,
        storage_quota=1000,
        browser_crawling_enabled=True,
    )
    body = json.loads(fake_http.calls[-1]["data"])
    assert body == {
        "role": "user",
        "bookmarkQuota": 10,
        "storageQuota": 1000,
        "browserCrawlingEnabled": True,
    }


# --- disable_response_validation across the remaining endpoint families ---


@pytest.mark.parametrize(
    "method_name, kwargs, http_method, path, response",
    [
        ("search_bookmarks", {"q": "x"}, "GET", "bookmarks/search", PAGINATED_BOOKMARKS),
        ("check_url", {"url": "https://example.com"}, "GET", "bookmarks/check-url", {"bookmarkId": None}),
        ("get_a_single_bookmark", {"bookmark_id": "bm123456"}, "GET", "bookmarks/bm123456", BOOKMARK),
        ("create_a_new_bookmark", {"type": "link", "url": "https://example.com"}, "POST", "bookmarks", BOOKMARK),
        ("get_bookmark_readable_content", {"bookmark_id": "bm123456"}, "GET", "bookmarks/bm123456/content", READABLE_CONTENT),
        ("get_lists_of_a_bookmark", {"bookmark_id": "bm123456"}, "GET", "bookmarks/bm123456/lists", {"lists": [LIST_MODEL]}),
        ("get_highlights_of_a_bookmark", {"bookmark_id": "bm123456"}, "GET", "bookmarks/bm123456/highlights", {"highlights": [HIGHLIGHT]}),
        ("attach_asset", {"bookmark_id": "bm123456", "asset_id": "a1", "asset_type": "pdf"}, "POST", "bookmarks/bm123456/assets", {"id": "a1", "assetType": "pdf"}),
        ("create_a_new_list", {"name": "n", "icon": "i"}, "POST", "lists", LIST_MODEL),
        ("get_a_single_list", {"list_id": "list1"}, "GET", "lists/list1", LIST_MODEL),
        ("update_a_list", {"list_id": "list1", "name": "n"}, "PATCH", "lists/list1", LIST_MODEL),
        ("get_bookmarks_in_the_list", {"list_id": "list1"}, "GET", "lists/list1/bookmarks", PAGINATED_BOOKMARKS),
        ("get_all_tags", {}, "GET", "tags", {"tags": [TAG], "nextCursor": None}),
        ("get_a_single_tag", {"tag_id": "tag1"}, "GET", "tags/tag1", TAG),
        ("get_bookmarks_with_the_tag", {"tag_id": "tag1"}, "GET", "tags/tag1/bookmarks", PAGINATED_BOOKMARKS),
        ("get_all_highlights", {}, "GET", "highlights", {"highlights": [HIGHLIGHT], "nextCursor": None}),
        ("create_a_new_highlight", {"bookmark_id": "bm123456", "start_offset": 0, "end_offset": 5}, "POST", "highlights", HIGHLIGHT),
        ("get_a_single_highlight", {"highlight_id": "hl1"}, "GET", "highlights/hl1", HIGHLIGHT),
        ("delete_a_highlight", {"highlight_id": "hl1"}, "DELETE", "highlights/hl1", HIGHLIGHT),
        ("update_a_highlight", {"highlight_id": "hl1", "color": "red"}, "PATCH", "highlights/hl1", HIGHLIGHT),
        ("get_all_backups", {}, "GET", "backups", {"backups": [BACKUP]}),
        ("trigger_a_new_backup", {}, "POST", "backups", BACKUP),
        ("get_a_single_backup", {"backup_id": "backup1"}, "GET", "backups/backup1", BACKUP),
        ("get_asset_signed_url", {"asset_id": "asset123"}, "GET", "assets/asset123/signed-url", SIGNED_URL),
        ("create_a_new_feed", {"name": "n", "url": "https://example.com/rss.xml"}, "POST", "feeds", FEED),
        ("get_a_single_feed", {"feed_id": "feed1"}, "GET", "feeds/feed1", FEED),
        ("update_a_feed", {"feed_id": "feed1", "name": "n"}, "PATCH", "feeds/feed1", FEED),
    ],
)
def test_disable_response_validation_all_wrappers(
    fake_http, method_name, kwargs, http_method, path, response
):
    client = KarakeepAPI(
        api_key="k", api_endpoint=OFFLINE_ENDPOINT, disable_response_validation=True
    )
    fake_http.add(http_method, path, FakeResponse(json_data=response))
    result = getattr(client, method_name)(**kwargs)
    assert result == response


def test_disable_validation_upload_and_readable_content_fetch_all(fake_http, tmp_path):
    client = KarakeepAPI(
        api_key="k", api_endpoint=OFFLINE_ENDPOINT, disable_response_validation=True
    )
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF")
    fake_http.add("POST", "assets", FakeResponse(json_data=UPLOADED_ASSET))
    assert client.upload_a_new_asset(file=str(f)) == UPLOADED_ASSET

    fake_http.add(
        "GET", "bookmarks/bm123456/content", FakeResponse(json_data=READABLE_CONTENT)
    )
    result = client.get_bookmark_readable_content(bookmark_id="bm123456", fetch_all=True)
    assert result["content"] == READABLE_CONTENT["content"]
    assert result["nextCursor"] is None
