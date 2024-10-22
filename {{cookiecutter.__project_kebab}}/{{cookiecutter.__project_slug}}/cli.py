"""
Command-line interface for launching the application.

The entry-point of the application and the way to pass arguments
"""

# We import inside functions to achieve better performance of `--help` function
# pylint: disable=[C0415]


import logging
import logging.config

import typer

logger = logging.getLogger(__name__)

# This app is referenced by [tool.poetry.scripts] in pyproject.toml
#
# When you install the application `poetry install`
# (to install with lint and tests run `poetry install --with lint,test`)
#
# It makes the 'script' available in your environment. After that
# the application can be executed by simply typing in the console
#
# `{{cookiecutter.__project_kebab}} run`
#
# Or to get some help
# `{{cookiecutter.__project_kebab}} --help`
app = typer.Typer(
    name="{{cookiecutter.__project_kebab}}",
    help="{{cookiecutter.description}}",
)


def _get_logging_config(level: int, formatter: str):
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s %(levelname)-8s| %(message)s",
                "datefmt": "%H:%M:%S",
            },
            "json": {
                "()": "{{cookiecutter.__project_slug}}.slog.GcpStructuredFormatter",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": formatter,
            },
        },
        "loggers": {
            "uvicorn": {"level": "WARNING"},
            # "tortoise": {"level": "DEBUG"},
        },
        "root": {
            "handlers": ["console"],
            "level": level,
        },
    }


@app.callback()
def global_vars(
    verbose: bool = False,
    sentry_dsn: str | None = typer.Option(None, envvar="SENTRY_DSN"),
    sentry_environment: str | None = typer.Option(None, envvar="SENTRY_ENVIRONMENT"),
    formatter: str = typer.Option("standard", envvar="LOG_FORMATTER"),
) -> None:
    """
    Hook that sets up
    global variables such sentry configuration and logging config.

    Will be executed before any other app command
    """
    import sentry_sdk

    loglevel = logging.INFO

    if verbose:
        loglevel = logging.DEBUG

    # Configure logging
    logging.config.dictConfig(_get_logging_config(loglevel, formatter))

    # Configure setnry
    sentry_sdk.init(
        dsn=sentry_dsn,
        environment=sentry_environment,
    )


@app.command()
def run(
    host: str = "127.0.0.1",
    port: int = 8000,
    root_path: str = typer.Option("", envvar="API_ROOT_PATH"),
    # Add here more arguments/environment variables if needed
) -> None:
    """
    Run server.
    Start accepting new connections on the specified host/port in an infinite loop,
    and for every request and provide some responses
    """

    from .main import AppSettings, main

    main(
        AppSettings(
            host=host,
            port=port,
            root_path=root_path,
        )
    )
