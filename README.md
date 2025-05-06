# Karakeep Python API Client

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![PyPI version](https://badge.fury.io/py/karakeep-python-api.svg)](https://badge.fury.io/py/karakeep-python-api) <!-- TODO: Add PyPI link once published -->

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
- [Development](#development)
- [License](#license)

## Overview

This library provides a Python interface (both a class and a command-line tool) to interact with a Karakeep instance's API.

The development process involved:

1.  Starting with the official Karakeep OpenAPI specification: [karakeep-openapi-spec.json](https://github.com/karakeep-app/karakeep/blob/main/packages/open-api/karakeep-openapi-spec.json).
2.  Generating Pydantic data models from the specification using [datamodel-code-generator](https://koxudaxi.github.io/datamodel-code-generator/).
3.  Using [aider.chat](https://aider.chat), an AI pair programming tool, to write the `KarakeepAPI` client class, the Click-based CLI, and the initial Pytest suite.

## Current Status & Caveats

*   **Experimental Methods:** The included Pytest suite currently only covers a subset of the available API methods (primarily 'get all' endpoints and client initialization). Methods *not* explicitly tested should be considered **experimental**.
*   **Ongoing Development:** The author intends to improve and validate methods as they are needed for personal use cases. Contributions and bug reports are welcome!

## API Method Coverage

The following table lists the public methods available in the `KarakeepAPI` class and indicates whether they are currently covered by the automated test suite (`tests/test_karakeep_api.py`). Methods marked as "No" should be used with caution as their behavior has not been automatically verified.

| Method Name                      | Tested | Remarks                                      |
| -------------------------------- | :----: | -------------------------------------------- |
| `get_all_bookmarks`              |   ✅   | Tested with pagination.                      |
| `create_a_new_bookmark`          |   ✅   | Only tested for `type="link"`.               |
| `search_bookmarks`               |   ✅   | Tested as part of create/delete flow.        |
| `get_a_single_bookmark`          |   ✅   | Tested as part of create/delete flow.        |
| `delete_a_bookmark`              |   ✅   | Tested as part of create/delete flow.        |
| `update_a_bookmark`              |   ✅   | Tested for title updates.                    |
| `summarize_a_bookmark`           |   ❌   |                                              |
| `attach_tags_to_a_bookmark`      |   ❌   |                                              |
| `detach_tags_from_a_bookmark`    |   ❌   |                                              |
| `get_highlights_of_a_bookmark`   |   ❌   |                                              |
| `attach_asset`                   |   ❌   |                                              |
| `replace_asset`                  |   ❌   |                                              |
| `detach_asset`                   |   ❌   |                                              |
| `get_all_lists`                  |   ✅   |                                              |
| `create_a_new_list`              |   ✅   | Tested as part of create/delete flow.        |
| `get_a_single_list`              |   ✅   | Tested as part of create/delete flow.        |
| `delete_a_list`                  |   ✅   | Tested as part of create/delete flow.        |
| `update_a_list`                  |   ❌   |                                              |
| `get_a_bookmarks_in_a_list`      |   ❌   |                                              |
| `add_a_bookmark_to_a_list`       |   ❌   |                                              |
| `remove_a_bookmark_from_a_list`  |   ❌   |                                              |
| `get_all_tags`                   |   ✅   |                                              |
| `get_a_single_tag`               |   ❌   |                                              |
| `delete_a_tag`                   |   ❌   |                                              |
| `update_a_tag`                   |   ❌   |                                              |
| `get_a_bookmarks_with_the_tag`   |   ❌   |                                              |
| `get_all_highlights`             |   ✅   | Tested with pagination.                      |
| `create_a_new_highlight`         |   ❌   |                                              |
| `get_a_single_highlight`         |   ❌   |                                              |
| `delete_a_highlight`             |   ❌   |                                              |
| `update_a_highlight`             |   ❌   |                                              |
| `get_current_user_info`          |   ✅   | Tested indirectly during client initialization. |
| `get_current_user_stats`         |   ✅   |                                              |

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

*   `KARAKEEP_PYTHON_API_BASE_URL`: **Required**. The full base URL of your Karakeep API, including the `/api/v1/` path (e.g., `https://your-karakeep.example.com/api/v1/` or `https://try.karakeep.app/api/v1/`).
*   `KARAKEEP_PYTHON_API_KEY`: **Required**. Your Karakeep API key (Bearer token).
*   `KARAKEEP_PYTHON_API_VERIFY_SSL`: Set to `false` to disable SSL certificate verification (default: `true`).
*   `KARAKEEP_PYTHON_API_VERBOSE`: Set to `true` to enable verbose debug logging for the client and CLI (default: `false`).
*   `KARAKEEP_PYTHON_API_DISABLE_RESPONSE_VALIDATION`: Set to `true` to disable Pydantic validation of API responses. The client will return raw dictionary/list data instead of Pydantic models (default: `false`).
*   `KARAKEEP_PYTHON_API_ENSURE_ASCII`: Set to `true` to escape non-ASCII characters in the JSON output (default: `false`, which means Unicode characters are kept).

### Command Line Interface (CLI)

The CLI dynamically generates commands based on the API methods. You need to provide your API key and base URL either via environment variables (recommended) or command-line options.

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
# Note: Ensure the base URL includes the /api/v1/ path
python -m karakeep_python_api --base-url https://my.karakeep.com/api/v1/ --api-key YOUR_API_KEY get-all-bookmarks --limit 10

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
# Example: os.environ["KARAKEEP_PYTHON_API_BASE_URL"] = "https://your-karakeep.example.com/api/v1/"
# Example: os.environ["KARAKEEP_PYTHON_API_KEY"] = "your_secret_api_key"

try:
    # Initialize the client (reads from env vars by default)
    client = KarakeepAPI(
        # Optionally override env vars:
        # base_url="https://another.karakeep.com",
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
    # Handles missing API key/base URL during initialization
    print(f"Configuration error: {e}")
except Exception as e:
    print(f"An unexpected error occurred: {e}")

```

## Development

1.  Clone the repository.
2.  Create a virtual environment and activate it.
3.  Install dependencies, including development tools (using `uv` recommended):

    ```bash
    uv pip install -e ".[dev]"
    ```
4.  Set the required environment variables (`KARAKEEP_PYTHON_API_BASE_URL`, `KARAKEEP_PYTHON_API_KEY`) for running tests against a live instance.
5.  Run tests:

    ```bash
    pytest
    ```

## License

This project is licensed under the **GNU General Public License v3 (GPLv3)**. See the [LICENSE](LICENSE) file for details.

---

*This README was generated with assistance from [aider.chat](https://aider.chat).*
