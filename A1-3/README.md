# Levelly — 영어를, 나의 속도로

하나의 영어 글을 **A1·A2·B1·B2 네 수준으로 한 번에 변환**하고, 표현 변화와 한국어 설명을 비교하는 영어 학습 코치입니다.

- 소개 / 레벨 변환 / 레벨 가이드의 3개 섹션과 메뉴 이동
- 원문 1~1,500자, 레벨별 변환문·최대 2개 표현 설명·학습 팁
- 레벨 탭은 결과를 전환할 뿐 추가 API 요청을 보내지 않음
- 반응형, 키보드 탭 조작, 로딩·입력 오류·API 오류·한도·타임아웃 안내
- 로그인·DB·저장·Jev·보너스 기능 없음

## 배포 및 저장소

- 배포 URL: https://levelly-english-coach.vercel.app
- GitHub: https://github.com/jimchoi9/codyssey-native/tree/codex/english-level-coach/A1-3
- 모노레포 프로젝트 경로: `A1-3`
- 작업 브랜치: `codex/english-level-coach` (main에 병합하지 않음). Git 연결 후 작업 브랜치 푸시는 Preview 배포를 생성하며 검증된 배포를 Production으로 승격할 수 있습니다.

## 기술 스택과 구조

프론트는 순수 HTML/CSS/JavaScript입니다. 백엔드는 `api/rewrite.py`의 Python Flask 앱이며 Vercel Function으로 실행합니다. Flask는 서버 라우팅에만 쓰며 React/Vue 등 프론트 프레임워크는 사용하지 않습니다. Gemini API는 Python 표준 라이브러리의 HTTP 클라이언트로 호출합니다.

```text
public/index.html           세 섹션과 입력·결과 화면
public/css/style.css        반응형 스타일
public/js/app.js            fetch, 상태 관리, 레벨 탭, 안전한 텍스트 표시
api/rewrite.py              Python HTTP 엔드포인트
services/coach.py           입력·응답 검증, 프롬프트, Gemini 호출
requirements.txt           Python 의존성
pyproject.toml              Python 버전과 Vercel entrypoint
vercel.json                 실행 시간과 응답 보안 헤더
.env.example                값 없는 환경 변수 예시
 tests/                     Python 및 브라우저 테스트
 docs/service-plan.md       제출용 기획서
 docs/verification.md       확인 결과와 제한
 docs/evidence/             화면·AI 도구 사용 증빙
```

## 로컬 실행

Python 3.12 이상이 필요합니다. 명령은 `A1-3` 디렉터리에서 실행합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env.local
```

`.env.local`을 에디터로 열고 **본인의 Gemini API 키**를 입력합니다. 키를 프론트 코드·채팅·스크린샷에 넣지 마세요.

```dotenv
GEMINI_API_KEY=발급받은_키
GEMINI_MODEL=gemini-3.5-flash-lite
```

[Google AI Studio](https://aistudio.google.com/apikey)에서 키를 발급받고 해당 프로젝트가 무료 구간인지 확인합니다. 키 문자열만으로 무료/유료 여부를 앱이 판별할 수는 없습니다. 모델은 계정에서 무료 사용 가능한 모델을 설정하며 유료 전환·다른 모델 폴백은 하지 않습니다.

```bash
python -m flask --app api.rewrite:app --env-file .env.local run --port 4173
```

브라우저에서 http://127.0.0.1:4173 에 접속합니다. 환경 변수를 변경하면 서버를 재시작합니다. `index.html`을 파일로 직접 열거나 정적 서버만 실행하면 Python API가 동작하지 않습니다.

## 테스트

```bash
.venv/bin/python -m unittest discover -s tests -v
```

외부 API는 mock으로 대체하므로 키나 네트워크 없이 입력 경계, 네 레벨 응답, API 실패, HTTP 계약을 검증합니다.

브라우저 테스트는 로컬 서버가 켜진 상태에서 별도 터미널로 실행합니다. Node.js 및 npm이 필요합니다. 프론트 실행에는 npm 빌드가 필요하지 않습니다.

```bash
npm install
npx playwright install chromium
npm test
```

`TEST_URL`로 검사 URL, `CHROME_PATH`로 설치된 Chrome 실행 파일을 지정할 수 있습니다. 브라우저 테스트의 API 응답은 테스트용으로 대체되며 실제 AI 품질 증빙이 아닙니다. 실제 호출 증빙과 품질 검토는 `docs/verification.md`에 구분해 기록합니다.

## GitHub → Vercel 배포

1. GitHub 저장소에 코드를 커밋·푸시합니다.
2. Vercel에서 저장소를 Import하고 **Root Directory를 `A1-3`**로 지정합니다.
3. Flask 프리셋을 사용합니다. `pyproject.toml`의 `api.rewrite:app`을 진입점으로 사용하고 `public/` 정적 파일을 제공합니다.
4. Vercel 환경 변수에 `GEMINI_API_KEY`, `GEMINI_MODEL`을 등록합니다. Production과 테스트할 Preview 환경을 확인합니다.
5. 배포 후 로그인하지 않은 브라우저에서도 접속 가능한지 확인합니다. 과제 평가자가 Vercel 로그인 없이 접속해야 합니다.
6. 배포 URL에서 메뉴, 모바일 화면, 실제 AI 네 레벨 생성, 빈 입력·실패 안내를 확인합니다.
7. 코드 수정은 커밋·푸시 후 재배포하며 환경 변수 변경도 재배포해야 반영됩니다.

`public/`에는 공개할 프론트 파일만 둡니다. `.env.local`, Python 소스, 제출 문서가 정적 파일로 서비스되지 않도록 구분합니다.

## API

`POST /api/rewrite`에 `{"text":"영어 원문"}`을 전송합니다. 성공 시 `results` 배열에 A1·A2·B1·B2가 하나씩 들어 있습니다. 각 항목은 `level`, `rewritten_text`, `changes`, `note_ko`로 구성됩니다.

실패는 `{"error":{"code":"...","message":"한국어 안내"}}` 형식입니다. 빈 입력 400, 비영문 422, 무료 한도 429, 공급자·형식 오류 502, 지연 504를 구분합니다. 일부 레벨만 생성된 응답은 완료로 표시하지 않습니다.

## 동작 원리와 학습 포인트

- **HTML**은 메뉴·폼·결과 영역의 의미와 구조를, **CSS**는 배치·색·반응형을 담당합니다.
- **JavaScript**는 입력을 검사하고 `fetch('/api/rewrite')`로 JSON 요청을 보내며, 응답의 네 결과를 메모리에 보관합니다.
- **Python**은 서버에서 입력을 재검사하고 Gemini를 호출합니다. 브라우저는 API 키를 받지 않습니다.
- **Vercel Function**은 배포된 Python 코드를 요청에 따라 실행합니다. 로컬 Flask 실행과 동일한 앱을 사용하지만 배포 환경 변수·네트워크·실행 제한은 별도로 확인해야 합니다.
- 로컬에서 성공하고 배포에서 실패한다면 응답 코드, 환경 변수 이름, Root Directory, 진입점, 배포 로그 순서로 확인합니다. 로그에 원문이나 키를 출력하지 않습니다.
- 개발 중 실제 Gemini 출력에서 행동의 의미가 바뀌는 사례를 확인하고 프롬프트에 보존 기준과 짧은 글 예시를 보완했습니다. API 성공과 언어 품질은 별도 검사 항목입니다.

## 키 관리와 유출 대응

`.env.local`은 Git에서 제외되며 `.env.example`에는 실제 값을 넣지 않습니다. 키 유출이 의심되면:

1. Google AI Studio에서 기존 키를 즉시 폐기하고 새 키를 발급합니다.
2. 로컬·Vercel 환경 변수를 교체하고 재배포합니다.
3. 코드·문서·캡처에서 키를 제거합니다. 노출 커밋은 `git filter-repo` 등으로 이력을 정리해야 하며 공유 저장소의 강제 푸시는 협업자와 조율합니다. 단순 삭제 커밋으로 과거 노출이 사라지지는 않습니다.
4. API 사용량과 쿼터를 확인합니다.

입력은 이 앱에 저장하지 않지만 Gemini로 전송되므로 Google의 데이터 처리 정책이 적용됩니다. AI 출력은 오류가 있을 수 있으며 CEFR 정확도를 보장하지 않습니다.

## 공식 참고 문서

- [Gemini 콘텐츠 생성 API](https://ai.google.dev/api/generate-content)
- [Gemini 가격·무료 구간](https://ai.google.dev/gemini-api/docs/pricing)
- [Vercel Python 런타임](https://vercel.com/docs/functions/runtimes/python)
- [Vercel Flask 배포](https://vercel.com/docs/frameworks/backend/flask)
