# OAuth 로그인 화면 구현 결과

2026-10-16, 승인 OAuth 계획 Task3 frontend. 이 기록은 frontend 독립 검증이며 root의 fresh runtime 합류 검증 전이다.

## 변경

- `frontend/src/features/auth/AuthGate.tsx`: 공개 `/api/v1/client-config` 조회, 로딩·오류·재시도·빈 provider 안내, 설정된 Google/Kakao만 페이지 이동 링크 제공. 기존 `/me`·쿠키·CSRF·동의·개발 로그인·사용자 소유권 및 로그아웃 초기화 호출 유지. 성공 세션 확인 후 URL의 `auth_error`를 제거한다.
- `frontend/src/features/auth/oauth.ts`: 복귀 경로 allowlist, provider 필터, 공개 오류 enum의 고정 한국어 문구.
- `frontend/src/api/types.ts`: `AuthProvider = 'google'|'kakao'`, `Config.auth_providers: AuthProvider[]` 추가. 런타임 누락·잘못된 목록은 빈 배열로 처리한다.
- `frontend/src/api/session.ts`, `frontend/tests/session_reset.test.mjs`: coordinator의 편집 범위 확장 승인 후 공개 단일키 client-config 조회 보존. 사용자별 client-config 캐시는 계속 제거한다.
- `frontend/tests/oauth_login.test.mjs`: helper 4개와 선택 ReactDOMServer 렌더 검사 2개.

OAuth 이동 후 메모리 draft 복원을 약속하지 않으며 미저장 입력 유실 가능성을 로그인 링크 아래 표시한다. raw 오류·URL·토큰·secret은 오류 문구에 사용하지 않는다. provider 조회 실패는 기존값이 있어도 링크를 숨기고 재시도를 제공한다.

## 공개 helper 인터페이스 및 검사 연결

```ts
oauthLoginUrl(provider: AuthProvider, returnTo?: string): string
oauthErrorMessage(search: string): string
oauthProviders(value: unknown): AuthProvider[]
```

기본 returnTo는 `/albums`. 허용 값은 `/albums` 또는 `/albums/UUID/edit|progress|review|view`이며 query/hash 및 다른 경로는 `/albums`로 대체한다. 알 수 없는 provider는 throw한다.

Node 테스트의 `argv[2]`는 tsc로 컴파일한 oauth 모듈 URL이고, 선택 `argv[3]`은 AuthGate ESM bundle URL이다. 후자는 `OAuthLoginOptions` export를 실제 ReactDOMServer로 렌더하며 React 의존성은 external로 공유한다. root에 Dockerfile 검사 연결을 요청했고 연결 완료 응답을 받았다. Dockerfile 자체는 편집·조회하지 않았다.

기존 `mori-ai:gen-frontend-check` 이미지 `/build`에서 실행한 핵심 명령:

```sh
node_modules/.bin/tsc src/features/auth/oauth.ts --outDir /tmp/oauth --module es2022 --target es2022 --skipLibCheck
cp /tmp/oauth/features/auth/oauth.js /tmp/oauth.mjs
node_modules/.bin/esbuild src/features/auth/AuthGate.tsx --bundle --platform=node --format=esm --packages=external --jsx=automatic --outfile=/build/auth-gate.mjs
node tests/oauth_login.test.mjs file:///tmp/oauth.mjs file:///build/auth-gate.mjs
node_modules/.bin/esbuild src/api/session.ts --bundle --platform=node --format=esm --packages=external --outfile=/build/session.mjs
node tests/session_reset.test.mjs file:///build/session.mjs
npm run typecheck
```

## 검증 결과

- 구현 전 empty OAuth module 및 기존 AuthGate export 대상으로 6개 모두 기능 부재로 실패(RED).
- 구현 후 OAuth helper 4개 및 실제 React 렌더 2개 모두 통과(GREEN).
- 기존 session privacy 회귀 3개와 공개 OAuth 설정 보존 회귀 1개 통과. 보존 회귀는 수정 전 취소됨(true !== false)으로 RED를 확인했다.
- frontend `tsc --noEmit` 통과.
- 테스트 추가 중 줄바꿈 사례의 문법 오류를 수정한 뒤 재실행했고 최종 검사에서는 실패 없음.
- host 의존성 설치 없음, 기존 이미지 재사용. 전체 빌드·전체 테스트·fresh backend runtime 통합·실제 OAuth 외부 redirect/계정/쿠키 검증은 root 소유로 미실행.

## 통합 의존성과 범위

기존 `resetSession`이 `/me` 401에서 공개 `client-config` query를 취소·제거하는 문제를 발견해 coordinator에게 보고했다. coordinator가 session.ts와 session_reset.test.mjs의 편집 범위를 명시적으로 확장하여 단일키 공개 조회만 보존하도록 보완했고 RED→GREEN을 검증했다. Task1/2 backend와 합친 fresh runtime은 이 worker의 검증 완료를 의미하지 않는다.

원본 코드 출처는 이 저장소의 기존 AuthGate·API 타입·테스트 패턴이며 기존 moriai 파일을 읽거나 이식하지 않았다. root가 고정한 공개 HTTP interface를 반영했으며 추가 계약 변경은 없다. backend/schema/root 설정/Dockerfile/lock/Git/.env는 조회·편집하지 않았다.
