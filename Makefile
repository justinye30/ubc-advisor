.PHONY: up down reset logs shell psql test lint fetch parse extract eval cli fetch-policy chunk embed search eval-retrieval rebuild-edges ask eval-routing eval-entities eval-composer eval-e2e smoke web-install web-dev web-mock web-build web-test db-dump db-restore aws-keys aws-deploy aws-start aws-stop aws-url aws-logs aws-shell aws-destroy

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
	docker compose exec -e EMBED_TIMEOUT=60 -e EMBED_MAX_RETRIES=6 app python -m ingest.embed_policy $(ARGS)

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

eval-e2e:      ## end-to-end: make eval-e2e ARGS="--show" / "--audit" / "--save eval/results/e2e_baseline.json"
	docker compose exec app python -m eval.run_e2e_eval $(ARGS)

Q ?= I did CPSC 110, 121 and 210. Can I take CPSC 221?
smoke:         ## hit the running API: make smoke Q="can I retake a course?"
	curl -s localhost:8000/health/ready | python3 -m json.tool
	curl -s -X POST localhost:8000/api/ask -H 'Content-Type: application/json' \
	  -d '{"question": "$(Q)"}' | python3 -m json.tool

# --- web UI (runs on your machine, not in the container; needs Node 22) ---
web-install:   ## install front-end dependencies exactly as locked
	cd web && npm ci

web-dev:       ## Vite dev server on :5173, proxying /api to Flask on :8000
	cd web && npm run dev

web-mock:      ## Vite dev server with canned answers: no Flask, no API calls
	cd web && npm run dev:mock

web-build:     ## build web/dist; Flask then serves the UI at localhost:8000
	cd web && npm run build

web-test:      ## front-end unit tests
	cd web && npm test

# --- AWS (Step 19). Needs the AWS CLI (default region set) and Terraform. ---
TF    = terraform -chdir=infra
TFOUT = terraform -chdir=infra output -raw
SHA   = $(shell git rev-parse --short HEAD)

db-dump:       ## dump the local database for AWS (no scraped pages, no query logs)
	mkdir -p data
	docker compose exec -T db pg_dump -U advisor -d advisor -Fc --no-owner --no-acl \
	  --exclude-table-data=raw_pages --exclude-table-data=query_logs > data/advisor.dump
	@ls -lh data/advisor.dump

db-restore:    ## load data/advisor.dump into RDS (opens the DB to your IP, then closes it)
	@test -s data/advisor.dump || { echo "No dump yet: run make db-dump"; exit 1; }
	$(TF) apply -var db_public=true \
	  -target=aws_db_instance.main -target=aws_vpc_security_group_ingress_rule.db_from_me
	URL=$$(aws secretsmanager get-secret-value --secret-id $$($(TFOUT) db_secret_id) \
	  --query SecretString --output text); \
	docker compose exec -T db pg_restore --no-owner --no-acl -d "$$URL" < data/advisor.dump; \
	status=$$?; \
	$(TF) apply -target=aws_db_instance.main -target=aws_vpc_security_group_ingress_rule.db_from_me; \
	exit $$status

aws-keys:      ## copy ANTHROPIC_API_KEY and VOYAGE_API_KEY from .env into Secrets Manager
	python3 -c 'import json; from dotenv import dotenv_values as d; e = d(".env"); \
	  print(json.dumps({k: e[k] for k in ("ANTHROPIC_API_KEY", "VOYAGE_API_KEY")}))' \
	| aws secretsmanager put-secret-value --secret-id $$($(TFOUT) api_keys_secret_id) \
	    --secret-string file:///dev/stdin --query VersionId --output text

aws-deploy:    ## build the current commit, push it to ECR, and roll it out
	@git diff --quiet && git diff --cached --quiet || \
	  { echo "Commit first: the image is tagged with the commit."; exit 1; }
	REPO=$$($(TFOUT) ecr_repository_url); \
	if aws ecr describe-images --repository-name $${REPO##*/} --image-ids imageTag=$(SHA) >/dev/null 2>&1; then \
	  echo "$(SHA) is already in ECR"; \
	else \
	  docker build --platform linux/amd64 -t $$REPO:$(SHA) . && \
	  aws ecr get-login-password | docker login --username AWS --password-stdin $${REPO%%/*} && \
	  docker push $$REPO:$(SHA); \
	fi
	echo 'image_tag = "$(SHA)"' > infra/image.auto.tfvars
	$(TF) apply
	aws ecs wait services-stable --cluster $$($(TFOUT) cluster) --services $$($(TFOUT) service)

aws-start:     ## start the database (if stopped) and one app task, then print its URL
	-aws rds start-db-instance --db-instance-identifier $$($(TFOUT) db_identifier) >/dev/null 2>&1
	aws rds wait db-instance-available --db-instance-identifier $$($(TFOUT) db_identifier)
	aws ecs update-service --cluster $$($(TFOUT) cluster) --service $$($(TFOUT) service) \
	  --desired-count 1 --query service.desiredCount --output text
	aws ecs wait services-stable --cluster $$($(TFOUT) cluster) --services $$($(TFOUT) service)
	@infra/task-url.sh

aws-stop:      ## stop the app task and the database (RDS restarts itself after 7 days)
	aws ecs update-service --cluster $$($(TFOUT) cluster) --service $$($(TFOUT) service) \
	  --desired-count 0 --query service.desiredCount --output text
	aws rds stop-db-instance --db-instance-identifier $$($(TFOUT) db_identifier) \
	  --query DBInstance.DBInstanceStatus --output text

aws-url:       ## print the running task's URL
	@infra/task-url.sh

aws-logs:      ## follow the app's logs in CloudWatch
	aws logs tail $$($(TFOUT) log_group) --follow --since 30m

aws-shell:     ## shell inside the running container (needs the Session Manager plugin)
	TASK=$$(aws ecs list-tasks --cluster $$($(TFOUT) cluster) --service-name $$($(TFOUT) service) \
	  --query 'taskArns[0]' --output text); \
	aws ecs execute-command --cluster $$($(TFOUT) cluster) --task $$TASK --container app \
	  --interactive --command /bin/sh

aws-destroy:   ## delete everything in AWS (asks first)
	$(TF) destroy
