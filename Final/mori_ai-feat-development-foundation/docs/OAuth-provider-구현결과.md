# OAuth provider adapter 구현 결과

2026-10-16, Orca Task `task_11f92bb7ef9f`, Dispatch `ctx_1b3e29051b8f`의 제공자 adapter 부분만 수행했다.

## 변경 파일과 구현

- `backend/auth/oauth_providers.py`: `authorization_url`, async `exchange_identity`, 일반 `OAuthProviderError` 구현.
- `backend/tests/test_oauth_providers.py`: Google/Kakao MockTransport 검사 80개.
- `docs/OAuth-provider-구현결과.md`: 이 보고서.

실제 Task1의 frozen `OAuthIdentity`를 import하며 stub을 만들지 않았다. Settings의 SecretStr은 `get_secret_value()`로만 사용한다. 제공자별 고정 HTTPS endpoint, form POST code 교환, Bearer header 프로필 조회, 요청별 timeout 10초와 redirect 비활성화를 적용했다. 재시도 loop나 SDK를 추가하지 않았다.

Google은 `openid profile`만 요청하고 sub를 비어 있지 않은 최대 255자 문자열로 검증한다. Kakao는 bool/float/string을 제외한 양의 int id만 받아 문자열로 바꾼다(최대 255자). 이름은 name/nickname에서 선택하며 누락·잘못된 타입·공백이면 '사용자', 최대 100자다. 이메일 권한·refresh·토큰 저장을 추가하지 않았다.

토큰은 비어 있지 않은 문자열 최대 16KiB이며 header에 들어갈 수 없는 공백·제어문자·비ASCII는 거부한다. token/userinfo 모두 decoded body를 stream으로 읽어 1MiB를 넘으면 중단하고 닫는다. HTTP 실패·redirect·timeout·비정상 JSON·배열/null·provider error·식별자 누락은 같은 일반 예외가 된다. upstream 예외 handler 밖에서 새 오류를 발생시켜 `__cause__`와 `__context__`도 남기지 않는다.

## 실제 실행 기록

기존 locked `mori-ai:verify-tests` 이미지와 backend read-only bind mount만 사용했다. host 의존성 설치는 하지 않았다. 외부 호출을 막기 위해 Docker `--network none`을 사용했다.

RED — 구현 파일 생성 전:

```text
docker run --rm --network none -v "$PWD/backend:/app/backend:ro" mori-ai:verify-tests python -m pytest -q backend/tests/test_oauth_providers.py
ModuleNotFoundError: No module named 'backend.auth.oauth_providers'
60 errors in 0.81s
exit 1
```

최초 구현 후 중간 검사에서 `18 failed, 42 passed in 0.50s`를 관찰했다. 오류 traceback의 호출 소스 행에 테스트 자체의 literal `code-marker`가 들어가 민감정보 assertion이 실패한 것이었다. 호출 인자로 변수를 사용하도록 테스트를 수정하고, 예외의 cause/context가 실제로 None인지 직접 검사했다. 수정 후 `60 passed in 0.30s`였다.

양쪽 제공자 오류 행렬과 실제 AsyncByteStream 조기 중단 검사를 확장한 최종 GREEN:

```text
docker run --rm --platform linux/amd64 --network none -v "$PWD/backend:/app/backend:ro" mori-ai:verify-tests python -m pytest -q backend/tests/test_oauth_providers.py
........................................................................ [ 90%]
........                                                                 [100%]
80 passed in 0.38s
exit 0
```

고정 endpoint/form/timeout/header, Kakao 선택 secret, 이름 fallback/절단, subject/id 타입·길이, token 길이·타입, 양쪽 제공자의 token/profile 4xx·5xx·redirect·timeout·invalid JSON·wrong shape·oversize·error, 예외 상세 미노출을 검증했다. 1MiB 경계는 수용하며 Content-Length 없는 초과 스트림은 64KiB chunk 17개에서 멈추고 close됨을 확인했다. 주입 client에 follow_redirects=True를 설정해도 adapter가 redirect를 따라가지 않음을 확인했다.

`git diff --check -- backend/auth/oauth_providers.py backend/tests/test_oauth_providers.py`는 exit 0이었다. 전체 DB/HTTP/화면 회귀는 총괄 통합 검증 범위이며 여기서는 실행하지 않았다. 실제 Google/Kakao token/userinfo 요청·브라우저 로그인·자격증명 유효성 검증은 미실행이다.

## 공식 근거와 남은 작업

[Google 웹 서버 OAuth](https://developers.google.com/identity/protocols/oauth2/web-server)의 code form 교환·Bearer 사용과 [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect)의 sub 식별자 및 userinfo endpoint를 확인했다. [Kakao REST 로그인](https://developers.kakao.com/docs/ko/kakaologin/rest-api)의 인가·토큰·사용자 정보 endpoint, 선택 client_secret 및 Bearer 프로필 조회를 확인했다.

기존 `moriai` 원본 코드 이식은 없다. `.env`와 기존 저장소를 읽지 않았고, root 공통 파일·Git·의존성·모델·schema·route는 수정하지 않았다. 계약 변경은 없으며 지정된 공개 함수와 예외를 제공한다. 남은 작업은 service/HTTP 합류, 총괄의 전체 회귀·독립 리뷰와 실제 제공자 로그인 검증이다.
