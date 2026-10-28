# Google·Kakao 실제 로그인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. 사용자 지정 실행 방식은 Orca Run → Task → worker-start → 완료 보고이며 이를 유지한다.

**Goal:** 준비된 새 서비스 OAuth 앱으로 로그인하고 기존 동의·책장·업로드 흐름을 사용한다.

**Architecture:** 공통계약의 start/callback을 구현하고 서버가 제공자 토큰을 교환해 검증한 계정 식별자를 기존 사용자·세션에 연결한다. DB의 일회용 로그인 요청과 브라우저 전용 cookie를 함께 검증한다. 제공자별 identity는 분리하며 이메일 자동 병합·계정 연결은 추가하지 않는다.

**Tech Stack:** 기존 FastAPI, SQLAlchemy/asyncpg/Alembic, httpx, React/TanStack Query. 새 SDK 없이 공식 HTTPS REST endpoint를 사용하고 토큰을 브라우저로 전달하지 않는다.

**Spec:** 기능요구명세서 COM-06, docs/공통계약-v1.md 2.2·4.1·4.2, docs/설계.md 1·3·4절. 아래 구체화 사항은 이 계획의 검토 대상이다.

## 범위와 전제

- 2026-10-16 .env의 항목 존재·origin·예산·모델 일치만 출력으로 확인했다. secret 유효성·콘솔 등록 성공은 미검증이다. 값은 보고서·로그에 복사하지 않는다.
- 새 서비스 전용 앱만 사용한다. R2 연결·실제 AI 호출·배포는 이 계획 밖이며 AI_REAL_CALLS_ENABLED=false를 유지한다.
- AUTH provider 설정은 root가 Settings/Compose에 선택적으로 연결한다. 미설정 제공자만 비활성화하고 로컬 가짜 모드는 유지한다. 세션·CSRF·소유권 기존 규칙을 재사용한다.
- 직접 Python 실행에 .env 자동 로딩을 추가하지 않는다. Compose의 명시적인 필요한 OAuth 변수 전달만 추가한다. R2/OpenAI 키는 이 단계에서 컨테이너에 전달하지 않는다.
- 기존 moriai의 코드·설정·데이터는 이식하지 않는다. 공통 파일·migration·Dockerfile·Git은 총괄 단독 소유다.
- 로그인 요청 TTL 600초, 무작위 state·브라우저 바인딩 토큰 각각 32bytes 이상. DB에는 해시만 보관하고 유효 요청을 원자적으로 1회 소비한다. cookie는 HttpOnly·SameSite=Lax·Path=/, Secure는 기존 환경 정책을 따른다.
- DB 요청에는 provider·return_to·expires_at·consumed_at을 저장한다. state 원문·인증 code·provider token·secret은 저장하거나 로그에 남기지 않는다.
- 내부 복귀는 /albums, /albums/{UUID}/edit, /albums/{UUID}/progress, /albums/{UUID}/review, /albums/{UUID}/view만 허용한다. query/fragment, 외부 origin, //, 백슬래시, 제어문자·인코딩 우회는 거부한다. query 세부 상태 복원은 추가하지 않는다.
- Google은 authorization code→token→HTTPS userinfo의 sub, Kakao는 code→token→/v2/user/me의 id를 사용한다. 서명 검증 없이 ID token을 decode하여 인증하지 않는다. Google scope는 openid profile, Kakao는 기본 계정 식별자와 허용된 프로필만 사용한다. 이메일 권한은 요청하지 않는다.
- 표시 이름 누락은 '사용자', 최대 100자로 제한. 동일 provider+subject는 단일 user로 수렴하며 서로 다른 제공자의 동일 이메일은 별개다. 삭제된 기존 사용자 identity로 로그인하면 재활성화하지 않는다.
- httpx timeout 10초, 자동 retry 0, 임의 redirect 추적 금지. callback의 성공·실패 모두 no-store 및 Referrer-Policy:no-referrer. 검증 실패는 세션 발급 없이 /login?auth_error=failed, 정상 요청에서 사용자 취소는 /login?auth_error=cancelled로 이동한다. provider 상세 오류는 UI에 노출하지 않는다.
- callback 소비 후 외부 실패는 새 start로 다시 로그인한다. auth code 교환을 자동 재시도하지 않는다. 이미 로그인한 사용자의 시작 요청은 계정 전환으로 처리하고 callback 성공 시 이전 세션을 철회한다.

## Review Focus

1. 다른 브라우저가 state를 복사하거나 callback을 재전송해도 로그인되지 않는다(Task 1/2).
2. 동시 callback과 최초 로그인 경쟁에서 중복 사용자·중복 세션이 생기지 않는다(Task 1/2).
3. 제공자 취소·timeout·비정상 JSON·프로필 누락이 세션 발급이나 secret 노출로 이어지지 않는다(Task 2).
4. return_to 우회·다른 provider callback이 외부 redirect나 계정 혼동을 만들지 않는다(Task 1/2).
5. 계정 전환·로그아웃 때 이전 사용자 사진·미저장 글귀가 남지 않고 동의 화면을 우회하지 않는다(Task 3).

## Task 1: identity·로그인 요청·설정

**Files:** 총괄은 backend/models.py, backend/settings.py, backend/migrations/versions/0003_real_oauth.py(실행 전 현재 head 및 파일명 충돌 확인), compose.yaml을 소유한다. 작업자는 backend/auth/oauth_repository.py 및 backend/tests/integration/test_oauth_repository.py를 편집한다.

**Interfaces:** OAuthIdentity(provider, subject, display_name)는 backend/auth/oauth_types.py의 frozen dataclass. provider는 google/kakao, subject는 비어 있지 않은 최대 255자 문자열이다. OAuthLoginRequest는 UUID id, provider, state_hash(unique), binding_hash, return_to, expires_at, consumed_at을 갖는다. 기존 AuthIdentity(provider, provider_subject, user_id)를 재사용한다. 이미 provider+provider_subject unique 및 user_id FK를 갖고 있으므로 별도 identity 테이블은 추가하지 않는다.
- begin_login(session, provider: str, state_hash: str, binding_hash: str, return_to: str, expires_at: datetime) -> UUID.
- consume_login(session, provider: str, state_hash: str, binding_hash: str, now: datetime) -> str | None: 성공 시 허용된 return_to 반환, 그 외 None.
- resolve_identity(session, identity: OAuthIdentity) -> User: 최초 생성/재로그인 경합 수렴, 삭제된 user는 거부.

- [x] 실제 DB 검사로 같은 provider/subject 동시 생성은 user 1개, 다른 provider는 2개, 삭제 user는 거부함을 먼저 RED 확인한다.
- [x] state 만료/재사용/다른 binding/provider/동시 소비 중 성공 1회만 허용하는 검사를 RED 확인한다.
- [x] 모델·설정·migration·repository를 구현한다. secret 필드는 repr=False, callback은 APP_ORIGIN과 해당 계약 path에 정확히 일치하도록 검증한다.
- [x] 실제 DB 대상 검사와 upgrade→downgrade→upgrade→Alembic check 통과 후 총괄 commit.

## Task 2: provider adapter·start/callback

**Files:** backend/auth/oauth_types.py, oauth_providers.py, oauth_service.py, oauth_routes.py, backend/tests/test_oauth_providers.py, backend/tests/integration/test_oauth_http.py. 총괄은 backend/main.py의 router 등록 및 callback query를 제거하는 access log 설정, 공통계약·샘플의 오류/설정 응답을 소유한다.

**Interfaces:** authorization_url(settings, provider: str, state: str) -> str; exchange_identity(client: httpx.AsyncClient, settings, provider: str, code: str) -> OAuthIdentity. start_login(factory, settings, provider, return_to) -> tuple[str,str,str]: authorization URL, state, binding token. complete_login(factory, settings, provider, code, state, binding, previous_session_token: str | None) -> tuple[str,str]: 새 원문 session token, return_to.

- [x] httpx MockTransport로 token/userinfo 성공 및 timeout/5xx/invalid JSON/누락 subject/큰 응답 경계를 RED 확인한다. access token은 Authorization header로만 프로필 요청에 사용한다.
- [x] start의 미설정/미지원 provider404, 위험 return_to422, state binding cookie와 no-store를 RED 확인한다.
- [x] callback의 중복 query/state 누락·틀림·만료·다른 cookie/provider, code+error 동시 입력 거부, 취소, 세션 회전, 이전 세션 철회, provider 실패 시 새 세션0을 실제 DB 검사로 RED 확인한다.
- [x] 공식 REST 흐름과 route를 구현한다. 이전 raw token/새 token/provider token은 응답 URL에 넣지 않는다. callback query를 포함한 access log는 비활성화하거나 query를 제거하도록 bootstrap/로컬 실행 설정을 함께 검증한다. 로그인 시작/실패를 무제한 보존하지 않도록 만료 요청 정리도 추가한다.
- [x] 대상 검사 통과 후 실제 DB 전체 회귀와 검토를 진행하고 총괄 commit.

## Task 3: 화면·실제 로그인 합류

**Files:** frontend/src/features/auth/AuthGate.tsx, frontend/src/api/types.ts, frontend/tests/oauth_login.test.mjs. 총괄은 backend/http/schemas.py, docs/공통계약-v1.md·examples.json, Dockerfile의 기존 Node 검사 연결, README.md를 소유한다.

**Interfaces:** GET /api/v1/client-config에 auth_providers: Array<'google'|'kakao'>를 추가하고 샘플/타입/검사를 함께 갱신한다. 값은 secret이 아니라 설정 완료 제공자 목록이다. 기존 client-config 필드는 보존한다.

- [x] 설정된 제공자만 실제 로그인 링크를 보여주고 링크가 동일 origin의 /api/v1/auth/{provider}/start를 사용하는 Node 검사를 먼저 RED 확인한다.
- [x] 일반 로그인 화면에 두 제공자 버튼·취소/실패 안내·재시도를 연결한다. 가짜 계정은 DEV_AUTH_ENABLED인 local에만 유지한다.
- [x] OAuth는 페이지 이동으로 처리하고 기존 세션 복원·계정 변경 캐시 정리·동의 화면을 사용한다. OAuth 왕복 중 새로고침으로 미저장 글귀를 복원한다고 약속하지 않는다.
- [x] make verify-install 및 bash scripts/verify-db.sh backend/tests 통과, 독립 전체 코드 리뷰의 중요 문제 해결 후 총괄 판정·commit.
- [ ] 실제 브라우저에서 제공자별 로그인→동의→책장→로그아웃→재로그인, Google/Kakao 사용자 격리와 취소를 확인한다. 제공자 로그인 화면의 비밀번호·MFA는 사용자가 직접 입력한다.
- [ ] mock 성공과 실제 제공자 성공을 구분해 docs/실제OAuth-검증결과.md에 기록한다. 전용 QA만 정리하고 사용자 앱/계정 설정은 임의 수정하지 않는다.

## 검증 명령과 실행 방식

작업자의 최초 RED·GREEN은 필요한 경로만 기존 검증 이미지에서 실행한다. 실제 DB는 scripts/verify-db.sh의 전용 DB guard와 /dev/null Compose env를 유지해 .env가 검증 로그에 흘러가지 않도록 한다. 최종 명령은 make verify-install, bash scripts/verify-db.sh backend/tests, git diff --check다. fresh OAuth 소스가 이미지에 포함된 뒤 실행하며 기존 이미지 검사를 새 구현 성공으로 세지 않는다.

기존 승인된 Orca 감독형 실행을 유지한다. Task1→Task2→Task3 순서이며 frontend는 Task2 공개 인터페이스가 고정되면 경로 소유권을 분리해 진행할 수 있다. worker에게 .env를 읽거나 원문 값을 보고할 작업을 배정하지 않는다. 총괄이 필요한 프로세스에만 설정을 주입한다.

## 자체 검토·핸드오프

기존 계약 endpoint·세션·소유권·동의 규칙을 보존한다. 추가하는 DB identity/state 및 client-config의 공개 제공자 목록은 타입·샘플·회귀를 동반한다. 다섯 Review Focus는 Task별 검증에 배정했다. R2/AI 예산 ledger와 실제 AI 호출은 이 계획에 포함하지 않았다.

2026-10-16 사용자가 “응 착수시켜”로 검토·실행을 승인했다. Run run_e4206c698a2c에서 구현을 시작했다. 검토 대상은 위 로그인 요청 TTL/내부 복귀 허용 목록/이메일 미요청/실패 복귀 정책을 포함한다. 실행 방식은 이미 지정된 Orca를 유지한다.

공식 근거: [Google 웹 서버 OAuth](https://developers.google.com/identity/protocols/oauth2/web-server), [Kakao REST 로그인](https://developers.kakao.com/docs/ko/kakaologin/rest-api).

실행 소유권 구체화: Task1 worker는 oauth_types.py까지 소유한다. 제공자 adapter는 독립 Task로 선행 병렬화하며 해당 worker가 oauth_providers.py·단위 검사만 소유한다. HTTP/service는 저장소·adapter 고정 후 후속 Dispatch로 배정한다. frontend는 root가 고정한 auth_providers 공개 인터페이스를 소비한다. shared checkout의 공통 파일은 총괄만 편집하며 기존 사용자 .gitignore 변경은 보존한다.

최종 자동 검증: 실제 DB482/Node43/타입·빌드 통과, 독립 중요 결함0. source/검증 근거와 실제 로그인 대기 경계는 [최종 결과](../../실제OAuth-검증결과.md)를 따른다. 실제 계정 왕복과 그 후 QA 정리는 미완료로 유지한다.

사용자 후속 확인: Google/Kakao 모두 실제 로그인 성공, DB 별도 사용자2명·제공자별 동의 기록 확인. 정상 인증 경로는 확인했으나 위 실제 취소/재로그인/교차 접근의 전체 수동 조합과 QA 종료 정리는 미완료로 유지한다. 최신 근거는 최종 결과 문서의 사용자 실계정 로그인 확인 절을 따른다.
