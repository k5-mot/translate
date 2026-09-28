FROM ghcr.io/astral-sh/uv:python3.12-trixie

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends pandoc \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN uv sync --frozen --all-extras --no-dev

EXPOSE 8501

CMD ["uv", "run", "--no-sync", "streamlit", "run", "main.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
