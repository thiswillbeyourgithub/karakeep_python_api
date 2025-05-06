import time
import os
import requests
import time
import inspect
import functools
import re
import sys
import pathlib
import json  # Still needed for spec loading if parse_spec not available, and _call
import datetime
import typing  # Need full import for get_type_hints resolution with forward refs
from typing import Optional, Dict, Any, List, Callable, Tuple, Union, Type, Literal
from urllib.parse import urljoin, urlparse
from loguru import logger
from pydantic import BaseModel  # Import BaseModel for type checking and serialization
from . import datatypes  # Import the generated Pydantic models

# --- Custom Exceptions ---


class APIError(Exception):
    """Base exception class for Karakeep API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message

    def __str__(self) -> str:
        if self.status_code:
            return f"[Status Code: {self.status_code}] {self.message}"
        return self.message


class AuthenticationError(APIError):
    """Exception raised for authentication errors (401)."""

    def __init__(self, message: str):
        super().__init__(message, status_code=401)


# --- Optional Imports ---

# Optional type checking with beartype
try:
    from beartype import beartype as optional_typecheck
except ImportError:

    def optional_typecheck(callable_obj: Callable) -> Callable:
        """Dummy decorator if beartype is not installed."""
        return callable_obj


# Optional BeautifulSoup for parsing HTML errors
try:
    from bs4 import BeautifulSoup

    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    BeautifulSoup = None  # Define as None if not available


@optional_typecheck
class KarakeepAPI:
    """
    A Python client for the Karakeep API.

    Provides methods to interact with a Karakeep instance, based on its OpenAPI specification.

    The official API documentation can be found at:
    https://docs.karakeep.app/API/

    The OpenAPI specification used by this client is based on:
    https://github.com/karakeep-app/karakeep/blob/main/packages/open-api/karakeep-openapi-spec.json

    Attributes:
        api_key (str): The API key used for authentication.
        api_base_url (str): The base URL of the Karakeep API instance.
        openapi_spec (dict): The parsed content of the OpenAPI specification file.
        verify_ssl (bool): Whether SSL verification is enabled.
        verbose (bool): Whether verbose logging is enabled.
        disable_response_validation (bool): Whether Pydantic response validation is disabled.
    """

    # Version reflects the client library version, updated by bumpver
    VERSION: str = "0.1.3"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        openapi_spec_path: Optional[str] = None,  # Allow None, default handled below
        verify_ssl: bool = True,
        verbose: bool = False,
        strict_response_parsing: bool = False,  # Kept for potential future use
        disable_response_validation: Optional[bool] = None,
    ):
        """
        Initialize the Karakeep API client.

        Args:
            api_key: Karakeep API key (Bearer token).
                     Defaults to KARAKEEP_PYTHON_API_KEY environment variable if not provided.
            base_url: Override the base URL for the API. Must be provided either as an argument
                      or via the KARAKEEP_PYTHON_API_BASE_URL environment variable.
            openapi_spec_path: Path to the OpenAPI JSON specification file.
                               Defaults to 'openapi_reference.json' alongside the package code if not provided.
                               The loaded spec is available via the `openapi_spec` attribute.
            verify_ssl: Whether to verify SSL certificates (default: True).
                        Can be overridden with KARAKEEP_PYTHON_API_VERIFY_SSL environment variable (true/false).
            verbose: Enable verbose logging (default: False).
                     Can be overridden with KARAKEEP_PYTHON_API_VERBOSE environment variable (true/false).
            strict_response_parsing: (Currently unused) If True, raise an APIError when response parsing fails.
            disable_response_validation: If True, skip Pydantic validation of API responses and return raw data.
                                         Defaults to False. Can be overridden by setting the
                                         KARAKEEP_PYTHON_API_DISABLE_RESPONSE_VALIDATION environment variable to "true".
        """
        # --- API Key Validation ---
        resolved_api_key = api_key or os.environ.get("KARAKEEP_PYTHON_API_KEY")
        if not resolved_api_key:
            raise ValueError(
                "API Key is required. Provide 'api_key' argument or set KARAKEEP_PYTHON_API_KEY environment variable."
            )
        self.api_key = resolved_api_key
        logger.debug("API Key loaded successfully.")

        # --- Base URL Validation ---
        env_base_url = os.environ.get("KARAKEEP_PYTHON_API_BASE_URL")
        logger.debug(
            f"Checked KARAKEEP_PYTHON_API_BASE_URL environment variable, found: '{env_base_url}'"
        )
        logger.debug(f"Base URL provided as argument: '{base_url}'")

        if base_url:
            self.api_base_url = base_url
            logger.info(f"Using provided base URL: {self.api_base_url}")
        elif env_base_url:
            self.api_base_url = env_base_url
            logger.info(
                f"Using base URL from KARAKEEP_PYTHON_API_BASE_URL: {self.api_base_url}"
            )
        else:
            # No base_url from arg or env var - raise error as per requirement
            raise ValueError(
                "API base URL is required. Provide 'base_url' argument or set KARAKEEP_PYTHON_API_BASE_URL environment variable."
            )

        # Ensure base URL ends with /v1/
        resolved_url = self.api_base_url  # Use a temporary variable for checks
        if resolved_url.endswith("/v1"):
            # Ends with /v1, needs a slash
            self.api_base_url = resolved_url + "/"
            logger.info(
                f"Appended trailing slash to base URL ending in /v1: {self.api_base_url}"
            )
        elif resolved_url.endswith("/v1/"):
            # Already ends correctly, do nothing
            logger.debug(f"Base URL already ends with /v1/: {self.api_base_url}")
        else:
            # Doesn't end with /v1 or /v1/, append /v1/
            # First, remove any existing trailing slash to avoid //v1/
            if resolved_url.endswith("/"):
                resolved_url = resolved_url[:-1]
            self.api_base_url = resolved_url + "/v1/"
            logger.info(f"Appended /v1/ to base URL: {self.api_base_url}")

        logger.debug(f"Final API Base URL after /v1/ check: {self.api_base_url}")

        # --- Load and Parse OpenAPI Spec ---
        if openapi_spec_path is None:
            # Default path relative to this file
            openapi_spec_path = os.path.join(
                os.path.dirname(__file__), "openapi_reference.json"
            )
            logger.debug(
                f"OpenAPI spec path not provided, using default: {openapi_spec_path}"
            )
        else:
            logger.debug(f"Using provided OpenAPI spec path: {openapi_spec_path}")

        self.openapi_spec: Optional[Dict[str, Any]] = None  # Initialize attribute
        try:
            with open(openapi_spec_path, "r", encoding="utf-8") as f:
                self.openapi_spec = json.load(f)
            logger.info(f"Successfully loaded OpenAPI spec from: {openapi_spec_path}")
        except FileNotFoundError:
            logger.error(
                f"OpenAPI specification file not found at: {openapi_spec_path}"
            )
            # Decide if this should be a fatal error or just a warning
            # For now, log error and continue, self.openapi_spec remains None
            # raise APIError(f"OpenAPI specification file not found: {openapi_spec_path}")
        except json.JSONDecodeError as e:
            logger.error(
                f"Failed to parse OpenAPI specification file at {openapi_spec_path}: {e}"
            )
            # Decide if this should be a fatal error
            # raise APIError(f"Invalid JSON in OpenAPI specification file: {openapi_spec_path}") from e
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while loading the OpenAPI spec from {openapi_spec_path}: {e}"
            )
            # raise APIError(f"Failed to load OpenAPI spec: {openapi_spec_path}") from e

        self.verify_ssl = verify_ssl
        self.verbose = verbose
        self.strict_response_parsing = (
            strict_response_parsing  # Currently unused but kept
        )
        self.last_request_time: float = time.monotonic()  # Initialize timestamp for rate limiting

        # --- Response Validation Setting ---
        # Argument takes precedence over environment variable
        if disable_response_validation is not None:
            self.disable_response_validation = disable_response_validation
            logger.debug(
                f"Response validation explicitly set to {not self.disable_response_validation} via argument."
            )
        else:
            env_disable_validation = os.environ.get(
                "KARAKEEP_PYTHON_API_DISABLE_RESPONSE_VALIDATION", "false"
            ).lower()
            self.disable_response_validation = env_disable_validation == "true"
            logger.debug(
                f"Response validation set to {not self.disable_response_validation} via environment variable (KARAKEEP_PYTHON_API_DISABLE_RESPONSE_VALIDATION={env_disable_validation})."
            )

        # Configure logger based on verbosity
        if self.verbose:
            logger.add(
                sys.stderr,
                level="DEBUG",
                format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            )
            logger.info("Verbose logging enabled.")
        else:
            logger.add(sys.stderr, level="INFO")  # Default level

        logger.debug("KarakeepAPI client initialized.")
        logger.debug(f"  Base URL: {self.api_base_url}")
        logger.debug(f"  Verify SSL: {self.verify_ssl}")
        logger.debug(f"  Verbose: {self.verbose}")
        logger.debug(
            f"  Disable Response Validation: {self.disable_response_validation}"
        )
        # API Key is intentionally not logged for security

        # --- Initial Connection Check ---
        try:
            logger.debug("Performing initial connection check by fetching user info...")
            # Call the user info endpoint to verify connection and authentication
            user_info = self.get_current_user_info()  # Use the correct method name
            logger.info(
                f"Successfully connected to Karakeep API as user ID: {user_info.get('id', 'N/A')}"
            )
        except (APIError, AuthenticationError) as e:
            logger.error(f"Initial connection check failed: {e}")
            # Re-raise the exception to indicate initialization failure
            raise e
        except Exception as e:
            # Catch any other unexpected errors during the initial check
            logger.error(f"Unexpected error during initial connection check: {e}")
            raise APIError(
                f"Unexpected error during client initialization check: {e}"
            ) from e

    @optional_typecheck
    def _call(
        self,
        method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"],
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[
            Union[BaseModel, dict, list, str, bytes]
        ] = None,  # More specific type hint
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """
        Internal method to make an HTTP call to the Karakeep API. Handles authentication,
        request formatting, response parsing, and error handling.

        Args:
            method: HTTP method ('GET', 'POST', 'PUT', 'PATCH', 'DELETE').
            endpoint: API endpoint path relative to the base URL (e.g., 'bookmarks' or 'bookmarks/some_id').
                      Path parameters (like {bookmarkId}) MUST be substituted *before* calling _call.
            params: Dictionary of URL query parameters. Values should be primitive types suitable for URLs.
            data: Request body data. Can be a Pydantic model, dict, list, bytes, or str.
                  - Pydantic models, dicts, and lists will be automatically JSON-encoded
                    with 'Content-Type: application/json' unless overridden in extra_headers.
                  - For bytes or str, ensure 'Content-Type' is set correctly via extra_headers if needed.
            extra_headers: Additional headers to include or override default headers.

        Returns:
            The parsed JSON response from the API as a dict or list, or None for 204 No Content responses.
            The calling wrapper method is responsible for further parsing/validation into specific Pydantic models.

        Raises:
            AuthenticationError: If authentication fails (401).
            APIError: For other HTTP errors or request issues.
        """
        # Ensure endpoint doesn't start with / if base_url ends with /
        safe_endpoint = endpoint.lstrip("/")
        url = urljoin(self.api_base_url, safe_endpoint)

        # Default headers
        headers = {
            "Accept": "application/json",  # Default accept type
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": f"KarakeepPythonAPI/{self.VERSION}",
        }

        # Merge extra headers, allowing overrides (extra_headers takes precedence)
        if extra_headers:
            # Ensure header keys and values are strings
            stringified_extra_headers = {
                str(k): str(v) for k, v in extra_headers.items()
            }
            headers.update(stringified_extra_headers)

        # Prepare request body (data) and Content-Type header
        request_body_arg: Optional[Union[bytes, str]] = (
            None  # requests takes bytes or str for data arg
        )
        # Determine Content-Type, prioritizing extra_headers
        content_type = headers.get("Content-Type")

        if data is not None:
            if isinstance(data, BaseModel):
                # Serialize Pydantic model to JSON bytes
                request_body_arg = data.model_dump_json(
                    by_alias=True, exclude_none=True
                ).encode("utf-8")
                # Set Content-Type to application/json if not already set differently
                if content_type is None:
                    headers["Content-Type"] = "application/json"
                    content_type = "application/json"  # Update local var for logging
            elif isinstance(data, (dict, list)):
                # Serialize dict/list to JSON bytes
                try:
                    request_body_arg = json.dumps(data, ensure_ascii=False).encode(
                        "utf-8"
                    )
                except TypeError as e:
                    raise APIError(
                        f"Failed to JSON encode request data (dict/list): {e}"
                    ) from e
                # Set Content-Type to application/json if not already set differently
                if content_type is None:
                    headers["Content-Type"] = "application/json"
                    content_type = "application/json"  # Update local var for logging
            elif isinstance(data, str):
                # Pass string directly, requests will encode based on Content-Type or default
                request_body_arg = data
                if content_type is None:
                    logger.warning(
                        "Request data is str, but Content-Type header is not set. Assuming utf-8."
                    )
                    # Optionally set a default? Or rely on requests default?
                    # headers['Content-Type'] = 'text/plain; charset=utf-8' # Example
            elif isinstance(data, bytes):
                # Pass bytes directly
                request_body_arg = data
                if content_type is None:
                    logger.warning(
                        "Request data is bytes, but Content-Type header is not set."
                    )
            else:
                # Should not happen with type hints, but handle defensively
                raise APIError(
                    f"Unsupported request data type: {type(data)}. Use Pydantic model, dict, list, str, or bytes."
                )

            # Log warning if Content-Type seems mismatched with data type (e.g., JSON data without JSON header)
            if content_type != "application/json" and isinstance(
                data, (BaseModel, dict, list)
            ):
                logger.warning(
                    f"Request data is {type(data).__name__} but Content-Type is '{content_type}'. Ensure this is intended."
                )
            elif content_type == "application/json" and isinstance(data, (str, bytes)):
                logger.warning(
                    f"Request data is {type(data).__name__} but Content-Type is 'application/json'. Ensure data is valid JSON."
                )

        if self.verbose:
            # Mask Authorization header for logging
            log_headers = {
                k: ("Bearer ..." if k.lower() == "authorization" else v)
                for k, v in headers.items()
            }
            logger.debug(f"API Request:")
            logger.debug(f"  Method: {method}")
            logger.debug(f"  URL: {url}")
            logger.debug(f"  Params: {params}")
            logger.debug(f"  Headers: {log_headers}")
            # Log body carefully, decoding bytes if possible for readability
            log_body_display = "None"
            if request_body_arg:
                if isinstance(request_body_arg, bytes):
                    try:
                        # Try decoding as UTF-8 for logging, fallback to repr
                        log_body_display = request_body_arg.decode(
                            "utf-8", errors="replace"
                        )
                    except Exception:  # Broad catch for safety
                        log_body_display = repr(request_body_arg)
                else:  # Should be str or dict/list if not bytes
                    log_body_display = repr(request_body_arg)

            # Truncate long bodies for logging
            if len(log_body_display) > 500:
                log_body_display = log_body_display[:500] + "...(truncated)"
            logger.debug(f"  Body: {log_body_display}")  # Logging body remains the same

        # --- Make the Request ---
        try:
            # Filter out None values from params before sending
            filtered_params = (
                {k: v for k, v in params.items() if v is not None} if params else None
            )

            # Explicitly convert boolean values in params to capitalized strings "True" or "False"
            # This is needed if the API specifically expects these strings instead of standard 'true'/'false'.
            stringified_bool_params = {}
            if filtered_params:
                for k, v in filtered_params.items():
                    if isinstance(v, bool):
                        # Convert Python bool to lowercase string "true" or "false"
                        stringified_bool_params[k] = str(v).lower()
                    else:
                        stringified_bool_params[k] = v
                # Use the dictionary with stringified booleans for the request
                request_params = stringified_bool_params
            else:
                request_params = None

            # Using requests.request directly for simplicity, session might be better for performance
            response = None
            trial = 0
            max_trial = 3
            while response is None:
                trial += 1
                try:
                    # Enforce rate limit before making the request
                    self._enforce_rate_limit()

                    response = requests.request(
                        method=method,
                        url=url,
                        params=request_params,  # Use params with stringified booleans
                        data=request_body_arg,  # Serialized data (bytes or str)
                        headers=headers,
                        verify=self.verify_ssl,
                        timeout=60,  # Increased default timeout
                    )
                except Exception as e:
                    if trial >= max_trial:
                        logger.error("Too many retries. Crashing.")
                        raise
                    if "max retries exceeded" in str(e).lower():
                        logger.warning(
                            f"Error encounterd during requests. Trial={trial}/{max_trial}. Retrying after a small wait.\nError: {e}"
                        )
                        time.sleep(trial * 3)
                    else:
                        raise

            if self.verbose:
                logger.debug(f"API Response:")
                logger.debug(f"  Status Code: {response.status_code}")
                logger.debug(f"  Headers: {response.headers}")

            # --- Handle Response ---

            # Check for specific auth error first for a more specific exception
            if response.status_code == 401:
                error_msg = f"Authentication failed (401): Check your API Key. URL: {method} {url}"
                logger.error(error_msg)
                # Attempt to get more details from response body
                try:
                    details = response.json().get("message", response.text)
                    error_msg += f" Details: {details[:200]}..."  # Add snippet
                except Exception:
                    error_msg += f" Raw Response: {response.text[:200]}..."
                raise AuthenticationError(error_msg)

            # Check for other client/server errors (4xx/5xx)
            response.raise_for_status()  # Raises requests.exceptions.HTTPError for bad responses

            # Handle successful No Content response (204)
            if response.status_code == 204 or not response.content:
                if self.verbose:
                    logger.debug("  Body: None (204 No Content or empty response body)")
                return None

            # Attempt to parse successful response as JSON
            try:
                result = response.json()
                if self.verbose:
                    # Log parsed response body carefully
                    log_resp_str = repr(result)
                    if len(log_resp_str) > 1000:
                        log_resp_str = log_resp_str[:1000] + "...(truncated)"
                    logger.debug(f"  Body (JSON Parsed): {log_resp_str}")
                # Return the raw parsed JSON (dict/list). Deserialization into
                # specific Pydantic models should happen in the calling wrapper method.
                return result
            except json.JSONDecodeError as e:
                # Handle cases where the response is successful (2xx) but not valid JSON
                logger.error(
                    f"API Error: Failed to decode JSON response from {method} {url}. Status: {response.status_code}. Content: {response.text[:500]}..."
                )
                # Raise APIError as the response format is unexpected
                raise APIError(
                    message=f"Failed to parse successful API response JSON from {url}: {e}. Response text: {response.text[:200]}...",
                    status_code=response.status_code,
                ) from e

        except requests.exceptions.HTTPError as e:
            # Handle 4xx/5xx errors raised by response.raise_for_status()
            error_status_code = e.response.status_code
            error_body = e.response.text
            error_details = error_body  # Default to raw body

            # Attempt to extract a more meaningful message from the error response body
            try:
                parsed_error = json.loads(error_body)
                if isinstance(parsed_error, dict):
                    # Look for common error message keys
                    error_details = parsed_error.get(
                        "message", parsed_error.get("detail", error_body)
                    )
            except json.JSONDecodeError:
                # Not JSON, try parsing as HTML if bs4 is available and looks like HTML
                if BS4_AVAILABLE and error_body.strip().startswith(
                    ("<html", "<!DOCTYPE")
                ):
                    try:
                        soup = BeautifulSoup(error_body, "html.parser")
                        # Extract text, remove excessive whitespace
                        html_text = " ".join(soup.get_text().split())
                        if html_text:  # Use parsed text if not empty
                            error_details = html_text
                    except Exception as parse_err:  # Catch potential parsing errors
                        logger.warning(
                            f"Failed to parse HTML error body with BeautifulSoup: {parse_err}. Falling back to raw text."
                        )
                        # error_details remains raw body

            # Log the error
            max_log_len = 500
            log_details = (
                error_details[:max_log_len] + "..."
                if len(error_details) > max_log_len
                else error_details
            )
            logger.error(
                f"API HTTP Error {error_status_code} for {method} {url}. Response: {log_details}"
            )

            # Raise our custom APIError
            max_exc_len = 500
            truncated_details = (
                error_details[:max_exc_len] + "..."
                if len(error_details) > max_exc_len
                else error_details
            )
            raise APIError(
                message=f"API request failed for {method} {url}: {truncated_details}",
                status_code=error_status_code,
            ) from e

        except requests.exceptions.Timeout as e:
            logger.error(f"API Error: Request timed out for {method} {url}: {e}")
            raise APIError(message=f"Request timed out for {method} {url}") from e
        except requests.exceptions.ConnectionError as e:
            logger.error(f"API Error: Connection error for {method} {url}: {e}")
            raise APIError(
                message=f"Connection error for {method} {url}: {str(e)}"
            ) from e
        except requests.exceptions.RequestException as e:
            # Catch other potential request-related errors
            logger.error(
                f"API Error: An unexpected request exception occurred for {method} {url}: {e}"
            )
            raise APIError(
                message=f"API request failed for {method} {url}: {str(e)}"
            ) from e

    @optional_typecheck
    def _enforce_rate_limit(self, min_interval_sec: float = 2.0) -> None:
        """
        Ensures a minimum time interval between consecutive API calls.

        If the time since the last call is less than `min_interval_sec`, this method
        will sleep for the remaining duration. It then updates the timestamp of the
        last request.

        Args:
            min_interval_sec: The minimum desired interval between requests in seconds.
        """
        current_time = time.monotonic()
        time_since_last = current_time - self.last_request_time

        if time_since_last < min_interval_sec:
            sleep_duration = min_interval_sec - time_since_last
            if self.verbose:
                logger.debug(
                    f"Rate limit triggered. Sleeping for {sleep_duration:.3f} seconds."
                )
            time.sleep(sleep_duration)

        # Update last request time *after* potential sleep
        self.last_request_time = time.monotonic()

    # --- Dynamically Generated API Methods ---

    @optional_typecheck
    def get_all_bookmarks(
        self,
        archived: Optional[bool] = None,
        favourited: Optional[bool] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        include_content: bool = True,  # Default from spec
    ) -> Any:  # Returns PaginatedBookmarks or raw dict/list
        """
        Get all bookmarks. Corresponds to GET /bookmarks.

        Args:
            archived: Filter by archived status (optional).
            favourited: Filter by favourited status (optional).
            limit: Maximum number of bookmarks to return (optional).
            cursor: Pagination cursor for the next page (optional).
            include_content: If set to true, bookmark's content will be included (default: True).

        Returns:
            datatypes.PaginatedBookmarks: Paginated list of bookmarks.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails.
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        params = {
            "archived": archived,
            "favourited": favourited,
            "limit": limit,
            "cursor": cursor,
            "includeContent": include_content,  # Use camelCase as per API spec query param
        }
        response_data = self._call("GET", "bookmarks", params=params)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match PaginatedBookmarks schema
            return datatypes.PaginatedBookmarks.model_validate(response_data)

    @optional_typecheck
    def create_a_new_bookmark(
        self,
        type: Literal["link", "text", "asset"],
        # Common optional fields
        title: Optional[str] = None,
        archived: Optional[bool] = None,
        favourited: Optional[bool] = None,
        note: Optional[str] = None,
        summary: Optional[str] = None,
        createdAt: Optional[str] = None,  # ISO 8601 format string
        # Link specific
        url: Optional[str] = None,
        precrawledArchiveId: Optional[str] = None,
        # Text specific
        text: Optional[str] = None,
        sourceUrl: Optional[str] = None,  # Also used by asset
        # Asset specific
        asset_type: Optional[Literal["image", "pdf"]] = None,
        assetId: Optional[str] = None,
        fileName: Optional[str] = None,
        # size: Optional[int] = None, # Size is not in POST spec
        # content: Optional[str] = None, # Content is not in POST spec
    ) -> Any:  # Returns Bookmark or raw dict/list
        """
        Create a new bookmark. Corresponds to POST /bookmarks.

        Args:
            type: The type of bookmark ('link', 'text', 'asset'). Required.
            title: Optional title for the bookmark (max 1000 chars).
            archived: Optional boolean indicating if the bookmark is archived.
            favourited: Optional boolean indicating if the bookmark is favourited.
            note: Optional note content for the bookmark.
            summary: Optional summary content for the bookmark.
            createdAt: Optional creation timestamp override (ISO 8601 format string).

            --- Link Type Specific ---
            url: The URL for the link bookmark. Required if type='link'.
            precrawledArchiveId: Optional ID of a pre-crawled archive.

            --- Text Type Specific ---
            text: The text content for the text bookmark. Required if type='text'.
            sourceUrl: Optional source URL where the text originated.

            --- Asset Type Specific ---
            asset_type: The type of asset ('image' or 'pdf'). Required if type='asset'.
            assetId: The ID of the uploaded asset. Required if type='asset'.
            fileName: Optional filename for the asset.
            sourceUrl: Optional source URL where the asset originated.

        Returns:
            datatypes.Bookmark: The created bookmark.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            ValueError: If required arguments for the specified type are missing.
            APIError: If the API request fails (e.g., bad request).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        # --- Construct the request body ---
        request_body: Dict[str, Any] = {"type": type}

        # Add common optional fields if provided
        if title is not None:
            request_body["title"] = title
        if archived is not None:
            request_body["archived"] = archived
        if favourited is not None:
            request_body["favourited"] = favourited
        if note is not None:
            request_body["note"] = note
        if summary is not None:
            request_body["summary"] = summary
        if createdAt is not None:
            request_body["createdAt"] = createdAt

        # Add type-specific fields and perform validation
        if type == "link":
            if url is None:
                raise ValueError("Argument 'url' is required when type is 'link'.")
            request_body["url"] = url
            if precrawledArchiveId is not None:
                request_body["precrawledArchiveId"] = precrawledArchiveId
        elif type == "text":
            if text is None:
                raise ValueError("Argument 'text' is required when type is 'text'.")
            request_body["text"] = text
            if sourceUrl is not None:
                request_body["sourceUrl"] = sourceUrl
        elif type == "asset":
            if asset_type is None:
                raise ValueError(
                    "Argument 'asset_type' ('image' or 'pdf') is required when type is 'asset'."
                )
            if assetId is None:
                raise ValueError(
                    "Argument 'assetId' is required when type is 'asset'."
                )
            request_body["assetType"] = asset_type
            request_body["assetId"] = assetId
            if fileName is not None:
                request_body["fileName"] = fileName
            if sourceUrl is not None:
                request_body["sourceUrl"] = sourceUrl
        else:
            # Should not happen with Literal type hint, but defensive check
            raise ValueError(f"Invalid bookmark type specified: {type}")

        # --- Make the API call ---
        response_data = self._call("POST", "bookmarks", data=request_body)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match Bookmark schema
            return datatypes.Bookmark.model_validate(response_data)

    @optional_typecheck
    def search_bookmarks(
        self,
        q: str,  # Search query is required
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        include_content: bool = True,  # Default from spec
    ) -> Any:  # Returns PaginatedBookmarks or raw dict/list
        """
        Search bookmarks. Corresponds to GET /bookmarks/search.

        Args:
            q: The search query string.
            limit: Maximum number of bookmarks to return (optional).
            cursor: Pagination cursor for the next page (optional).
            include_content: If set to true, bookmark's content will be included (default: True).

        Returns:
            datatypes.PaginatedBookmarks: Paginated list of bookmarks matching the search query.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails.
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        params = {
            "q": q,
            "limit": limit,
            "cursor": cursor,
            "includeContent": include_content,  # Use camelCase as per API spec query param
        }
        response_data = self._call("GET", "bookmarks/search", params=params)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match PaginatedBookmarks schema
            return datatypes.PaginatedBookmarks.model_validate(response_data)

    @optional_typecheck
    def get_a_single_bookmark(
        self, bookmark_id: str, include_content: bool = True  # Default from spec
    ) -> Any:  # Returns Bookmark or raw dict/list
        """
        Get a single bookmark by its ID. Corresponds to GET /bookmarks/{bookmarkId}.

        Args:
            bookmark_id: The ID (string) of the bookmark to retrieve.
            include_content: If set to true, bookmark's content will be included (default: True).

        Returns:
            datatypes.Bookmark: The requested bookmark.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails (e.g., 404 bookmark not found).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        endpoint = f"bookmarks/{bookmark_id}"
        params = {
            "includeContent": include_content
        }  # Use camelCase as per API spec query param
        response_data = self._call("GET", endpoint, params=params)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match Bookmark schema
            return datatypes.Bookmark.model_validate(response_data)

    @optional_typecheck
    def delete_a_bookmark(self, bookmark_id: str) -> None:
        """
        Delete a bookmark by its ID. Corresponds to DELETE /bookmarks/{bookmarkId}.

        Args:
            bookmark_id: The ID (string) of the bookmark to delete.

        Returns:
            None: Returns None upon successful deletion (204 No Content).

        Raises:
            APIError: If the API request fails (e.g., 404 bookmark not found).
        """
        endpoint = f"bookmarks/{bookmark_id}"
        self._call("DELETE", endpoint)  # Expects 204 No Content
        return None  # Explicitly return None for 204

    @optional_typecheck
    def update_a_bookmark(
        self, bookmark_id: str, update_data: dict
    ) -> Any:  # Returns dict
        """
        Update a bookmark by its ID. Corresponds to PATCH /bookmarks/{bookmarkId}.
        Allows updating fields like 'archived', 'favourited', 'summary', 'note', 'title', etc.

        Args:
            bookmark_id: The ID (string) of the bookmark to update.
            update_data: A dictionary containing the fields to update (e.g., `{"archived": True}`).
                         See the OpenAPI spec for allowed fields in the request body.

        Returns:
            dict: A dictionary representing the updated bookmark (partial representation).
                  The response typically includes 'id', 'createdAt', 'modifiedAt', 'title', 'archived', 'favourited',
                  'taggingStatus', 'note', 'summary'.
                  Validation is not performed on this response type by default.

        Raises:
            APIError: If the API request fails (e.g., 404 bookmark not found).
        """
        endpoint = f"bookmarks/{bookmark_id}"
        response_data = self._call("PATCH", endpoint, data=update_data)
        # The response schema is a subset of Bookmark, return as dict as specified in spec
        # No Pydantic validation applied here as the spec defines a partial response (dict)
        return response_data

    @optional_typecheck
    def summarize_a_bookmark(self, bookmark_id: str) -> Any:  # Returns dict
        """
        Summarize a bookmark by its ID. Corresponds to POST /bookmarks/{bookmarkId}/summarize.
        This triggers the summarization process and returns the updated bookmark record (partially).

        Args:
            bookmark_id: The ID (string) of the bookmark to summarize.

        Returns:
            dict: A dictionary representing the updated bookmark with the summary (partial representation).
                  Similar structure to the response of `update_a_bookmark`.
                  Validation is not performed on this response type by default.

        Raises:
            APIError: If the API request fails (e.g., 404 bookmark not found, summarization failure).
        """
        endpoint = f"bookmarks/{bookmark_id}/summarize"
        response_data = self._call("POST", endpoint)
        # The response schema is a subset of Bookmark, return as dict as specified in spec
        # No Pydantic validation applied here as the spec defines a partial response (dict)
        return response_data

    @optional_typecheck
    def attach_tags_to_a_bookmark(
        self, bookmark_id: str, tags_data: dict
    ) -> Any:  # Returns dict
        """
        Attach one or more tags to a bookmark. Corresponds to POST /bookmarks/{bookmarkId}/tags.

        Args:
            bookmark_id: The ID (string) of the bookmark.
            tags_data: Dictionary specifying the tags to attach. Must contain a "tags" key
                       which is a list of objects, each having *either* "tagId" (string) *or* "tagName" (string).
                       Example: `{"tags": [{"tagId": "existing_tag_id"}, {"tagName": "new_or_existing_tag_name"}]}`

        Returns:
            dict: A dictionary containing the list of attached tag IDs under the key "attached".
                  Example: `{"attached": ["tag_id_1", "tag_id_2"]}`
                  Validation is not performed on this response type by default.

        Raises:
            APIError: If the API request fails (e.g., 404 bookmark not found).
        """
        endpoint = f"bookmarks/{bookmark_id}/tags"
        response_data = self._call("POST", endpoint, data=tags_data)
        # Response schema is {"attached": [TagId]}, return as dict
        # No Pydantic validation applied here as the spec defines a simple dict response
        return response_data

    @optional_typecheck
    def detach_tags_from_a_bookmark(
        self, bookmark_id: str, tags_data: dict
    ) -> Any:  # Returns dict
        """
        Detach one or more tags from a bookmark. Corresponds to DELETE /bookmarks/{bookmarkId}/tags.

        Args:
            bookmark_id: The ID (string) of the bookmark.
            tags_data: Dictionary specifying the tags to detach. Must contain a "tags" key
                       which is a list of objects, each having *either* "tagId" (string) *or* "tagName" (string).
                       Example: `{"tags": [{"tagId": "tag_id_to_remove"}, {"tagName": "tag_name_to_remove"}]}`

        Returns:
            dict: A dictionary containing the list of detached tag IDs under the key "detached".
                  Example: `{"detached": ["tag_id_1", "tag_id_2"]}`
                  Validation is not performed on this response type by default.

        Raises:
            APIError: If the API request fails (e.g., 404 bookmark not found).
        """
        endpoint = f"bookmarks/{bookmark_id}/tags"
        response_data = self._call("DELETE", endpoint, data=tags_data)
        # Response schema is {"detached": [TagId]}, return as dict
        # No Pydantic validation applied here as the spec defines a simple dict response
        return response_data

    @optional_typecheck
    def get_highlights_of_a_bookmark(
        self, bookmark_id: str
    ) -> Any:  # Returns List[Highlight] or raw dict/list
        """
        Get all highlights associated with a specific bookmark. Corresponds to GET /bookmarks/{bookmarkId}/highlights.

        Args:
            bookmark_id: The ID (string) of the bookmark.

        Returns:
            List[datatypes.Highlight]: A list of highlight objects associated with the bookmark.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails (e.g., 404 bookmark not found).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        endpoint = f"bookmarks/{bookmark_id}/highlights"
        response_data = self._call("GET", endpoint)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            # Return raw data, which might be {"highlights": [...]} or something else
            return response_data
        else:
            # Response schema is {"highlights": [Highlight]}, extract the list and validate
            if (
                isinstance(response_data, dict)
                and "highlights" in response_data
                and isinstance(response_data["highlights"], list)
            ):
                try:
                    return [
                        datatypes.Highlight.model_validate(h)
                        for h in response_data["highlights"]
                    ]
                except (
                    Exception
                ) as e:  # Catch validation errors during list comprehension
                    logger.error(f"Validation failed for one or more highlights: {e}")
                    raise  # Re-raise the validation error
            else:
                # Raise error if format is unexpected and validation is enabled
                raise APIError(
                    f"Unexpected response format for get_highlights_of_a_bookmark when validation is enabled: {response_data}"
                )

    @optional_typecheck
    def attach_asset(
        self, bookmark_id: str, asset_data: dict
    ) -> Any:  # Returns Asset or raw dict/list
        """
        Attach a new asset to a bookmark. Corresponds to POST /bookmarks/{bookmarkId}/assets.

        Args:
            bookmark_id: The ID (string) of the bookmark.
            asset_data: Dictionary specifying the asset to attach. Must contain "id" (string) and "assetType" (string enum).
                        Example: `{"id": "asset_id_string", "assetType": "screenshot"}`
                        See `datatypes.AssetType1` enum for possible asset types.

        Returns:
            datatypes.Asset: The attached asset object.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails (e.g., 404 bookmark not found).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        endpoint = f"bookmarks/{bookmark_id}/assets"
        response_data = self._call("POST", endpoint, data=asset_data)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match Asset schema
            return datatypes.Asset.model_validate(response_data)

    @optional_typecheck
    def replace_asset(
        self, bookmark_id: str, asset_id: str, new_asset_data: dict
    ) -> None:
        """
        Replace an existing asset associated with a bookmark with a new one.
        Corresponds to PUT /bookmarks/{bookmarkId}/assets/{assetId}.

        Args:
            bookmark_id: The ID (string) of the bookmark.
            asset_id: The ID (string) of the asset to be replaced.
            new_asset_data: Dictionary specifying the new asset ID. Must contain "assetId" (string).
                            Example: `{"assetId": "new_asset_id_string"}`

        Returns:
            None: Returns None upon successful replacement (204 No Content).

        Raises:
            APIError: If the API request fails (e.g., 404 bookmark or asset not found).
        """
        endpoint = f"bookmarks/{bookmark_id}/assets/{asset_id}"
        self._call("PUT", endpoint, data=new_asset_data)  # Expects 204 No Content
        return None  # Explicitly return None for 204

    @optional_typecheck
    def detach_asset(self, bookmark_id: str, asset_id: str) -> None:
        """
        Detach an asset from a bookmark. Corresponds to DELETE /bookmarks/{bookmarkId}/assets/{assetId}.

        Args:
            bookmark_id: The ID (string) of the bookmark.
            asset_id: The ID (string) of the asset to detach.

        Returns:
            None: Returns None upon successful detachment (204 No Content).

        Raises:
            APIError: If the API request fails (e.g., 404 bookmark or asset not found).
        """
        endpoint = f"bookmarks/{bookmark_id}/assets/{asset_id}"
        self._call("DELETE", endpoint)  # Expects 204 No Content
        return None  # Explicitly return None for 204

    @optional_typecheck
    def get_all_lists(self) -> Any:  # Returns List[ListModel] or raw dict/list
        """
        Get all lists for the current user. Corresponds to GET /lists.

        Returns:
            List[datatypes.ListModel]: A list of list objects.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails.
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        response_data = self._call("GET", "lists")

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            # Return raw data, which might be {"lists": [...]} or something else
            return response_data
        else:
            # Response schema is {"lists": [ListModel]}, extract the list and validate
            if (
                isinstance(response_data, dict)
                and "lists" in response_data
                and isinstance(response_data["lists"], list)
            ):
                try:
                    return [
                        datatypes.ListModel.model_validate(lst)
                        for lst in response_data["lists"]
                    ]
                except (
                    Exception
                ) as e:  # Catch validation errors during list comprehension
                    logger.error(f"Validation failed for one or more lists: {e}")
                    raise  # Re-raise the validation error
            else:
                # Raise error if format is unexpected and validation is enabled
                raise APIError(
                    f"Unexpected response format for get_all_lists when validation is enabled: {response_data}"
                )

    @optional_typecheck
    def create_a_new_list(
        self, list_data: dict
    ) -> Any:  # Returns ListModel or raw dict/list
        """
        Create a new list (manual or smart). Corresponds to POST /lists.

        Args:
            list_data: Dictionary containing the data for the new list. Requires "name" (string) and "icon" (string).
                       Optional fields include "description", "parentId", "type" ('manual' or 'smart'), "query".
                       See the OpenAPI spec for details. Example: `{"name": "My List", "icon": "📚"}`

        Returns:
            datatypes.ListModel: The created list object.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails (e.g., bad request, invalid data).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        response_data = self._call("POST", "lists", data=list_data)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match ListModel schema
            return datatypes.ListModel.model_validate(response_data)

    @optional_typecheck
    def get_a_single_list(
        self, list_id: str
    ) -> Any:  # Returns ListModel or raw dict/list
        """
        Get a single list by its ID. Corresponds to GET /lists/{listId}.

        Args:
            list_id: The ID (string) of the list to retrieve.

        Returns:
            datatypes.ListModel: The requested list object.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails (e.g., 404 list not found).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        endpoint = f"lists/{list_id}"
        response_data = self._call("GET", endpoint)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match ListModel schema
            return datatypes.ListModel.model_validate(response_data)

    @optional_typecheck
    def delete_a_list(self, list_id: str) -> None:
        """
        Delete a list by its ID. Corresponds to DELETE /lists/{listId}.

        Args:
            list_id: The ID (string) of the list to delete.

        Returns:
            None: Returns None upon successful deletion (204 No Content).

        Raises:
            APIError: If the API request fails (e.g., 404 list not found).
        """
        endpoint = f"lists/{list_id}"
        self._call("DELETE", endpoint)  # Expects 204 No Content
        return None  # Explicitly return None for 204

    @optional_typecheck
    def update_a_list(
        self, list_id: str, update_data: dict
    ) -> Any:  # Returns ListModel or raw dict/list
        """
        Update a list by its ID. Corresponds to PATCH /lists/{listId}.
        Allows updating fields like "name", "description", "icon", "parentId", "query".

        Args:
            list_id: The ID (string) of the list to update.
            update_data: A dictionary containing the fields to update (e.g., `{"name": "new name"}`).
                         See the OpenAPI spec for allowed fields.

        Returns:
            datatypes.ListModel: The updated list object.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails (e.g., 404 list not found).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        endpoint = f"lists/{list_id}"
        response_data = self._call("PATCH", endpoint, data=update_data)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match ListModel schema
            return datatypes.ListModel.model_validate(response_data)

    @optional_typecheck
    def get_a_bookmarks_in_a_list(
        self,
        list_id: str,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        include_content: bool = True,  # Default from spec
    ) -> Any:  # Returns PaginatedBookmarks or raw dict/list
        """
        Get the bookmarks contained within a specific list. Corresponds to GET /lists/{listId}/bookmarks.

        Args:
            list_id: The ID (string) of the list.
            limit: Maximum number of bookmarks to return (optional).
            cursor: Pagination cursor for the next page (optional).
            include_content: If set to true, bookmark's content will be included (default: True).

        Returns:
            datatypes.PaginatedBookmarks: Paginated list of bookmarks in the specified list.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails (e.g., 404 list not found).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        endpoint = f"lists/{list_id}/bookmarks"
        params = {
            "limit": limit,
            "cursor": cursor,
            "includeContent": include_content,  # Use camelCase as per API spec query param
        }
        response_data = self._call("GET", endpoint, params=params)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match PaginatedBookmarks schema
            return datatypes.PaginatedBookmarks.model_validate(response_data)

    @optional_typecheck
    def add_a_bookmark_to_a_list(self, list_id: str, bookmark_id: str) -> None:
        """
        Add a bookmark to a specific list. Corresponds to PUT /lists/{listId}/bookmarks/{bookmarkId}.

        Args:
            list_id: The ID (string) of the list.
            bookmark_id: The ID (string) of the bookmark to add.

        Returns:
            None: Returns None upon successful addition (204 No Content).

        Raises:
            APIError: If the API request fails (e.g., 404 list or bookmark not found, 400 bookmark already in list).
        """
        endpoint = f"lists/{list_id}/bookmarks/{bookmark_id}"
        self._call("PUT", endpoint)  # Expects 204 No Content
        return None  # Explicitly return None for 204

    @optional_typecheck
    def remove_a_bookmark_from_a_list(self, list_id: str, bookmark_id: str) -> None:
        """
        Remove a bookmark from a specific list. Corresponds to DELETE /lists/{listId}/bookmarks/{bookmarkId}.

        Args:
            list_id: The ID (string) of the list.
            bookmark_id: The ID (string) of the bookmark to remove.

        Returns:
            None: Returns None upon successful removal (204 No Content).

        Raises:
            APIError: If the API request fails (e.g., 404 list or bookmark not found, 400 bookmark not in list).
        """
        endpoint = f"lists/{list_id}/bookmarks/{bookmark_id}"
        self._call("DELETE", endpoint)  # Expects 204 No Content
        return None  # Explicitly return None for 204

    @optional_typecheck
    def get_all_tags(self) -> Any:  # Returns List[Tag1] or raw dict/list
        """
        Get all tags for the current user. Corresponds to GET /tags.

        Returns:
            List[datatypes.Tag1]: A list of tag objects, including bookmark counts.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails.
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        response_data = self._call("GET", "tags")

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            # Return raw data, which might be {"tags": [...]} or something else
            return response_data
        else:
            # Response schema is {"tags": [Tag1]}, extract the list and validate
            if (
                isinstance(response_data, dict)
                and "tags" in response_data
                and isinstance(response_data["tags"], list)
            ):
                try:
                    return [
                        datatypes.Tag1.model_validate(tag)
                        for tag in response_data["tags"]
                    ]
                except (
                    Exception
                ) as e:  # Catch validation errors during list comprehension
                    logger.error(f"Validation failed for one or more tags: {e}")
                    raise  # Re-raise the validation error
            else:
                # Raise error if format is unexpected and validation is enabled
                raise APIError(
                    f"Unexpected response format for get_all_tags when validation is enabled: {response_data}"
                )

    @optional_typecheck
    def get_a_single_tag(self, tag_id: str) -> Any:  # Returns Tag1 or raw dict/list
        """
        Get a single tag by its ID. Corresponds to GET /tags/{tagId}.

        Args:
            tag_id: The ID (string) of the tag to retrieve.

        Returns:
            datatypes.Tag1: The requested tag object.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails (e.g., 404 tag not found).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        endpoint = f"tags/{tag_id}"
        response_data = self._call("GET", endpoint)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match Tag1 schema
            return datatypes.Tag1.model_validate(response_data)

    @optional_typecheck
    def delete_a_tag(self, tag_id: str) -> None:
        """
        Delete a tag by its ID. Corresponds to DELETE /tags/{tagId}.

        Args:
            tag_id: The ID (string) of the tag to delete.

        Returns:
            None: Returns None upon successful deletion (204 No Content).

        Raises:
            APIError: If the API request fails (e.g., 404 tag not found).
        """
        endpoint = f"tags/{tag_id}"
        self._call("DELETE", endpoint)  # Expects 204 No Content
        return None  # Explicitly return None for 204

    @optional_typecheck
    def update_a_tag(
        self, tag_id: str, update_data: dict
    ) -> Any:  # Returns Tag1 or raw dict/list
        """
        Update a tag by its ID. Currently only supports updating the "name".
        Corresponds to PATCH /tags/{tagId}.

        Args:
            tag_id: The ID (string) of the tag to update.
            update_data: A dictionary containing the fields to update. Must include "name" (string).
                         Example: `{"name": "new tag name"}`

        Returns:
            datatypes.Tag1: The updated tag object.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails (e.g., 404 tag not found).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        endpoint = f"tags/{tag_id}"
        response_data = self._call("PATCH", endpoint, data=update_data)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # As of version 0.24.1 of karakeep: we do not check the correct
            # validation type because there is an error on the
            # server side: https://github.com/karakeep-app/karakeep/issues/1365
            return response_data

            # Response should match Tag1 schema
            return datatypes.Tag1.model_validate(response_data)

    @optional_typecheck
    def get_a_bookmarks_with_the_tag(
        self,
        tag_id: str,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        include_content: bool = True,  # Default from spec
    ) -> Any:  # Returns PaginatedBookmarks or raw dict/list
        """
        Get the bookmarks associated with a specific tag. Corresponds to GET /tags/{tagId}/bookmarks.

        Args:
            tag_id: The ID (string) of the tag.
            limit: Maximum number of bookmarks to return (optional).
            cursor: Pagination cursor for the next page (optional).
            include_content: If set to true, bookmark's content will be included (default: True).

        Returns:
            datatypes.PaginatedBookmarks: Paginated list of bookmarks associated with the specified tag.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails (e.g., 404 tag not found).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        endpoint = f"tags/{tag_id}/bookmarks"
        params = {
            "limit": limit,
            "cursor": cursor,
            "includeContent": include_content,  # Use camelCase as per API spec query param
        }
        response_data = self._call("GET", endpoint, params=params)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match PaginatedBookmarks schema
            return datatypes.PaginatedBookmarks.model_validate(response_data)

    @optional_typecheck
    def get_all_highlights(
        self, limit: Optional[int] = None, cursor: Optional[str] = None
    ) -> Any:  # Returns PaginatedHighlights or raw dict/list
        """
        Get all highlights for the current user. Corresponds to GET /highlights.

        Args:
            limit: Maximum number of highlights to return (optional).
            cursor: Pagination cursor for the next page (optional).

        Returns:
            datatypes.PaginatedHighlights: Paginated list of highlights.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails.
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        params = {"limit": limit, "cursor": cursor}
        response_data = self._call("GET", "highlights", params=params)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match PaginatedHighlights schema
            return datatypes.PaginatedHighlights.model_validate(response_data)

    @optional_typecheck
    def create_a_new_highlight(
        self, highlight_data: dict
    ) -> Any:  # Returns Highlight or raw dict/list
        """
        Create a new highlight on a bookmark. Corresponds to POST /highlights.

        Args:
            highlight_data: Dictionary containing the data for the new highlight. Requires "bookmarkId" (string),
                            "startOffset" (number), "endOffset" (number). Optional fields include "color", "text", "note".
                            See the OpenAPI spec for details. Example: `{"bookmarkId": "...", "startOffset": 10, "endOffset": 25}`

        Returns:
            datatypes.Highlight: The created highlight object.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails (e.g., 400 bad request, 404 bookmark not found).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        response_data = self._call("POST", "highlights", data=highlight_data)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match Highlight schema
            return datatypes.Highlight.model_validate(response_data)

    @optional_typecheck
    def get_a_single_highlight(
        self, highlight_id: str
    ) -> Any:  # Returns Highlight or raw dict/list
        """
        Get a single highlight by its ID. Corresponds to GET /highlights/{highlightId}.

        Args:
            highlight_id: The ID (string) of the highlight to retrieve.

        Returns:
            datatypes.Highlight: The requested highlight object.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails (e.g., 404 highlight not found).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        endpoint = f"highlights/{highlight_id}"
        response_data = self._call("GET", endpoint)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match Highlight schema
            return datatypes.Highlight.model_validate(response_data)

    @optional_typecheck
    def delete_a_highlight(
        self, highlight_id: str
    ) -> Any:  # Returns Highlight or raw dict/list
        """
        Delete a highlight by its ID. Corresponds to DELETE /highlights/{highlightId}.
        Note: Unlike most DELETE endpoints, this returns the deleted highlight object on success (status 200).

        Args:
            highlight_id: The ID (string) of the highlight to delete.

        Returns:
            datatypes.Highlight: The deleted highlight object.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails (e.g., 404 highlight not found).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        endpoint = f"highlights/{highlight_id}"
        response_data = self._call("DELETE", endpoint)  # Expects 200 OK with body

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match Highlight schema
            return datatypes.Highlight.model_validate(response_data)

    @optional_typecheck
    def update_a_highlight(
        self, highlight_id: str, update_data: dict
    ) -> Any:  # Returns Highlight or raw dict/list
        """
        Update a highlight by its ID. Currently only supports updating the "color".
        Corresponds to PATCH /highlights/{highlightId}.

        Args:
            highlight_id: The ID (string) of the highlight to update.
            update_data: A dictionary containing the fields to update. Must include "color" (string enum).
                         See `datatypes.Color` enum. Example: `{"color": "red"}`

        Returns:
            datatypes.Highlight: The updated highlight object.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails (e.g., 404 highlight not found).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        endpoint = f"highlights/{highlight_id}"
        response_data = self._call("PATCH", endpoint, data=update_data)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match Highlight schema
            return datatypes.Highlight.model_validate(response_data)

    @optional_typecheck
    def get_current_user_info(self) -> Any:  # Returns dict
        """
        Get information about the current authenticated user. Corresponds to GET /users/me.

        Returns:
            dict: A dictionary containing user information ('id', 'name', 'email').
                  Validation is not performed on this response type by default.

        Raises:
            APIError: If the API request fails (e.g., authentication error).
        """
        response_data = self._call("GET", "users/me")
        # No Pydantic validation applied here as the spec defines a simple dict response
        return response_data

    @optional_typecheck
    def get_current_user_stats(self) -> Any:  # Returns dict
        """
        Get statistics about the current authenticated user's data. Corresponds to GET /users/me/stats.

        Returns:
            dict: A dictionary containing user statistics ('numBookmarks', 'numFavorites', 'numArchived', etc.).
                  Validation is not performed on this response type by default.

        Raises:
            APIError: If the API request fails (e.g., authentication error).
        """
        response_data = self._call("GET", "users/me/stats")
        # No Pydantic validation applied here as the spec defines a simple dict response
        return response_data
