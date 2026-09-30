# Enterprise RAG on Amazon Bedrock Knowledge Bases — common tasks.
# Run `make help` for the list.

TF      := terraform -chdir=infrastructure/terraform
TF_ARGS ?=

.PHONY: help install test build init plan deploy upload sync sync-status users evaluate evaluate-full web-local destroy clean

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## Install Python dev dependencies
	python3 -m pip install -r backend/requirements-dev.txt

test: ## Run backend unit tests
	cd backend && python3 -m pytest -q

build: ## Package the Lambda code into build/lambda
	./scripts/build_lambda.sh

init: ## terraform init
	$(TF) init -upgrade

plan: build init ## Show what would change
	$(TF) plan

# The OpenSearch provider needs the collection endpoint, which only exists after
# the collection is created. Phase 1 creates it; phase 2 creates everything else.
deploy: test build init ## Deploy everything (two phases)
	$(TF) apply $(TF_ARGS) \
	  -target=aws_opensearchserverless_collection.kb \
	  -target=aws_opensearchserverless_access_policy.data \
	  -target=time_sleep.aoss_policy_propagation
	$(TF) apply $(TF_ARGS)
	@echo ""
	@echo "Web app: $$($(TF) output -raw web_url)"

upload: ## Upload sample-docs/documents to S3 (sync starts automatically)
	./scripts/upload_docs.sh

sync: ## Start a sync now and wait for it
	./scripts/sync_now.sh

sync-status: ## Show recent sync jobs
	./scripts/sync_status.sh

users: ## Create one demo user per role (edit passwords first!)
	./scripts/create_user.sh admin@example.com   'Change-Me-Admin#2026' admin
	./scripts/create_user.sh hr.user@example.com 'Change-Me-Hr#2026'    hr
	./scripts/create_user.sh fin.user@example.com 'Change-Me-Fin#2026'  finance
	./scripts/create_user.sh it.user@example.com 'Change-Me-It#2026'    it
	./scripts/create_user.sh secops@example.com  'Change-Me-Sec#2026'   it confidential

evaluate: ## Retrieval quality + access-leak check
	python3 scripts/evaluate.py

evaluate-full: ## Also generate and check answers
	python3 scripts/evaluate.py --generate

web-local: ## Run the web app on http://localhost:8080 against the deployed API
	./scripts/write_local_config.sh
	python3 -m http.server 8080 -d frontend

destroy: ## Delete every AWS resource (stops OpenSearch charges)
	$(TF) destroy $(TF_ARGS)

clean:
	rm -rf build frontend/config.js
