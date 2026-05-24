.PHONY: install seed dev test migrate backup

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

# Snapshot textual do DB em ./data/backups/ (gzipado). Bom pra ter um
# estado "diff-ável" em git ou pra restaurar em outra máquina sem
# carregar o .db binário.
backup:
	@mkdir -p data/backups
	@TS=$$(date +%Y%m%d-%H%M%S); \
		sqlite3 numis_geek.db .dump | gzip > data/backups/numis_geek-$$TS.sql.gz; \
		echo "Backup → data/backups/numis_geek-$$TS.sql.gz ($$(ls -lh data/backups/numis_geek-$$TS.sql.gz | awk '{print $$5}'))"
