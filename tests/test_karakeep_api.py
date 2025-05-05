import pytest
import os
import subprocess
import random
import string
import time

# Import API, errors, and datatypes from the main package
from karakeep_python_api import KarakeepAPI, APIError, AuthenticationError, datatypes

# Note: The karakeep_client fixture is defined in conftest.py and provides a valid client instance.

# --- Test 'Get All' Endpoints ---


def test_get_all_bookmarks_paginated(karakeep_client: KarakeepAPI):
    """Test retrieving bookmarks with pagination."""
    try:
        # Get the first page
        page1 = karakeep_client.get_all_bookmarks(limit=2)
        assert isinstance(
            page1, datatypes.PaginatedBookmarks
        ), "Response should be PaginatedBookmarks model"
        assert isinstance(page1.bookmarks, list), "Bookmarks attribute should be a list"
        assert len(page1.bookmarks) <= 2, "Should return at most 'limit' bookmarks"
        print(f"✓ Retrieved first page with {len(page1.bookmarks)} bookmarks.")

        # If there's a next cursor, get the next page
        if page1.nextCursor:
            print(f"  Attempting to fetch next page with cursor: {page1.nextCursor}")
            page2 = karakeep_client.get_all_bookmarks(limit=2, cursor=page1.nextCursor)
            assert isinstance(page2, datatypes.PaginatedBookmarks)
            assert isinstance(page2.bookmarks, list)
            assert len(page2.bookmarks) <= 2
            print(f"✓ Retrieved second page with {len(page2.bookmarks)} bookmarks.")
            # Ensure bookmarks are different from page 1 (simple check)
            if page1.bookmarks and page2.bookmarks:
                assert (
                    page1.bookmarks[0].id != page2.bookmarks[0].id
                ), "Bookmarks on page 1 and 2 should differ"
        else:
            print("  No next cursor found, pagination test ends.")

    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during paginated bookmark retrieval: {e}")
    except Exception as e:
        pytest.fail(
            f"An unexpected error occurred during paginated bookmark retrieval: {e}"
        )

    # --- Add CLI call ---
    try:
        print("\n  Running CLI equivalent: get-all-bookmarks --limit 2")
        # Assumes KARAKEEP_PYTHON_API_BASE_URL and KARAKEEP_PYTHON_API_KEY are set in env
        subprocess.run(
            "python -m karakeep_python_api get-all-bookmarks --limit 2",
            shell=True,
            check=True,
            capture_output=True,  # Capture output to avoid printing it during tests unless verbose
            text=True,
        )
        print("✓ CLI command executed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"  CLI command failed with exit code {e.returncode}")
        # Print stdout/stderr only if the command failed to aid debugging
        print(f"  Stdout: {e.stdout}")
        print(f"  Stderr: {e.stderr}")
        pytest.fail(f"CLI command 'get-all-bookmarks --limit 2' failed: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred running the CLI command: {e}")


def test_get_all_lists(karakeep_client: KarakeepAPI):
    """Test retrieving all lists."""
    try:
        lists = karakeep_client.get_all_lists()
        assert isinstance(lists, list), "Response should be a list"
        if lists:  # Only check elements if the list is not empty
            assert all(
                isinstance(item, datatypes.ListModel) for item in lists
            ), "All items should be ListModel instances"
        print(f"✓ Successfully retrieved {len(lists)} lists.")
    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during list retrieval: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred during list retrieval: {e}")

    # --- Add CLI call ---
    try:
        print("\n  Running CLI equivalent: get-all-lists")
        # Assumes KARAKEEP_PYTHON_API_BASE_URL and KARAKEEP_PYTHON_API_KEY are set in env
        subprocess.run(
            "python -m karakeep_python_api get-all-lists",
            shell=True,
            check=True,
            capture_output=True,  # Capture output to avoid printing it during tests unless verbose
            text=True,
        )
        print("✓ CLI command executed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"  CLI command failed with exit code {e.returncode}")
        # Print stdout/stderr only if the command failed to aid debugging
        print(f"  Stdout: {e.stdout}")
        print(f"  Stderr: {e.stderr}")
        pytest.fail(f"CLI command 'get-all-lists' failed: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred running the CLI command: {e}")


def test_get_all_tags(karakeep_client: KarakeepAPI):
    """Test retrieving all tags."""
    try:
        tags = karakeep_client.get_all_tags()
        assert isinstance(tags, list), "Response should be a list"
        if tags:  # Only check elements if the list is not empty
            assert all(
                isinstance(item, datatypes.Tag1) for item in tags
            ), "All items should be Tag1 instances"
        print(f"✓ Successfully retrieved {len(tags)} tags.")
    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during tag retrieval: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred during tag retrieval: {e}")

    # --- Add CLI call ---
    try:
        print("\n  Running CLI equivalent: get-all-tags")
        # Assumes KARAKEEP_PYTHON_API_BASE_URL and KARAKEEP_PYTHON_API_KEY are set in env
        subprocess.run(
            "python -m karakeep_python_api get-all-tags",
            shell=True,
            check=True,
            capture_output=True,  # Capture output to avoid printing it during tests unless verbose
            text=True,
        )
        print("✓ CLI command executed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"  CLI command failed with exit code {e.returncode}")
        # Print stdout/stderr only if the command failed to aid debugging
        print(f"  Stdout: {e.stdout}")
        print(f"  Stderr: {e.stderr}")
        pytest.fail(f"CLI command 'get-all-tags' failed: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred running the CLI command: {e}")


def test_get_all_highlights_paginated(karakeep_client: KarakeepAPI):
    """Test retrieving highlights with pagination."""
    try:
        # Get the first page
        page1 = karakeep_client.get_all_highlights(limit=3)
        assert isinstance(
            page1, datatypes.PaginatedHighlights
        ), "Response should be PaginatedHighlights model"
        assert isinstance(
            page1.highlights, list
        ), "Highlights attribute should be a list"
        assert len(page1.highlights) <= 3, "Should return at most 'limit' highlights"
        print(f"✓ Retrieved first page with {len(page1.highlights)} highlights.")

        # If there's a next cursor, get the next page
        if page1.nextCursor:
            print(f"  Attempting to fetch next page with cursor: {page1.nextCursor}")
            page2 = karakeep_client.get_all_highlights(limit=3, cursor=page1.nextCursor)
            assert isinstance(page2, datatypes.PaginatedHighlights)
            assert isinstance(page2.highlights, list)
            assert len(page2.highlights) <= 3
            print(f"✓ Retrieved second page with {len(page2.highlights)} highlights.")
            # Ensure highlights are different from page 1 (simple check)
            if page1.highlights and page2.highlights:
                assert (
                    page1.highlights[0].id != page2.highlights[0].id
                ), "Highlights on page 1 and 2 should differ"
        else:
            print("  No next cursor found, pagination test ends.")

    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during paginated highlight retrieval: {e}")
    except Exception as e:
        pytest.fail(
            f"An unexpected error occurred during paginated highlight retrieval: {e}"
        )

    # --- Add CLI call ---
    try:
        print("\n  Running CLI equivalent: get-all-highlights --limit 3")
        # Assumes KARAKEEP_PYTHON_API_BASE_URL and KARAKEEP_PYTHON_API_KEY are set in env
        subprocess.run(
            "python -m karakeep_python_api get-all-highlights --limit 3",
            shell=True,
            check=True,
            capture_output=True,  # Capture output to avoid printing it during tests unless verbose
            text=True,
        )
        print("✓ CLI command executed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"  CLI command failed with exit code {e.returncode}")
        # Print stdout/stderr only if the command failed to aid debugging
        print(f"  Stdout: {e.stdout}")
        print(f"  Stderr: {e.stderr}")
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
        assert (
            "openapi" in spec
        ), "openapi_spec should contain the 'openapi' version key"
        print(
            f"✓ Successfully accessed openapi_spec attribute. Version: {spec.get('openapi', 'N/A')}"
        )
    except Exception as e:
        pytest.fail(f"An unexpected error occurred while accessing openapi_spec: {e}")

    # --- Add CLI call ---
    # The closest CLI equivalent is dumping the spec file content
    try:
        print("\n  Running CLI equivalent: --dump-openapi-specification")
        # This command doesn't require API key or base URL
        subprocess.run(
            "python -m karakeep_python_api --dump-openapi-specification",
            shell=True,
            check=True,
            capture_output=True,  # Capture output to avoid printing it during tests unless verbose
            text=True,
        )
        print("✓ CLI command executed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"  CLI command failed with exit code {e.returncode}")
        # Print stdout/stderr only if the command failed to aid debugging
        print(f"  Stdout: {e.stdout}")
        print(f"  Stderr: {e.stderr}")
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
        random_suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        list_name = f"Test List {timestamp}-{random_suffix}"
        list_icon = "🧪"  # Test tube icon

        print(f"\nAttempting to create list: Name='{list_name}', Icon='{list_icon}'")

        # 2. Get initial list count (optional, for comparison)
        initial_lists = karakeep_client.get_all_lists()
        initial_list_count = len(initial_lists)
        print(f"  Initial list count: {initial_list_count}")

        # 3. Create the new list
        create_payload = {"name": list_name, "icon": list_icon, "type": "manual"}
        created_list = karakeep_client.create_a_new_list(list_data=create_payload)
        assert isinstance(
            created_list, datatypes.ListModel
        ), "Response should be a ListModel"
        assert created_list.name == list_name, "Created list name should match"
        assert created_list.icon == list_icon, "Created list icon should match"
        assert created_list.id, "Created list must have an ID"
        created_list_id = created_list.id  # Store the ID for deletion
        print(f"✓ Successfully created list with ID: {created_list_id}")

        # 4. Verify the list appears in get_all_lists
        current_lists_after_create = karakeep_client.get_all_lists()
        assert (
            len(current_lists_after_create) == initial_list_count + 1
        ), "List count should increase by one after creation"
        assert any(
            lst.id == created_list_id for lst in current_lists_after_create
        ), "Created list should be present in the list of all lists"
        print(f"  List count after creation: {len(current_lists_after_create)}")
        print(f"✓ Verified list {created_list_id} is present in get_all_lists.")


        # 5. Verify the list exists by getting it directly (redundant but good check)
        retrieved_list = karakeep_client.get_a_single_list(list_id=created_list_id)
        assert isinstance(retrieved_list, datatypes.ListModel)
        assert retrieved_list.id == created_list_id
        print(f"✓ Successfully retrieved the created list by ID.")

    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during list creation/verification: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred during list creation/verification: {e}")
    finally:
        # 6. Delete the list (ensure cleanup even if assertions fail)
        if created_list_id:
            print(f"\nAttempting to delete list with ID: {created_list_id}")
            try:
                karakeep_client.delete_a_list(list_id=created_list_id)
                print(f"✓ Successfully deleted list with ID: {created_list_id}")

                # 7. Verify the list is gone by trying to get it (should fail)
                try:
                    karakeep_client.get_a_single_list(list_id=created_list_id)
                    pytest.fail(
                        f"List with ID {created_list_id} should not exist after deletion, but get_a_single_list succeeded."
                    )
                except APIError as e:
                    assert (
                        e.status_code == 404
                    ), f"Expected 404 Not Found when getting deleted list, but got status {e.status_code}"
                    print(
                        f"✓ Confirmed list {created_list_id} is deleted (received 404)."
                    )

                # 8. Verify list count decreased (optional check)
                final_lists = karakeep_client.get_all_lists()
                assert (
                    len(final_lists) == initial_list_count
                ), "List count should return to initial count after deletion"
                assert not any(
                    lst.id == created_list_id for lst in final_lists
                ), "Deleted list should not be present in the final list of all lists"
                print(f"  Final list count: {len(final_lists)}")

            except (APIError, AuthenticationError) as e:
                pytest.fail(f"API error during list deletion: {e}")
            except Exception as e:
                pytest.fail(f"An unexpected error occurred during list deletion: {e}")
        else:
            print("\nSkipping deletion because list creation failed or ID was not obtained.")


def test_create_and_delete_bookmark(karakeep_client: KarakeepAPI):
    """Test creating a new URL bookmark and then deleting it."""
    created_bookmark_id = None
    test_url = "https://en.wikipedia.org/wiki/Example"
    try:
        # 1. Define bookmark payload
        print(f"\nAttempting to create bookmark for URL: {test_url}")

        # 2. Create the bookmark
        # Call the method with keyword arguments matching its signature
        created_bookmark = karakeep_client.create_a_new_bookmark(
            type="link", url=test_url
        )
        assert isinstance(
            created_bookmark, datatypes.Bookmark
        ), "Response should be a Bookmark model"
        assert created_bookmark.content.url == test_url, "Created bookmark URL should match"
        assert created_bookmark.id, "Created bookmark must have an ID"
        created_bookmark_id = created_bookmark.id
        print(f"✓ Successfully created bookmark with ID: {created_bookmark_id}")

        # 3. Verify the bookmark exists by getting it directly
        retrieved_bookmark = karakeep_client.get_a_single_bookmark(
            bookmark_id=created_bookmark_id
        )
        assert isinstance(retrieved_bookmark, datatypes.Bookmark)
        assert retrieved_bookmark.id == created_bookmark_id
        assert retrieved_bookmark.content.url == test_url
        print(f"✓ Successfully retrieved the created bookmark by ID.")

        # 4. Search for the created bookmark
        print(f"\nAttempting to search for bookmark with query: 'wikipedia'")
        search_query = "Example - Wikipedia"
        search_results = karakeep_client.search_bookmarks(q=search_query, limit=50)
        assert isinstance(
            search_results, datatypes.PaginatedBookmarks
        ), "Search response should be PaginatedBookmarks model"
        assert isinstance(
            search_results.bookmarks, list
        ), "Search results bookmarks attribute should be a list"
        assert any(
            b.id == created_bookmark_id for b in search_results.bookmarks
        ), f"Created bookmark {created_bookmark_id} not found in search results for '{search_query}'"
        print(f"✓ Found created bookmark in search results for '{search_query}'.")

        # 4a. Test CLI search equivalent
        print(f"\n  Running CLI equivalent: search-bookmarks --q '{search_query}' --limit 10")
        try:
            cli_search_command = f"python -m karakeep_python_api search-bookmarks --q '{search_query}' --limit 10"
            search_cli_output = subprocess.run(
                cli_search_command,
                shell=True,
                check=True,
                capture_output=True,
                text=True,
            )
            # Basic check: Ensure the created ID is somewhere in the output JSON
            # A more robust check would parse the JSON and verify structure/content
            assert created_bookmark_id in search_cli_output.stdout, f"Created bookmark ID {created_bookmark_id} not found in CLI search output for '{search_query}'"
            print("✓ CLI search command executed successfully and contained the bookmark ID.")
        except subprocess.CalledProcessError as e:
            print(f"  CLI search command failed with exit code {e.returncode}")
            print(f"  Stdout: {e.stdout}")
            print(f"  Stderr: {e.stderr}")
            pytest.fail(f"CLI command 'search-bookmarks --q {search_query}' failed: {e}")
        except Exception as e:
            pytest.fail(f"An unexpected error occurred running the CLI search command: {e}")


    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during bookmark creation/verification/search: {e}")
    except Exception as e:
        pytest.fail(
            f"An unexpected error occurred during bookmark creation/verification/search: {e}"
        )
    finally:
        # 5. Delete the bookmark (ensure cleanup)
        if created_bookmark_id:
            print(f"\nAttempting to delete bookmark with ID: {created_bookmark_id}")
            try:
                karakeep_client.delete_a_bookmark(bookmark_id=created_bookmark_id)
                print(f"✓ Successfully deleted bookmark with ID: {created_bookmark_id}")

                # 6. Verify the bookmark is gone by trying to get it (should fail)
                try:
                    karakeep_client.get_a_single_bookmark(
                        bookmark_id=created_bookmark_id
                    )
                    pytest.fail(
                        f"Bookmark with ID {created_bookmark_id} should not exist after deletion, but get_a_single_bookmark succeeded."
                    )
                except APIError as e:
                    assert (
                        e.status_code == 404
                    ), f"Expected 404 Not Found when getting deleted bookmark, but got status {e.status_code}"
                    print(
                        f"✓ Confirmed bookmark {created_bookmark_id} is deleted via API (received 404)."
                    )

                # 7. Attempt to delete the same bookmark via CLI (should ideally fail or do nothing)
                print(f"\n  Attempting CLI deletion for already deleted bookmark ID: {created_bookmark_id}")
                try:
                    cli_delete_command = f"python -m karakeep_python_api delete-a-bookmark --bookmark-id {created_bookmark_id}"
                    subprocess.run(
                        cli_delete_command,
                        shell=True,
                        check=True, # Set to False if CLI errors on 404, True if it exits 0
                        capture_output=True,
                        text=True,
                    )
                    # If check=True and it succeeds, it means the CLI might not error on 404.
                    print(f"  ✓ CLI delete command executed (check=True implies it might not error on 404).")
                except subprocess.CalledProcessError as e:
                    # If check=True, this block means the CLI command failed, which *might* be expected if it errors on 404.
                    print(f"  ✓ CLI delete command failed as expected (exit code {e.returncode}), likely because bookmark was already deleted.")
                    # Optional: Assert specific exit code if known
                    # assert e.returncode == EXPECTED_EXIT_CODE_FOR_NOT_FOUND
                except Exception as cli_e:
                    pytest.fail(f"An unexpected error occurred running the CLI delete command: {cli_e}")

                # 8. Verify again via API that the bookmark is still gone after CLI attempt
                try:
                    karakeep_client.get_a_single_bookmark(bookmark_id=created_bookmark_id)
                    pytest.fail(
                        f"Bookmark {created_bookmark_id} should *still* not exist after CLI deletion attempt, but get_a_single_bookmark succeeded."
                    )
                except APIError as e:
                    assert (
                        e.status_code == 404
                    ), f"Expected 404 Not Found after CLI deletion attempt, but got status {e.status_code}"
                    print(
                        f"✓ Confirmed bookmark {created_bookmark_id} is *still* deleted after CLI attempt (received 404)."
                    )

            except (APIError, AuthenticationError) as e:
                # Catch errors from the initial Python API deletion or subsequent checks
                pytest.fail(f"API error during bookmark deletion/verification: {e}")
            except Exception as e:
                pytest.fail(f"An unexpected error occurred during bookmark deletion: {e}")
        else:
            print(
                "\nSkipping deletion because bookmark creation failed or ID was not obtained."
            )


# --- Test User Info/Stats Endpoints ---

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

        print(f"✓ Successfully retrieved user stats: {stats}")

    except (APIError, AuthenticationError) as e:
        pytest.fail(f"API error during user stats retrieval: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred during user stats retrieval: {e}")

    # --- Add CLI call ---
    try:
        print("\n  Running CLI equivalent: get-current-user-stats")
        # Assumes KARAKEEP_PYTHON_API_BASE_URL and KARAKEEP_PYTHON_API_KEY are set in env
        subprocess.run(
            "python -m karakeep_python_api get-current-user-stats",
            shell=True,
            check=True,
            capture_output=True, # Capture output to avoid printing it during tests unless verbose
            text=True,
        )
        print("✓ CLI command executed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"  CLI command failed with exit code {e.returncode}")
        # Print stdout/stderr only if the command failed to aid debugging
        print(f"  Stdout: {e.stdout}")
        print(f"  Stderr: {e.stderr}")
        pytest.fail(f"CLI command 'get-current-user-stats' failed: {e}")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred running the CLI command: {e}")


# --- End of Tests ---
