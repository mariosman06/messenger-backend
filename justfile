format:
    uv run ruff format src/ tests/

lint: 
    uv run ruff check --fix src/ tests/

check:
    just format
    just lint

test:
    uv run -m pytest tests/ -v
