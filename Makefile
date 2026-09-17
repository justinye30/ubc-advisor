.PHONY: up down reset logs shell psql test lint fetch parse extract eval cli fetch-policy chunk embed search eval-retrieval rebuild-edges ask eval-routing eval-entities eval-composer

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

cli:           ## run the CLI: make cli ARGS="check --want 'CPSC 221'"
	docker compose exec app python -m core.cli $(ARGS)

fetch-policy:  ## fetch policy pages into raw_pages
	docker compose exec app python -m ingest.fetch --type policy

chunk:         ## chunk cached policy pages into policy_chunks
	docker compose exec app python -m ingest.chunk_policy

embed:          ## embed policy chunks: make embed ARGS="--dry-run"
	docker compose exec app python -m ingest.embed_policy $(ARGS)

search:         ## search policy text: make search Q="can I retake a course" ARGS="--mode hybrid"
	docker compose exec app python -m core.retrieval "$(Q)" $(ARGS)

eval-retrieval: ## recall@k for policy retrieval, vector vs hybrid
	docker compose exec app python -m eval.run_retrieval_eval $(ARGS)

rebuild-edges: ## regenerate prereq_edges from stored trees: make rebuild-edges ARGS="--dry-run"
	docker compose exec app python -m ingest.rebuild_edges $(ARGS)

ask:           ## ask in plain English: make ask Q="can I retake a course?" ARGS="--route-only"
	docker compose exec app python -m agent $(ARGS) "$(Q)"

eval-routing:  ## routing accuracy: make eval-routing ARGS="--runs 2"
	docker compose exec app python -m eval.run_routing_eval $(ARGS)

eval-entities: ## entity extraction accuracy: make eval-entities ARGS="--save eval/results/entities_baseline.json"
	docker compose exec app python -m eval.run_entities_eval $(ARGS)

eval-composer: ## composer drift + answers: make eval-composer ARGS="--show"
	docker compose exec app python -m eval.run_composer_eval $(ARGS)
