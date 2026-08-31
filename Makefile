.PHONY: up down reset logs shell psql test lint fetch parse extract eval

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

parse:         ## parse cached pages into courses
	docker compose exec app python -m ingest.parse_courses

extract:       ## extract prereq trees (LLM)
	docker compose exec app python -m ingest.extract_trees

eval:          ## measure extraction accuracy against golden set
	docker compose exec app python -m eval.run_eval
