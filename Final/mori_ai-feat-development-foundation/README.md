# Mori AI 사진첩

사진을 올리면 AI가 세로 3:4 이미지와 한 문장 글귀를 만들고, 사용자가 글귀를 수정해 모바일 사진첩으로 감상하는 서비스다. Google/Kakao 로그인, JPEG·PNG·WebP·HEIF/HEIC 업로드, WebP 정규화, 책장·글귀 수정·소유자 뷰어와 배경음악을 포함한다.

## 현재 상태 — 2026-10-17

- Google/Kakao 실제 로그인, R2 실제 업로드·읽기, OpenAI 글귀·이미지 생성이 연결됐다. 사용자가 모바일 기본 흐름, 사진 품질과 최근 성능 개선 결과를 확인했다.
- 정확한 세로 3:4 사진은 이미지 AI를 생략한다. 글귀는 설정 가능한 `gpt-5.4-mini`, 이미지는 `gpt-image-2`를 사용한다. 새 글귀는 담백한 회상형 `openai-memory-v3`; 기존 run은 생성 당시 프롬프트를 유지한다.
- 생성 동시 실행은 DB 전역 글귀 4·이미지 2·최적화 1, 업로드 검증은 worker 프로세스당 1이다. 실제 병렬화·중복 다운로드 제거·구간 로그를 반영했다. 업로드 완료 확인만 최대 180초, 일반 API는 30초를 기다린다.
- 승인된 UI 커밋 `a6e601b`를 총괄 `feat/development-foundation`에 통합했다. 통합·회귀 검증 근거는 [UI 통합 검증](docs/UI-통합검증.md)을 따른다.
- BGM은 `assets/audio/bgm.mp3`를 제공하며 버튼으로 시작·반복 재생한다. 뷰어 이탈·백그라운드 전환 시 정지하고 복귀해도 자동 재생하지 않는다.
- 외부 배포는 아직 수행하지 않았다. 실제 모바일 네트워크 중단·복귀, 장시간 외부 서비스 부하, 배포 환경 메모리 검증이 남아 있다. HDR/10bit 입력은 지원하지 않으며 고밀도 40MP 사진 일부는 이미지 처리 메모리 한도에서 거절된다.

## 굿즈 확장 — 2026-10-18

사진 1장 기반 시안 생성·수정·선택, 이탈 폐기, 완성 저장·내 디자인·앨범 연결을 구현했다. 굿즈 기본 모델은 `gpt-image-2.5-sunburst`이며 `GOODS_IMAGE_MODEL`로 교체한다. 사진첩 모델은 유지한다. API는 [굿즈 계약](docs/굿즈-공통계약-v1.md), 실제 호출·비용·UI 검증은 [검증 기록](docs/굿즈-실제연동-검증.md)을 따른다.

이번 굿즈 변경의 운영 배포·migration은 아직 수행하지 않았다. 제작 주문·PDF·메일은 후속 범위다. 별도 로컬 주소 18183의 새 앨범 직접 업로드 CORS는 사용자 결정으로 재검증을 보류했으며, 배포 후 사진 1장 업로드로 확인한다. 서버 경유 R2 검증과 브라우저 CORS 검증을 구분한다.

## 문서 진입점

| 문서 | 내용 |
|---|---|
| [기능요구명세서](기능요구명세서.md) | 초기 기능·제외 범위·사용자 테스트와 제출 조건 |
| [공통계약](docs/공통계약-v1.md) · [샘플](docs/공통계약-v1.examples.json) | 현재 API·DTO·상태·오류 기준 |
| [설계](docs/설계.md) | 화면·구조·worker·복구·배포 설계 |
| [재사용 조사](docs/재사용조사.md) | 기존 moriai에서 참고한 모듈과 출처 |
| [검증 계획](docs/검증계획.md) | 인수 기준·실행 결과·남은 확인 |
| [개발 운영](docs/개발운영.md) · [AGENTS.md](AGENTS.md) | 편집 소유권·환경 격리·Orca 협업 규칙 |

최근 검증 근거: [실제 OAuth](docs/실제OAuth-검증결과.md), [R2](docs/R2-통합검증.md), [실제 AI·비용](docs/실제-AI-검증.md), [성능·업로드 시간 초과](docs/성능-검증결과.md), [병렬 안정성](docs/병렬처리-안정성-검증.md), [BGM](docs/BGM-구현검증.md). 오래된 문서의 ‘미구현/검증 전’ 문장은 당시 이력이며 최신 결과가 우선한다. [문서 이력](docs/archive/2026-10-16/README.md)과 초기 구현 계획은 보존한다.

## 새 로컬 환경 실행

Docker Desktop을 실행하고 다음 절차를 따른다. 기존 `.env`가 있으면 덮어쓰지 않는다.

```sh
cp .env.example .env
# POSTGRES_PASSWORD를 새 로컬 전용 값으로 지정하고 사용할 adapter 설정을 채운다.
# 다른 checkout과 COMPOSE_PROJECT_NAME·WEB_PORT를 다르게 지정한다.
make up
make down
```

`make up`은 이미지 빌드와 migration 후 web·worker를 시작한다. `make down`은 DB·media volume을 보존한다. 기존 moriai의 운영 DB·계정·사진을 복사하거나 연결하지 않는다.

- 개발 로그인: 새 로컬 환경에서 `APP_ENV=local`, `DEV_AUTH_ENABLED=true`, `SESSION_COOKIE_ALLOW_INSECURE_LOCAL=true`, `APP_ORIGIN=http://127.0.0.1:<WEB_PORT>`. 운영에서는 개발 로그인과 insecure cookie를 허용하지 않는다.
- 가짜 AI: 로컬에서만 `DEV_AI_ENABLED=true`. 실제 API와 비용이 없는 고정 글귀·테스트 canvas다.
- 실제 연동: `.env.example`의 OAuth, R2, OpenAI 항목을 채우고 `STORAGE_MODE=r2`, `AI_REAL_CALLS_ENABLED=true`를 명시한다. SDK 호출은 누적 비용 장부·사전 예약·unknown 보수적 집계를 거친다. 사용자 승인 총 한도는 $100, 초기 운용 한도는 $5다. 한도는 소비 목표가 아니다.
- 음원: 저장소의 `assets/audio/bgm.mp3`를 Docker 이미지에 포함한다. 임의 디렉터리를 공개하지 않고 `/audio/bgm.mp3`만 제공한다. 외부 음원 계정이나 환경변수는 필요 없다.

현재 테스트 서버는 `.env.qa`와 Compose project `mori-r2-qa`, `http://127.0.0.1:8000`을 사용한다. 기존 DB·OAuth origin을 보존하기 위해 이 환경을 다른 `.env`로 임의 재생성하지 않는다. 병렬 UI 세션은 별도 worktree·포트·DB를 사용한다. `.env*`와 키는 출력하거나 커밋하지 않는다.

OAuth 인증 code가 로그에 남지 않도록 Uvicorn은 `--no-access-log`로 실행한다. `mori.performance` 구조화 로그는 허용된 시간·단계·ID·오류 분류만 기록하며 사진·서명 URL·본문을 기록하지 않는다.

## R2 설정과 검증

비공개 bucket의 로컬 CORS는 [JSON](docs/storage/r2-cors.local.json)을 사용한다. `http://127.0.0.1:8000`과 `localhost`는 다른 origin이다. 배포 주소나 별도 모바일 접속 주소에는 그 origin의 OAuth callback·R2 CORS 설정이 필요하다.

`make verify-storage`는 실제 R2의 고유 `mori-ai-storage-check/<UUID>/` 경로에서 합성 파일·hash·조건부 덮어쓰기 거부·서명·CORS·삭제 등을 검증하고 생성 객체를 정리한다. 실제 저장소 요청은 발생하지만 사용자 사진·AI는 사용하지 않는다. local 객체가 있는 DB를 그대로 R2 모드로 바꾸지 않는다.

## 자동 검증

```sh
make verify-install       # 의존성·빌드·기본 테스트
make verify-isolation     # 임시 Compose 환경 격리
make verify-codecs
make verify-db            # 전용 임시 PostgreSQL의 통합 검사
make verify-worker
make verify-media-load    # 기존 순차 미디어 부하 검사
```

현재 검증 이미지는 `mori-ai:ai-tests`다. 이를 사용할 때는 `MORI_VERIFY_TEST_IMAGE=mori-ai:ai-tests`를 지정한다. 이미지가 없으면 먼저 설치 검증으로 검증 이미지를 빌드한다. 전체 backend 검증은 `bash scripts/verify-db.sh backend/tests`를 사용한다. 병렬 메모리·다중 프로세스 재현 명령은 [병렬 안정성 보고서](docs/병렬처리-안정성-검증.md)에 있다. 테스트용 DB는 QA DB와 분리되고 종료 시 자신의 임시 볼륨만 제거한다.

## 남은 작업

배포 선택(2026-10-17): 사용자 요청으로 Render 대신 Lightsail 단일 VPS `ai_mori`와 `https://aimori.kro.kr`을 사용한다. 운영용 파일과 단계별 실행·백업 절차는 [Lightsail 배포](docs/Lightsail-배포.md)를 따른다. 2026-10-18 사용자가 Lightsail 실제 연동·모바일 접속 성공을 보고했다. 2GB 장시간 부하와 백업 복구의 완료 보고는 별도로 확인한다.

1. 미디어 v1.6 변경 배포 후 실제 모바일 전처리·화질·중단·복귀 검증. 로컬 구현 및 합성40MP 근거는 [미디어 전처리 검증](docs/미디어-전처리-검증.md)을 따른다.
2. 배포 후 개선 UI의 모바일 실기기·BGM 청취 확인.
3. 운영 DB 백업 복구·비용/오류·장시간 부하 점검 및 미디어 업데이트 배포.
4. 명세 기준 최소 5명 사용자 테스트와 피드백 반영·제출 자료 정리.

외부 배포와 운영 변경은 별도 승인 범위다. 공유·결제·TTS·영상 등 제외 기능을 남은 초기 구현으로 추가하지 않는다.
