from textwrap import dedent
import inspect
import json
import sys
import os
import functools
import re  # Import re module
import click
import traceback  # Moved import to top
from typing import (
    Any,
    List,
    Dict,
    Optional,
    Callable,
    Union,
    get_origin,
    get_args,
    Literal,
)
from pydantic import BaseModel, ValidationError
from loguru import logger  # Import logger

# Attempt relative imports for package execution
try:
    # Import API class and errors directly from the module
    from .karakeep_api import KarakeepAPI, APIError, AuthenticationError

    # Models are not directly used here, API methods handle data types
except ImportError:
    # Fallback for direct script execution (e.g., python -m karakeep_python_api ...)
    # Import API class and errors directly from the module
    from karakeep_api import KarakeepAPI, APIError, AuthenticationError


# --- Serialization Helper ---
def serialize_output(data: Any) -> Any:
    """
    Recursively serialize data for JSON output, handling Pydantic models,
    dataclasses, lists, and dicts.
    """
    if isinstance(data, BaseModel):
        return data.model_dump(
            mode="json"
        )  # Use Pydantic's built-in JSON serialization
    elif isinstance(data, list):
        return [serialize_output(item) for item in data]
    elif isinstance(data, dict):
        # Serialize dictionary values
        return {k: serialize_output(v) for k, v in data.items()}
    # Add handling for other types like datetime if needed, though Pydantic's
    # model_dump(mode='json') often handles them.
    # Basic types (str, int, float, bool, None) are returned as is.
    return data


# --- Click CLI Setup ---

# Shared options for the API client
shared_options = [
    click.option(
        "--api-endpoint",
        envvar="KARAKEEP_PYTHON_API_ENDPOINT",
        help="Full Karakeep API endpoint URL, including /api/v1/ (e.g., https://instance.com/api/v1/).",
    ),
    click.option(
        "--api-key",
        envvar="KARAKEEP_PYTHON_API_KEY",
        help="Karakeep API Key (required, uses env var if not provided).",
        required=False,
    ),  # Made not required here, checked in context
    click.option(
        "--verify-ssl/--no-verify-ssl",
        default=True,
        envvar="KARAKEEP_PYTHON_API_VERIFY_SSL",
        help="Verify SSL certificates.",
    ),
    click.option(
        "--verbose",
        "-v",
        is_flag=True,
        default=False,
        help="Enable verbose logging.",
    ),
    click.option(
        "--disable-response-validation",
        is_flag=True,
        default=False,
        envvar="KARAKEEP_PYTHON_API_DISABLE_RESPONSE_VALIDATION",
        help="Disable Pydantic validation of API responses (returns raw data).",
    ),
    click.option(
        "--ascii",
        "ensure_ascii",  # Use 'ensure_ascii' as the destination variable name
        is_flag=True,
        default=False,  # Default is False, meaning ensure_ascii=False by default
        envvar="KARAKEEP_PYTHON_API_ENSURE_ASCII",
        help="Escape non-ASCII characters in the JSON output (default: keep Unicode).",
    ),
]


def add_options(options):
    """Decorator to add a list of click options to a command."""

    def _add_options(func):
        for option in reversed(options):
            func = option(func)
        return func

    return _add_options


# --- Callback for --dump-openapi-specification ---
def print_openapi_spec(ctx, param, value):
    """Callback function for the --dump-openapi-specification option."""
    if not value or ctx.resilient_parsing:
        # Exit if the flag is not set, or if Click is doing resilient parsing (e.g., for completion)
        return
    try:
        package_dir = os.path.dirname(__file__)
        spec_path = os.path.join(package_dir, "openapi_reference.json")
        if not os.path.exists(spec_path):
            click.echo(
                f"Error: Specification file not found at expected location: {spec_path}",
                err=True,
            )
            ctx.exit(1)  # Use ctx.exit
        with open(spec_path, "r") as f:
            click.echo(f.read())  # Use click.echo
    except Exception as e:
        click.echo(f"Error reading or printing specification file: {e}", err=True)
        ctx.exit(1)  # Exit with error code if reading failed
    # Exit successfully *after* the try/except block if no error occurred
    ctx.exit(0)


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
@click.option(
    "--dump-openapi-specification",
    is_flag=True,
    callback=print_openapi_spec,
    expose_value=False,  # Don't pass the value to the main cli function
    is_eager=True,  # Process this option before others
    help="Dump the OpenAPI specification JSON to stdout and exit.",
)
@add_options(
    shared_options
)  # Apply shared options to the group (ensure_ascii is now included)
@click.pass_context
def cli(
    ctx,
    api_endpoint,
    api_key,
    verify_ssl,
    verbose,
    disable_response_validation,
    ensure_ascii,
):
    """
    Karakeep Python API Command Line Interface.

    Dynamically generates commands based on the OpenAPI specification.
    Requires KARAKEEP_PYTHON_API_KEY environment variable or --api-key option.
    """
    # Ensure the context object exists
    ctx.ensure_object(dict)

    # --- Strict Check for API Key and Endpoint ---
    # Check for API key (must be provided via arg or env)
    resolved_api_key = api_key or os.environ.get("KARAKEEP_PYTHON_API_KEY")
    if not resolved_api_key:
        raise click.UsageError(
            "API Key is required. Provide --api-key option or set KARAKEEP_PYTHON_API_KEY environment variable."
        )

    # Check for API endpoint (must be provided via arg or env)
    resolved_api_endpoint = api_endpoint or os.environ.get(
        "KARAKEEP_PYTHON_API_ENDPOINT"
    )
    if not resolved_api_endpoint:
        raise click.UsageError(
            "API endpoint is required. Provide --api-endpoint option or set KARAKEEP_PYTHON_API_ENDPOINT environment variable. "
            "The URL must include the API path, e.g., 'https://your-instance.com/api/v1/'."
        )

    # Store common API parameters in the context for commands to use
    ctx.obj["API_ENDPOINT"] = resolved_api_endpoint  # Store the resolved endpoint
    ctx.obj["API_KEY"] = resolved_api_key  # Store the resolved key
    ctx.obj["VERIFY_SSL"] = verify_ssl
    ctx.obj["VERBOSE"] = verbose
    ctx.obj["DISABLE_RESPONSE_VALIDATION"] = (
        disable_response_validation  # Store the flag
    )
    ctx.obj["ENSURE_ASCII"] = ensure_ascii  # Store the ensure_ascii flag


def create_click_command(
    api_method_name: str, api_method: Callable
) -> Optional[click.Command]:
    """
    Dynamically creates a Click command for a given API method instance,
    inspecting its signature for arguments. Returns None if creation fails.
    """
    # Get the signature from the bound method (which copied it from the original function)
    try:
        sig = inspect.signature(api_method)
        # Exclude 'self' parameter from the signature when creating CLI options
        params = [p for p in sig.parameters.values() if p.name != "self"]
    except (ValueError, TypeError) as e:
        logger.warning(f"Could not get signature for method '{api_method_name}': {e}")
        return None

    # Define the command function template using a closure
    def command_func_factory(method_name, signature):
        @click.pass_context
        def command_func(ctx, **kwargs):
            """Dynamically generated command function wrapper."""
            # Retrieve API parameters from context, ensuring API key is present now
            api_endpoint = ctx.obj["API_ENDPOINT"]
            api_key = ctx.obj["API_KEY"]
            verify_ssl = ctx.obj["VERIFY_SSL"]
            verbose = ctx.obj["VERBOSE"]
            disable_validation = ctx.obj["DISABLE_RESPONSE_VALIDATION"]  # Retrieve flag
            ensure_ascii_output = ctx.obj["ENSURE_ASCII"]  # Retrieve ensure_ascii flag

            if not api_key:
                click.echo(
                    "Error: API Key is required via --api-key or KARAKEEP_PYTHON_API_KEY environment variable.",
                    err=True,
                )
                ctx.exit(1)

            try:
                # Initialize API client within the command context
                # Method generation already happened during inspection phase or initial load
                api = KarakeepAPI(
                    api_key=api_key,
                    api_endpoint=api_endpoint,
                    verify_ssl=verify_ssl,
                    verbose=verbose,
                    disable_response_validation=disable_validation,  # Pass flag to constructor
                )
                # Get the actual bound method from the initialized API instance
                instance_method = getattr(
                    api, method_name
                )  # Use the captured method_name

                # Prepare arguments for the API call from Click's kwargs
                call_args = {}
                sig_params = signature.parameters  # Use captured signature

                # Process Click kwargs into API call arguments
                # Convert kebab-case keys from Click back to snake_case for Python call
                call_args = {
                    k.replace("-", "_"): v for k, v in kwargs.items() if v is not None
                }

                # Remove arguments that are not part of the method signature
                # (e.g., if extra options were somehow passed)
                valid_arg_names = set(signature.parameters.keys())
                call_args = {k: v for k, v in call_args.items() if k in valid_arg_names}

                # --- JSON Parsing for Dict/List Parameters ---
                # Iterate through the expected parameters from the signature
                for param_name, param_sig in signature.parameters.items():
                    if param_name in call_args:
                        param_value = call_args[param_name]
                        param_annotation = param_sig.annotation
                        origin = getattr(param_annotation, "__origin__", None)

                        # Check if the annotation is dict/list or typing.Dict/List
                        # and if the received value is a string (needs parsing)
                        if (
                            param_annotation in (dict, list)
                            or origin in (dict, list, Dict, List)
                        ) and isinstance(param_value, str):
                            try:
                                # Attempt to parse the JSON string
                                call_args[param_name] = json.loads(param_value)
                                logger.debug(
                                    f"Parsed JSON string for parameter '{param_name}'."
                                )
                            except json.JSONDecodeError as json_err:
                                # Handle invalid JSON input from the user
                                click.echo(
                                    f"Error: Invalid JSON provided for parameter '{param_name.replace('_', '-')}': {json_err}",
                                    err=True,
                                )
                                click.echo(f"Provided value: {param_value}", err=True)
                                ctx.exit(1)

                # Call the API method
                try:
                    if method_name == "get_all_bookmarks":
                        logger.debug(
                            f"Special CLI pagination handling for '{method_name}'."
                        )
                        cli_total_limit = call_args.pop("limit", None)
                        # Other relevant params for get_all_bookmarks
                        archived_filter = call_args.get("archived")
                        favourited_filter = call_args.get("favourited")
                        include_content_cli = call_args.get("include_content", True)

                        call_args.pop("cursor", None)  # Ignore CLI cursor

                        all_bookmarks_data = []
                        current_page_api_cursor = None
                        fetched_count = 0
                        API_INTERNAL_PAGE_SIZE = 50  # Define a page size for API calls

                        while True:
                            api_call_limit = API_INTERNAL_PAGE_SIZE
                            if cli_total_limit is not None:
                                remaining_needed = cli_total_limit - fetched_count
                                if remaining_needed <= 0:
                                    break  # Reached or exceeded CLI total limit
                                api_call_limit = min(
                                    API_INTERNAL_PAGE_SIZE, remaining_needed
                                )

                            if (
                                api_call_limit <= 0 and cli_total_limit is not None
                            ):  # Avoid asking for 0 or negative items unless fetching all
                                break

                            logger.debug(
                                f"Fetching page for '{method_name}' with cursor: {current_page_api_cursor}, api_limit: {api_call_limit}"
                            )

                            page_call_args = {
                                "archived": archived_filter,
                                "favourited": favourited_filter,
                                "limit": api_call_limit,
                                "cursor": current_page_api_cursor,
                                "include_content": include_content_cli,
                            }
                            page_call_args_filtered = {
                                k: v for k, v in page_call_args.items() if v is not None
                            }

                            try:
                                page_result_obj = instance_method(
                                    **page_call_args_filtered
                                )
                            except TypeError as call_error_page:
                                logger.error(
                                    f"Error calling API method '{method_name}' (paginated): {call_error_page}"
                                )
                                logger.error(
                                    f"Provided arguments for page: {page_call_args_filtered}"
                                )
                                if verbose:
                                    logger.debug(traceback.format_exc())
                                ctx.exit(1)

                            bookmarks_on_this_page = []
                            next_api_cursor = None

                            # Convert Pydantic model to dict using model_dump if available
                            if hasattr(page_result_obj, "model_dump"):
                                result_dict = page_result_obj.model_dump()
                            elif isinstance(page_result_obj, dict):
                                result_dict = page_result_obj
                            else:
                                logger.warning(
                                    f"Unexpected result type: {type(page_result_obj)}"
                                )
                                result_dict = {}

                            # Extract data and cursor from the dict
                            bookmarks_on_this_page = result_dict.get("bookmarks", [])
                            next_api_cursor = result_dict.get("nextCursor")

                            logger.debug(
                                f"Extracted {len(bookmarks_on_this_page)} bookmarks and cursor: {next_api_cursor}"
                            )

                            if not isinstance(bookmarks_on_this_page, list):
                                logger.warning(
                                    f"Expected a list of bookmarks, got {type(bookmarks_on_this_page)}. Stopping pagination."
                                )
                                break

                            all_bookmarks_data.extend(bookmarks_on_this_page)
                            fetched_count += len(bookmarks_on_this_page)
                            logger.debug(
                                f"Fetched {len(bookmarks_on_this_page)} bookmarks this page. Total fetched: {fetched_count}."
                            )

                            current_page_api_cursor = next_api_cursor
                            if not current_page_api_cursor:
                                logger.debug(
                                    "No nextCursor from API, pagination complete."
                                )
                                break
                            if (
                                cli_total_limit is not None
                                and fetched_count >= cli_total_limit
                            ):
                                logger.debug(
                                    f"CLI total limit of {cli_total_limit} reached or exceeded."
                                )
                                break
                            if not bookmarks_on_this_page and api_call_limit > 0:
                                logger.debug(
                                    "API returned an empty list of bookmarks while a positive limit was set, assuming end of data."
                                )
                                break

                        result = all_bookmarks_data  # This will be a list of Bookmark models or dicts
                    else:
                        # Original behavior for other commands
                        logger.debug(
                            f"Calling API method '{method_name}' with args: {call_args}"
                        )
                        result = instance_method(**call_args)

                except TypeError as call_error:
                    logger.error(
                        f"Error calling API method '{method_name}': {call_error}"
                    )
                    logger.error(f"Provided arguments: {call_args}")
                    logger.error(f"Expected signature: {signature}")
                    # Add traceback in verbose mode
                    if verbose:
                        logger.debug(traceback.format_exc())
                    ctx.exit(1)

                # Serialize and print the result
                if result is not None:
                    output_data = serialize_output(result)
                    # Use ensure_ascii_output flag to control JSON encoding
                    click.echo(
                        json.dumps(
                            output_data, indent=2, ensure_ascii=ensure_ascii_output
                        )
                    )
                else:
                    # Handle None result (e.g., 204 No Content) gracefully
                    # Verbose check is implicitly handled by logger level
                    logger.debug("Operation successful (No content returned).")

            except (
                APIError,
                AuthenticationError,
                ValueError,
                ValidationError,
                TypeError,
            ) as e:
                logger.error(f"Error: {e}")
                # Provide more detail for TypeErrors during binding/call
                if isinstance(e, TypeError):
                    logger.error(f"Error: {e}")
                    # Provide more detail for TypeErrors during binding/call
                    if isinstance(e, TypeError) and verbose:
                        logger.debug(traceback.format_exc())  # Use top-level import
                sys.exit(1)
            except Exception as e:
                logger.error(f"An unexpected error occurred: {e}")
                if verbose:
                    logger.debug(traceback.format_exc())  # Use top-level import
                sys.exit(1)

        # Set the name of the inner function for help display purposes
        command_func.__name__ = method_name
        return command_func

    # Create the actual command function instance using the factory
    command_func = command_func_factory(api_method_name, sig)

    # --- Add Click options/arguments based on the captured method signature ---
    click_params = []
    # Use the docstring from the original method (captured by functools.update_wrapper)
    docstring = api_method.__doc__ or f"Execute the {api_method_name} API operation."
    docstring = dedent(docstring)
    docstring_lines = docstring.split("\n")
    help_text = " ".join(
        docstring.split("\n\n")[0].splitlines()
    ).strip()  # First lines as short help
    # Full docstring as help
    full_help = docstring

    # tweak the whitespaces in the full help:
    full_help = full_help.replace("\n               ", " ")
    full_help = full_help.replace("\n", "\n\n")

    # Extract parameter descriptions from the Args section of the docstring
    param_descriptions = {}
    in_args_section = False
    args_section_lines = []
    assert "Returns:" in docstring
    assert "Raises:" in docstring
    for line in docstring_lines:
        stripped_line = line.strip()
        if stripped_line == "Args:":
            in_args_section = True
        elif stripped_line == "Returns:" or stripped_line == "Raises:":
            in_args_section = False  # Stop capturing when Returns/Raises section starts
        elif in_args_section and stripped_line:
            args_section_lines.append(stripped_line)
            # Use regex to capture 'param_name: description' structure, allowing leading whitespace
            # Pattern: ^\s+ (parameter_name): \s* (description) $
            match = re.match(r"^\s+([a-zA-Z_][a-zA-Z0-9_]*):\s+(.*)$", line)
            if match and match.group(1) != "Example":
                param_name = match.group(1)
                description = match.group(2).strip()
                param_descriptions[param_name] = description
                logger.trace(
                    f"Parsed docstring param: '{param_name}' -> '{description}'"
                )
            else:
                param_descriptions[param_name] += " " + stripped_line

    # Removed breakpoint() that was added for debugging
    # Add parameters from signature to Click command
    for param in params:  # Use the filtered list from signature inspection
        param_name_cli = param.name.replace("_", "-")  # Use kebab-case for CLI options
        is_required_in_sig = param.default is inspect.Parameter.empty
        default_value = param.default if not is_required_in_sig else None
        param_type = click.STRING  # Default to string for CLI

        # Basic type mapping for Click
        annotation = param.annotation
        origin = getattr(annotation, "__origin__", None)
        args = getattr(annotation, "__args__", [])

        # Determine Click type and if it's a flag
        is_flag = False
        click_type = click.STRING
        if annotation is int:
            click_type = click.INT
        elif annotation is float:
            click_type = click.FLOAT
        elif annotation is bool:
            click_type = click.BOOL
            # Boolean options are flags if they don't have a default or default is False
            is_flag = is_required_in_sig or default_value is False
        # Handle Optional[T] - makes the option not required unless T is bool
        elif origin is Union and type(None) in args and len(args) == 2:
            non_none_type = args[0] if args[1] is type(None) else args[1]
            if non_none_type is int:
                click_type = click.INT
            elif non_none_type is float:
                click_type = click.FLOAT
            elif non_none_type is bool:
                click_type = click.BOOL
                # Optional bools are typically flags like --enable-feature/--disable-feature
                # For simplicity, treat as a standard option unless explicitly designed as toggle
                is_flag = (
                    False  # Treat Optional[bool] as --option/--no-option by default
                )
            # Keep click_type as STRING for Optional[List/Dict/str/Any]
            is_required_in_sig = False  # Optional means not required
            default_value = None  # Default for Optional is None

        # Handle List[T] or Dict[K, V] - expect JSON string
        elif origin in (list, dict, List, Dict) or annotation in (list, dict):
            click_type = click.STRING  # Expect JSON string
        # Handle Literal[...] for choices
        elif origin is Literal:
            choices = get_args(annotation)
            # Ensure all choices are strings for click.Choice
            if all(isinstance(c, str) for c in choices):
                click_type = click.Choice(choices, case_sensitive=False)
            else:
                logger.warning(
                    f"Parameter '{param.name}' is Literal but contains non-string types. Treating as STRING."
                )
                click_type = click.STRING  # Fallback

        # Determine option name(s) and help text
        option_names = [f"--{param_name_cli}"]
        # Add /--no- option for boolean flags that are not required and default to True
        if (
            is_flag
            and annotation is bool
            and not is_required_in_sig
            and default_value is True
        ):
            option_names.append(f"--no-{param_name_cli}")

        param_help = param_descriptions.get(param.name, f"Parameter '{param.name}'.")
        if click_type is click.STRING and (
            origin in (list, dict) or annotation in (list, dict)
        ):
            param_help += " (Provide as JSON string)"
        elif isinstance(click_type, click.Choice):
            param_help += f" (Choices: {', '.join(click_type.choices)})"

        click_required = is_required_in_sig and default_value is None and not is_flag

        # Make copies of properties that might be modified for specific commands/params
        current_param_help = param_help
        current_click_required = click_required
        current_default_value = default_value
        current_is_flag = (
            is_flag  # Though is_flag interpretation might change help/required
        )

        # Special handling for 'get_all_bookmarks' command parameters
        if api_method_name == "get_all_bookmarks":
            if param.name == "cursor":
                current_param_help = (
                    "[Ignored by CLI for get-all-bookmarks] " + param_help
                )
                current_click_required = (
                    False  # Cursor is handled by CLI, not required from user
                )
                current_default_value = (
                    None  # Explicitly set default to None for ignored param
                )
            elif param.name == "limit":
                current_param_help = "Total maximum number of bookmarks to fetch across pages for get-all-bookmarks. If omitted, all are fetched."
                # For 'limit', required status and default remain as derived from its Optional[int] type hint
                # current_click_required and current_default_value will be correctly False and None respectively.

        # Add the Click Option
        click_params.append(
            click.Option(
                option_names,
                type=click_type,
                required=current_click_required,
                default=current_default_value if not current_is_flag else None,
                help=current_param_help,
                is_flag=(current_is_flag if len(option_names) == 1 else False),
                show_default=not current_is_flag and current_default_value is not None,
                # Click derives the Python identifier (e.g., 'bookmark_id') from the first long option name
            )
        )

    # Create the Click command
    try:
        dynamic_command = click.Command(
            name=api_method_name.replace("_", "-"),  # Use kebab-case for command names
            callback=command_func,
            params=click_params,
            help=full_help,
            short_help=help_text,
        )
        return dynamic_command
    except Exception as e:
        logger.warning(f"Failed to create click command for '{api_method_name}': {e}")
        return None


# --- Dynamically Add Commands to CLI Group ---
def add_commands_to_cli(cli_group):
    """
    Inspects the KarakeepAPI class *statically* to find public methods
    and adds them as Click commands. Does NOT require API keys or URL for inspection.
    """
    logger.info("Statically inspecting KarakeepAPI class and generating commands...")

    try:
        added_count = 0
        skipped_count = 0
        # Inspect the KarakeepAPI class directly, not an instance
        for name, member in inspect.getmembers(KarakeepAPI):
            # Check if it's a public function/method defined in the class
            if (
                not name.startswith("_")
                and inspect.isfunction(
                    member
                )  # Check if it's a function (method in class def)
                # Add further checks if needed, e.g., based on naming convention or decorators
            ):
                try:
                    # Attempt to create a command for the method
                    # We pass the function object directly. The command_func will later
                    # get the bound method from the API instance created at runtime.
                    command = create_click_command(name, member)
                    if command:
                        cli_group.add_command(command)
                        added_count += 1
                    else:
                        logger.warning(f"Skipped command generation for method: {name}")
                        skipped_count += 1
                except Exception as cmd_gen_e:
                    logger.warning(
                        f"Failed to create command for method '{name}': {cmd_gen_e}"
                    )
                    skipped_count += 1

        if added_count == 0:
            logger.warning(
                "No API commands were dynamically added. Check KarakeepAPI class definition and logs."
            )
        else:
            logger.info(f"Added {added_count} API commands. Skipped {skipped_count}.")

    except Exception as e:
        # Handle errors during static inspection or command creation
        logger.error(f"Unexpected error during dynamic command setup: {e}")
        # Determine verbosity from environment for traceback logging during setup
        verbose_setup = os.environ.get("KARAKEEP_PYTHON_API_VERBOSE", "").lower() in (
            "true",
            "1",
            "yes",
        )
        if verbose_setup:
            logger.debug(traceback.format_exc())  # Use top-level import
        # Raise an exception to halt execution if setup fails
        error_message = f"Error: Unexpected error during dynamic command setup: {e}"
        raise click.ClickException(error_message)


# Add commands when the script is loaded by calling the function
add_commands_to_cli(cli)

# Main entry point for the script
if __name__ == "__main__":
    # Normal Click execution starts here. The --dump-openapi-specification
    # is now handled by its callback function defined above.
    cli(obj={})  # Pass initial empty object for context
