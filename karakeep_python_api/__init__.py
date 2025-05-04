# Import API class and errors directly from the module
from .karakeep_api import KarakeepAPI, APIError, AuthenticationError

# Import the datatypes module so users can do `from karakeep_python_api.datatypes import ...`
from . import datatypes

# Define the package version
# This is the single source of truth, read by setup.py and updated by bumpver.
__version__ = KarakeepAPI.VERSION

__all__ = [
    "KarakeepAPI",
    "APIError",
    "AuthenticationError",
    "datatypes",  # Expose the datatypes module
    "__version__",
]

# Models are available via `from karakeep_python_api.datatypes import ...`
