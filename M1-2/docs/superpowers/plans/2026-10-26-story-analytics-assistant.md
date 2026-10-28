# 동화 열람 데이터 AI 비서 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 일별 열람 데이터 CRUD, 통계 요약, GPT 채팅과 대화 기록을 구현하고 필수 배포·제출 자료를 완성한다.

**Architecture:** 입력 모델과 저장소 인터페이스를 먼저 고정하고, 저장소·순수 요약 함수·바닐라 프론트를 병렬 구현한다. Firestore/GPT는 의존성 주입으로 교체하여 키 없이 테스트하고 실제 연결은 별도로 검증한다. 요약 API와 채팅은 같은 계산 서비스를 사용한다.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, Uvicorn, firebase-admin, openai, python-dotenv, pytest/httpx, HTML/CSS/JavaScript, Node 테스트 러너, Playwright(테스트 전용), Render/Vercel.

**Spec:** `M1-2/SPEC.md` (과제 폴더 기준 `SPEC.md`). 충돌 시 명세와 최신 사용자 결정이 우선한다.

## Global Constraints

- Python 3.10 이상, venv, FastAPI, Uvicorn, Pydantic
- HTML/CSS/JavaScript: 프론트 프레임워크 사용 금지
- Render: 백엔드, Vercel: 프론트
- 보너스 과제는 수행하지 않는다. Function Calling, MCP/GPT Actions, 추가 통계 API, 그래프, 내보내기, 다크 모드를 만들지 않는다.
- 기준일은 오늘이 아닌 저장 데이터의 마지막 날짜다.
- 최초~마지막 날짜 사이의 누락일은 0회. 실제 문서 수와 보완 후 달력 일수를 구분한다.
- N >= 14: 7일 대 7일. 2 <= N < 14: floor(N/2)일 대 같은 일수. N < 2: 비교 기간 부족.
- 홀수 길이에서 남는 가장 오래된 하루는 비교에서만 제외하고 전체 통계에는 포함한다.
- 직전 평균이 0이면 변화율은 null이고 상황 설명을 별도 제공한다.
- CSV 원본을 수정하지 않는다. 실제 CSV 요약 미리 계산은 이번 계획 작성 범위에 없다.
- 비밀 키는 백엔드에만 두고 Git·브라우저·로그에 노출하지 않는다.
- 최초 작성은 계획 전용이었다. 단계 0·1 완료 후 사용자가 단계 2·3·4의 구현·실연동·배포 검증을 승인했다. 보너스는 계속 제외한다.

## Review Focus

- 같은 날짜 동시 추가: 한 요청만 생성되고 나머지는409여야 한다. Task 2에서 원자적 create 충돌 검증.
- CSV 후반 오류·BOM·중복: 잘못된 파일로 일부만 쓰지 않아야 한다. Task 3에서 쓰기0회 검증.
- 메모·AI 답변의 HTML/지시문: 화면에서 실행되지 않고 상위 지침으로 승격되지 않아야 한다. Task 6/8 검증.
- 채팅 중 삭제·동시 저장: 없는 대화를 되살리거나 메시지를 잃지 않아야 한다. Task 4/6 검증.
- 204·422·지연·0 기준값: 파싱 오류, 영구 로딩, null의 0% 표시가 없어야 한다. Task 7/8 검증.

---

## 실행 방식과 Git 범위

Git 루트는 `/Users/choijimin/dev/active/codyssey`, 과제 경로는 `M1-2/`다. 별도 git init을 하지 않는다.
실행 시 using-git-worktrees 스킬로 기존 작업 공간을 확인하거나 `codex/story-analytics-assistant` 브랜치의 격리 공간을 준비한다.
미커밋 SPEC·CSV·이 계획을 보존하고 새 작업 공간에 없으면 복사한다. 아래 경로는 해당 공간의 `M1-2/` 기준이다. 다른 과제 폴더는 수정·스테이징하지 않는다.

사용자가 병렬 구현을 지정했으므로 SDD의 기본 직렬 규칙 대신 **파일 소유권이 겹치지 않는 작업만 병렬화**한다. 작업별 보고·독립 리뷰·진행 원장은 유지한다.

- 총괄: 공통 계약, 요약, 채팅, 통합, 원장 관리. 공통 main/models/ports/dependencies/config와 백엔드 의존성 파일을 전담한다.
- A: 데이터·대화 저장소/API와 CSV. B: 프론트와 브라우저 검증. C: 배포 문서와 독립 리뷰.
- 작업마다 새 에이전트에 필요한 명세 발췌·파일 소유권·인터페이스·검증 명령을 전달한다. 재위임은 금지한다.
- 총괄 포함 최대4개 활성 슬롯. 완료된 구현 에이전트가 종료된 뒤 새 리뷰어를 배정한다. 자신의 구현을 독립 리뷰하지 않는다.
- 공유 체크아웃에서 에이전트는 commit/stage하지 않는다. 총괄이 작업별 정확한 파일만 순차 커밋한다.
- 리뷰에는 작업별 파일 diff와 기준 커밋을 전달한다. 다른 병렬 변경을 섞지 않는다.
- 다른 담당 파일은 수정하지 않는다. 공통 인터페이스 변경은 총괄에게 요청한다.
- 실행 시작 시 SDD workspace와 progress 원장에 체크박스, 테스트 결과, 리뷰, 외부 의존성, 판단 변경을 기록한다.
- 키·권한 미준비 시 해당 외부 검증만 대기로 표시하고 독립 작업을 계속한다. fake 성공을 실연동 성공으로 보고하지 않는다.

## 병렬 순서와 사용자 준비

| 단계 | 총괄 | A | B | C | 사용자 준비 |
| --- | --- | --- | --- | --- | --- |
| 0 | Task 1 계약·기반 | 대기 | 대기 | 대기 | Firebase·OpenAI 준비 시작 |
| 1 | Task 5 요약 | Task 2 데이터 API | Task 7 화면 | Task 9 배포 파일·문서 | Firestore·키 로컬 설정 |
| 2 | 리뷰·통합 | Task 3 CSV → Task 4 대화 | Task 7 마무리 | 완료 작업 독립 리뷰 | GitHub·Render·Vercel 준비 |
| 3 | Task 6 채팅 | 담당 결함 수정 | Task 8 준비 | 작업 리뷰 | 외부 연결 준비 완료 |
| 4 | Task 8 통합 완료 후 Task 10 | 필요 수정 | 통합 검증·필요 수정 | 최종 독립 리뷰 | 로그인·연결 승인·환경 변수 |

Task 8 전체 시나리오는 Task 2/4/5/6/7 완료 후 실행한다. Task 9는 설정 초안까지 병렬 가능하며 실제 배포는 Task 10에서 수행한다.

| 사용자 준비 | 필요한 상태 | 이것이 없으면 대기하는 작업 |
| --- | --- | --- |
| Firebase | 과제용 프로젝트 ID, Firestore, 서비스 계정 JSON 또는 로컬 키 경로 | Task 10 실제 저장·CSV 가져오기 |
| OpenAI | API 사용 가능한 키·결제 상태, 접근 가능한 모델명 | Task 10 실제 GPT 호출 |
| GitHub | 저장소·인증·코드 반영 권한 | Task 10 push·서비스 연결 |
| Render/Vercel | 로그인·저장소 연결·환경 변수 등록 가능 | Task 10 배포 |

키를 채팅에 붙여넣게 하지 않는다. .env.example과 비밀 제외 규칙을 먼저 제공하고 사용자가 실제 값을 입력한다.
실제 DB 적재와 공개 배포는 실행 당시 승인 범위와 대상 프로젝트를 확인한다. 준비 전에도 로컬 구현·fake 검증은 완료할 수 있다.

## 파일 구조와 공통 계약

```text
backend/
  requirements.txt, requirements-dev.txt, .env.example
  app/__init__.py, main.py, config.py, models.py, ports.py, dependencies.py
  app/data/{repository,service,router}.py
  app/conversations/{repository,service,router}.py
  app/summary/{service,router}.py
  app/chat/{gateway,service,router}.py
  scripts/import_csv.py
  tests/conftest.py, fakes.py, test_*.py
frontend/
  index.html, styles.css, config.example.js
  js/{api,app,data,summary,chat,conversations}.js
  scripts/build.mjs
  tests/{api,build}.test.mjs, e2e.spec.js, playwright.config.js
  package.json
render.yaml, frontend/vercel.json, .gitignore, README.md
docs/deployment-checklist.md, docs/screenshots/
```

models.py: SPEC §4~6의 Record/RecordCreate/RecordUpdate, Message/MessageInput, Conversation/ConversationCreate/ConversationListItem, Summary, ChatRequest/ChatResponse.
API 날짜는 ISO 문자열, Python 내부 Record.date는 date, 서버 시각은 UTC datetime. Summary JSON 속성은 SPEC을 따른다.
MessageInput은 role/content만 받으며 created_at은 서버에서 부여한다. 알 수 없는 입력 필드는 거절한다.

ports.py의 동기 인터페이스:
- `DataRepository.list_records() -> list[Record]`
- `DataRepository.create(record: RecordCreate) -> Record`
- `DataRepository.update(record_id: str, patch: RecordUpdate) -> Record`
- `DataRepository.delete(record_id: str) -> None`
- `ConversationRepository.create(payload: ConversationCreate) -> Conversation`
- `ConversationRepository.list_conversations() -> list[ConversationListItem]`
- `ConversationRepository.get(conversation_id: str) -> Conversation`
- `ConversationRepository.append_turn(conversation_id: str, question: str, answer: str) -> Conversation`
- `ConversationRepository.delete(conversation_id: str) -> None`
- `ChatGateway.complete(system: str, messages: list[MessageInput]) -> str`

공통 예외 DuplicateRecord/NotFound/StorageUnavailable/GenerationUnavailable은 각각409/404/503/502로 변환한다.
dependencies.py: `get_data_repository()`, `get_conversation_repository()`, `get_chat_gateway()`. 테스트는 dependency_overrides로 fake 주입.
동기 SDK는 동기 def 라우트로 호출한다. `main.create_app() -> FastAPI`는 키 없이 생성되며 실클라이언트는 의존성을 처음 사용할 때 구성한다.

## Task 1: 테스트 가능한 API 기반과 공통 계약

**Owner/Dependencies:** 총괄, 선행 작업.
**Files:** Create `backend/app/{__init__,main,config,models,ports,dependencies}.py`, `backend/requirements.txt`, `backend/requirements-dev.txt`, `backend/.env.example`, `backend/tests/{conftest,fakes,test_contract}.py`, `.gitignore`.
**Interfaces:** Consumes SPEC §3/4/6/9. Produces 위 모델·포트·의존성 함수·create_app.

- [x] venv와 테스트 의존성을 준비하고 호환 버전을 고정한다. 비밀·venv·빌드 결과·임시 파일을 Git에서 제외한다.
- [x] `test_record_validation`: value=-1/true/1.5/"1", 잘못된 날짜, 추가 필드는 거절하고 memo 생략은 빈 문자열. `test_app_without_secrets`: 키 없이 /docs=200을 기대하는 테스트 작성.
- [x] backend에서 `python -m pytest tests/test_contract.py -q` 실행. 기능 미구현으로 FAIL인지 확인한다.
- [x] 모델·포트·fake·create_app·오류 처리·ALLOWED_ORIGINS 구현. value는 strict int, 날짜는 유효한 YYYY-MM-DD만 허용. 이후 라우터 등록도 총괄이 담당한다.
- [x] 같은 명령으로 PASS 확인. 허용/불허용 출처의 프리플라이트 응답도 검증한다.
- [x] 독립 리뷰 후 해당 파일만 `chore: establish API contracts and test foundation`으로 커밋한다.

## Task 2: 일별 데이터 CRUD

**Owner/Dependencies:** A, Task 1 이후. Task 5/7/9와 병렬.
**Files:** Create `backend/app/data/{__init__,repository,service,router}.py`, `backend/tests/test_data_api.py`, `backend/tests/test_data_repository.py`.
**Interfaces:** Consumes DataRepository/Record. Produces `FirestoreDataRepository(client)`, `DataService(repo)`의 list_records/create/update/delete(포트와 동일 서명), router.

- [x] `test_data_crud`: POST=201, id=date, 중복=409, PUT 후 값 반영, DELETE=204, 삭제 후 PUT=404, 목록 날짜 오름차순을 검증한다.
- [x] backend에서 `python -m pytest tests/test_data_api.py tests/test_data_repository.py -q`로 RED 확인.
- [x] data 컬렉션 연결 구현. document.create로 원자적 추가, 기존 문서는409. 수정은 upsert하지 않고 날짜 변경을 거절한다.
- [x] `test_atomic_duplicate`: SDK AlreadyExists를 모의하여409 확인. 저장 장애는 비밀 없는503으로 변환. 같은 명령으로 PASS 확인.
- [x] 총괄의 라우터 등록과 독립 리뷰 후 `feat: implement daily reading data CRUD`로 커밋한다.

## Task 3: CSV 초기 가져오기

**Owner/Dependencies:** A, Task 2 이후.
**Files:** Create `backend/scripts/{__init__,import_csv}.py`, `backend/tests/test_import_csv.py`.
**Interfaces:** Consumes DataRepository. Produces `parse_csv(path: Path) -> list[RecordCreate]`, `import_records(records: list[RecordCreate], repo: DataRepository) -> ImportResult`. ImportResult: created/skipped 정수.

- [x] 합성 CSV 테스트: BOM, 마지막 행 오류, 중복 날짜. 전체 검증 실패 시 `repo.create.call_count == 0`. 재실행 created=0, 기존 값 보존.
- [x] backend에서 `python -m pytest tests/test_import_csv.py -q`로 RED 확인.
- [x] utf-8-sig로 읽고 CSV의 정수 표현만 int 변환한다. 전체 검증 후 저장하며 DuplicateRecord만 skip. 통신 실패는 비정상 종료하고 완료 건수를 보고해 재실행 가능하게 한다.
- [x] `python -m scripts.import_csv --file ../moriai_daily_book_views_120days.csv --dry-run`은 형식·건수만 확인하고 집계·쓰기를 하지 않게 한다. 테스트 PASS 확인.
- [x] 독립 리뷰 후 `feat: import validated CSV without overwriting records`로 커밋. 실DB 적재는 Task 10에서 수행한다.

## Task 4: 대화 기록 API

**Owner/Dependencies:** A, Task 2/3 이후.
**Files:** Create `backend/app/conversations/{__init__,repository,service,router}.py`, `backend/tests/test_conversations.py`.
**Interfaces:** Consumes ConversationRepository/대화 모델. Produces `FirestoreConversationRepository(client)`, `ConversationService(repo)`의 포트 동명 메서드, router.

- [x] `test_history_round_trip`: 생성201, 목록에 messages 없음, 상세에 messages 있음, UTC 시각, updated_at 내림차순, 삭제 후404. system 역할 수동 저장은422.
- [x] backend에서 `python -m pytest tests/test_conversations.py -q`로 RED 확인.
- [x] 생성·목록·상세·삭제와 append_turn 구현. append_turn은 트랜잭션으로 최신 messages에 한 턴을 추가하고 삭제된 문서를 다시 만들지 않는다. 삭제 경쟁은 NotFound.
- [x] `test_append_preserves_existing_turns`, `test_append_deleted_conversation`: 트랜잭션 재시도에도 기존 메시지 보존, 없는 문서는404. 같은 명령으로 PASS.
- [x] 라우터 등록과 독립 리뷰 후 `feat: persist and restore conversation history`로 커밋한다.

## Task 5: 순수 요약 계산과 API

**Owner/Dependencies:** 총괄, Task 1 이후 병렬.
**Files:** Create `backend/app/summary/{__init__,service,router}.py`, `backend/tests/test_summary.py`.
**Interfaces:** Consumes list[Record]. Produces `build_summary(records: list[Record]) -> Summary`, router. 요약 API와 채팅은 같은 함수를 쓴다.

- [x] 아래 합성 데이터 테스트 작성. 실제 CSV 요약은 미리 계산하지 않는다.

```python
def test_five_days_excludes_oldest_only_from_comparison():
    s = build_summary(records_from_values([99, 2, 4, 6, 8]))
    assert s.metrics.total == 119
    assert s.comparison.window_days == 2
    assert s.comparison.previous.average == 3
    assert s.comparison.recent.average == 7

def test_zero_baseline_is_not_zero_percent():
    s = build_summary(records_from_values([0, 4]))
    assert s.comparison.status == "zero_baseline"
    assert s.comparison.change_percent is None
    assert s.comparison.trend == "increase"
```

- [x] 같은 테스트 파일에 `records_from_values(values: list[int], start: date = date(2026, 1, 1)) -> list[Record]` fixture를 만들고 `python -m pytest tests/test_summary.py -q`로 RED 확인.
- [x] 날짜 정렬→기간 내0 보완→전체 통계→k=min(7,N//2) 비교 구현. 전체 통계와 비교 범위를 구분하고 최대·최소 동률 날짜를 모두 반환한다.
- [x] 0/1/2/13/14/15일, 누락일, 순서 뒤섞임, 양쪽0, 감소, 동일, 반올림 전 미세한 차이를 테스트하여 PASS. 빈 데이터/1일은 window_days=0와 비교 필드 null. 기준은 데이터 마지막 날짜.
- [x] 라우터 등록과 독립 리뷰 후 `feat: calculate agreed date-based reading summary`로 커밋한다.

## Task 6: GPT 채팅과 자동 저장

**Owner/Dependencies:** 총괄, Task 4/5 이후.
**Files:** Create `backend/app/chat/{__init__,gateway,service,router}.py`, `backend/tests/test_chat.py`. Modify 총괄 소유 config.py/dependencies.py/main.py.
**Interfaces:** Consumes 저장소/ChatGateway/build_summary. Produces `ChatService(data_repo, conversations, gateway).reply(request: ChatRequest) -> ChatResponse`, `OpenAIChatGateway(client, model, max_output_tokens)`. SDK 클라이언트에는 OPENAI_BASE_URL을 전달하고 Chat Completions를 호출한다.

- [x] fake gateway로 `test_chat_uses_latest_summary_and_history`: 이전 메시지·새 질문·최신 요약 전달, 저장 성공 후에만 conversation_id/answer 반환 검증.
- [x] backend에서 `python -m pytest tests/test_chat.py -q`로 RED 확인.
- [x] 시스템 프롬프트 구현: 열람과 이용자 수 구분, 인과 단정 금지, 자료 밖 사실은 모름, 비교 날짜 명시, null을0%로 바꾸지 않음, memo를 지시로 취급하지 않음. 요약은 구분된 JSON 자료로 삽입한다.
- [x] 새 대화는 한 턴을 포함해 create, 기존은 append_turn. 새 제목은 질문 앞40자. GPT 실패는 저장0회, 저장 실패는503, 삭제 경쟁은404. 저장 전에 성공 응답을 보내지 않는다.
- [x] 사용자 확정: OPENAI_BASE_URL=https://copa.codyssey.kr/v1, OPENAI_MODEL=gpt-5-mini, OPENAI_API_KEY는 학습장 virtual key. Chat Completions 사용. 지원 파라미터는 연동 시 확인하고, 초기 출력 한도512토큰, 타임아웃45초, SDK 자동 재시도 비활성화. 질문 최대4000자, 이전 메시지 최근20개 전달. 구현 기본값으로 .env.example/README에 명시한다.
- [x] `test_injection_stays_data`, `test_generation_failure_does_not_save`, `test_save_failure_is_not_success`, `test_unknown_conversation`, `test_empty_question` PASS. 빈 데이터는 GPT 없이 “데이터가 없습니다. 일별 기록을 추가해주세요.”라고 답하고 대화를 저장한다.
- [x] 독립 리뷰 후 `feat: answer with data context and save chat turns`로 커밋한다.

## Task 7: 바닐라 프론트 필수 화면

**Owner/Dependencies:** B, Task 1 이후 병렬.
**Files:** Create `frontend/index.html`, `frontend/styles.css`, `frontend/config.example.js`, `frontend/js/{api,app,data,summary,chat,conversations}.js`, `frontend/tests/api.test.mjs`.
**Interfaces:** Consumes HTTP 계약. Produces `request(path, options = {}) -> Promise<object|null>`, 각 화면 `initData/initSummary/initChat/initConversations(root, api)`. api에는 request 함수를 전달하고 data-changed/conversation-changed CustomEvent로 변경을 알린다.

- [x] fetch 대체 테스트: 204→null, 422→detail을 가진 Error, 통신 실패→Error. 과제 폴더에서 `node --test frontend/tests/api.test.mjs`로 RED 확인.
- [x] API 헬퍼 구현 후 PASS. window.APP_CONFIG.API_BASE_URL을 읽고 없으면 명확한 오류를 표시한다.
- [x] 데이터 추가·목록·횟수/메모 수정·삭제, 요약, 대화 목록·복원·삭제, 채팅·새 대화 구현. 외형만 따라 하는 단위 테스트는 만들지 않는다.
- [x] 질문·memo·답변은 textContent로 표시. 전송 중 버튼 비활성화,10초 후 지연 안내, 종료 시 로딩 해제. 자동 재전송 없음. API 타임아웃60초로 서버보다 먼저 정상 응답을 끊지 않는다.
- [x] 저장 성공 후 목록/요약 갱신. null은 “계산 불가”와 message로 표시하고0과 구분. 날짜 수정UI 없음. 합성 fixture를 운영 fallback으로 쓰지 않는다.
- [x] 안정된 입력 label·버튼 role 제공. 독립 리뷰 후 `feat: build required vanilla web interface`로 커밋한다.

## Task 8: 화면·API 통합 검증

**Owner/Dependencies:** B, Task 2/4/5/6/7 후. 테스트 준비는 선행 가능.
**Files:** Create `frontend/tests/e2e.spec.js`, `frontend/tests/playwright.config.js`, `backend/tests/test_flow.py`. Modify 발견한 결함이 있는 Task 7 소유 파일만.
**Interfaces:** Consumes create_app/fake 의존성/HTTP 계약. Produces 재현 가능한 통합 검증 증거.

- [x] test_flow.py: 기록 추가→요약→채팅→복원→기록 변경→다음 채팅에 새 요약 반영. backend에서 `python -m pytest tests/test_flow.py -q`로 확인하고 실패는 담당자에게 전달.
- [x] Playwright HTTP 대체 테스트: null 표시, HTML 실행 없음,422/503 후 로딩 해제,204 삭제 후 갱신, 복원 후 같은 ID로 이어가기.
- [x] frontend에서 `npm run test:e2e`로 PASS. API 대체 테스트와 실서버 연결을 구분한다.
- [x] 로컬 FastAPI+Firestore fake+GPT fake로 브라우저 흐름을 확인한다. 요청 경로·JSON 계약,360px/일반 화면, 키보드 접근, 빈 상태를 확인한다.
- [x] 수정 후 영향받는 검증만 재실행. 독립 리뷰 후 `test: verify required end-to-end flows`로 커밋한다.

## Task 9: 배포 파일과 문서 준비

**Owner/Dependencies:** C, Task 1 이후 병렬. 실제 배포는 하지 않는다.
**Files:** Create `frontend/scripts/build.mjs`, `frontend/tests/build.test.mjs`, `frontend/package.json`, `render.yaml`, `frontend/vercel.json`, `README.md`, `docs/deployment-checklist.md`. .gitignore 변경은 총괄에게 요청.
**Interfaces:** Consumes 프론트 소스/API_BASE_URL. Produces frontend/dist와 config.js의 `window.APP_CONFIG = { API_BASE_URL }`.

- [x] 빌드 테스트: 공개 설정에는 API_BASE_URL만 포함, 가짜 OPENAI_API_KEY가 있어도 출력에 없음, API_BASE_URL 누락 시 실패.
- [x] 과제 폴더에서 `node --test frontend/tests/build.test.mjs`로 RED 확인.
- [x] Node로 HTML/CSS/js/config를 dist에 출력. 설정은 JSON.stringify로 직렬화. package.json에 build·단위 테스트·Playwright E2E 명령을 정의한다.
- [x] Git 루트 기준 Render 경로 M1-2/backend, Vercel 경로 M1-2/frontend. Render 시작 `uvicorn app.main:app --host 0.0.0.0 --port "$PORT"`. Vercel build `npm run build`, 출력 dist. 서비스 설정 파일 위치·스키마는 구현 시 공식 문서로 확인한다.
- [x] 같은 테스트로 PASS. README에 실행/검증/CSV 가져오기/환경 변수/출력 제한/지연 안내 작성. 없는 URL·스크린샷은 미완료 표시. 비밀키·원본 CSV는 프론트 dist에 포함하지 않는다.
- [x] 독립 리뷰 후 `build: prepare deployment and runtime configuration`으로 커밋한다.

## Task 10: 실제 연동·배포·제출 증거

**Owner/Dependencies:** 총괄, Task 8/9 완료 및 필요한 사용자 준비 후.
**Files:** Modify README.md, docs/deployment-checklist.md. Create `docs/screenshots/{chat-summary,data-management,conversation-history}.png`.
**Interfaces:** Consumes 서비스 인증·배포 대상. Produces 검증한 URL·스크린샷·최종 상태.

- [x] 키를 출력하지 않고 준비 상태 확인. 미준비 서비스만 대기하며 나머지 검증은 계속한다.
- [x] Firebase 대상 확인 후 CSV dry-run과 적재. 빈 DB 기준 created=120, 재실행 created=0/skipped=120 확인. 기존 기록은 차이를 보고하고 강제 덮어쓰기하지 않는다.
- [x] 실제 Firestore/GPT로 소수 질문을 보내 근거·복원·최신 데이터 사용 확인. 파괴적 테스트는 fake에서 수행하고 원본을 임의 수정하지 않는다.
- [x] GitHub 반영→Render /docs→Vercel 배포→API_BASE_URL/CORS 최종 연결. 승인 필요한 외부 작업은 준비된 구체적 변경을 제시한다.
- [x] 배포URL에서 채팅·데이터 조작·복원·지연 안내 확인 후 스크린샷3점과 실제URL 기록. 시연용 기록은 원본과 겹치지 않게 만들고 정리해 기존 상태를 복원한다.
- [x] 독립 최종 리뷰로 SPEC 전체·diff·테스트 증거 대조. 중요 미해결 결함은 완료 처리하지 않는다. 변경이 없으면 같은 테스트를 반복하지 않는다.
- [x] `docs: record deployment and submission evidence`로 커밋하고 로컬·실연동·배포 결과를 구분해 보고한다.

## 계획 자기 검토와 재개 기준

- SPEC §1/3/9→Task 1/9/10, §2/4→Task 2/3/4, §5→Task 5, §6→Task 1/2/4/5/6, §7→Task 6, §8→Task 7/8, §10→각 테스트와 Task 10.
- Review Focus 다섯 조건에 담당 검증을 배정했다. count는 실제 문서 수이고 calendar_days는 일수다.
- 공통 함수·모델은 한곳에서 정의하며 후속 작업은 같은 계약을 사용한다.
- 문자 수·타임아웃 등 구현 기본값은 사용자 확정 요구와 구별했다. 새로운 제품 기능은 추가하지 않는다.
- 2026-10-26: 단계 0 / Task 1 완료. 계약 테스트 28개 PASS, 독립 리뷰 PASS. Python 3.13에서 검증했으며 3.10 실행은 미검증. Task 2 이후, 실데이터 집계·DB 쓰기·배포는 미실행.

## 외부 설정 후속 반영 (2026-10-26)

Firebase 프로젝트는 story-analytics-assistant. Firestore와 로컬 서비스 계정 JSON은 사용자가 준비 완료했다고 알렸다. 키 경로와 virtual key는 backend/.env에 설정한다. Base URL과 모델은 .env.example에 반영했으며 실제 호출은 아직 하지 않았다. Task 6은 위 Chat Completions 계약을 따른다.

## 단계 1 완료 (2026-10-26)

Task 2/5/7/9 완료. 백엔드65개·프론트15개 테스트 PASS, 정적 빌드 성공. 독립 리뷰 PASS. 합성 데이터로 데스크톱/360px 화면을 확인했다. 삭제·불러오기 경쟁 오류는 회귀 테스트로 수정했다. CSV 가져오기(Task3), 대화 API(Task4), AI 채팅(Task6), 전체 통합(Task8), 실제 배포(Task10)는 미실행이다.

## 단계 2~4 실행 중 확인한 변경

Copa 게이트웨이는 reasoning_effort를 허용하지 않는다. 실제 요약 질문은 초기512토큰을 추론에 모두 사용하여 빈 응답(length)이 발생했고, 2048 한도에서907토큰·정상종료로 확인했다. 따라서 출력 기본 한도를2048로 조정하고45초·재시도0회는 유지한다. 이 검증 결과가 Task6의 초기512 설정보다 우선한다. 실제 적재120개/재실행120개 건너뛰기 완료. 최종 배포·증거는 작업 보고서를 따른다.

## 최종 완료

단계2·3·4 완료. 백엔드113/프론트단위15/HTTP대체브라우저12/로컬API브라우저2 통과. 실제CSV120적재 및 재실행보존, 실제GPT저장·복원·최신데이터 반영, main반영·공개Render/Vercel검증·스크린샷3점 완료. 상세는 docs/stages-2-4-report.md. 보너스 제외 유지.
