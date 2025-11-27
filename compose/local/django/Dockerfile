# define an alias for the specific python version used in this file.
FROM docker.io/python:3.12.8-slim-bookworm AS python

# Python build stage
FROM python AS python-build-stage
ARG BUILD_ENVIRONMENT=local

# Install apt packages
RUN apt-get update && apt-get install --no-install-recommends -y \
    # dependencies for building Python packages
    build-essential \
    # psycopg dependencies
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv using the more reliable COPY method from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Requirements are installed here to ensure they will be cached.
COPY ./requirements .

# Install Python dependencies with cache mounting
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r ${BUILD_ENVIRONMENT}.txt

# Python 'run' stage  
FROM python AS python-run-stage
ARG BUILD_ENVIRONMENT=local
ARG APP_HOME=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV BUILD_ENV=${BUILD_ENVIRONMENT}
WORKDIR ${APP_HOME}

# devcontainer dependencies and utils (force IPv4 to avoid mirror stalls)
RUN apt-get update -o Acquire::ForceIPv4=true -o Acquire::Retries=3 -o Acquire::http::Timeout=20 \
    && apt-get install --no-install-recommends -y \
    sudo git bash-completion nano ssh \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* /var/cache/apt/archives/partial/*

# Create devcontainer user and add it to sudoers
RUN groupadd --gid 1000 dev-user \
    && useradd --uid 1000 --gid dev-user --shell /bin/bash --create-home dev-user \
    && echo dev-user ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/dev-user \
    && chmod 0440 /etc/sudoers.d/dev-user

# Install required system dependencies (force IPv4 to avoid mirror stalls)
RUN apt-get update -o Acquire::ForceIPv4=true -o Acquire::Retries=3 -o Acquire::http::Timeout=20 \
    && apt-get install --no-install-recommends -y \
    # psycopg dependencies
    libpq-dev \
    wait-for-it \
    # Translations dependencies
    gettext \
    # Graphviz for blueprint visualization
    graphviz \
    # cleaning up unused files
    && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from build stage - SAME Python base image ensures compatibility
COPY --from=python-build-stage /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=python-build-stage /usr/local/bin /usr/local/bin

COPY ./compose/production/django/entrypoint /entrypoint
RUN sed -i 's/\r$//g' /entrypoint
RUN chmod +x /entrypoint

COPY ./compose/local/django/start /start
RUN sed -i 's/\r$//g' /start
RUN chmod +x /start

# copy application code to WORKDIR
COPY . ${APP_HOME}

ENTRYPOINT ["/entrypoint"]
