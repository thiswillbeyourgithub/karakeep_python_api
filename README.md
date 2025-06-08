# Karakeep Python API Client

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![PyPI version](https://badge.fury.io/py/karakeep-python-api.svg)](https://badge.fury.io/py/karakeep-python-api)

A community-developed Python client for the [Karakeep](https://karakeep.app/) API.

**Disclaimer:** This is an unofficial, community-driven project. The developers of Karakeep were not consulted during its creation. Use at your own discretion.

## Table of Contents

- [Overview](#overview)
- [Current Status & Caveats](#current-status--caveats)
- [API Method Coverage](#api-method-coverage)
- [Installation](#installation)
- [Usage](#usage)
  - [Environment Variables](#environment-variables)
  - [Command Line Interface (CLI)](#command-line-interface-cli)
  - [Python Library](#python-library)
- [Community Scripts](#community-scripts)
- [Development](#development)
- [License](#license)

## Overview

This library provides a Python interface (both a class and a command-line tool) to interact with a Karakeep instance's API. The author also developed [freshrss_to_karakeep](https://github.com/thiswillbeyourgithub/freshrss_to_karakeep), a Python script that periodically sends FreshRSS "favourite" articles to Karakeep (a bookmarking and read-it-later app, see [Karakeep on GitHub](https://github.com/karakeep-app/karakeep)).

The development process involved:

1.  Starting with the official Karakeep OpenAPI specification: [karakeep-openapi-spec.json](https://github.com/karakeep-app/karakeep/blob/main/packages/open-api/karakeep-openapi-spec.json).
2.  Generating Pydantic data models from the specification using [datamodel-code-generator](https://koxudaxi.github.io/datamodel-code-generator/).
3.  Using [aider.chat](https://aider.chat), an AI pair programming tool, to write the `KarakeepAPI` client class, the Click-based CLI, and the initial Pytest suite.

## Current Status & Caveats

*   **Experimental Methods:** The included Pytest suite currently only covers a subset of the available API methods (primarily 'get all' endpoints and client initialization). Methods *not* explicitly tested should be considered **experimental**.
*   **Ongoing Development:** The author intends to improve and validate methods as they are needed for personal use cases. Contributions and bug reports are welcome!

## API Method Coverage

The following table lists the public methods available in the `KarakeepAPI` class.
*   The "Pytest" column indicates whether the Python library method is covered by the automated test suite (`tests/test_karakeep_api.py`).
*   The "CLI" column indicates whether the corresponding CLI command for that method is tested within the Pytest suite (typically via `subprocess`).
Methods or CLI commands marked with ❌ should be used with caution as their behavior has not been automatically verified within the test suite.

| Method Name                      | Pytest | CLI  | Remarks                                      |
| -------------------------------- | :----: | :--: | -------------------------------------------- |
| `get_all_bookmarks`              |   ✅   |  ✅  | Tested with pagination.                      |
| `create_a_new_bookmark`          |   ✅   |  ❌  | Pytest for `type="link"` via fixture and `type="asset"` via PDF test. CLI not directly tested. |
| `search_bookmarks`               |   ✅   |  ✅  | Seems to be nondeterministic and fails if using more than 3 words        |
| `get_a_single_bookmark`          |   ✅   |  ❌  |  |
| `delete_a_bookmark`              |   ✅   |  ❌  |  |
| `update_a_bookmark`              |   ✅   |  ✅  | Tested for title updates.                    |
| `summarize_a_bookmark`           |   ❌   |  ❌  |                                              |
| `attach_tags_to_a_bookmark`      |   ✅   |  ❌  |  |
| `detach_tags_from_a_bookmark`    |   ✅   |  ❌  |  |
| `get_highlights_of_a_bookmark`   |   ❌   |  ❌  | Works from the CLI; not yet added to Pytest. |
| `attach_asset`                   |   ❌   |  ❌  |                                              |
| `replace_asset`                  |   ❌   |  ❌  |                                              |
| `detach_asset`                   |   ❌   |  ❌  |                                              |
| `get_all_lists`                  |   ✅   |  ✅  |                                              |
| `create_a_new_list`              |   ✅   |  ❌  | |
| `get_a_single_list`              |   ✅   |  ❌  | |
| `delete_a_list`                  |   ✅   |  ❌  | |
| `update_a_list`                  |   ❌   |  ❌  |                                              |
| `get_bookmarks_in_the_list`      |   ❌   |  ❌  |                                              |
| `add_a_bookmark_to_a_list`       |   ❌   |  ❌  |                                              |
| `remove_a_bookmark_from_a_list`  |   ❌   |  ❌  |                                              |
| `get_all_tags`                   |   ✅   |  ✅  |                                              |
| `create_a_new_tag`               |   ❌   |  ❌  |                                              |
| `get_a_single_tag`               |   ✅   |  ❌  |  |
| `delete_a_tag`                   |   ✅   |  ❌  |  |
| `update_a_tag`                   |   ✅   |  ❌  |  No output validation due to [server bug](https://github.com/karakeep-app/karakeep/issues/1365). |
| `get_bookmarks_with_the_tag`   |   ❌   |  ❌  |                                              |
| `get_all_highlights`             |   ✅   |  ✅  | Tested with pagination.                      |
| `create_a_new_highlight`         |   ❌   |  ❌  |                                              |
| `get_a_single_highlight`         |   ❌   |  ❌  |                                              |
| `delete_a_highlight`             |   ❌   |  ❌  | Works from the CLI; not yet added to Pytest. |
| `update_a_highlight`             |   ❌   |  ❌  |                                              |
| `upload_a_new_asset`             |   ✅   |  ❌  | Tested in PDF asset lifecycle test.         |
| `get_a_single_asset`             |   ✅   |  ❌  | Tested in PDF asset lifecycle test.         |
| `get_current_user_info`          |   ✅   |  ❌  | Pytest: Tested indirectly during client init. CLI not directly tested. |
| `get_current_user_stats`         |   ✅   |  ✅  |                                              |

## Installation

It is recommended to use `uv` for faster installation:

```bash
uv pip install karakeep-python-api
```

Alternatively, use standard `pip`:

```bash
pip install karakeep-python-api
```

## Usage

This package can be used as a Python library or as a command-line interface (CLI).

### Environment Variables

The client can be configured using the following environment variables:

*   `KARAKEEP_PYTHON_API_ENDPOINT`: **Required**. The full URL of your Karakeep API, including the `/api/v1/` path (e.g., `https://karakeep.domain.com/api/v1/` or `https://try.karakeep.app/api/v1/`).
*   `KARAKEEP_PYTHON_API_KEY`: **Required**. Your Karakeep API key (Bearer token).
*   `KARAKEEP_PYTHON_API_VERIFY_SSL`: Set to `false` to disable SSL certificate verification (default: `true`).
*   `KARAKEEP_PYTHON_API_VERBOSE`: Set to `true` to enable verbose debug logging for the client and CLI (default: `false`).
*   `KARAKEEP_PYTHON_API_DISABLE_RESPONSE_VALIDATION`: Set to `true` to disable Pydantic validation of API responses. The client will return raw dictionary/list data instead of Pydantic models (default: `false`).
*   `KARAKEEP_PYTHON_API_ENSURE_ASCII`: Set to `true` to escape non-ASCII characters in the JSON output (default: `false`, which means Unicode characters are kept).

### Command Line Interface (CLI)

The CLI dynamically generates commands based on the API methods. You need to provide your API key and endpoint either via environment variables (recommended) or command-line options.

**Basic Structure:**

```bash
python -m karakeep_python_api [GLOBAL_OPTIONS] <COMMAND> [COMMAND_OPTIONS]
```

**Getting Help:**

```bash
# General help and list of commands
python -m karakeep_python_api --help

# Help for a specific command
python -m karakeep_python_api get-all-bookmarks --help
```

**Examples:**

```bash
# List all tags (requires env vars set)
python -m karakeep_python_api get-all-tags

# Get the first page of bookmarks with a limit, overriding env vars if needed
# Note: The /api/v1/ path will be automatically appended if not present
python -m karakeep_python_api --base-url https://karakeep.domain.com/api/v1/ --api-key YOUR_API_KEY get-all-bookmarks --limit 10

# Get all lists and pipe the JSON output to jq to extract the first list
python -m karakeep_python_api get-all-lists | jq '.[0]'

# Create a new bookmark from a link (body provided as JSON string)
python -m karakeep_python_api create-a-new-bookmark --data '{"type": "link", "url": "https://example.com"}'

# Get all tags and ensure ASCII output (e.g., for compatibility with systems that don't handle Unicode well)
python -m karakeep_python_api --ascii get-all-tags

# Dump the raw OpenAPI spec used by the client
python -m karakeep_python_api --dump-openapi-specification
```

### Python Library

Import the `KarakeepAPI` class and instantiate it.

```python
import os
from karakeep_python_api import KarakeepAPI, APIError, AuthenticationError, datatypes

# Ensure required environment variables are set
# Example: os.environ["KARAKEEP_PYTHON_API_ENDPOINT"] = "https://karakeep.domain.com/api/v1/"
# Example: os.environ["KARAKEEP_PYTHON_API_KEY"] = "your_secret_api_key"

try:
    # Initialize the client (reads from env vars by default)
    client = KarakeepAPI(
        # Optionally override env vars:
        # api_endpoint="https://karakeep.domain.com/api/v1/",
        # api_key="another_key",
        # verbose=True,
        # disable_response_validation=False
    )

    # Example: Get all lists
    all_lists = client.get_all_lists()
    if all_lists:
        print(f"Retrieved {len(all_lists)} lists.")
        # Access list properties (uses Pydantic models by default)
        print(f"First list name: {all_lists[0].name}")
        print(f"First list ID: {all_lists[0].id}")
    else:
        print("No lists found.")

    # Example: Get first page of bookmarks
    bookmarks_page = client.get_all_bookmarks(limit=5)
    print(f"\nRetrieved {len(bookmarks_page.bookmarks)} bookmarks.")
    if bookmarks_page.bookmarks:
        print(f"First bookmark title: {bookmarks_page.bookmarks[0].title}")
    if bookmarks_page.nextCursor:
        print(f"Next page cursor: {bookmarks_page.nextCursor}")


except AuthenticationError as e:
    print(f"Authentication failed: {e}")
except APIError as e:
    print(f"An API error occurred: {e}")
except ValueError as e:
    # Handles missing API key/endpoint during initialization
    print(f"Configuration error: {e}")
except Exception as e:
    print(f"An unexpected error occurred: {e}")

```

## Community Scripts

Community Scripts are a bunch of scripts made to solve specific issues. They are made by the community so don't hesitate to submit yours or open an issue if you have a bug. They also serve as example of how to use the API.

They can be found in the [./community_scripts](https://github.com/thiswillbeyourgithub/karakeep_python_api/tree/main/community_scripts) folder. Don't hesitate to submit yours, the contribution guidelines are in the community_scripts directory README.md file.

| Community Script | Description                                                                                                | Documentation |
|----------------|--------------------------------------------------------------------------------------------------------------|---------------|
| **Karakeep-Time-Tagger** | Automatically adds time-to-read tags (`0-5m`, `5-10m`, etc.) to bookmarks based on content length analysis. Includes systemd service and timer files for automated periodic execution. | [`Link`](https://github.com/thiswillbeyourgithub/karakeep_python_api/tree/main/community_scripts/karakeep-time-tagger) |
| **Karakeep-List-To-Tag** | Converts a Karakeep list into tags by adding a specified tag to all bookmarks within that list.                                                                                        | [`Link`](https://github.com/thiswillbeyourgithub/karakeep_python_api/tree/main/community_scripts/karakeep-list-to-tag) |
| **Omnivore2Karakeep-Highlights** | Imports highlights from Omnivore export data to Karakeep, with intelligent position detection and bookmark matching. Supports dry-run mode for testing.                                | [`Link`](https://github.com/thiswillbeyourgithub/karakeep_python_api/tree/main/community_scripts/omnivore2karakeep-highlights) |
| **Omnivore2Karakeep-Archived** | (Should not be needed anymore) Fixes the archived status of bookmarks imported from Omnivore by reading export data and updating Karakeep accordingly.                                 | [`Link`](https://github.com/thiswillbeyourgithub/karakeep_python_api/tree/main/community_scripts/omnivore2karakeep-archived) |
| **pocket2karakeep-archived** by [@youenchene](https://github.com/youenchene) | (Should not be needed anymore) Fixes the archived status of bookmarks imported from Pocket by reading export data and updating Karakeep accordingly.                                   | [`Link`](https://github.com/thiswillbeyourgithub/karakeep_python_api/tree/main/community_scripts/pocket2karakeep-archived) |
| **Karakeep-Archive-Before-Date** by [@youenchene](https://github.com/youenchene) | Allow you to archive all not archived post before a given date                                                                                                                         | [`Link`](https://github.com/thiswillbeyourgithub/karakeep_python_api/tree/main/community_scripts/karakeep-archive-before-date) |
| **Freshrss-To-Karakeep**  |  Syncs some links from Freshrss to Karakeep      | [`Link`](https://github.com/thiswillbeyourgithub/freshrss_to_karakeep) |

## Development

1.  Clone the repository.
2.  Create a virtual environment and activate it.
3.  Install dependencies, including development tools (using `uv` recommended):

    ```bash
    uv pip install -e ".[dev]"
    ```
4.  Set the required environment variables (`KARAKEEP_PYTHON_API_ENDPOINT`, `KARAKEEP_PYTHON_API_KEY`) for running tests against a live instance.
5.  Run tests:

    ```bash
    pytest
    ```

## License

This project is licensed under the **GNU General Public License v3 (GPLv3)**. See the [LICENSE](LICENSE) file for details.

---

*This README was generated with assistance from [aider.chat](https://aider.chat).*
