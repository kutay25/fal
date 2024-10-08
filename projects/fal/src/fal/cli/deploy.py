import argparse
from collections import namedtuple
from pathlib import Path

from .parser import FalClientParser, RefAction

User = namedtuple("User", ["user_id", "username"])


def _remove_http_and_port_from_url(url):
    # Remove http://
    if "http://" in url:
        url = url.replace("http://", "")

    # Remove https://
    if "https://" in url:
        url = url.replace("https://", "")

    # Remove port information
    url_parts = url.split(":")
    if len(url_parts) > 1:
        url = url_parts[0]

    return url


def _get_user() -> User:
    import json
    from http import HTTPStatus

    import openapi_fal_rest.api.users.get_current_user as get_current_user

    from fal.api import FalServerlessError
    from fal.rest_client import REST_CLIENT

    try:
        user_details_response = get_current_user.sync_detailed(
            client=REST_CLIENT,
        )
    except Exception as e:
        raise FalServerlessError(f"Error fetching user details: {str(e)}")

    if user_details_response.status_code != HTTPStatus.OK:
        try:
            content = json.loads(user_details_response.content.decode("utf8"))
        except Exception:
            raise FalServerlessError(
                f"Error fetching user details: {user_details_response}"
            )
        else:
            raise FalServerlessError(content["detail"])
    try:
        full_user_id = user_details_response.parsed.user_id
        _provider, _, user_id = full_user_id.partition("|")
        if not user_id:
            user_id = full_user_id

        return User(user_id=user_id, username=user_details_response.parsed.nickname)
    except Exception as e:
        raise FalServerlessError(f"Could not parse the user data: {e}")


def _deploy(args):
    from fal.api import FalServerlessError, FalServerlessHost
    from fal.utils import load_function_from

    file_path, func_name = args.app_ref
    if file_path is None:
        # Try to find a python file in the current directory
        options = list(Path(".").glob("*.py"))
        if len(options) == 0:
            raise FalServerlessError("No python files found in the current directory")
        elif len(options) > 1:
            raise FalServerlessError(
                "Multiple python files found in the current directory. "
                "Please specify the file path of the app you want to deploy."
            )

        [file_path] = options
        file_path = str(file_path)

    user = _get_user()
    host = FalServerlessHost(args.host)
    loaded = load_function_from(
        host,
        file_path,
        func_name,
    )
    isolated_function = loaded.function
    app_name = args.app_name or loaded.app_name
    app_auth = args.auth or loaded.app_auth or "private"
    app_id = host.register(
        func=isolated_function.func,
        options=isolated_function.options,
        application_name=app_name,
        application_auth_mode=app_auth,
        metadata=isolated_function.options.host.get("metadata", {}),
    )

    if app_id:
        gateway_host = _remove_http_and_port_from_url(host.url)
        gateway_host = (
            gateway_host.replace("api.", "").replace("alpha.", "").replace("ai", "run")
        )

        args.console.print(
            "Registered a new revision for function "
            f"'{app_name}' (revision='{app_id}')."
        )
        args.console.print("Playground:")
        for endpoint in loaded.endpoints:
            args.console.print(
                f"\thttps://fal.ai/models/{user.username}/{app_name}{endpoint}"
            )
        args.console.print("Endpoints:")
        for endpoint in loaded.endpoints:
            args.console.print(
                f"\thttps://{gateway_host}/{user.username}/{app_name}{endpoint}"
            )


def add_parser(main_subparsers, parents):
    from fal.sdk import ALIAS_AUTH_MODES

    def valid_auth_option(option):
        if option not in ALIAS_AUTH_MODES:
            raise argparse.ArgumentTypeError(f"{option} is not a auth option")
        return option

    deploy_help = "Deploy a fal application."
    epilog = (
        "Examples:\n"
        "  fal deploy\n"
        "  fal deploy path/to/myfile.py\n"
        "  fal deploy path/to/myfile.py::MyApp\n"
        "  fal deploy path/to/myfile.py::MyApp --app-name myapp --auth public\n"
    )
    parser = main_subparsers.add_parser(
        "deploy",
        parents=[*parents, FalClientParser(add_help=False)],
        description=deploy_help,
        help=deploy_help,
        epilog=epilog,
    )
    parser.add_argument(
        "app_ref",
        nargs="?",
        action=RefAction,
        help=(
            "Application reference. " "For example: `myfile.py::MyApp`, `myfile.py`."
        ),
    )
    parser.add_argument(
        "--app-name",
        help="Application name to deploy with.",
    )
    parser.add_argument(
        "--auth",
        type=valid_auth_option,
        help="Application authentication mode (private, public).",
    )
    parser.set_defaults(func=_deploy)
