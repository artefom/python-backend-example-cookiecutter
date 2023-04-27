FROM python:3.11-slim-bullseye

WORKDIR /app

RUN pip install --no-input "poetry==1.3.2"

# Install packages in a cache-friendly way
COPY poetry.lock ./
COPY pyproject.toml ./

# Configure credentials for distribusion pacakge repo
ARG GITLAB_REGISTRY_USERNAME
ARG GITLAB_REGISTRY_PASSWORD
RUN poetry config http-basic.distribusion $GITLAB_REGISTRY_USERNAME $GITLAB_REGISTRY_PASSWORD

RUN POETRY_VIRTUALENVS_CREATE=false poetry install --no-root

# Copy package source code
COPY ./{{cookiecutter.__project_slug}} ./{{cookiecutter.__project_slug}}

# Install package
RUN pip install --no-deps .

# Run application
# Use run by file name because otherwise sigterm on docker shutdown
# is not propagated to the python application and cannot be handled
CMD python {{cookiecutter.__project_slug}}/main.py
