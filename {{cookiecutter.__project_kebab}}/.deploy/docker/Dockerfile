FROM python:3.14-slim-trixie

WORKDIR /app

RUN pip install --no-input "uv"

# Install packages in a cache-friendly way
COPY uv.lock ./
COPY pyproject.toml ./

# Configure credentials for distribusion package repo
ARG GITLAB_REGISTRY_USERNAME
ARG GITLAB_REGISTRY_PASSWORD
ENV UV_INDEX_DISTRIBUSION_USERNAME=$GITLAB_REGISTRY_USERNAME
ENV UV_INDEX_DISTRIBUSION_PASSWORD=$GITLAB_REGISTRY_PASSWORD

RUN uv export --frozen --no-dev --no-editable --no-emit-project --format requirements.txt --output-file requirements.txt \
    && uv pip sync --system requirements.txt \
    && rm -f requirements.txt

COPY ./{{cookiecutter.__project_slug}} ./{{cookiecutter.__project_slug}}
RUN uv pip install --system .
# If needed, feel free to add more entrypoints and configure them
# to be executed in different cronjobs/deployments/stateful sets/ etc...
COPY .deploy/docker/webserver.sh /webserver.sh
RUN chmod +x /webserver.sh
CMD ["/webserver.sh"]
