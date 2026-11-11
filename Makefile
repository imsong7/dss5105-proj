# One entry point for the common tasks. Run from the repo root with the virtual
# environment active:   source .venv/bin/activate
#
#   make install   Python packages (app) and frontend packages
#   make run       start the email-sorter app on http://127.0.0.1:5001
#   make test      all Python tests
#   make lint      ruff (mistakes only: undefined names, unused imports)
#   make build     typecheck and build the React frontend
#   make check     lint + test + build (what CI runs)

PYTHON ?= python
FRONTEND := email-sorter/frontend

.PHONY: install run test test-app test-claude test-reply lint build check

install:
	$(PYTHON) -m pip install -r requirements.txt
	cd $(FRONTEND) && npm ci

run:
	cd email-sorter && $(PYTHON) run.py

test: test-app test-claude test-reply

test-app:
	cd email-sorter && PYTHONPATH=. $(PYTHON) -m pytest -q

test-claude:
	cd claude && $(PYTHON) -m pytest -q

test-reply:
	cd email-sorter/llm-reply && $(PYTHON) -m unittest discover -s tests

lint:
	$(PYTHON) -m ruff check .

build:
	cd $(FRONTEND) && npm run typecheck && npm run build

check: lint test build
