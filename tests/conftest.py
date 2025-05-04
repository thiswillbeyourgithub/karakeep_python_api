import os
import pytest
from karakeep_python_api import KarakeepAPI


@pytest.fixture
def karakeep_client():
    """
    Fixture that provides a configured Karakeep API client.

    Requires the following environment variables:
    - KARAKEEP_PYTHON_API_BASE_URL
    - KARAKEEP_PYTHON_API_KEY
    - KARAKEEP_PYTHON_API_VERIFY_SSL (optional, defaults to true)
    """
    base_url = os.environ.get("KARAKEEP_PYTHON_API_BASE_URL")
    api_key = os.environ.get("KARAKEEP_PYTHON_API_KEY")
    verify_ssl_str = os.environ.get("KARAKEEP_PYTHON_API_VERIFY_SSL", "true")

    if not base_url or not api_key:
        missing = []
        if not base_url:
            missing.append("KARAKEEP_PYTHON_API_BASE_URL")
        if not api_key:
            missing.append("KARAKEEP_PYTHON_API_KEY")
        pytest.skip(
            f"Missing required environment variables for Karakeep API tests: {', '.join(missing)}. Set these to run integration tests."
        )

    verify_ssl = verify_ssl_str.lower() in ("true", "1", "yes")

    # Instantiate the client using standard environment variables
    # KarakeepAPI constructor handles base_url and api_key directly
    return KarakeepAPI(
        base_url=base_url,
        api_key=api_key,
        verify_ssl=verify_ssl,
        verbose=True,  # Enable verbose logging for tests
    )
