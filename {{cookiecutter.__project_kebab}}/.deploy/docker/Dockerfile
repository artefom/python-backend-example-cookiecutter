FROM python:3.13-slim-bookworm

WORKDIR /app

RUN pip install --no-input "poetry==1.8.4"

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

# This webserver.sh is configured to run in the deployment.yaml
#
# If needed, feel free to add more entrypoints and configure them
# to be executed in different cronjobs/deployments/stateful sets/ etc...
COPY .deploy/docker/webserver.sh /webserver.sh
RUN chmod +x /webserver.sh
