format:
    uv run ruff format src/ tests/    

lint: 
    uv run ruff check --fix src/ tests/

check:
    just format
    just lint

test:
    uv run -m pytest tests/ -v

load-test users="300" rate="20" duration="30s" host="http://127.0.0.1:8008" pre_register="3000":
    uv run -m locust -f tests/load/locustfile.py \
        --headless \
        --users {{users}} \
        --spawn-rate {{rate}} \
        --run-time {{duration}} \
        --host {{host}} \
        --pre-register {{pre_register}}
