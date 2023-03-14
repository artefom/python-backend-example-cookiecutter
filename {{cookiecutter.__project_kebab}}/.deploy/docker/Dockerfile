FROM python:3.11-slim-bullseye

WORKDIR /app

RUN pip install --no-input "poetry>=1.2.2<2.0"

# Configure credentials for distribusion pacakge repo
ARG GITLAB_REGISTRY_USERNAME
ARG GITLAB_REGISTRY_PASSWORD
RUN poetry config http-basic.distribusion $GITLAB_REGISTRY_USERNAME $GITLAB_REGISTRY_PASSWORD

# Install packages in a cache-friendly way
COPY poetry.lock ./
COPY pyproject.toml ./
RUN POETRY_VIRTUALENVS_CREATE=false poetry install --no-root

# Copy package source code
COPY ./{{cookiecutter.__project_slug}} ./{{cookiecutter.__project_slug}}
COPY ./.deploy/docker/logging-config.yaml ./logging-config.yaml

# Install package
RUN pip install --no-deps .

# Start single uvicorn worker
CMD uvicorn {{cookiecutter.__project_slug}}.main:app --host 0.0.0.0 --port 8000 --log-config logging-config.yaml
