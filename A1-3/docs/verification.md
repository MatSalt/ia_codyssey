# 검증 기록

검증일: 2026-10-06. 구현: Levelly, Gemini `gemini-3.5-flash-lite`.

## 자동 검증

- Python: `.venv/bin/python -m unittest discover -s tests -v` — **16개 통과**.
- 입력: 공백, 잘못된 타입, 1자·1,500자 경계, 1,501자 초과, 읽을 수 없는 유니코드.
- 응답: 네 레벨 누락·중복, 빈 변환문, 필수 설명 누락, 레벨별 변경 2개 초과, 불완전 JSON, 생성 중단.
- HTTP: 정상 200, 입력 400, 메서드 405, 대용량 413, 비영문 422, 제한 429, 설정 500, 공급자 502, 지연 504.
- 네트워크 중간 절단: 별도 리뷰에서 발견한 IncompleteRead·ConnectionResetError를 테스트로 재현 후 안전한 502 안내로 수정.
- `node --check public/js/app.js` — 통과.
- Playwright/Chrome: 390·768·1440px 가로 넘침 없음, 샘플·빈 값·길이 검사, 네 탭 전환 시 추가 호출 없음, 키보드 이동, 요청 도중 수정한 원문과 결과 연결 유지, 429·502·504·잘못된 JSON·부분 결과·HTML 텍스트 안전 표시·30초 타임아웃·버튼 복구 — 통과.

브라우저 자동 검사에서는 HTTP 응답을 fixture로 대체했다. 실제 Gemini 동작은 아래에서 별도 확인했다.

## 실제 Gemini 확인

- 200자 이상 Mina 도서관 샘플: 실제 API 호출 성공, A1·A2·B1·B2와 한국어 설명 반환. 실제 브라우저에서도 입력 → 결과 → 레벨 탭 표시 확인.
- 날짜·숫자·부정·행동이 포함된 Maya 샘플: 네 결과 생성 성공 (약 3.42초, 해당 1회 측정값).
- `The cat is sleeping.`: 네 결과 반환 (약 2.46초, 해당 1회 측정값).
- 한국어만 있는 입력: `422 NOT_ENGLISH` 안내 확인.
- 첫 결과에서 recommended → gave 의미 변화, 짧은 문장에 soundly 추가, B2에 과도한 격식 표현이 나타났다. 행동·불확실성 보존 및 짧은 글은 네 수준 동일 출력 허용 예시를 프롬프트에 보완했다.
- 성공 응답이나 구조 검사 통과만으로 CEFR 정확도와 의미 보존을 보장하지 않는다. 소규모 수동 검토이며 공인 평가가 아니다.

- 보완 후 재검증: 짧은 고양이 문장은 네 레벨 모두 동일하게 유지하며 불필요한 사실 추가가 없어졌다. Maya 샘플의 날짜·숫자·부정은 유지됐지만 A1의 recommended → talked about 표현은 추천 의미를 약화시키는 한계가 남았다. 학습용 도구이며 결과 검토가 필요하다.

## 화면과 증빙

- `evidence/desktop.png`: 1440px 데스크톱 전체 화면.
- `evidence/mobile.png`: 390px 모바일 전체 화면.
- `evidence/ai-live-desktop.png`: 실제 Gemini를 호출한 결과 화면.
- `evidence/ai-live-mobile.png`: 실제 결과의 B2 탭을 표시한 모바일 화면.
- `evidence/ai-coding-log.md`: 실제 AI 코딩 도구 대화의 선별 발췌.

## 배포 상태

Vercel Production 배포 빌드 성공. URL: https://levelly-english-coach.vercel.app

사용자가 이 프로젝트의 공개 접근을 명시적으로 승인한 후 Vercel Authentication 보호를 해제했다. 로그인 없는 새 Chrome에서 200자 이상 샘플의 실제 AI 변환과 A1/B2 표시를 확인했다. 배포 URL에서도 브라우저 자동 검사 전체가 통과했다.

실제 HTTP 검증: `/` 200, `/css/style.css` 200, 빈 입력 `/api/rewrite` 400 JSON, `/.env.local` 및 `/services/coach.py` 404. 인증 우회 토큰 없이 검사했다.

GitHub `jimchoi9/codyssey-native`와 Vercel 연동 완료. Root Directory는 `A1-3`으로 설정했다. 작업은 `codex/english-level-coach` 브랜치에 기록하며 기존 main과 다른 과제 파일은 수정하지 않는다. 마지막 기능 검증 커밋 `1c610fa`의 GitHub 푸시로 Vercel 자동 배포가 생성되었고, GitHub Vercel 상태 검사와 배포 상태가 모두 성공/READY로 확인됐다.

## 과제 요구사항 대응

| 요구사항 | 구현·증빙 |
|---|---|
| 서비스 기획 | service-plan.md: 목적·타겟·구성·입출력·실패 |
| 폴더 구조·Git 이력 | public/와 api/ 분리, requirements.txt, 작업 브랜치 커밋 |
| 바닐라 화면과 메뉴 | public/index.html, public/css/style.css, public/js/app.js |
| 반응형 | 390·768·1440px 검사, 데스크톱·모바일 캡처 |
| AI UX | 폼·결과·로딩·오류·원문 유지 |
| Python AI API | api/rewrite.py → services/coach.py → Gemini |
| Vercel 배포 | 공개 URL 실제 동작 확인, GitHub 연동 |
| 제출 5종 | README·기획서·GitHub·배포 URL·증빙 준비 |
