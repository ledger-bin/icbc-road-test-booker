FROM python:3.14-slim

# Chromium + its matching chromedriver (apt keeps them in lockstep,
# which is more reliable in a container than webdriver-manager's dynamic
# download-and-match against an arbitrary installed Chrome version).
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_BINARY_PATH=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# uv for fast, reproducible installs from uv.lock
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Dependencies first (better layer caching -- only reinstalls when these
# actually change, not on every code edit)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# No .env in the image (it's gitignored, never gets this far) -- all
# secrets come from the platform's environment variables at runtime.
CMD ["uv", "run", "python", "main.py"]
