import inspect
import json
import sys
import os
import functools
import click
import traceback  # Moved import to top
from typing import Any, List, Dict, Optional, Callable, Union, get_origin, get_args
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
    # Removed dataclass handling as API uses Pydantic models primarily
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
        "--base-url",
        envvar="KARAKEEP_PYTHON_API_BASE_URL",
        help="Full Karakeep API base URL, including /api/v1/ (e.g., https://instance.com/api/v1/).",
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
        envvar="KARAKEEP_PYTHON_API_VERBOSE",
        help="Enable verbose logging.",
    ),
    click.option(
        "--disable-response-validation",
        is_flag=True,
        default=False,
        envvar="KARAKEEP_PYTHON_API_DISABLE_RESPONSE_VALIDATION",
        help="Disable Pydantic validation of API responses (returns raw data).",
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
@add_options(shared_options)  # Apply shared options to the group
@click.pass_context
def cli(ctx, base_url, api_key, verify_ssl, verbose, disable_response_validation):
    """
    Karakeep Python API Command Line Interface.

    Dynamically generates commands based on the OpenAPI specification.
    Requires KARAKEEP_PYTHON_API_KEY environment variable or --api-key option.
    """
    # Ensure the context object exists
    ctx.ensure_object(dict)

    # --- Strict Check for API Key and Base URL ---
    # Check for API key (must be provided via arg or env)
    resolved_api_key = api_key or os.environ.get("KARAKEEP_PYTHON_API_KEY")
    if not resolved_api_key:
        raise click.UsageError(
            "API Key is required. Provide --api-key option or set KARAKEEP_PYTHON_API_KEY environment variable."
        )

    # Check for Base URL (must be provided via arg or env)
    resolved_base_url = base_url or os.environ.get("KARAKEEP_PYTHON_API_BASE_URL")
    if not resolved_base_url:
        raise click.UsageError(
            "API Base URL is required. Provide --base-url option or set KARAKEEP_PYTHON_API_BASE_URL environment variable. "
            "The URL must include the API path, e.g., 'https://your-instance.com/api/v1/'."
        )

    # Store common API parameters in the context for commands to use
    ctx.obj["BASE_URL"] = resolved_base_url  # Store the resolved URL
    ctx.obj["API_KEY"] = resolved_api_key  # Store the resolved key
    ctx.obj["VERIFY_SSL"] = verify_ssl
    ctx.obj["VERBOSE"] = verbose
    ctx.obj["DISABLE_RESPONSE_VALIDATION"] = (
        disable_response_validation  # Store the flag
    )

    # --- Configure Logger ---
    log_level = "DEBUG" if verbose else "INFO"
    logger.remove()  # Remove default handler
    logger.add(sys.stderr, level=log_level)
    logger.debug("Logger configured for level: {}", log_level)
    logger.debug("CLI context initialized.")


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
            base_url = ctx.obj["BASE_URL"]
            api_key = ctx.obj["API_KEY"]
            verify_ssl = ctx.obj["VERIFY_SSL"]
            verbose = ctx.obj["VERBOSE"]
            disable_validation = ctx.obj["DISABLE_RESPONSE_VALIDATION"]  # Retrieve flag

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
                    base_url=base_url,
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

                # Find the parameter designated for the request body (mapped from --data)
                body_param_name = None
                for p_name, p_obj in sig_params.items():
                    # Heuristic: Find param annotated as dict, BaseModel, or Union containing them
                    # This assumes only one such parameter exists for the body.
                    # More robust: Use a specific marker/convention if possible.
                    is_body_type = False
                    if (
                        p_obj.annotation is dict
                        or isinstance(p_obj.annotation, type)
                        and issubclass(p_obj.annotation, BaseModel)
                    ):
                        is_body_type = True
                    elif get_origin(p_obj.annotation) is Union:
                        union_args = get_args(p_obj.annotation)
                        if any(
                            arg is dict
                            or (isinstance(arg, type) and issubclass(arg, BaseModel))
                            for arg in union_args
                        ):
                            is_body_type = True

                    # Use the same heuristic as in create_click_command
                    is_body_type = False
                    param_annotation = p_obj.annotation
                    if param_annotation is dict or (
                        isinstance(param_annotation, type)
                        and issubclass(param_annotation, BaseModel)
                    ):
                        is_body_type = True
                    elif get_origin(param_annotation) is Union:
                        union_args = get_args(param_annotation)
                        if any(
                            arg is dict or (isinstance(arg, type) and issubclass(arg, BaseModel))
                            for arg in union_args
                        ):
                            is_body_type = True

                    if is_body_type:
                        if body_param_name is not None:
                            # Found a second body candidate - this logic assumes only one.
                            logger.warning(f"Method '{method_name}' has multiple potential body parameters ('{body_param_name}', '{p_name}'). Using the first one found for '--data'.")
                        else:
                            body_param_name = p_name
                            logger.debug(f"Identified '{p_name}' as the body parameter for method '{method_name}'.")

                # If no body parameter was identified by type, but --data was potentially added
                # (e.g., if the type hint was Any), we might have an issue.
                # However, create_click_command should only add --data if is_body_candidate is True.

                # Process Click kwargs into API call arguments
                for cli_name, value in kwargs.items():
                    py_name = cli_name.replace("-", "_") # Convert kebab-case back to snake_case

                    # Handle the special '--data' argument
                    if cli_name == "data" and body_param_name:
                        if value is not None:
                            try:
                                # Parse JSON here, API method expects dict/list/model
                                parsed_data = json.loads(value)
                                call_args[body_param_name] = (
                                    parsed_data  # Assign to correct param name
                                )
                            except json.JSONDecodeError:
                                raise click.BadParameter(
                                    f"Invalid JSON string provided for --data: {value}",
                                    param_hint="--data",
                                )
                            # else: value is None (e.g., --data not provided but param optional?) - skip assignment
                        else:
                            # This case should ideally not happen if create_click_command works correctly.
                            # It means --data was passed but no body parameter was identified.
                            logger.warning(f"Received '--data' argument but could not identify a body parameter for method '{method_name}'. Ignoring '--data'.")

                    # Handle other arguments (non-body parameters)
                    # Ensure we don't overwrite the body parameter if it somehow got into kwargs directly
                    # (which it shouldn't if mapped to --data)
                    elif py_name != body_param_name and py_name in sig_params:
                        # Pass through non-None values. Click handles type conversion for basic types.
                        # Boolean flags are handled correctly by Click (value is True/False/None).
                        # Optional parameters will have value=None if not provided.
                        if value is not None:
                             # Re-evaluate the JSON parsing for list/dict here.
                             # It might be better to let the API method handle the type if it expects str.
                             # For now, keep the existing logic but ensure it doesn't apply to the body param.
                            param_annotation = sig_params[py_name].annotation
                            is_list_or_dict = False
                            try:
                                origin = get_origin(param_annotation)
                                is_list_or_dict = origin in (list, dict, List, Dict) or param_annotation in (list, dict)
                            except Exception: pass

                            if is_list_or_dict and isinstance(value, str):
                                try:
                                    call_args[py_name] = json.loads(value)
                                    logger.debug(f"Interpreted string value for '{cli_name}' as JSON.")
                                except json.JSONDecodeError:
                                    logger.warning(f"Failed to parse '{cli_name}' value as JSON for list/dict param. Passing as string.")
                                    call_args[py_name] = value
                            else:
                                call_args[py_name] = value # Pass other types directly
                        # else: value is None, don't add to call_args if API method uses defaults

                # Call the API method
                try:
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
                    click.echo(
                        json.dumps(output_data, indent=2)
                    )  # Keep this for stdout result
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
    docstring_lines = docstring.split("\n")
    help_text = docstring_lines[0].strip()  # First line as short help
    full_help = docstring  # Full docstring as help

    # Extract parameter descriptions from the Args section of the docstring
    param_descriptions = {}
    in_args_section = False
    args_section_lines = []
    for line in docstring_lines:
        stripped_line = line.strip()  # Corrected indentation
        if stripped_line == "Args:":  # Corrected indentation
            in_args_section = True  # Corrected indentation
        elif (
            stripped_line == "Returns:" or stripped_line == "Raises:"
        ):  # Corrected indentation
            in_args_section = False  # Stop capturing when Returns/Raises section starts # Corrected indentation
        elif in_args_section and stripped_line:  # Corrected indentation
            args_section_lines.append(stripped_line)  # Corrected indentation
            # Try parsing the parameter name and description
            parts = stripped_line.split(":", 1)  # Corrected indentation
            if len(parts) == 2:  # Corrected indentation
                # Extract name, assuming format "name (type): description"
                name_part = parts[0].split(" ")[0]  # Corrected indentation
                # Clean potential trailing parenthesis from type hint parsing
                name_part = name_part.rstrip(")")  # Corrected indentation
                param_descriptions[name_part] = parts[
                    1
                ].strip()  # Corrected indentation

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

        # --- Determine if this parameter should be mapped to the '--data' option ---
        # Heuristic: Check type annotation for dict, BaseModel, or Union containing them
        is_body_candidate = False
        param_annotation = param.annotation
        if param_annotation is dict or (
            isinstance(param_annotation, type)
            and issubclass(param_annotation, BaseModel)
        ):
            is_body_candidate = True
        elif get_origin(param_annotation) is Union:
            union_args = get_args(param_annotation)
            if any(
                arg is dict or (isinstance(arg, type) and issubclass(arg, BaseModel))
                for arg in union_args
            ):
                is_body_candidate = True
        # TODO: Add more robust check? Maybe based on parameter name conventions?

        # If it's a body candidate, map it to '--data' and make it a required string
        if is_body_candidate:
            option_names = ["--data"]
            click_type = click.STRING
            param_help = f"JSON string for the request body ('{param.name}' parameter)."
            # Body data is usually required if the parameter itself is required in the signature
            click_required = is_required_in_sig
            is_flag = False  # Body is never a flag
            default_value = None  # Default is handled by parsing JSON string
            # REMOVE THE MARKER LOGIC:
            # param_name_cli += "_is_body" # Append marker to CLI name (won't be used directly)
        else:
            # Standard parameter handling (not the body)
            click_required = (
                is_required_in_sig and default_value is None and not is_flag
            )

        # Add the Click Option/Argument
        click_params.append(
            click.Option(
                option_names,  # This positional argument provides the parameter declarations
                # param_decls=[param_name_cli], # REMOVED: Redundant keyword argument
                # The `name` attribute of the Option object is derived from the first element in option_names
                # unless explicitly set via `param_decls`. If option_names is ['--data'], the name becomes 'data'.
                # If it's ['--bookmark-data'], the name becomes 'bookmark_data'.
                # The marker logic `param_name_cli += "_is_body"` seems intended to pass information
                # but it's not used correctly later.
                type=click_type,
                required=click_required,
                default=default_value if not is_flag else None,
                help=param_help,
                is_flag=(is_flag if len(option_names) == 1 else False),
                show_default=True,
                # We need to ensure the `name` passed to the command function corresponds
                # to the original parameter name if it's the body parameter mapped to '--data'.
                # Click uses the first long option name ('--data') to create the Python identifier ('data').
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
                            get_origin(param_annotation) is Union
                            and bool in get_args(param_annotation)
                        )

                        if is_bool_param:
                            # Click provides True/False for flags, None otherwise if not required
                            if (
                                value is not None
                            ):  # Only pass if flag was actually provided or has a non-None default
                                call_args[py_name] = value
                        # Handle other types - pass non-None values
                        elif value is not None:
                            # If param expects list/dict (and isn't the body param), try parsing JSON string
                            is_list_or_dict = False
                            try:
                                origin = get_origin(param_annotation)
                                is_list_or_dict = origin in (
                                    list,
                                    dict,
                                    List,
                                    Dict,
                                ) or param_annotation in (list, dict)
                            except Exception:
                                pass  # Ignore errors in annotation check

                            if is_list_or_dict and isinstance(value, str):
                                try:
                                    call_args[py_name] = json.loads(value)
                                    logger.debug(
                                        f"Interpreted string value for '{cli_name}' as JSON."
                                    )
                                except json.JSONDecodeError:
                                    logger.warning(
                                        f"Failed to parse '{cli_name}' value as JSON for list/dict param. Passing as string."
                                    )
                                    call_args[py_name] = value
                            else:
                                call_args[py_name] = value  # Pass other types directly

                # Call the API method
                try:
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
                    click.echo(
                        json.dumps(output_data, indent=2)
                    )  # Keep this for stdout result
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
    docstring_lines = docstring.split("\n")
    help_text = docstring_lines[0].strip()  # First line as short help
    full_help = docstring  # Full docstring as help

    # Extract parameter descriptions from the Args section of the docstring
    param_descriptions = {}
    in_args_section = False
    args_section_lines = []
    for line in docstring_lines:
        stripped_line = line.strip()  # Corrected indentation
        if stripped_line == "Args:":  # Corrected indentation
            in_args_section = True  # Corrected indentation
        elif (
            stripped_line == "Returns:" or stripped_line == "Raises:"
        ):  # Corrected indentation
            in_args_section = False  # Stop capturing when Returns/Raises section starts # Corrected indentation
        elif in_args_section and stripped_line:  # Corrected indentation
            args_section_lines.append(stripped_line)  # Corrected indentation
            # Try parsing the parameter name and description
            parts = stripped_line.split(":", 1)  # Corrected indentation
            if len(parts) == 2:  # Corrected indentation
                # Extract name, assuming format "name (type): description"
                name_part = parts[0].split(" ")[0]  # Corrected indentation
                # Clean potential trailing parenthesis from type hint parsing
                name_part = name_part.rstrip(")")  # Corrected indentation
                param_descriptions[name_part] = parts[
                    1
                ].strip()  # Corrected indentation

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

        # --- Determine if this parameter should be mapped to the '--data' option ---
        # Heuristic: Check type annotation for dict, BaseModel, or Union containing them
        is_body_candidate = False
        param_annotation = param.annotation
        if param_annotation is dict or (
            isinstance(param_annotation, type)
            and issubclass(param_annotation, BaseModel)
        ):
            is_body_candidate = True
        elif get_origin(param_annotation) is Union:
            union_args = get_args(param_annotation)
            if any(
                arg is dict or (isinstance(arg, type) and issubclass(arg, BaseModel))
                for arg in union_args
            ):
                is_body_candidate = True
        # TODO: Add more robust check? Maybe based on parameter name conventions?

        # If it's a body candidate, map it to '--data' and make it a required string
        if is_body_candidate:
            option_names = ["--data"]
            click_type = click.STRING
            param_help = f"JSON string for the request body ('{param.name}' parameter)."
            # Body data is usually required if the parameter itself is required in the signature
            click_required = is_required_in_sig
            is_flag = False  # Body is never a flag
            default_value = None  # Default is handled by parsing JSON string
            # Add a marker to kwargs so the command function can identify this parameter
            param_name_cli += (
                "_is_body"  # Append marker to CLI name (won't be used directly)
            )
        else:
            # Standard parameter handling (not the body)
            click_required = (
                is_required_in_sig and default_value is None and not is_flag
            )

        # Add the Click Option/Argument
        click_params.append(
            click.Option(
                option_names,  # This positional argument provides the parameter declarations
                # param_decls=[param_name_cli], # REMOVED: Redundant keyword argument
                type=click_type,
                required=click_required,
                default=default_value if not is_flag else None,
                help=param_help,
                is_flag=(is_flag if len(option_names) == 1 else False),
                show_default=True,
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
