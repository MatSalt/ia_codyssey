# Backend

Use Python 3.10 or later. From this worktree's `M1-2/backend` directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs or http://127.0.0.1:8000/openapi.json.
These work without credentials. Registered routes include data CRUD, `/api/data/summary`,
conversation creation/list/detail/deletion, and `/api/chat` with automatic turn saving.
Data and conversation requests lazily initialize Firestore and require configured credentials.

Copy `.env.example` to `backend/.env` (or `.env` when already in this directory)
to configure exact, comma-separated frontend origins. Never paste real keys into chat
or commit `.env` or service-account JSON. Firebase and OpenAI credentials remain
server-only; local automated tests inject fake boundaries and do not load `.env` secrets.
The configured model is gpt-5-mini via the Copa Chat Completions gateway. The adapter
uses a 2048 completion token limit, a 45 second timeout, and zero automatic retries.
Gateway initialization occurs only when generation is needed; empty-data replies are
saved without OpenAI credentials.

Missing Firestore credentials or storage failures return a sanitized 503; generation
failures return a sanitized 502 and do not save a successful turn. Tests replace providers
through `app.dependency_overrides`.

The actual CSV imported 120 records, and a repeated import skipped all 120 existing records.
Live app chat returned 200, saved the turn, and restored the conversation successfully.
See the [stages 2–4 report](../docs/stages-2-4-report.md) for current validation and deployment status.

## 확정된 연결 설정

- Firebase 프로젝트: `story-analytics-assistant`
- 서비스 계정은 `GOOGLE_APPLICATION_CREDENTIALS`에 로컬 JSON의 절대 경로 지정
- `OPENAI_API_KEY`: 학습장에서 발급한 virtual key를 로컬 `.env`에만 입력
- `OPENAI_BASE_URL`: `https://copa.codyssey.kr/v1`
- `OPENAI_MODEL`: `gpt-5-mini`
- 호출 방식: Chat Completions. gateway는 이 Base URL을 SDK 클라이언트에 명시적으로 전달한다.
