.PHONY: install seed dev test migrate

# Instala todas as dependências (Python + Node)
install:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]" -q
	npm install --prefix frontend

# Aplica migrations e cria usuário/workspace inicial
seed:
	.venv/bin/alembic upgrade head
	.venv/bin/python scripts/seed.py

# Inicia backend e frontend em desenvolvimento (Ctrl+C encerra os dois)
dev:
	@bash dev.sh

# Roda os testes
test:
	.venv/bin/pytest

# Aplica novas migrations
migrate:
	.venv/bin/alembic upgrade head
