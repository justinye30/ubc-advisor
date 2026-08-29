.PHONY: up down reset logs shell psql test lint fetch

up:            ## start the stack (foreground)
	docker compose up --build

down:          ## stop containers, keep data
	docker compose down

reset:         ## destroy the volume and re-run migrations
	docker compose down -v && docker compose up --build

logs:          ## tail app logs
	docker compose logs -f app

shell:         ## bash inside the app container
	docker compose exec app bash

psql:          ## interactive psql session
	docker compose exec db psql -U advisor -d advisor

test:          ## run pytest inside the container
	docker compose exec app pytest -q

lint:          ## run ruff
	docker compose exec app ruff check .

fetch:         ## fetch subject index pages into raw_pages
	docker compose exec app python -m ingest.fetch
