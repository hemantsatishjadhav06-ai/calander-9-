FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js for Tailwind build
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# The lock, not the ranges: every build installs exactly the versions CI
# tested, each checked against its hash. Regenerate it after editing
# requirements.txt (see the header of requirements.lock).
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY . .

# Build Tailwind CSS
RUN cd theme/static_src && npm ci && npm run build

# Collect static files
RUN DJANGO_SETTINGS_MODULE=config.settings.production \
    SECRET_KEY=build-placeholder \
    DATABASE_URL=sqlite:///tmp/build.db \
    python manage.py collectstatic --noinput

EXPOSE 8000

# One worker, threaded. Importing this app costs ~100 MB before serving a
# single request, so two workers alone exceeded a 512 MB dyno's quota and the
# whole thing ran in swap. Raise --workers only alongside the container memory
# to match (budget ~250 MB per worker).
#
# Deliberately NO --max-requests. gthread sets ``alive = False`` at the START of
# the request that trips the counter, which stops the heartbeat while that
# request is still running — the arbiter then SIGKILLs the worker after
# ``timeout`` (30s) and the client gets a dropped connection. Verified against
# gunicorn 22: a 12s request that tripped --max-requests was killed, while the
# same request without it returned 200. Uploads here are allowed up to 1 GB, so
# no fixed timeout makes recycling safe. The RSS ratchet it was guarding against
# is fixed at the source instead (AWS_S3_MAX_MEMORY_SIZE + streaming reads).
# Exec form, so gunicorn is PID 1 and receives SIGTERM itself. In shell form
# it ran under `sh -c`, which does not forward the signal: Railway sent
# SIGTERM, nothing drained, and the container was SIGKILLed mid-request.
# `check --deploy` first: its warnings (DEBUG on, a missing secret, an unset
# salt, insecure cookies — see apps/common/checks.py) land in the deploy log on
# every start, and an Error-level check stops the container before it takes
# traffic. It runs here rather than as a Railway pre-deploy command because the
# pre-deploy step is shared with the worker service (see railway.toml).
CMD ["sh", "-c", "python manage.py check --deploy && exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4"]
