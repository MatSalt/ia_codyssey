.PHONY: up down verify-install verify-isolation
up:
	docker compose up --build -d --wait

down:
	docker compose down --remove-orphans

verify-install:
	./scripts/verify-install.sh

verify-isolation:
	./scripts/verify-isolation.sh

.PHONY: verify-codecs verify-media-load verify-db verify-worker
verify-codecs:
	./scripts/verify-codecs.sh

verify-media-load:
	./scripts/verify-media-load.sh

verify-db:
	./scripts/verify-db.sh

verify-worker:
	./scripts/verify-worker.sh

.PHONY: verify-storage
verify-storage:
	./scripts/verify-storage.sh
