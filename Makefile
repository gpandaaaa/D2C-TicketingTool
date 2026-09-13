PYTHON ?= $(if $(wildcard .runtime/bin/python),$(abspath .runtime/bin/python),$(if $(wildcard .venv/bin/python),$(abspath .venv/bin/python),python3))

.PHONY: up seed test lint migrate browser
up:
	docker compose up --build -d
seed:
	docker compose run --rm seed
test:
	$(PYTHON) -m pytest
lint:
	$(PYTHON) -m ruff check backend scripts
	$(PYTHON) -m ruff format --check backend scripts
migrate:
	cd backend && $(PYTHON) -m alembic upgrade head
browser:
	APP_URL=http://localhost:3000 $(PYTHON) scripts/browser_acceptance.py
