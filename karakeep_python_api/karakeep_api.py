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
        api_endpoint (str): The endpoint of the Karakeep API instance, including /api/v1 (e.g., https://instance.com/api/v1/).
        openapi_spec (dict): The parsed content of the OpenAPI specification file.
        verify_ssl (bool): Whether SSL verification is enabled.
        verbose (bool): Whether verbose logging is enabled.
        disable_response_validation (bool): Whether Pydantic response validation is disabled.
    """

    # Version reflects the client library version, updated by bumpver
    VERSION: str = "1.2.3"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_endpoint: Optional[str] = None,
        openapi_spec_path: Optional[str] = None,  # Allow None, default handled below
        verify_ssl: bool = True,
        verbose: Optional[bool] = None,
        disable_response_validation: Optional[bool] = None,
        rate_limit: Union[
            float, int
        ] = 0.0,  # Minimum interval between API calls in seconds
    ):
        """
        Initialize the Karakeep API client.

        Args:
            api_key: Karakeep API key (Bearer token).
                     Defaults to KARAKEEP_PYTHON_API_KEY environment variable if not provided.
            api_endpoint: Override the endpoint for the API. Must be provided either as an argument
                          or via the KARAKEEP_PYTHON_API_ENDPOINT environment variable.
                          Example: 'https://karakeep.domain.com/api/v1/'
            openapi_spec_path: Path to the OpenAPI JSON specification file.
                               Defaults to 'openapi_reference.json' alongside the package code if not provided.
                               The loaded spec is available via the `openapi_spec` attribute.
            verify_ssl: Whether to verify SSL certificates (default: True).
                        Can be overridden with KARAKEEP_PYTHON_API_VERIFY_SSL environment variable (true/false).
            verbose: Enable verbose logging. If None (default), reads from KARAKEEP_PYTHON_API_VERBOSE environment variable.
                     If True or False, uses the explicit value regardless of environment variable.
            disable_response_validation: If True, skip Pydantic validation of API responses and return raw data.
                                         Defaults to False. Can be overridden by setting the
                                         KARAKEEP_PYTHON_API_DISABLE_RESPONSE_VALIDATION environment variable to "true".
            rate_limit: The minimum time interval in seconds between consecutive API calls.
                        Defaults to 0.0 (no explicit rate limiting).
                        Can be overridden with KARAKEEP_PYTHON_API_RATE_LIMIT environment variable.
        """
        # --- Verbose Setting and Logger Configuration ---
        # Handle verbose environment variable if not explicitly provided
        if verbose is None:
            env_verbose = os.environ.get("KARAKEEP_PYTHON_API_VERBOSE", "").lower()
            self.verbose = env_verbose in ("true", "1", "yes")
            verbose_mess = f"Verbose set to {self.verbose} from KARAKEEP_PYTHON_API_VERBOSE environment variable."
        else:
            self.verbose = verbose
            verbose_mess = f"Verbose explicitly set to {self.verbose} via argument."

        # Configure logger based on verbose setting
        log_level = "DEBUG" if self.verbose else "INFO"
        logger.remove()  # Remove default handler
        if self.verbose:
            logger.add(
                sys.stderr,
                level=log_level,
                format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            )
            logger.debug("Verbose logging enabled with detailed format.")
        else:
            logger.add(sys.stderr, level=log_level)  # Default format for INFO

        logger.debug(verbose_mess)
        logger.debug("Logger configured for level: {}", log_level)

        # --- API Key Validation ---
        resolved_api_key = api_key or os.environ.get("KARAKEEP_PYTHON_API_KEY")
        if not resolved_api_key:
            raise ValueError(
                "API Key is required. Provide 'api_key' argument or set KARAKEEP_PYTHON_API_KEY environment variable."
            )
        self.api_key = resolved_api_key
        logger.debug("API Key loaded successfully.")

        # --- Endpoint Validation ---
        env_endpoint = os.environ.get("KARAKEEP_PYTHON_API_ENDPOINT")
        logger.debug(
            f"Checked KARAKEEP_PYTHON_API_ENDPOINT environment variable, found: '{env_endpoint}'"
        )
        logger.debug(f"Endpoint provided as argument: '{api_endpoint}'")

        if api_endpoint:
            self.api_endpoint = api_endpoint
            logger.info(f"Using provided endpoint: {self.api_endpoint}")
        elif env_endpoint:
            self.api_endpoint = env_endpoint
            logger.info(
                f"Using endpoint from KARAKEEP_PYTHON_API_ENDPOINT: {self.api_endpoint}"
            )
        else:
            # No api_endpoint from arg or env var - raise error as per requirement
            raise ValueError(
                "API endpoint is required. Provide 'api_endpoint' argument or set KARAKEEP_PYTHON_API_ENDPOINT environment variable."
            )

        # Ensure endpoint ends with /api/v1/
        resolved_url = self.api_endpoint  # Use a temporary variable for checks
        if resolved_url.endswith("/api/v1"):
            # Ends with /api/v1, needs a slash
            self.api_endpoint = resolved_url + "/"
            logger.info(
                f"Appended trailing slash to endpoint ending in /api/v1: {self.api_endpoint}"
            )
        elif resolved_url.endswith("/api/v1/"):
            # Already ends correctly, do nothing
            logger.debug(f"Endpoint already ends with /api/v1/: {self.api_endpoint}")
        else:
            # Doesn't end with /api/v1 or /api/v1/, append /api/v1/
            # First, remove any existing trailing slash to avoid //api/v1/
            if resolved_url.endswith("/"):
                resolved_url = resolved_url[:-1]
            self.api_endpoint = resolved_url + "/api/v1/"
            logger.info(f"Appended /api/v1/ to endpoint: {self.api_endpoint}")

        logger.debug(f"Final API Endpoint after /api/v1/ check: {self.api_endpoint}")

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

        # --- Rate Limit Setting ---
        # Argument takes precedence over environment variable
        env_rate_limit_str = os.environ.get("KARAKEEP_PYTHON_API_RATE_LIMIT")
        if rate_limit != 0.0:  # Argument provided and not default
            self.rate_limit = rate_limit
            logger.debug(f"Rate limit set to {self.rate_limit}s via argument.")
        elif env_rate_limit_str is not None:
            try:
                self.rate_limit = float(env_rate_limit_str)
                logger.debug(
                    f"Rate limit set to {self.rate_limit}s via KARAKEEP_PYTHON_API_RATE_LIMIT environment variable."
                )
            except ValueError:
                self.rate_limit = 0.0  # Default if env var is invalid
                logger.warning(
                    f"Invalid value for KARAKEEP_PYTHON_API_RATE_LIMIT ('{env_rate_limit_str}'). Rate limiting disabled (0.0s)."
                )
        else:
            self.rate_limit = rate_limit  # Use default from signature (0.0)
            logger.debug(f"Rate limit set to default: {self.rate_limit}s.")

        self.last_request_time: float = (
            time.monotonic()
        )  # Initialize timestamp for rate limiting

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

        logger.debug("KarakeepAPI client initialized.")
        logger.debug(f"  Endpoint: {self.api_endpoint}")
        logger.debug(f"  Verify SSL: {self.verify_ssl}")
        logger.debug(f"  Verbose: {self.verbose}")
        logger.debug(
            f"  Disable Response Validation: {self.disable_response_validation}"
        )
        logger.debug(f"  Rate Limit: {self.rate_limit}s")
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
        files: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Union[Dict[str, Any], List[Any], None, bytes]:
        """
        Internal method to make an HTTP call to the Karakeep API. Handles authentication,
        request formatting, response parsing, and error handling.

        Args:
            method: HTTP method ('GET', 'POST', 'PUT', 'PATCH', 'DELETE').
            endpoint: API endpoint path relative to the endpoint (e.g., 'bookmarks' or 'bookmarks/some_id').
                      Path parameters (like {bookmarkId}) MUST be substituted *before* calling _call.
            params: Dictionary of URL query parameters. Values should be primitive types suitable for URLs.
            data: Request body data. Can be a Pydantic model, dict, list, bytes, or str.
                  - Pydantic models, dicts, and lists will be automatically JSON-encoded
                    with 'Content-Type: application/json' unless overridden in extra_headers.
                  - For bytes or str, ensure 'Content-Type' is set correctly via extra_headers if needed.
            files: Dictionary for file uploads (multipart/form-data). If provided, data parameter is ignored.
            extra_headers: Additional headers to include or override default headers.

        Returns:
            The parsed JSON response from the API as a dict or list, None for 204 No Content responses,
            or raw bytes for non-JSON responses. The calling wrapper method is responsible for further
            parsing/validation into specific Pydantic models.

        Raises:
            AuthenticationError: If authentication fails (401).
            APIError: For other HTTP errors or request issues.
        """
        # Ensure endpoint doesn't start with / if endpoint ends with /
        safe_endpoint = endpoint.lstrip("/")
        url = urljoin(self.api_endpoint, safe_endpoint)

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

        # Handle file uploads (multipart/form-data)
        if files is not None:
            # When files are provided, let requests handle Content-Type automatically
            # Don't set Content-Type header for multipart uploads
            if "Content-Type" in headers:
                # Remove Content-Type if it was set, let requests set it for multipart
                headers.pop("Content-Type")
            # Don't process data when files are provided
            request_body_arg = None
        elif data is not None:
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
                        files=files,  # File uploads for multipart/form-data
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

            # Check if the response is expected to be JSON based on Accept header
            accept_header = headers.get("Accept", "application/json")
            expects_json = "application/json" in accept_header

            # Attempt to parse successful response as JSON if we expect JSON
            if expects_json:
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
            else:
                # For non-JSON responses (like asset downloads), return raw bytes
                if self.verbose:
                    content_type = response.headers.get("Content-Type", "unknown")
                    content_length = len(response.content)
                    logger.debug(
                        f"  Body (Binary): {content_length} bytes, Content-Type: {content_type}"
                    )
                return response.content

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
    def _enforce_rate_limit(self) -> None:
        """
        Ensures a minimum time interval between consecutive API calls, based on `self.rate_limit`.
        If `self.rate_limit` is 0 or less, this method does nothing.
        Otherwise, if the time since the last call is less than `self.rate_limit`,
        this method will sleep for the remaining duration. It then updates the
        timestamp of the last request.
        """
        if self.rate_limit <= 0:
            # Update last request time even if rate limiting is disabled or not triggered,
            # so the next call has an accurate timestamp if rate_limit is changed.
            self.last_request_time = time.monotonic()
            return

        current_time = time.monotonic()
        time_since_last = current_time - self.last_request_time

        if time_since_last < self.rate_limit:
            sleep_duration = self.rate_limit - time_since_last
            if self.verbose:
                logger.debug(
                    f"Rate limit triggered (interval {self.rate_limit}s). Sleeping for {sleep_duration:.3f} seconds."
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
        sort_order: Optional[Literal["asc", "desc"]] = None,
        limit: Optional[int] = None,  # This is the per-page limit for the API
        cursor: Optional[str] = None,
        include_content: bool = True,  # Default from spec
    ) -> Union[datatypes.PaginatedBookmarks, Dict[str, Any], List[Any]]:
        """
        Get bookmarks, one page at a time. Corresponds to GET /bookmarks.

        This method fetches a single page of bookmarks.
        The 'limit' parameter controls the number of items per page for this API call.
        The 'cursor' parameter is used for pagination to get the next page.

        CLI Usage Notes:
        - When the 'get-all-bookmarks' command is used via the CLI:
          - The `--cursor` CLI option is ignored; pagination is handled automatically.
          - The `--limit` CLI option specifies the *total* number of bookmarks to fetch
            across multiple pages. If omitted, all bookmarks are fetched.
          - The CLI internally calls this API method multiple times to achieve this.

        Args:
            archived: Filter by archived status (optional).
            favourited: Filter by favourited status (optional).
            limit: Maximum number of bookmarks to return *per page* in this API call (optional).
                   When used from the CLI's 'get-all-bookmarks' command, this translates to an
                   internal per-page fetching limit, while the CLI's `--limit` controls the total.
            cursor: Pagination cursor for fetching the next page (optional).
            include_content: If set to true, bookmark's content will be included (default: True).

        Returns:
            datatypes.PaginatedBookmarks: Paginated list of bookmarks for the current page.
            If response validation is disabled, returns the raw API response (dict/list) for the current page.

        Raises:
            APIError: If the API request fails.
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        params = {
            "archived": archived,
            "favourited": favourited,
            "sortOrder": sort_order,
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
    ) -> Union[datatypes.Bookmark, Dict[str, Any], List[Any]]:
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
                raise ValueError("Argument 'assetId' is required when type is 'asset'.")
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
        sort_order: Optional[Literal["asc", "desc", "relevance"]] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        include_content: bool = True,  # Default from spec
    ) -> Union[datatypes.PaginatedBookmarks, Dict[str, Any], List[Any]]:
        """
        Search bookmarks. Corresponds to GET /bookmarks/search.

        Args:
            q: The search query string.
            sort_order: Sort order for results ("asc", "desc", "relevance"). Default from API is "relevance" (optional).
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
            "sortOrder": sort_order,
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
    ) -> Union[datatypes.Bookmark, Dict[str, Any], List[Any]]:
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
        self,
        bookmark_id: str,
        update_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Update a bookmark by its ID. Corresponds to PATCH /bookmarks/{bookmarkId}.
        Allows updating various bookmark fields including metadata, content, and status.

        Args:
            bookmark_id: The ID (string) of the bookmark to update.
            update_data: Dictionary containing the fields to update. Supported keys include:
                        'title', 'archived', 'favourited', 'note', 'summary', 'createdAt',
                        'url', 'description', 'author', 'publisher', 'datePublished',
                        'dateModified', 'text', 'assetContent'.

        Returns:
            dict: A dictionary representing the updated bookmark (partial representation).
                  The response typically includes 'id', 'createdAt', 'modifiedAt', 'title', 'archived', 'favourited',
                  'taggingStatus', 'summarizationStatus', 'note', 'summary'.
                  Validation is not performed on this response type by default.

        Raises:
            ValueError: If update_data is empty or no valid fields are provided to update.
            APIError: If the API request fails (e.g., 404 bookmark not found).
        """
        # Ensure at least one field is being updated
        if not update_data:
            raise ValueError("update_data must contain at least one field to update.")

        endpoint = f"bookmarks/{bookmark_id}"
        response_data = self._call("PATCH", endpoint, data=update_data)
        # The response schema is a subset of Bookmark, return as dict as specified in spec
        # No Pydantic validation applied here as the spec defines a partial response (dict)
        return response_data

    @optional_typecheck
    def summarize_a_bookmark(self, bookmark_id: str) -> Dict[str, Any]:
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
        self,
        bookmark_id: str,
        tag_ids: Optional[List[str]] = None,
        tag_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Attach one or more tags to a bookmark. Corresponds to POST /bookmarks/{bookmarkId}/tags.

        Args:
            bookmark_id: The ID (string) of the bookmark.
            tag_ids: List of existing tag IDs to attach (optional).
            tag_names: List of tag names to attach (will create tags if they don't exist) (optional).

        Returns:
            dict: A dictionary containing the list of attached tag IDs under the key "attached".
                  Example: `{"attached": ["tag_id_1", "tag_id_2"]}`
                  Validation is not performed on this response type by default.

        Raises:
            ValueError: If no tags are provided or if arguments are invalid.
            APIError: If the API request fails (e.g., 404 bookmark not found).
        """
        # Validate that at least one tag source is provided
        if not tag_ids and not tag_names:
            raise ValueError(
                "At least one of 'tag_ids' or 'tag_names' must be provided"
            )

        # Validate input types
        if tag_ids is not None and not isinstance(tag_ids, list):
            raise ValueError("'tag_ids' must be a list of strings")

        if tag_names is not None and not isinstance(tag_names, list):
            raise ValueError("'tag_names' must be a list of strings")

        # Validate individual elements
        if tag_ids:
            for i, tag_id in enumerate(tag_ids):
                if not isinstance(tag_id, str) or not tag_id.strip():
                    raise ValueError(f"Tag ID at index {i} must be a non-empty string")

        if tag_names:
            for i, tag_name in enumerate(tag_names):
                if not isinstance(tag_name, str) or not tag_name.strip():
                    raise ValueError(
                        f"Tag name at index {i} must be a non-empty string"
                    )

        # Construct the tags_data dict in the format expected by the API
        tags_list = []

        if tag_ids:
            for tag_id in tag_ids:
                tags_list.append({"tagId": tag_id.strip()})

        if tag_names:
            for tag_name in tag_names:
                tags_list.append({"tagName": tag_name.strip()})

        tags_data = {"tags": tags_list}

        # Optional validation using Tag datatype if validation is enabled
        if not self.disable_response_validation:
            # Validate the constructed structure matches expected format
            # This is primarily for development/debugging purposes
            logger.debug("Validating constructed tags_data structure")

        endpoint = f"bookmarks/{bookmark_id}/tags"
        response_data = self._call("POST", endpoint, data=tags_data)
        # Response schema is {"attached": [TagId]}, return as dict
        # No Pydantic validation applied here as the spec defines a simple dict response
        return response_data

    @optional_typecheck
    def detach_tags_from_a_bookmark(
        self,
        bookmark_id: str,
        tag_ids: Optional[List[str]] = None,
        tag_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Detach one or more tags from a bookmark. Corresponds to DELETE /bookmarks/{bookmarkId}/tags.

        Args:
            bookmark_id: The ID (string) of the bookmark.
            tag_ids: List of existing tag IDs to detach (optional).
            tag_names: List of tag names to detach (optional).

        Returns:
            dict: A dictionary containing the list of detached tag IDs under the key "detached".
                  Example: `{"detached": ["tag_id_1", "tag_id_2"]}`
                  Validation is not performed on this response type by default.

        Raises:
            ValueError: If no tags are provided or if arguments are invalid.
            APIError: If the API request fails (e.g., 404 bookmark not found).
        """
        # Validate that at least one tag source is provided
        if not tag_ids and not tag_names:
            raise ValueError(
                "At least one of 'tag_ids' or 'tag_names' must be provided"
            )

        # Validate input types
        if tag_ids is not None and not isinstance(tag_ids, list):
            raise ValueError("'tag_ids' must be a list of strings")

        if tag_names is not None and not isinstance(tag_names, list):
            raise ValueError("'tag_names' must be a list of strings")

        # Validate individual elements
        if tag_ids:
            for i, tag_id in enumerate(tag_ids):
                if not isinstance(tag_id, str) or not tag_id.strip():
                    raise ValueError(f"Tag ID at index {i} must be a non-empty string")

        if tag_names:
            for i, tag_name in enumerate(tag_names):
                if not isinstance(tag_name, str) or not tag_name.strip():
                    raise ValueError(
                        f"Tag name at index {i} must be a non-empty string"
                    )

        # Construct the tags_data dict in the format expected by the API
        tags_list = []

        if tag_ids:
            for tag_id in tag_ids:
                tags_list.append({"tagId": tag_id.strip()})

        if tag_names:
            for tag_name in tag_names:
                tags_list.append({"tagName": tag_name.strip()})

        tags_data = {"tags": tags_list}

        # Optional validation using Tag datatype if validation is enabled
        if not self.disable_response_validation:
            # Validate the constructed structure matches expected format
            # This is primarily for development/debugging purposes
            logger.debug("Validating constructed tags_data structure")

        endpoint = f"bookmarks/{bookmark_id}/tags"
        response_data = self._call("DELETE", endpoint, data=tags_data)
        # Response schema is {"detached": [TagId]}, return as dict
        # No Pydantic validation applied here as the spec defines a simple dict response
        return response_data

    @optional_typecheck
    def get_highlights_of_a_bookmark(
        self, bookmark_id: str
    ) -> Union[List[datatypes.Highlight], Dict[str, Any], List[Any]]:
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
        self,
        bookmark_id: str,
        asset_id: str,
        asset_type: Literal[
            "screenshot",
            "assetScreenshot",
            "bannerImage",
            "fullPageArchive",
            "video",
            "bookmarkAsset",
            "precrawledArchive",
            "unknown",
        ],
    ) -> Union[datatypes.BookmarkAsset, Dict[str, Any], List[Any]]:
        """
        Attach a new asset to a bookmark. Corresponds to POST /bookmarks/{bookmarkId}/assets.

        Args:
            bookmark_id: The ID (string) of the bookmark.
            asset_id: The ID (string) of the asset to attach.
            asset_type: The type of asset being attached. Must be one of: "screenshot", "assetScreenshot",
                        "bannerImage", "fullPageArchive", "video", "bookmarkAsset", "precrawledArchive", "unknown".

        Returns:
            datatypes.BookmarkAsset: The attached asset object.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails (e.g., 404 bookmark not found).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        # Construct the asset data dict as expected by the API
        asset_data = {"id": asset_id, "assetType": asset_type}

        endpoint = f"bookmarks/{bookmark_id}/assets"
        response_data = self._call("POST", endpoint, data=asset_data)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match BookmarkAsset schema
            return datatypes.BookmarkAsset.model_validate(response_data)

    @optional_typecheck
    def replace_asset(self, bookmark_id: str, asset_id: str, new_asset_id: str) -> None:
        """
        Replace an existing asset associated with a bookmark with a new one.
        Corresponds to PUT /bookmarks/{bookmarkId}/assets/{assetId}.

        Args:
            bookmark_id: The ID (string) of the bookmark.
            asset_id: The ID (string) of the asset to be replaced.
            new_asset_id: The ID (string) of the new asset to replace with.

        Returns:
            None: Returns None upon successful replacement (204 No Content).

        Raises:
            APIError: If the API request fails (e.g., 404 bookmark or asset not found).
        """
        # Construct the request body as expected by the API
        new_asset_data = {"assetId": new_asset_id}

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
    def get_all_lists(
        self,
    ) -> Union[List[datatypes.ListModel], Dict[str, Any], List[Any]]:
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
        self,
        name: str,
        icon: str,
        description: Optional[str] = None,
        parent_id: Optional[str] = None,
        list_type: Optional[Literal["manual", "smart"]] = "manual",
        query: Optional[str] = None,
        public: bool = False,
    ) -> Union[datatypes.ListModel, Dict[str, Any], List[Any]]:
        """
        Create a new list (manual or smart). Corresponds to POST /lists.

        Args:
            name: The name of the list (required, max 40 characters).
            icon: The icon for the list (required).
            description: Optional description for the list (max 100 characters).
            parent_id: Optional parent list ID for nested lists.
            list_type: The type of list ('manual' or 'smart'). Default is 'manual'.
            query: Optional query string for smart lists (required if list_type is 'smart').
            public: Whether the list is public (default: False).

        Returns:
            datatypes.ListModel: The created list object.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            ValueError: If required arguments are missing or invalid.
            APIError: If the API request fails (e.g., bad request, invalid data).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        # Validate smart list requirements
        if list_type == "smart" and not query:
            raise ValueError("Argument 'query' is required when list_type is 'smart'.")

        # Construct the request body
        list_data = {
            "name": name,
            "icon": icon,
            "type": list_type,
            "public": public,
        }

        # Add optional fields if provided
        if description is not None:
            list_data["description"] = description
        if parent_id is not None:
            list_data["parentId"] = parent_id
        if query is not None:
            list_data["query"] = query

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
    ) -> Union[datatypes.ListModel, Dict[str, Any], List[Any]]:
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
        self,
        list_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        icon: Optional[str] = None,
        parent_id: Optional[str] = None,
        query: Optional[str] = None,
        public: Optional[bool] = None,
    ) -> Union[datatypes.ListModel, Dict[str, Any], List[Any]]:
        """
        Update a list by its ID. Corresponds to PATCH /lists/{listId}.
        Allows updating various list fields including name, description, icon, parent relationship, query, and public status.

        Args:
            list_id: The ID (string) of the list to update.
            name: Optional new name for the list (1-40 characters).
            description: Optional new description for the list (0-100 characters, can be None to clear).
            icon: Optional new icon for the list.
            parent_id: Optional new parent list ID (can be None to remove parent relationship).
            query: Optional new query string for smart lists (minimum 1 character).
            public: Optional new public status for the list.

        Returns:
            datatypes.ListModel: The updated list object.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            ValueError: If no fields are provided to update.
            APIError: If the API request fails (e.g., 404 list not found).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        # Construct update_data from provided arguments, excluding None values that weren't explicitly passed
        update_data = {}
        if name is not None:
            update_data["name"] = name
        if description is not None:
            update_data["description"] = description
        if icon is not None:
            update_data["icon"] = icon
        if parent_id is not None:
            update_data["parentId"] = parent_id
        if query is not None:
            update_data["query"] = query
        if public is not None:
            update_data["public"] = public

        # Ensure at least one field is being updated
        if not update_data:
            raise ValueError("At least one field must be provided to update.")

        endpoint = f"lists/{list_id}"
        response_data = self._call("PATCH", endpoint, data=update_data)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match ListModel schema
            return datatypes.ListModel.model_validate(response_data)

    @optional_typecheck
    def get_bookmarks_in_the_list(
        self,
        list_id: str,
        sort_order: Optional[Literal["asc", "desc"]] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        include_content: bool = True,  # Default from spec
    ) -> Union[datatypes.PaginatedBookmarks, Dict[str, Any], List[Any]]:
        """
        Get the bookmarks contained within a specific list. Corresponds to GET /lists/{listId}/bookmarks.

        Args:
            list_id: The ID (string) of the list.
            sort_order: Sort order for results ("asc", "desc"). Default from API is "desc" (optional).
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
            "sortOrder": sort_order,
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
            APIError: If the API request fails (e.g., 404 list or bookmark not found).
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
    def get_all_tags(self) -> Union[List[datatypes.Tag], Dict[str, Any], List[Any]]:
        """
        Get all tags for the current user. Corresponds to GET /tags.

        Returns:
            List[datatypes.Tag]: A list of tag objects, including bookmark counts.
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
            # Response schema is {"tags": [Tag]}, extract the list and validate
            if (
                isinstance(response_data, dict)
                and "tags" in response_data
                and isinstance(response_data["tags"], list)
            ):
                try:
                    return [
                        datatypes.Tag.model_validate(tag)
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
    def create_a_new_tag(self, name: str) -> Dict[str, Any]:
        """
        Create a new tag. Corresponds to POST /tags.

        Args:
            name: The name of the tag (required, minimum length 1).

        Returns:
            dict: A dictionary containing the created tag information with "id" and "name" fields.
                  Validation is not performed on this response type by default.

        Raises:
            ValueError: If the name is empty or invalid.
            APIError: If the API request fails (e.g., bad request, invalid data).
        """
        # Validate the name
        if not name or not name.strip():
            raise ValueError("Tag name cannot be empty.")

        # Construct the request body
        tag_data = {"name": name.strip()}

        response_data = self._call("POST", "tags", data=tag_data)
        # Response schema is a simple dict with id and name, return as dict
        # No Pydantic validation applied here as the spec defines a simple dict response
        return response_data

    @optional_typecheck
    def get_a_single_tag(
        self, tag_id: str
    ) -> Union[datatypes.Tag, Dict[str, Any], List[Any]]:
        """
        Get a single tag by its ID. Corresponds to GET /tags/{tagId}.

        Args:
            tag_id: The ID (string) of the tag to retrieve.

        Returns:
            datatypes.Tag: The requested tag object.
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
            # Response should match Tag schema
            return datatypes.Tag.model_validate(response_data)

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
    def update_a_tag(self, tag_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update a tag by its ID. Currently only supports updating the "name".
        Corresponds to PATCH /tags/{tagId}.

        Args:
            tag_id: The ID (string) of the tag to update.
            update_data: Dictionary containing the fields to update. Supported keys include:
                        'name' (string).

        Returns:
            dict: A dictionary containing the updated tag information with "id" and "name" fields.
                  Validation is not performed on this response type by default.

        Raises:
            ValueError: If update_data is empty or no valid fields are provided to update.
            APIError: If the API request fails (e.g., 404 tag not found).
        """
        # Ensure at least one field is being updated
        if not update_data:
            raise ValueError("update_data must contain at least one field to update.")

        endpoint = f"tags/{tag_id}"
        response_data = self._call("PATCH", endpoint, data=update_data)
        # Response schema is a simple dict with id and name, return as dict
        # No Pydantic validation applied here as the spec defines a simple dict response
        return response_data

    @optional_typecheck
    def get_bookmarks_with_the_tag(
        self,
        tag_id: str,
        sort_order: Optional[Literal["asc", "desc"]] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        include_content: bool = True,  # Default from spec
    ) -> Union[datatypes.PaginatedBookmarks, Dict[str, Any], List[Any]]:
        """
        Get the bookmarks associated with a specific tag. Corresponds to GET /tags/{tagId}/bookmarks.

        Args:
            tag_id: The ID (string) of the tag.
            sort_order: Sort order for results ("asc", "desc"). Default from API is "desc" (optional).
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
            "sortOrder": sort_order,
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
    ) -> Union[datatypes.PaginatedHighlights, Dict[str, Any], List[Any]]:
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
        self,
        bookmark_id: str,
        start_offset: Union[float, int],
        end_offset: Union[float, int],
        color: Optional[Literal["yellow", "red", "green", "blue"]] = "yellow",
        text: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Union[datatypes.Highlight, Dict[str, Any], List[Any]]:
        """
        Create a new highlight on a bookmark. Corresponds to POST /highlights.

        Args:
            bookmark_id: The ID of the bookmark to create the highlight on.
            start_offset: The start position of the highlight in the text.
            end_offset: The end position of the highlight in the text.
            color: The color of the highlight ("yellow", "red", "green", "blue"). Default is "yellow".
            text: Optional text content of the highlight.
            note: Optional note associated with the highlight.

        Returns:
            datatypes.Highlight: The created highlight object.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            APIError: If the API request fails (e.g., 400 bad request, 404 bookmark not found).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        # Construct the request body
        highlight_data = {
            "bookmarkId": bookmark_id,
            "startOffset": start_offset,
            "endOffset": end_offset,
            "color": color,
            "text": text,
            "note": note,
        }

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
    ) -> Union[datatypes.Highlight, Dict[str, Any], List[Any]]:
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
    ) -> Union[datatypes.Highlight, Dict[str, Any], List[Any]]:
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
        self,
        highlight_id: str,
        color: Optional[Literal["yellow", "red", "green", "blue"]] = None,
    ) -> Union[datatypes.Highlight, Dict[str, Any], List[Any]]:
        """
        Update a highlight by its ID. Currently only supports updating the "color".
        Corresponds to PATCH /highlights/{highlightId}.

        Args:
            highlight_id: The ID (string) of the highlight to update.
            color: Optional new color for the highlight ("yellow", "red", "green", "blue").

        Returns:
            datatypes.Highlight: The updated highlight object.
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            ValueError: If no fields are provided to update.
            APIError: If the API request fails (e.g., 404 highlight not found).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        # Construct update_data from provided arguments, excluding None values
        update_data = {}
        if color is not None:
            update_data["color"] = color

        # Ensure at least one field is being updated
        if not update_data:
            raise ValueError("At least one field must be provided to update.")

        endpoint = f"highlights/{highlight_id}"
        response_data = self._call("PATCH", endpoint, data=update_data)

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match Highlight schema
            return datatypes.Highlight.model_validate(response_data)

    @optional_typecheck
    def get_current_user_info(self) -> Dict[str, Any]:
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
    def get_current_user_stats(self) -> Dict[str, Any]:
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

    @optional_typecheck
    def upload_a_new_asset(
        self, file: str
    ) -> Union[datatypes.Asset, Dict[str, Any], List[Any]]:
        """
        Upload a new asset file. Corresponds to POST /assets.

        Args:
            file: Path to the file to upload.

        Returns:
            datatypes.Asset: Details about the uploaded asset (assetId, contentType, size, fileName).
            If response validation is disabled, returns the raw API response (dict/list).

        Raises:
            FileNotFoundError: If the specified file does not exist.
            APIError: If the API request fails (e.g., unsupported file type, file too large).
            pydantic.ValidationError: If response validation fails (and is not disabled).
        """
        import os
        import mimetypes

        # Validate file path exists
        if not os.path.isfile(file):
            raise FileNotFoundError(f"File not found: {file}")

        # Get filename from path
        file_name = os.path.basename(file)

        # Detect MIME type
        mime_type, _ = mimetypes.guess_type(file)
        if mime_type is None:
            mime_type = "application/octet-stream"

        if self.verbose:
            logger.debug(
                f"Uploading asset: {file} (filename: {file_name}, type: {mime_type})"
            )

        # Prepare file for upload
        try:
            with open(file, "rb") as f:
                file_content = f.read()
            # Note: The 'file' key must match the OpenAPI spec parameter name
            files = {"file": (file_name, file_content, mime_type)}
            response_data = self._call("POST", "assets", files=files)
        except IOError as e:
            raise APIError(f"Failed to read file {file}: {e}") from e

        if self.disable_response_validation:
            logger.debug("Skipping response validation as requested.")
            return response_data
        else:
            # Response should match Asset schema
            return datatypes.Asset.model_validate(response_data)

    @optional_typecheck
    def get_a_single_asset(self, asset_id: str) -> bytes:
        """
        Get the raw content of an asset by its ID. Corresponds to GET /assets/{assetId}.

        Args:
            asset_id: The ID (string) of the asset to retrieve.

        Returns:
            bytes: The raw asset content. The Content-Type is determined by the asset type.
                   Use response headers to determine the actual content type if needed.

        Raises:
            APIError: If the API request fails (e.g., 404 asset not found).
            ValueError: If asset_id is empty or invalid.

        Note:
            This method always returns raw bytes regardless of the disable_response_validation setting,
            as the response is binary content rather than JSON.
        """
        # Validate asset_id
        if not asset_id or not asset_id.strip():
            raise ValueError("asset_id cannot be empty")

        asset_id = asset_id.strip()

        # Validate asset_id format (basic check for reasonable ID format)
        if len(asset_id) < 5:  # Assuming asset IDs are at least 5 characters
            raise ValueError(f"asset_id appears to be invalid: {asset_id}")

        endpoint = f"assets/{asset_id}"

        # Override the Accept header to get raw content instead of JSON
        # This is crucial for the assets endpoint to return binary data
        extra_headers = {"Accept": "*/*"}

        if self.verbose:
            logger.debug(f"Retrieving asset: {asset_id}")

        response_data = self._call("GET", endpoint, extra_headers=extra_headers)

        # The _call method should return bytes for non-JSON responses when Accept is not application/json
        if isinstance(response_data, bytes):
            if self.verbose:
                logger.debug(f"Retrieved asset {asset_id}: {len(response_data)} bytes")
            return response_data
        elif response_data is None:
            # Handle empty response (valid for some assets like empty files)
            if self.verbose:
                logger.debug(f"Retrieved empty asset {asset_id}")
            return b""
        else:
            # This shouldn't happen with the updated _call method, but handle gracefully
            error_msg = f"Expected bytes from asset endpoint for asset {asset_id}, got {type(response_data).__name__}"
            if isinstance(response_data, (dict, list)):
                # If we got JSON, it might be an error response that wasn't caught
                error_detail = (
                    str(response_data)[:200] + "..."
                    if len(str(response_data)) > 200
                    else str(response_data)
                )
                error_msg += f". Response content: {error_detail}"

            logger.error(error_msg)
            raise APIError(error_msg)
