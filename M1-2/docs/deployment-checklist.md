# 배포·제출 체크리스트

2026-10-26. 사용자 설정 확인, 자동 테스트, 실제 서비스 검증을 구분해 기록합니다.

## 로컬 검증 완료

- [x] CSV 가져오기·대화 API·AI 채팅 구현 및 독립 리뷰
- [x] 백엔드 전체 113개, 프론트 단위 15개 통과
- [x] Playwright HTTP 대체 12개 및 실제 로컬 API+fake 통합 2개 통과
- [x] 데스크톱·360px, 키보드, 오류·빈 상태, 안전한 HTML 표시 검증
- [x] 공개 빌드에는 API_BASE_URL만 포함; CSV·비밀 제외

## 실제 연결

- [x] 지정 Firebase 프로젝트 `story-analytics-assistant`에 SDK 인증으로 접근
- [x] CSV dry-run 120개 형식 검증
- [x] 최초 가져오기 created=120/skipped=0
- [x] 재실행 created=0/skipped=120 (덮어쓰기 없음)
- [x] Copa Chat Completions 지원 옵션 확인: reasoning_effort 미지원, max_completion_tokens 지원
- [x] 512토큰 빈 응답 원인 확인; 2048 한도에서 정상 답변 확인
- [x] 실제 앱 AI 대화 저장·복원, 임시 기록 수정 후 최신 합계 반영 확인 (공개 브라우저 이어가기는 배포 후 검증)

## 배포 설정

아래 서비스 설정은 사용자 보고에 기반합니다. 공개 URL 및 연결 값은 별도로 확인했습니다.

- [x] GitHub `jimchoi9/codyssey-native`, 배포 브랜치 main
- [x] Render `https://codyssey-native.onrender.com`, Python 3.13.5
- [x] Render Firebase Secret File 및 GOOGLE_APPLICATION_CREDENTIALS 경로 일치 (사용자 재배포로 503 해결)
- [x] Render virtual key·Base URL·모델 및 Vercel 출처 CORS 설정 완료
- [x] Vercel `https://codyssey-native-frontend.vercel.app`, 공개 config.js API URL 일치
- [x] 이번 변경 main 반영 후 Render/Vercel 최종 배포 확인 (/docs·대화 API200)
- [x] 공개 /docs·대화 API·CORS·실제 브라우저 CRUD/채팅/복원 확인

Blueprint Path는 `M1-2/render.yaml`, Render rootDir는 `M1-2/backend`입니다. Vercel Root Directory는 `M1-2/frontend`, 설정은 `frontend/vercel.json`, Build Command는 `npm run build`, Output Directory는 `dist`입니다. Secret File의 실제 경로는 `/etc/secrets/firebase-service-account.json`입니다.

## 제출 증거

- [x] docs/screenshots/chat-summary.png
- [x] docs/screenshots/data-management.png
- [x] docs/screenshots/conversation-history.png
- [x] README와 단계 보고서에 실제 결과 반영

파괴적·경쟁 상태 테스트는 fake에서 수행합니다. 실제 데이터 검증용 임시 기록은 원본 날짜와 겹치지 않게 생성하고 삭제해 원상복구합니다. 합성 테스트 화면은 제출용 실제 화면으로 표시하지 않습니다.
