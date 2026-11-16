"""
Command-line interface for launching the application.

The entry-point of the application and the way to pass arguments
"""

# We import inside functions to achieve better performance of `--help` function

import logging
import logging.config

import typer

logger = logging.getLogger(__name__)

# This app is referenced by [project.scripts] in pyproject.toml
#
# When you install the application `uv sync`
# (to install with lint and tests run `uv sync --group lint --group test`)
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
    formatter: str = typer.Option("standard", envvar="LOG_FORMATTER"),
    environment: str | None = typer.Option(
        None,
        envvar="ENVIRONMENT",
        help="Deployment environment (e.g. production), reported to Sentry and tracing",
    ),
) -> None:
    """
    Hook that sets up
    global variables such sentry configuration, logging config and tracing.

    Will be executed before any other app command
    """
    import sentry_sdk

    from .tracing import TraceSettings, configure

    loglevel = logging.INFO

    if verbose:
        loglevel = logging.DEBUG

    # Configure logging
    logging.config.dictConfig(_get_logging_config(loglevel, formatter))

    sentry_sdk.init(attach_stacktrace=True, environment=environment)

    configure(
        TraceSettings(
            "{{cookiecutter.__project_kebab}}",
            environment=environment,
            otlp_endpoint="https://telemetry.googleapis.com",
            otlp_headers=None,
            gcp_project_id="distribusion-next-13",
        )
    )


@app.command()
def run(
    host: str = "127.0.0.1",
    port: int = 8000,
    root_path: str = typer.Option("", envvar="API_ROOT_PATH"),
) -> None:
    """
    Run server.
    Start accepting new connections on the specified host/port in an infinite loop,
    and for every request and provide some responses
    """

    from .main import AppSettings, main

    main(AppSettings(host=host, port=port, root_path=root_path))
