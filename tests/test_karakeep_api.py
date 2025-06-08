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
                assert (
                    page1.bookmarks[0].id != page2.bookmarks[0].id
                ), "Bookmarks on page 1 and 2 should differ"
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
            assert all(
                isinstance(item, datatypes.ListModel) for item in lists
            ), "All items should be ListModel instances"
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
        assert isinstance(tags, list), "Response should be a list"
        if tags:  # Only check elements if the list is not empty
            assert all(
                isinstance(item, datatypes.Tag) for item in tags
            ), "All items should be Tag instances"
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
        assert isinstance(
            page1, datatypes.PaginatedHighlights
        ), "Response should be PaginatedHighlights model"
        assert isinstance(
            page1.highlights, list
        ), "Highlights attribute should be a list"
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
                assert (
                    page1.highlights[0].id != page2.highlights[0].id
                ), "Highlights on page 1 and 2 should differ"
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
        assert (
            "openapi" in spec
        ), "openapi_spec should contain the 'openapi' version key"
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
        assert isinstance(
            created_list, datatypes.ListModel
        ), "Response should be a ListModel"
        assert created_list.name == list_name, "Created list name should match"
        assert created_list.icon == list_icon, "Created list icon should match"
        assert created_list.id, "Created list must have an ID"
        created_list_id = created_list.id  # Store the ID for deletion
        logger.info(f"✓ Successfully created list with ID: {created_list_id}")

        # 4. Verify the list appears in get_all_lists
        current_lists_after_create = karakeep_client.get_all_lists()
        assert (
            len(current_lists_after_create) == initial_list_count + 1
        ), "List count should increase by one after creation"
        assert any(
            lst.id == created_list_id for lst in current_lists_after_create
        ), "Created list should be present in the list of all lists"
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
                    assert (
                        e.status_code == 404
                    ), f"Expected 404 Not Found when getting deleted list, but got status {e.status_code}"
                    logger.info(
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
            assert isinstance(
                search_results, datatypes.PaginatedBookmarks
            ), "Search response should be PaginatedBookmarks model"
            assert isinstance(
                search_results.bookmarks, list
            ), "Search results bookmarks attribute should be a list"

            titles_in_search = [b.title for b in search_results.bookmarks]
            found_in_search = any(
                b.id == created_bookmark_id for b in search_results.bookmarks
            )
            if found_in_search:
                break
            else:
                time.sleep(3)
        assert (
            found_in_search
        ), f"Managed bookmark {created_bookmark_id} (Title: '{original_title}') not found in {trial + 1} different search results for '{search_query_component}'. Titles were: '{titles_in_search}'."
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
            assert (
                created_bookmark_id in search_cli_output.stdout
            ), f"Managed bookmark ID {created_bookmark_id} not found in CLI search output for '{search_query_component}'"
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
        assert isinstance(
            updated_bookmark_partial, dict
        ), "Update response should be a dict"
        assert (
            updated_bookmark_partial.get("title") == target_api_title
        ), f"Partial response title '{updated_bookmark_partial.get('title')}' does not match target API title '{target_api_title}'"
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
        assert (
            retrieved_bookmark_after_api_update.title == target_api_title
        ), f"Retrieved bookmark title '{retrieved_bookmark_after_api_update.title}' does not match expected API-updated title '{target_api_title}'"
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
            assert (
                retrieved_bookmark_after_cli_update.title == target_cli_title
            ), f"Retrieved bookmark title '{retrieved_bookmark_after_cli_update.title}' after CLI update does not match expected '{target_cli_title}'"
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
        assert (
            updated_tag["name"] == updated_tag_name
        ), "Tag name was not updated as expected"
        logger.info(f"✓ Tag {tag_id_to_manage} updated to name '{updated_tag['name']}'")

        # 3. Verify tag update by getting it directly
        logger.info(
            f"\nFetching tag {tag_id_to_manage} to verify its name is '{updated_tag_name}'"
        )
        retrieved_tag = karakeep_client.get_a_single_tag(tag_id=tag_id_to_manage)
        assert isinstance(
            retrieved_tag, datatypes.Tag
        ), "Get single tag response should be Tag model"
        assert (
            retrieved_tag.name == updated_tag_name
        ), "Retrieved tag name does not match updated name"
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
                    assert (
                        e.status_code == 404
                    ), f"Expected 404 Not Found when getting deleted tag, but got status {e.status_code}"
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
            assert (
                actual_count <= test_limit
            ), f"Expected at most {test_limit} bookmarks, got {actual_count}"

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
        assert (
            uploaded_asset.fileName == "PDF Bookmark Sample.pdf"
        ), "Asset filename should match the original file"
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
        assert (
            len(retrieved_bookmark.assets) > 0
        ), "Bookmark should have at least one asset"

        # Check that our uploaded asset is among the bookmark's assets
        asset_ids = [asset.id for asset in retrieved_bookmark.assets]
        assert (
            uploaded_asset_id in asset_ids
        ), f"Uploaded asset {uploaded_asset_id} should be attached to bookmark"
        logger.info(f"✓ Verified bookmark contains the PDF asset {uploaded_asset_id}")

        # 4. Retrieve and verify the asset content
        logger.info(f"\nRetrieving asset content for ID: {uploaded_asset_id}")
        asset_content = karakeep_client.get_a_single_asset(asset_id=uploaded_asset_id)
        assert isinstance(asset_content, bytes), "Asset content should be bytes"
        assert len(asset_content) > 0, "Asset content should not be empty"
        assert asset_content.startswith(b"%PDF"), "PDF should start with PDF header"
        logger.info(f"✓ Retrieved PDF asset content ({len(asset_content)} bytes)")

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


# --- End of Tests ---
