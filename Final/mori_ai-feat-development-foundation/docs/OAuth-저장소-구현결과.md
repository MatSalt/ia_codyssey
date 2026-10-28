# OAuth 저장소 Task1 구현 결과

2026-10-16, 승인된 실제 OAuth 계획 Task1 작업자 범위 완료.

## 변경 파일

- `backend/auth/oauth_types.py`: frozen `OAuthIdentity(provider, subject, display_name)`. google/kakao, 문자열 subject 1~255자 검증. 표시 이름은 최대 100자, 없거나 공백뿐이면 `사용자`.
- `backend/auth/oauth_repository.py`: 계획의 `begin_login`, `consume_login`, `resolve_identity` 인터페이스와 추가 지시의 `prune_login_requests(session, now) -> int` 구현.
- `backend/tests/integration/test_oauth_repository.py`: 실제 PostgreSQL 대상 32개 검사. 별도 checkout/fixture 수정 없이 이 파일 전용 fixture에서 로그인 요청 테이블을 전후 정리한다.
- 이 보고서.

기존 서비스 원본 코드 이식 없음. `.env` 및 기존 `moriai` 읽기 없음. 공통 모델·migration·설정·Compose·Git 변경은 총괄 소유로 유지했다. 의존성 설치 및 agent spawn 없음.

## 저장소 동작과 계약

기존 `AuthIdentity(provider, provider_subject, user_id)`를 그대로 재사용한다. 계획의 새 UserIdentity 표기는 총괄 Dispatch 수정에 따라 적용하지 않았다. `OAuthLoginRequest`와 `0003_real_oauth`는 총괄이 제공했다.

로그인 요청은 SHA-256 소문자 64자리 해시만 받는다. begin에서 provider와 내부 복귀 허용목록을 검증하고 잘못된 값은 ValueError로 거부한다. 허용 경로는 `/albums`와 `/albums/{UUID}/edit|progress|review|view`이며 query/fragment/인코딩·백슬래시·제어문자 우회는 거부한다. Task2 서비스는 사용자 입력 실패를 공개 422 계약으로 변환해야 한다.

소비는 provider/state_hash/binding_hash/미소비/만료 조건을 포함한 단일 UPDATE RETURNING이다. 만료 비교는 `expires_at > greatest(now, clock_timestamp())`로 호출자 시계가 DB보다 느려도 만료를 연장하지 않고, consumed_at은 DB clock을 사용한다. 별도 DB 연결 경합에서 성공은 정확히 한 번이다. commit/rollback은 호출자 소유이며 rollback된 소비는 복구된다.

identity 생성은 provider+subject의 안정적인 SHA-256 기반 signed bigint advisory transaction lock으로 직렬화한다. 동일 identity의 경쟁 호출은 동일 User로 수렴하고 orphan User를 만들지 않는다. 기존 사용자는 row lock 후 표시 이름을 갱신하며 삭제 사용자는 `APIError(401, AUTH_REQUIRED)`로 거부하고 변경하지 않는다. 다른 제공자의 같은 subject는 별개 계정이다. 이메일은 수집·사용하지 않는다.

prune은 consumed_at 여부와 무관하게 expires_at <= now인 모든 요청을 지우고 삭제 개수를 반환한다. 스케줄러 연결은 다음 Task 소유다.

## RED → GREEN 실행 근거

명령: `bash scripts/verify-db.sh backend/tests/integration/test_oauth_repository.py`

- 초기 RED: 아직 types/model이 없을 때 `5 failed, 23 errors`. 로그 `/tmp/mori-oauth-repository-red.log`. 이는 초기 준비 부재 확인이며 동작 수준 RED로 간주하지 않는다.
- 총괄의 모델·migration 준비 통보 후 동작 RED: 저장소를 NotImplementedError stub으로 두고 `27 failed, 5 passed`. 실패는 저장소 미구현이 원인이다. 로그 `/tmp/mori-oauth-repository-behavior-red.log`.
- GREEN: 실제 PostgreSQL `17.11`, migration upgrade → downgrade base → upgrade head → Alembic check 모두 성공. `32 passed in 3.62s`, 명령 exit 0. 로그 `/tmp/mori-oauth-repository-green.log`.
- 허용 네 경로 대상 `git diff --check` exit 0.

검증 이미지는 기존 `mori-ai:verify-tests`이고 새 backend 소스를 read-only mount했다. Compose는 `/dev/null` env 및 전용 임시 DB guard를 유지하며 호스트 설치 없이 실행했다. Docker/Orca socket 접근은 elevated 도구로 수행했다. 임시 검증 프로젝트와 volume은 script가 정리했다.

검사 범위: identity 검증·동결·표시 이름, 해시 보관, 단일 소비/재사용, provider/binding/state 불일치, 만료 경계·DB clock, 서로 다른 pg_backend_pid의 소비·계정 생성 경합, orphan 없음, 제공자 분리, 삭제 계정 거부, 만료 요청 정리, 허용/위험 복귀 경로, 트랜잭션 rollback.

## 미실행과 후속 책임

전체 backend suite, make verify-install, 실제 Google/Kakao 왕복, frontend, worker 정리 스케줄러, 서비스/API 오류 변환 및 전체 독립 리뷰는 이 Task에서 실행하지 않았다. 전체 suite·최종 합류와 Git은 총괄 소유이며 Task2/3에서 연결한다. 이번 결과는 실제 PostgreSQL 저장소 검증으로, 실제 OAuth 제공자 인증 성공을 뜻하지 않는다.
