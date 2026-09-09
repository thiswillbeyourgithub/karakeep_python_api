import pytest
from loguru import logger
import os
import subprocess
import random
import string
import time
import beartype  # to trigger the runtime typechecking
import json  # Added for CLI test payload generation

# Import API, errors, and datatypes from the main package
from karakeep_python_api import KarakeepAPI, APIError, AuthenticationError, datatypes

# Note: The karakeep_client fixture is defined in conftest.py and provides a valid client instance.

# --- Offline datatype regression tests (no live server required) ---


def test_bookmark_accepts_null_tagging_status():
    """Regression: ``Bookmark.taggingStatus`` must accept ``null``.

    The Karakeep server can legitimately return ``taggingStatus: null`` (observed
    on a ``POST /api/v1/bookmarks`` response for an already-existing bookmark).
    Before the fix, ``taggingStatus`` was a required non-nullable ``Literal`` and
    ``Bookmark.model_validate`` raised a ``ValidationError`` on ``None``. This test
    fails before the fix and passes after it. It runs offline (no fixture needed)
    so the regression is guarded even without integration credentials.
    """
    bookmark = datatypes.Bookmark.model_validate(
        {
            "id": "wfoq4z9wu05to35tcnv8hbsr",
            "createdAt": "2026-07-05T08:00:02.000Z",
            "modifiedAt": "2026-07-05T08:00:02.000Z",
            "title": None,
            "archived": False,
            "favourited": True,
            "taggingStatus": None,
            "summarizationStatus": None,
            "embeddingStatus": None,
            "note": None,
            "summary": None,
            "userId": "user123",
            "tags": [],
            "content": {"type": "link", "url": "https://example.com"},
            "assets": [],
        }
    )
    assert bookmark.taggingStatus is None
    assert bookmark.summarizationStatus is None
    assert bookmark.embeddingStatus is None


def test_bookmark_parses_first_created_at_and_embedding_status():
    """``Bookmark`` must accept the fields added by the newer Karakeep spec.

    ``firstCreatedAt`` (optional) preserves the original creation timestamp when a
    bookmark is recreated, and ``embeddingStatus`` (required, nullable) reports the
    vector-embedding job used by semantic/hybrid search. Both were absent from the
    model before, and pydantic silently dropped them on validation.
    """
    bookmark = datatypes.Bookmark.model_validate(
        {
            "id": "wfoq4z9wu05to35tcnv8hbsr",
            "firstCreatedAt": "2026-01-02T03:04:05.000Z",
            "createdAt": "2026-07-05T08:00:02.000Z",
            "modifiedAt": "2026-07-05T08:00:02.000Z",
            "title": None,
            "archived": False,
            "favourited": True,
            "taggingStatus": "success",
            "summarizationStatus": "success",
            "embeddingStatus": "pending",
            "userId": "user123",
            "tags": [],
            "content": {"type": "link", "url": "https://example.com"},
            "assets": [],
        }
    )
    assert bookmark.firstCreatedAt == "2026-01-02T03:04:05.000Z"
    assert bookmark.embeddingStatus == "pending"


def test_link_content_parses_reader_view_fields():
    """``ContentTypeLink`` must accept the reader-view fields added by the new spec.

    The crawler now reports whether a distraction-free reader view could be
    extracted (``readerViewStatus``), how confident it is (``readerViewScore``,
    0-100) and which rendering the UI should prefer (``preferredPreview``).
    """
    bookmark = datatypes.Bookmark.model_validate(
        {
            "id": "wfoq4z9wu05to35tcnv8hbsr",
            "createdAt": "2026-07-05T08:00:02.000Z",
            "modifiedAt": None,
            "archived": False,
            "favourited": False,
            "taggingStatus": None,
            "summarizationStatus": None,
            "embeddingStatus": None,
            "userId": "user123",
            "tags": [],
            "content": {
                "type": "link",
                "url": "https://example.com",
                "readerViewStatus": "readable",
                "readerViewScore": 87,
                "preferredPreview": "reader_view",
            },
            "assets": [],
        }
    )
    assert bookmark.content.readerViewStatus == "readable"
    assert bookmark.content.readerViewScore == 87
    assert bookmark.content.preferredPreview == "reader_view"


def test_bookmark_requires_embedding_status():
    """``embeddingStatus`` is required (though nullable) in the upstream schema.

    Keeping it required means a server response that omits it is reported as a
    schema mismatch instead of silently defaulting to ``None``, which would hide
    the fact that the client is talking to an older Karakeep than it expects.
    """
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        datatypes.Bookmark.model_validate(
            {
                "id": "wfoq4z9wu05to35tcnv8hbsr",
                "createdAt": "2026-07-05T08:00:02.000Z",
                "modifiedAt": None,
                "archived": False,
                "favourited": False,
                "userId": "user123",
                "tags": [],
                "content": {"type": "unknown"},
                "assets": [],
            }
        )


def _readable_chunk(*, content, start, end, total, next_cursor, version="v1"):
    """Build a GET /bookmarks/{id}/content payload for the offline chunking tests."""
    return {
        "bookmarkId": "bm123",
        "bookmarkType": "link",
        "format": "markdown",
        "content": content,
        "contentVersion": version,
        "range": {"start": start, "end": end, "total": total},
        "nextCursor": next_cursor,
        "truncated": next_cursor is not None,
    }


def test_get_bookmark_readable_content_single_chunk(monkeypatch):
    """Without ``fetch_all`` the method returns exactly one chunk and one request.

    The cursor is left untouched so callers can drive the pagination themselves.
    """
    calls = []

    def fake_call(self, method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs.get("params")))
        return _readable_chunk(
            content="first", start=0, end=5, total=10, next_cursor="cursor-2"
        )

    monkeypatch.setattr(KarakeepAPI, "_call", fake_call, raising=True)
    client = KarakeepAPI.__new__(KarakeepAPI)
    client.disable_response_validation = False

    result = client.get_bookmark_readable_content(bookmark_id="bm123", max_chars=5)

    assert len(calls) == 1
    assert calls[0][1] == "bookmarks/bm123/content"
    assert calls[0][2]["maxChars"] == 5
    assert result.content == "first"
    assert result.nextCursor == "cursor-2"
    assert result.truncated is True


def test_get_bookmark_readable_content_fetch_all_merges_chunks(monkeypatch):
    """``fetch_all=True`` walks ``nextCursor`` and merges every chunk into one object.

    The merged result must span the whole document: content concatenated in order,
    range from the first chunk's start to the last chunk's end, and no leftover
    cursor so callers can tell the read is complete.
    """
    pages = [
        _readable_chunk(
            content="alpha ", start=0, end=6, total=16, next_cursor="cursor-2"
        ),
        _readable_chunk(
            content="beta ", start=6, end=11, total=16, next_cursor="cursor-3"
        ),
        _readable_chunk(content="gamma", start=11, end=16, total=16, next_cursor=None),
    ]
    seen_cursors = []

    def fake_call(self, method, endpoint, **kwargs):
        params = kwargs.get("params") or {}
        seen_cursors.append(params.get("cursor"))
        return pages[len(seen_cursors) - 1]

    monkeypatch.setattr(KarakeepAPI, "_call", fake_call, raising=True)
    client = KarakeepAPI.__new__(KarakeepAPI)
    client.disable_response_validation = False

    result = client.get_bookmark_readable_content(bookmark_id="bm123", fetch_all=True)

    assert seen_cursors == [None, "cursor-2", "cursor-3"]
    assert result.content == "alpha beta gamma"
    assert result.range.start == 0
    assert result.range.end == 16
    assert result.range.total == 16
    assert result.nextCursor is None
    assert result.truncated is False


@pytest.mark.parametrize(
    "command, option, method_name",
    [
        ("download-a-backup", "--backup-id", "download_a_backup"),
        ("get-a-single-asset", "--asset-id", "get_a_single_asset"),
    ],
)
@pytest.mark.parametrize(
    "payload",
    [b"PK\x03\x04\x00\x01\xff\xfe binary \x00 data", b""],
    ids=["binary", "empty"],
)
def test_cli_binary_result_written_raw(
    monkeypatch, command, option, method_name, payload
):
    """Regression: CLI commands returning bytes must not go through ``json.dumps``.

    ``download_a_backup`` and ``get_a_single_asset`` return raw bytes. The shared
    CLI result handler used to feed every result to ``json.dumps``, which raised
    ``TypeError: Object of type bytes is not JSON serializable`` after the download
    had already succeeded. The bytes are now written verbatim to stdout (no
    encoding, no trailing newline) so the output can be redirected into a file.
    This test fails before the fix and passes after it, and runs offline.
    """
    from click.testing import CliRunner
    from karakeep_python_api import __main__ as cli_main

    # Keep everything offline: the real __init__ validates credentials over HTTP.
    monkeypatch.setattr(
        cli_main.KarakeepAPI, "__init__", lambda self, **kwargs: None, raising=True
    )
    monkeypatch.setattr(
        cli_main.KarakeepAPI, method_name, lambda self, **kwargs: payload, raising=True
    )

    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(
        cli_main.cli,
        [
            "--api-endpoint",
            "https://example.invalid/api/v1/",
            "--api-key",
            "dummy-key",
            command,
            option,
            "someid123",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, f"CLI failed: {result.stderr}"
    assert result.stdout_bytes == payload, (
        f"Expected the raw bytes on stdout, got {result.stdout_bytes!r}"
    )


# --- Test 'Get All' Endpoints ---


def test_get_all_bookmarks_paginated(karakeep_client: KarakeepAPI):
    """Test retrieving bookmarks with pagination."""
    try:
        # Get the first page
        page1 = karakeep_client.get_all_bookmarks(limit=2)
        assert isinstance(page1, datatypes.PaginatedBookmarks), (
            "Response should be PaginatedBookmarks model"
        )
        assert isinstance(page1.bookmarks, list), "Bookmarks attribute should be a list"
        assert len(page1.bookmarks) <= 2, "Should return at most 'limit' bookmarks"
        logger.info(f"✓ Retrieved first page with {len(page1.bookmarks)} bookmarks.")

        # If there's a next cursor, get the next page
        if page1.nextCursor:
            logger.info(
                f"  Attempting to fetch next page with cursor: {page1.nextCursor}"
            )
            page2 = karakeep_client.get_all_bookmarks(limit=2, cursor=page1.nextCursor)
            assert isinstance(page2, datatypes.PaginatedBookmarks)
            assert isinstance(page2.bookmarks, list)
            assert len(page2.bookmarks) <= 2
            logger.info(
                f"✓ Retrieved second page with {len(page2.bookmarks)} bookmarks."
            )
            # Ensure bookmarks are different from page 1 (simple check)
            if page1.bookmarks and page2.bookmarks:
                assert page1.bookmarks[0].id != page2.bookmarks[0].id, (
                    "Bookmarks on page 1 and 2 should differ"
                )
        else:
            logger.info("  No next cursor found, pagination test ends.")

    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during paginated bookmark retrieval: {e}")
    except Exception as e:
        pytest.fail(
            f"An unexpected error occurred during paginated bookmark retrieval: {e}"
        )

    # --- Add CLI call ---
    try:
        logger.info("\n  Running CLI equivalent: get-all-bookmarks --limit 2")
        # Assumes KARAKEEP_PYTHON_API_ENDPOINT and KARAKEEP_PYTHON_API_KEY are set in env
        subprocess.run(
            "python -m karakeep_python_api get-all-bookmarks --limit 2",
            shell=True,
            check=True,
            capture_output=True,  # Capture output to avoid logger.infoing it during tests unless verbose
            text=True,
        )
        logger.info("✓ CLI command executed successfully.")
    except subprocess.CalledProcessError as e:
        logger.info(f"  CLI command failed with exit code {e.returncode}")
        # logger.info stdout/stderr only if the command failed to aid debugging
        logger.info(f"  Stdout: {e.stdout}")
        logger.info(f"  Stderr: {e.stderr}")
        pytest.fail(f"CLI command 'get-all-bookmarks --limit 2' failed: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred running the CLI command: {e}")


def test_get_all_lists(karakeep_client: KarakeepAPI):
    """Test retrieving all lists."""
    try:
        lists = karakeep_client.get_all_lists()
        assert isinstance(lists, list), "Response should be a list"
        if lists:  # Only check elements if the list is not empty
            assert all(isinstance(item, datatypes.ListModel) for item in lists), (
                "All items should be ListModel instances"
            )
        logger.info(f"✓ Successfully retrieved {len(lists)} lists.")
    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during list retrieval: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred during list retrieval: {e}")

    # --- Add CLI call ---
    try:
        logger.info("\n  Running CLI equivalent: get-all-lists")
        # Assumes KARAKEEP_PYTHON_API_ENDPOINT and KARAKEEP_PYTHON_API_KEY are set in env
        subprocess.run(
            "python -m karakeep_python_api get-all-lists",
            shell=True,
            check=True,
            capture_output=True,  # Capture output to avoid logger.infoing it during tests unless verbose
            text=True,
        )
        logger.info("✓ CLI command executed successfully.")
    except subprocess.CalledProcessError as e:
        logger.info(f"  CLI command failed with exit code {e.returncode}")
        # logger.info stdout/stderr only if the command failed to aid debugging
        logger.info(f"  Stdout: {e.stdout}")
        logger.info(f"  Stderr: {e.stderr}")
        pytest.fail(f"CLI command 'get-all-lists' failed: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred running the CLI command: {e}")


def test_get_all_tags(karakeep_client: KarakeepAPI):
    """Test retrieving all tags."""
    try:
        tags = karakeep_client.get_all_tags()
        assert isinstance(tags, datatypes.PaginatedTags), (
            "Response should be of type PaginatedTags"
        )
        tags = tags.tags
        assert isinstance(tags, list), "tags var should be of type list at this point"
        if tags:  # Only check elements if the list is not empty
            assert all(isinstance(item, datatypes.Tag) for item in tags), (
                "All items should be Tag instances"
            )
        logger.info(f"✓ Successfully retrieved {len(tags)} tags.")
    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during tag retrieval: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred during tag retrieval: {e}")

    # --- Add CLI call ---
    try:
        logger.info("\n  Running CLI equivalent: get-all-tags")
        # Assumes KARAKEEP_PYTHON_API_ENDPOINT and KARAKEEP_PYTHON_API_KEY are set in env
        subprocess.run(
            "python -m karakeep_python_api get-all-tags",
            shell=True,
            check=True,
            capture_output=True,  # Capture output to avoid logger.infoing it during tests unless verbose
            text=True,
        )
        logger.info("✓ CLI command executed successfully.")
    except subprocess.CalledProcessError as e:
        logger.info(f"  CLI command failed with exit code {e.returncode}")
        # logger.info stdout/stderr only if the command failed to aid debugging
        logger.info(f"  Stdout: {e.stdout}")
        logger.info(f"  Stderr: {e.stderr}")
        pytest.fail(f"CLI command 'get-all-tags' failed: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred running the CLI command: {e}")


def test_get_all_highlights_paginated(karakeep_client: KarakeepAPI):
    """Test retrieving highlights with pagination."""
    try:
        # Get the first page
        page1 = karakeep_client.get_all_highlights(limit=3)
        assert isinstance(page1, datatypes.PaginatedHighlights), (
            "Response should be PaginatedHighlights model"
        )
        assert isinstance(page1.highlights, list), (
            "Highlights attribute should be a list"
        )
        assert len(page1.highlights) <= 3, "Should return at most 'limit' highlights"
        logger.info(f"✓ Retrieved first page with {len(page1.highlights)} highlights.")

        # If there's a next cursor, get the next page
        if page1.nextCursor:
            logger.info(
                f"  Attempting to fetch next page with cursor: {page1.nextCursor}"
            )
            page2 = karakeep_client.get_all_highlights(limit=3, cursor=page1.nextCursor)
            assert isinstance(page2, datatypes.PaginatedHighlights)
            assert isinstance(page2.highlights, list)
            assert len(page2.highlights) <= 3
            logger.info(
                f"✓ Retrieved second page with {len(page2.highlights)} highlights."
            )
            # Ensure highlights are different from page 1 (simple check)
            if page1.highlights and page2.highlights:
                assert page1.highlights[0].id != page2.highlights[0].id, (
                    "Highlights on page 1 and 2 should differ"
                )
        else:
            logger.info("  No next cursor found, pagination test ends.")

    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during paginated highlight retrieval: {e}")
    except Exception as e:
        pytest.fail(
            f"An unexpected error occurred during paginated highlight retrieval: {e}"
        )

    # --- Add CLI call ---
    try:
        logger.info("\n  Running CLI equivalent: get-all-highlights --limit 3")
        # Assumes KARAKEEP_PYTHON_API_ENDPOINT and KARAKEEP_PYTHON_API_KEY are set in env
        subprocess.run(
            "python -m karakeep_python_api get-all-highlights --limit 3",
            shell=True,
            check=True,
            capture_output=True,  # Capture output to avoid logger.infoing it during tests unless verbose
            text=True,
        )
        logger.info("✓ CLI command executed successfully.")
    except subprocess.CalledProcessError as e:
        logger.info(f"  CLI command failed with exit code {e.returncode}")
        # logger.info stdout/stderr only if the command failed to aid debugging
        logger.info(f"  Stdout: {e.stdout}")
        logger.info(f"  Stderr: {e.stderr}")
        pytest.fail(f"CLI command 'get-all-highlights --limit 3' failed: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred running the CLI command: {e}")


# --- Test Client Initialization and Attributes ---


def test_openapi_spec_accessible(karakeep_client: KarakeepAPI):
    """Test that the openapi_spec attribute is loaded and accessible."""
    try:
        spec = karakeep_client.openapi_spec
        assert spec is not None, "openapi_spec attribute should not be None"
        assert isinstance(spec, dict), "openapi_spec should be a dictionary"
        # Check for a top-level key expected in an OpenAPI spec
        assert "openapi" in spec, (
            "openapi_spec should contain the 'openapi' version key"
        )
        logger.info(
            f"✓ Successfully accessed openapi_spec attribute. Version: {spec.get('openapi', 'N/A')}"
        )
    except Exception as e:
        pytest.fail(f"An unexpected error occurred while accessing openapi_spec: {e}")

    # --- Add CLI call ---
    # The closest CLI equivalent is dumping the spec file content
    try:
        logger.info("\n  Running CLI equivalent: --dump-openapi-specification")
        # This command doesn't require API key or endpoint
        subprocess.run(
            "python -m karakeep_python_api --dump-openapi-specification",
            shell=True,
            check=True,
            capture_output=True,  # Capture output to avoid logger.infoing it during tests unless verbose
            text=True,
        )
        logger.info("✓ CLI command executed successfully.")
    except subprocess.CalledProcessError as e:
        logger.info(f"  CLI command failed with exit code {e.returncode}")
        # logger.info stdout/stderr only if the command failed to aid debugging
        logger.info(f"  Stdout: {e.stdout}")
        logger.info(f"  Stderr: {e.stderr}")
        pytest.fail(f"CLI command '--dump-openapi-specification' failed: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred running the CLI command: {e}")


# --- Test Create/Delete Operations ---


def test_create_and_delete_list(karakeep_client: KarakeepAPI):
    """Test creating a new list and then deleting it."""
    created_list_id = None  # Initialize to ensure it's available in finally block
    try:
        # 1. Generate a unique list name
        timestamp = int(time.time())
        random_suffix = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=6)
        )
        list_name = f"Test List {timestamp}-{random_suffix}"
        list_icon = "🧪"  # Test tube icon

        logger.info(
            f"\nAttempting to create list: Name='{list_name}', Icon='{list_icon}'"
        )

        # 2. Get initial list count (optional, for comparison)
        initial_lists = karakeep_client.get_all_lists()
        initial_list_count = len(initial_lists)
        logger.info(f"  Initial list count: {initial_list_count}")

        # 3. Create the new list
        created_list = karakeep_client.create_a_new_list(
            name=list_name, icon=list_icon, list_type="manual"
        )
        assert isinstance(created_list, datatypes.ListModel), (
            "Response should be a ListModel"
        )
        assert created_list.name == list_name, "Created list name should match"
        assert created_list.icon == list_icon, "Created list icon should match"
        assert created_list.id, "Created list must have an ID"
        created_list_id = created_list.id  # Store the ID for deletion
        logger.info(f"✓ Successfully created list with ID: {created_list_id}")

        # 4. Verify the list appears in get_all_lists
        current_lists_after_create = karakeep_client.get_all_lists()
        assert len(current_lists_after_create) == initial_list_count + 1, (
            "List count should increase by one after creation"
        )
        assert any(lst.id == created_list_id for lst in current_lists_after_create), (
            "Created list should be present in the list of all lists"
        )
        logger.info(f"  List count after creation: {len(current_lists_after_create)}")
        logger.info(f"✓ Verified list {created_list_id} is present in get_all_lists.")

        # 5. Verify the list exists by getting it directly (redundant but good check)
        retrieved_list = karakeep_client.get_a_single_list(list_id=created_list_id)
        assert isinstance(retrieved_list, datatypes.ListModel)
        assert retrieved_list.id == created_list_id
        logger.info(f"✓ Successfully retrieved the created list by ID.")

    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during list creation/verification: {e}")
    except Exception as e:
        pytest.fail(
            f"An unexpected error occurred during list creation/verification: {e}"
        )
    finally:
        # 6. Delete the list (ensure cleanup even if assertions fail)
        if created_list_id:
            logger.info(f"\nAttempting to delete list with ID: {created_list_id}")
            try:
                karakeep_client.delete_a_list(list_id=created_list_id)
                logger.info(f"✓ Successfully deleted list with ID: {created_list_id}")

                # 7. Verify the list is gone by trying to get it (should fail)
                try:
                    karakeep_client.get_a_single_list(list_id=created_list_id)
                    pytest.fail(
                        f"List with ID {created_list_id} should not exist after deletion, but get_a_single_list succeeded."
                    )
                except APIError as e:
                    assert e.status_code == 404, (
                        f"Expected 404 Not Found when getting deleted list, but got status {e.status_code}"
                    )
                    logger.info(
                        f"✓ Confirmed list {created_list_id} is deleted (received 404)."
                    )

                # 8. Verify list count decreased (optional check)
                final_lists = karakeep_client.get_all_lists()
                assert len(final_lists) == initial_list_count, (
                    "List count should return to initial count after deletion"
                )
                assert not any(lst.id == created_list_id for lst in final_lists), (
                    "Deleted list should not be present in the final list of all lists"
                )
                logger.info(f"  Final list count: {len(final_lists)}")

            except (APIError, AuthenticationError) as e:
                pytest.fail(f"API error during list deletion: {e}")
            except Exception as e:
                pytest.fail(f"An unexpected error occurred during list deletion: {e}")
        else:
            logger.info(
                "\nSkipping deletion because list creation failed or ID was not obtained."
            )


def test_create_and_delete_bookmark(
    karakeep_client: KarakeepAPI, managed_bookmark: datatypes.Bookmark
):
    """
    Test verifying a created bookmark (via fixture) and searching for it.
    The fixture handles creation and deletion.
    """
    created_bookmark_id = managed_bookmark.id
    test_url = managed_bookmark.content.url  # Get URL from fixture
    original_title = managed_bookmark.title  # Get title from fixture

    try:
        # 1. Bookmark is already created by the 'managed_bookmark' fixture.
        logger.info(
            f"\nUsing managed bookmark ID: {created_bookmark_id}, URL: '{test_url}', Title: '{original_title}'"
        )

        # 2. Verify the bookmark exists by getting it directly
        retrieved_bookmark = karakeep_client.get_a_single_bookmark(
            bookmark_id=created_bookmark_id
        )
        assert isinstance(retrieved_bookmark, datatypes.Bookmark)
        assert retrieved_bookmark.id == created_bookmark_id
        assert retrieved_bookmark.content.url == test_url
        assert retrieved_bookmark.title == original_title
        logger.info(f"✓ Successfully retrieved the managed bookmark by ID.")

        # 3. Search for the created bookmark
        # Use a search query that is likely to match the fixture's title
        # The fixture title is "Managed Fixture Bookmark {timestamp}-{random_suffix}"
        # A simple search for "Managed Fixture Bookmark" should work.
        # If the title is very dynamic, searching by URL might be more robust if supported,
        # or by a known part of the title.

        # waiting a bit for the indexation just in case
        time.sleep(30)

        search_queries = [
            "Managed Fixture Bookmark",
            "managed fixture bookmark",
            "managed fixture",
            "fixture managed",
            "fixture",
            '"fixture"',
        ]
        for trial, search_query_component in enumerate(search_queries):
            logger.info(
                f"\nAttempting to search for bookmark with query based on title: '{search_query_component}'. Retrying multiple times because search is nondeterministic."
            )
            search_results = karakeep_client.search_bookmarks(
                q=search_query_component, limit=100, include_content=False
            )
            assert isinstance(search_results, datatypes.PaginatedBookmarks), (
                "Search response should be PaginatedBookmarks model"
            )
            assert isinstance(search_results.bookmarks, list), (
                "Search results bookmarks attribute should be a list"
            )

            titles_in_search = [b.title for b in search_results.bookmarks]
            found_in_search = any(
                b.id == created_bookmark_id for b in search_results.bookmarks
            )
            if found_in_search:
                break
            else:
                time.sleep(3)
        assert found_in_search, (
            f"Managed bookmark {created_bookmark_id} (Title: '{original_title}') not found in {trial + 1} different search results for '{search_query_component}'. Titles were: '{titles_in_search}'."
        )
        logger.info(
            f"✓ Found managed bookmark in search results for '{search_query_component}'."
        )

        # 4. Test CLI search equivalent
        logger.info(
            f"\n  Running CLI equivalent: search-bookmarks --q '{search_query_component}' --limit 10 --include-content false"
        )
        try:
            cli_search_command = f"python -m karakeep_python_api search-bookmarks --q '{search_query_component}' --limit 10 --include-content false"
            search_cli_output = subprocess.run(
                cli_search_command,
                shell=True,
                check=True,
                capture_output=True,
                text=True,
            )
            assert created_bookmark_id in search_cli_output.stdout, (
                f"Managed bookmark ID {created_bookmark_id} not found in CLI search output for '{search_query_component}'"
            )
            logger.info(
                "✓ CLI search command executed successfully and contained the bookmark ID."
            )
        except subprocess.CalledProcessError as e:
            logger.info(f"  CLI search command failed with exit code {e.returncode}")
            logger.info(f"  Stdout: {e.stdout}")
            logger.info(f"  Stderr: {e.stderr}")
            pytest.fail(
                f"CLI command 'search-bookmarks --q \"{search_query_component}\"' failed: {e}"
            )
        except Exception as e:
            pytest.fail(
                f"An unexpected error occurred running the CLI search command: {e}"
            )

    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during bookmark verification/search: {e}")
    except Exception as e:
        pytest.fail(
            f"An unexpected error occurred during bookmark verification/search: {e}"
        )
    # No 'finally' block for deletion needed, as 'managed_bookmark' fixture handles it.
    # The fixture also handles verification of deletion.


def test_update_bookmark_title(
    karakeep_client: KarakeepAPI, managed_bookmark: datatypes.Bookmark
):
    """Test updating a bookmark's title via API and CLI, using a managed bookmark."""
    created_bookmark_id = managed_bookmark.id
    original_title = managed_bookmark.title  # Get the original title from the fixture

    target_api_title = "this is a test title"
    target_cli_title = "this is a test title (CLI)"

    try:
        # The bookmark is already created by the 'managed_bookmark' fixture.
        # We have its ID in created_bookmark_id and its original title.
        logger.info(
            f"\nUsing managed bookmark ID: {created_bookmark_id}, Original Title: '{original_title}'"
        )

        # 1. Update the bookmark's title using the API client
        logger.info(
            f"\nAttempting to update bookmark ID {created_bookmark_id} title to: '{target_api_title}' via API"
        )
        update_payload_api = {"title": target_api_title}
        updated_bookmark_partial = karakeep_client.update_a_bookmark(
            bookmark_id=created_bookmark_id, update_data=update_payload_api
        )
        assert isinstance(updated_bookmark_partial, dict), (
            "Update response should be a dict"
        )
        assert updated_bookmark_partial.get("title") == target_api_title, (
            f"Partial response title '{updated_bookmark_partial.get('title')}' does not match target API title '{target_api_title}'"
        )
        logger.info(
            f"✓ API call to update_a_bookmark successful. Partial response title: '{updated_bookmark_partial.get('title')}'"
        )

        # 2. Verify the API update by fetching the bookmark again
        logger.info(
            f"\nFetching bookmark ID {created_bookmark_id} to verify API title update."
        )
        retrieved_bookmark_after_api_update = karakeep_client.get_a_single_bookmark(
            bookmark_id=created_bookmark_id
        )
        assert isinstance(retrieved_bookmark_after_api_update, datatypes.Bookmark)
        assert retrieved_bookmark_after_api_update.title == target_api_title, (
            f"Retrieved bookmark title '{retrieved_bookmark_after_api_update.title}' does not match expected API-updated title '{target_api_title}'"
        )
        logger.info(
            f"✓ Successfully verified bookmark title updated by API to: '{retrieved_bookmark_after_api_update.title}'"
        )

        # 3. Test CLI equivalent for updating the bookmark's title
        logger.info(
            f"\n  Running CLI equivalent to update title to: '{target_cli_title}'"
        )
        cli_update_payload_json = json.dumps({"title": target_cli_title})
        # Ensure the JSON string is properly quoted for the shell command
        cli_update_command = f"python -m karakeep_python_api update-a-bookmark --bookmark-id {created_bookmark_id} --update-data '{cli_update_payload_json}'"

        try:
            subprocess.run(
                cli_update_command,
                shell=True,
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("✓ CLI update command executed successfully.")

            # 4. Verify CLI update by fetching the bookmark again
            logger.info(
                f"\nFetching bookmark ID {created_bookmark_id} to verify CLI title update."
            )
            retrieved_bookmark_after_cli_update = karakeep_client.get_a_single_bookmark(
                bookmark_id=created_bookmark_id
            )
            assert isinstance(retrieved_bookmark_after_cli_update, datatypes.Bookmark)
            assert retrieved_bookmark_after_cli_update.title == target_cli_title, (
                f"Retrieved bookmark title '{retrieved_bookmark_after_cli_update.title}' after CLI update does not match expected '{target_cli_title}'"
            )
            logger.info(
                f"✓ Successfully verified bookmark title updated by CLI to: '{retrieved_bookmark_after_cli_update.title}'"
            )

        except subprocess.CalledProcessError as e:
            logger.info(f"  CLI update command failed with exit code {e.returncode}")
            logger.info(f"  Command: {cli_update_command}")
            logger.info(f"  Stdout: {e.stdout}")
            logger.info(f"  Stderr: {e.stderr}")
            pytest.fail(f"CLI command for update-a-bookmark failed: {e}")
        except Exception as e:
            pytest.fail(
                f"An unexpected error occurred running the CLI update command: {e}"
            )

    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during bookmark title update test: {e}")
    except Exception as e:
        pytest.fail(
            f"An unexpected error occurred during bookmark title update test: {e}"
        )
    # No finally block needed for deletion, as 'managed_bookmark' fixture handles it.


def test_tag_lifecycle_on_bookmark(
    karakeep_client: KarakeepAPI, managed_bookmark: datatypes.Bookmark
):
    """
    Test attaching a tag to a bookmark, updating the tag, detaching it, and deleting it.
    Uses the managed_bookmark fixture.
    """
    bookmark_id = managed_bookmark.id
    timestamp = int(time.time())
    random_chars = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    initial_tag_name = f"test-tag-{timestamp}-{random_chars}"
    updated_tag_name = f"updated-tag-{timestamp}-{random_chars}"
    tag_id_to_manage = None

    try:
        # 1. Attach a new tag by name to the bookmark
        logger.info(
            f"\nAttempting to attach tag '{initial_tag_name}' to bookmark {bookmark_id}"
        )
        attach_response = karakeep_client.attach_tags_to_a_bookmark(
            bookmark_id=bookmark_id, tag_names=[initial_tag_name]
        )
        assert (
            "attached" in attach_response and len(attach_response["attached"]) == 1
        ), "Failed to attach tag or response format incorrect"
        tag_id_to_manage = attach_response["attached"][0]
        assert isinstance(tag_id_to_manage, str), "Attached tag ID should be a string"
        logger.info(f"✓ Tag '{initial_tag_name}' attached with ID: {tag_id_to_manage}")

        # 2. Update the tag's name
        logger.info(
            f"\nAttempting to update tag {tag_id_to_manage} to name '{updated_tag_name}'"
        )
        update_payload = {"name": updated_tag_name}
        updated_tag = karakeep_client.update_a_tag(
            tag_id=tag_id_to_manage, update_data=update_payload
        )
        # Do not check the type because karakeep 0.24.1 has a server side bug
        # assert isinstance(updated_tag, datatypes.Tag), "Update tag response should be Tag model"
        # assert updated_tag.name == updated_tag_name, "Tag name was not updated as expected"
        # logger.info(f"✓ Tag {tag_id_to_manage} updated to name '{updated_tag.name}'")
        assert updated_tag["name"] == updated_tag_name, (
            "Tag name was not updated as expected"
        )
        logger.info(f"✓ Tag {tag_id_to_manage} updated to name '{updated_tag['name']}'")

        # 3. Verify tag update by getting it directly
        logger.info(
            f"\nFetching tag {tag_id_to_manage} to verify its name is '{updated_tag_name}'"
        )
        retrieved_tag = karakeep_client.get_a_single_tag(tag_id=tag_id_to_manage)
        assert isinstance(retrieved_tag, datatypes.Tag), (
            "Get single tag response should be Tag model"
        )
        assert retrieved_tag.name == updated_tag_name, (
            "Retrieved tag name does not match updated name"
        )
        assert retrieved_tag.id == tag_id_to_manage, "Retrieved tag ID does not match"
        logger.info(
            f"✓ Verified tag {tag_id_to_manage} has name '{retrieved_tag.name}'"
        )

        # 4. Detach the tag from the bookmark
        logger.info(
            f"\nAttempting to detach tag {tag_id_to_manage} from bookmark {bookmark_id}"
        )
        detach_response = karakeep_client.detach_tags_from_a_bookmark(
            bookmark_id=bookmark_id, tag_ids=[tag_id_to_manage]
        )
        assert (
            "detached" in detach_response
            and tag_id_to_manage in detach_response["detached"]
        ), "Failed to detach tag or response format incorrect"
        logger.info(f"✓ Tag {tag_id_to_manage} detached from bookmark {bookmark_id}")

    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during tag lifecycle test: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred during tag lifecycle test: {e}")
    finally:
        # 5. Delete the tag (ensure cleanup even if assertions fail mid-test)
        if tag_id_to_manage:
            logger.info(f"\nAttempting to delete tag {tag_id_to_manage} (cleanup)")
            try:
                karakeep_client.delete_a_tag(tag_id=tag_id_to_manage)
                logger.info(f"✓ Successfully deleted tag {tag_id_to_manage}")

                # 6. Verify the tag is gone by trying to get it (should fail with 404)
                try:
                    karakeep_client.get_a_single_tag(tag_id=tag_id_to_manage)
                    pytest.fail(
                        f"Tag {tag_id_to_manage} should not exist after deletion, but get_a_single_tag succeeded."
                    )
                except APIError as e:
                    assert e.status_code == 404, (
                        f"Expected 404 Not Found when getting deleted tag, but got status {e.status_code}"
                    )
                    logger.info(
                        f"✓ Confirmed tag {tag_id_to_manage} is deleted (received 404)."
                    )
            except (APIError, AuthenticationError) as e:
                # Log error during cleanup but don't let it mask original test failure
                logger.info(
                    f"  API error during tag deletion (cleanup) for ID {tag_id_to_manage}: {e}"
                )
            except Exception as e:
                logger.info(
                    f"  Unexpected error during tag deletion (cleanup) for ID {tag_id_to_manage}: {e}"
                )
        else:
            logger.info(
                "\nSkipping tag deletion (cleanup) because tag_id was not obtained or test failed before creation."
            )


# --- Test User Info/Stats Endpoints ---


def test_cli_get_bookmarks_count_with_jq(karakeep_client: KarakeepAPI):
    """Test that CLI get-all-bookmarks with --limit returns the expected number of items."""
    # Skip test if jq is not installed
    try:
        subprocess.run(["jq", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("jq is not installed. This test requires jq for JSON processing.")

    # Define the limit we want to test
    test_limit = 200

    try:
        logger.info(f"\nRunning CLI command: get-all-bookmarks --limit={test_limit}")
        # Use a two-command pipe: Run the CLI command and pipe to jq to count array length
        cmd = f"python -m karakeep_python_api --verbose get-all-bookmarks --limit={test_limit} | jq 'length'"

        # Execute the piped command
        result = subprocess.run(
            cmd,
            shell=True,
            check=True,
            capture_output=True,
            text=True,
        )

        # Parse the output (should be just a number)
        try:
            actual_count = int(result.stdout.strip())
            logger.info(f"✓ Command returned {actual_count} bookmarks")

            # Check if we got exactly the requested number or fewer (if there aren't enough bookmarks)
            assert actual_count <= test_limit, (
                f"Expected at most {test_limit} bookmarks, got {actual_count}"
            )

            # Check if we got any bookmarks at all (to ensure the test is meaningful)
            # This could fail if the account has no bookmarks
            assert actual_count > 0, "Expected at least some bookmarks to be returned"

            # If the account has enough bookmarks, we should get exactly the limit
            # But we can't assert this because we don't know how many bookmarks exist
            if actual_count < test_limit:
                logger.info(
                    f"Note: Only {actual_count} bookmarks were returned, which is less than the requested limit of {test_limit}. This is acceptable if the account doesn't have {test_limit} bookmarks."
                )
            else:
                logger.info(
                    f"✓ Command returned exactly the requested limit of {test_limit} bookmarks"
                )

        except ValueError:
            logger.error(f"Failed to parse jq output as integer: '{result.stdout}'")
            pytest.fail(f"jq output is not a valid integer: '{result.stdout}'")

    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed with exit code {e.returncode}")
        logger.error(f"Stdout: {e.stdout}")
        logger.error(f"Stderr: {e.stderr}")
        pytest.fail(f"CLI command failed: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        pytest.fail(f"Unexpected error: {e}")


def test_get_current_user_stats(karakeep_client: KarakeepAPI):
    """Test retrieving statistics for the current user."""
    try:
        stats = karakeep_client.get_current_user_stats()
        assert isinstance(stats, dict), "Response should be a dictionary"
        # Check for the presence of expected keys (adjust based on actual API response)
        assert "numBookmarks" in stats, "Stats should contain 'numBookmarks'"
        assert "numHighlights" in stats, "Stats should contain 'numHighlights'"
        assert "numLists" in stats, "Stats should contain 'numLists'"
        assert "numTags" in stats, "Stats should contain 'numTags'"
        # Check that values are non-negative integers
        assert isinstance(stats["numBookmarks"], int) and stats["numBookmarks"] >= 0
        assert isinstance(stats["numHighlights"], int) and stats["numHighlights"] >= 0
        assert isinstance(stats["numLists"], int) and stats["numLists"] >= 0
        assert isinstance(stats["numTags"], int) and stats["numTags"] >= 0

        logger.info(f"✓ Successfully retrieved user stats: {stats}")

    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during user stats retrieval: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred during user stats retrieval: {e}")

    # --- Add CLI call ---
    try:
        logger.info("\n  Running CLI equivalent: get-current-user-stats")
        # Assumes KARAKEEP_PYTHON_API_ENDPOINT and KARAKEEP_PYTHON_API_KEY are set in env
        subprocess.run(
            "python -m karakeep_python_api get-current-user-stats",
            shell=True,
            check=True,
            capture_output=True,  # Capture output to avoid logger.infoing it during tests unless verbose
            text=True,
        )
        logger.info("✓ CLI command executed successfully.")
    except subprocess.CalledProcessError as e:
        logger.info(f"  CLI command failed with exit code {e.returncode}")
        # logger.info stdout/stderr only if the command failed to aid debugging
        logger.info(f"  Stdout: {e.stdout}")
        logger.info(f"  Stderr: {e.stderr}")
        pytest.fail(f"CLI command 'get-current-user-stats' failed: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred running the CLI command: {e}")


def test_asset_lifecycle_with_pdf(karakeep_client: KarakeepAPI):
    """Test creating a PDF bookmark, verifying its asset, and deleting it."""
    pdf_file_path = "tests/PDF Bookmark Sample.pdf"
    uploaded_asset_id = None
    created_bookmark_id = None

    # Generate unique title to avoid collisions
    timestamp = int(time.time())
    random_suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    bookmark_title = f"Test PDF Bookmark {timestamp}-{random_suffix}"

    try:
        # 1. Upload the PDF asset
        logger.info(f"\nUploading PDF asset from: {pdf_file_path}")
        uploaded_asset = karakeep_client.upload_a_new_asset(file=pdf_file_path)
        assert isinstance(uploaded_asset, datatypes.Asset)
        assert uploaded_asset.assetId, "Uploaded asset must have an ID"
        assert "pdf" in uploaded_asset.contentType.lower(), "Asset should be PDF type"
        assert uploaded_asset.fileName == "PDF Bookmark Sample.pdf", (
            "Asset filename should match the original file"
        )
        uploaded_asset_id = uploaded_asset.assetId
        logger.info(f"✓ PDF uploaded with asset ID: {uploaded_asset_id}")

        # 2. Create a PDF bookmark using the uploaded asset
        logger.info(f"\nCreating PDF bookmark with title: '{bookmark_title}'")
        bookmark = karakeep_client.create_a_new_bookmark(
            type="asset",
            asset_type="pdf",
            assetId=uploaded_asset_id,
            title=bookmark_title,
            fileName="PDF Bookmark Sample.pdf",
        )
        assert isinstance(bookmark, datatypes.Bookmark)
        assert bookmark.id, "Created bookmark must have an ID"
        assert bookmark.title == bookmark_title, "Bookmark title should match"
        created_bookmark_id = bookmark.id
        logger.info(f"✓ PDF bookmark created with ID: {created_bookmark_id}")

        # 3. Verify the bookmark has the correct asset
        logger.info(f"\nVerifying bookmark {created_bookmark_id} has the PDF asset")
        retrieved_bookmark = karakeep_client.get_a_single_bookmark(
            bookmark_id=created_bookmark_id
        )
        assert isinstance(retrieved_bookmark, datatypes.Bookmark)
        assert len(retrieved_bookmark.assets) > 0, (
            "Bookmark should have at least one asset"
        )

        # Check that our uploaded asset is among the bookmark's assets
        asset_ids = [asset.id for asset in retrieved_bookmark.assets]
        assert uploaded_asset_id in asset_ids, (
            f"Uploaded asset {uploaded_asset_id} should be attached to bookmark"
        )
        logger.info(f"✓ Verified bookmark contains the PDF asset {uploaded_asset_id}")

        # 4. Retrieve and verify the asset content
        logger.info(f"\nRetrieving asset content for ID: {uploaded_asset_id}")
        asset_content = karakeep_client.get_a_single_asset(asset_id=uploaded_asset_id)
        assert isinstance(asset_content, bytes), "Asset content should be bytes"
        assert len(asset_content) > 0, "Asset content should not be empty"
        assert asset_content.startswith(b"%PDF"), "PDF should start with PDF header"
        logger.info(f"✓ Retrieved PDF asset content ({len(asset_content)} bytes)")

        # 5. Get a signed URL for the same asset and download it without an API key.
        #    The whole point of the signed URL is that it authenticates itself, so
        #    the download is deliberately made with a bare requests.get.
        logger.info(f"\nRequesting signed URL for asset ID: {uploaded_asset_id}")
        signed = karakeep_client.get_asset_signed_url(asset_id=uploaded_asset_id)
        assert isinstance(signed, datatypes.SignedAssetUrl), (
            "Response should be a SignedAssetUrl model"
        )
        assert signed.assetId == uploaded_asset_id
        assert signed.signedUrl.startswith("http"), "Signed URL should be absolute"
        assert signed.expiresAt, "Signed URL must carry an expiry"
        logger.info(f"✓ Got signed URL expiring at {signed.expiresAt}")

        import requests

        signed_response = requests.get(
            signed.signedUrl, verify=karakeep_client.verify_ssl, timeout=30
        )
        signed_response.raise_for_status()
        assert signed_response.content == asset_content, (
            "Signed URL download should return the same bytes as get_a_single_asset"
        )
        logger.info("✓ Downloaded the asset through the signed URL without an API key")

    except FileNotFoundError:
        pytest.skip(f"PDF test file not found: {pdf_file_path}")
    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during PDF asset test: {e}")
    except Exception as e:
        pytest.fail(f"Unexpected error during PDF asset test: {e}")
    finally:
        # 5. Clean up: Delete the bookmark
        if created_bookmark_id:
            logger.info(f"\nCleaning up: Deleting bookmark {created_bookmark_id}")
            try:
                karakeep_client.delete_a_bookmark(bookmark_id=created_bookmark_id)
                logger.info(f"✓ Successfully deleted bookmark {created_bookmark_id}")
            except Exception as e:
                logger.info(
                    f"  Error during cleanup - failed to delete bookmark {created_bookmark_id}: {e}"
                )
        else:
            logger.info("\nNo bookmark to clean up")


def test_backup_lifecycle(karakeep_client: KarakeepAPI):
    """Test creating, retrieving, downloading, and deleting a backup."""
    created_backup_id = None

    try:
        # 1. Get initial backup count
        logger.info("\nGetting initial backup list")
        initial_backups = karakeep_client.get_all_backups()
        assert isinstance(initial_backups, list), "Response should be a list"
        initial_backup_count = len(initial_backups)
        logger.info(f"  Initial backup count: {initial_backup_count}")

        # 2. Trigger a new backup
        logger.info("\nTriggering a new backup")
        created_backup = karakeep_client.trigger_a_new_backup()
        assert isinstance(created_backup, datatypes.Backup), (
            "Response should be a Backup model"
        )
        assert created_backup.id, "Created backup must have an ID"
        assert created_backup.status in ["pending", "success", "failure"], (
            "Backup status should be one of the valid enum values"
        )
        created_backup_id = created_backup.id
        logger.info(f"✓ Successfully triggered backup with ID: {created_backup_id}")
        logger.info(f"  Backup status: {created_backup.status}")

        # 3. Verify the backup appears in get_all_backups
        logger.info(f"\nVerifying backup {created_backup_id} appears in backup list")
        current_backups = karakeep_client.get_all_backups()
        assert len(current_backups) >= initial_backup_count + 1, (
            "Backup count should increase after creation"
        )
        assert any(backup.id == created_backup_id for backup in current_backups), (
            "Created backup should be present in the list of all backups"
        )
        logger.info(
            f"✓ Verified backup {created_backup_id} is present in get_all_backups"
        )

        # 4. Get the backup by ID to verify it exists
        logger.info(f"\nRetrieving backup {created_backup_id} by ID")
        retrieved_backup = karakeep_client.get_a_single_backup(
            backup_id=created_backup_id
        )
        assert isinstance(retrieved_backup, datatypes.Backup)
        assert retrieved_backup.id == created_backup_id
        logger.info(f"✓ Successfully retrieved backup by ID")
        logger.info(f"  Status: {retrieved_backup.status}")
        logger.info(f"  Bookmark count: {retrieved_backup.bookmarkCount}")
        logger.info(f"  Size: {retrieved_backup.size} bytes")

        # 5. Try to download the backup (only if status is "success")
        if retrieved_backup.status == "success" and retrieved_backup.assetId:
            logger.info(f"\nAttempting to download backup {created_backup_id}")
            try:
                backup_data = karakeep_client.download_a_backup(
                    backup_id=created_backup_id
                )
                assert isinstance(backup_data, bytes), (
                    "Downloaded backup should be bytes"
                )
                assert len(backup_data) > 0, "Downloaded backup should not be empty"
                # Verify it's a zip file by checking the magic number
                assert backup_data.startswith(b"PK\x03\x04") or backup_data.startswith(
                    b"PK\x05\x06"
                ), "Downloaded file should be a valid ZIP archive"
                logger.info(
                    f"✓ Successfully downloaded backup ({len(backup_data)} bytes)"
                )
            except APIError as e:
                # Some backups might not be downloadable immediately, log but don't fail
                logger.info(f"  Note: Could not download backup: {e}")
        else:
            logger.info(
                f"  Skipping download test (status: {retrieved_backup.status}, assetId: {retrieved_backup.assetId})"
            )

        # 6. Test CLI equivalent for getting all backups
        logger.info("\n  Running CLI equivalent: get-all-backups")
        try:
            subprocess.run(
                "python -m karakeep_python_api get-all-backups",
                shell=True,
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("✓ CLI command executed successfully.")
        except subprocess.CalledProcessError as e:
            logger.info(f"  CLI command failed with exit code {e.returncode}")
            logger.info(f"  Stdout: {e.stdout}")
            logger.info(f"  Stderr: {e.stderr}")
            pytest.fail(f"CLI command 'get-all-backups' failed: {e}")

    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during backup lifecycle test: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred during backup lifecycle test: {e}")
    finally:
        # 7. Clean up: Delete the backup
        if created_backup_id:
            logger.info(f"\nCleaning up: Deleting backup {created_backup_id}")
            try:
                karakeep_client.delete_a_backup(backup_id=created_backup_id)
                logger.info(f"✓ Successfully deleted backup {created_backup_id}")

                # 8. Verify the backup is deleted
                try:
                    karakeep_client.get_a_single_backup(backup_id=created_backup_id)
                    pytest.fail(
                        f"Backup {created_backup_id} should not exist after deletion, but get_a_single_backup succeeded."
                    )
                except APIError as e:
                    assert e.status_code == 404, (
                        f"Expected 404 Not Found when getting deleted backup, but got status {e.status_code}"
                    )
                    logger.info(
                        f"✓ Confirmed backup {created_backup_id} is deleted (received 404)"
                    )

            except (APIError, AuthenticationError) as e:
                logger.info(
                    f"  Error during cleanup - failed to delete backup {created_backup_id}: {e}"
                )
            except Exception as e:
                logger.info(f"  Unexpected error during cleanup: {e}")
        else:
            logger.info("\nNo backup to clean up")


def _skip_if_not_admin(error: APIError):
    """Skip a test if the API replied with a 403 (admin role required)."""
    if error.status_code == 403:
        pytest.skip(f"Test requires admin role: {error}")


def test_admin_trigger_reindex(karakeep_client: KarakeepAPI):
    """Smoke-test triggering a reindex job (admin only)."""
    try:
        result = karakeep_client.admin_trigger_reindex()
    except APIError as e:
        _skip_if_not_admin(e)
        raise
    assert isinstance(result, dict)
    assert result.get("success") is True


def test_admin_trigger_recrawl_failures(karakeep_client: KarakeepAPI):
    """Trigger a recrawl scoped to failed bookmarks only (admin only)."""
    try:
        result = karakeep_client.admin_trigger_recrawl(
            crawl_status="failure", run_inference=False
        )
    except APIError as e:
        _skip_if_not_admin(e)
        raise
    assert isinstance(result, dict)
    assert result.get("success") is True


def test_admin_trigger_inference_tag(karakeep_client: KarakeepAPI):
    """Trigger AI tagging inference on failed bookmarks (admin only)."""
    try:
        result = karakeep_client.admin_trigger_inference(type="tag", status="failure")
    except APIError as e:
        _skip_if_not_admin(e)
        raise
    assert isinstance(result, dict)
    assert result.get("success") is True


def test_feed_lifecycle(karakeep_client: KarakeepAPI):
    """Smoke-test feed CRUD + fetch trigger.

    Skips gracefully when the server has reached its feed quota or otherwise
    rejects the create call so this still works against shared instances.
    """
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    feed_name = f"karakeep-py-test-{suffix}"
    feed_url = f"https://example.com/test-feed-{suffix}.xml"

    created_id: str = ""
    try:
        try:
            feed = karakeep_client.create_a_new_feed(
                name=feed_name, url=feed_url, enabled=False
            )
        except APIError as e:
            pytest.skip(f"Could not create feed (quota or server config): {e}")

        assert isinstance(feed, datatypes.Feed)
        assert feed.id, "Created feed must have an id"
        assert feed.name == feed_name
        assert feed.url == feed_url
        assert feed.enabled is False
        created_id = feed.id

        # List feeds and ensure ours is present.
        feeds = karakeep_client.get_all_feeds()
        assert isinstance(feeds, list)
        assert any(f.id == created_id for f in feeds), "Created feed not in list"

        # Get single feed.
        single = karakeep_client.get_a_single_feed(feed_id=created_id)
        assert isinstance(single, datatypes.Feed)
        assert single.id == created_id

        # Update name.
        new_name = feed_name + "-updated"
        updated = karakeep_client.update_a_feed(feed_id=created_id, name=new_name)
        assert isinstance(updated, datatypes.Feed)
        assert updated.name == new_name

        # Trigger a fetch (returns None / 204). Tolerate failure on offline test URLs.
        try:
            assert karakeep_client.fetch_a_feed(feed_id=created_id) is None
        except APIError as e:
            logger.info(
                f"  fetch_a_feed returned an error (expected for fake URL): {e}"
            )

    finally:
        if created_id:
            try:
                karakeep_client.delete_a_feed(feed_id=created_id)
            except APIError as e:
                logger.warning(f"  Cleanup: failed to delete feed {created_id}: {e}")


def test_readable_content_of_a_text_bookmark(karakeep_client: KarakeepAPI):
    """Live test of GET /bookmarks/{id}/content against a freshly created text bookmark.

    A text bookmark is used rather than a link so the readable content is available
    immediately: link bookmarks only expose content once the crawler has run, which
    would make this test racy. The body is long enough that a small ``max_chars``
    forces the server to hand out a ``nextCursor``, which exercises both the
    single-chunk path and the ``fetch_all`` merge against a real server.
    """
    # Distinct repeated paragraphs so a partial read is obviously partial.
    paragraphs = [
        f"Paragraph number {i} of the readable content test." for i in range(20)
    ]
    body = "\n\n".join(paragraphs)
    created_id = None

    try:
        bookmark = karakeep_client.create_a_new_bookmark(
            type="text",
            title="karakeep-python-api readable content test",
            text=body,
        )
        assert isinstance(bookmark, datatypes.Bookmark)
        created_id = bookmark.id

        # Full read in one go.
        full = karakeep_client.get_bookmark_readable_content(bookmark_id=created_id)
        assert isinstance(full, datatypes.BookmarkReadableContent)
        assert full.bookmarkId == created_id
        assert full.bookmarkType == "text"
        assert full.format == "markdown"
        assert "Paragraph number 0" in full.content
        assert full.range.total >= len(full.content)
        logger.info(f"✓ Read {full.range.total} characters of readable content.")

        # Chunked read: a small max_chars must truncate and hand back a cursor.
        first = karakeep_client.get_bookmark_readable_content(
            bookmark_id=created_id, max_chars=50
        )
        assert isinstance(first, datatypes.BookmarkReadableContent)
        assert len(first.content) <= 50
        if not first.truncated:
            pytest.skip("Server returned the whole document despite max_chars=50")
        assert first.nextCursor, "A truncated chunk must carry a nextCursor"

        # Following the cursor manually must move forward in the document.
        second = karakeep_client.get_bookmark_readable_content(
            bookmark_id=created_id, cursor=first.nextCursor
        )
        assert second.range.start >= first.range.end

        # fetch_all must reassemble the same document as the single unbounded read.
        merged = karakeep_client.get_bookmark_readable_content(
            bookmark_id=created_id, max_chars=50, fetch_all=True
        )
        assert merged.nextCursor is None
        assert merged.truncated is False
        assert merged.content == full.content
        logger.info("✓ fetch_all reassembled the document identically.")

    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during readable content test: {e}")
    finally:
        if created_id:
            try:
                karakeep_client.delete_a_bookmark(bookmark_id=created_id)
            except APIError as e:
                logger.warning(
                    f"  Cleanup: failed to delete bookmark {created_id}: {e}"
                )


# --- End of Tests ---
