# Lightsail 배포 — ai_mori

2026-10-17 사용자 선택: Render 대신 서울 Lightsail 2GB 단일 VPS에 web·worker·PostgreSQL17·Caddy를 실행한다. 주소는 https://aimori.kro.kr 이며 사용자 DNS 조회 결과는 54.116.168.155다. 실제 서버 배포와 인증서 발급은 아직 검증하지 않았다.

## 파일과 격리

- `compose.lightsail.yaml`은 독립 파일이다. 로컬 `compose.yaml`과 병합하지 않는다.
- `bash scripts/lightsail.sh`는 `.env.production`만 읽고 프로젝트를 `mori-lightsail-prod`로 고정한다.
- QA `.env.qa`, `mori-r2-qa`, DB·사진·비용 장부는 건드리지 않는다. 운영은 새 DB와 전용 비공개 R2 bucket을 사용한다.
- 기존 Compose의 명시적 환경변수 목록을 재사용했다. 외부 저장소 코드 이식과 API 계약 변경은 없다.
- web 256MiB, worker 1GiB, DB 256MiB, Caddy 128MiB는 초기 상한이다. 2GB에서 전체 부하 통과를 뜻하지 않는다. OOM·재시작·호스트 메모리를 측정하고 필요한 경우 처리량 또는 사양을 조정한다.

## 최초 배포

먼저 이 변경을 GitHub에 반영한 다음 **Lightsail SSH**에서 실행한다. 아직 GitHub에 올리지 않은 로컬 파일은 `git pull`로 받을 수 없다.

```bash
cd ~/apps/mori_ai
git pull --ff-only
umask 077
test -e .env.production || cp deploy/lightsail/production.env.example .env.production
chmod 600 .env.production
nano .env.production
```

`POSTGRES_PASSWORD`는 `openssl rand -hex 24`로 생성한 새 값을 사용한다. 운영 DB 초기화 후에는 환경변수만 바꿔서 암호를 변경하지 않는다. `MORI_IMAGE`는 배포마다 `mori-ai:lightsail-<커밋>`처럼 고유하게 지정한다. 환경 파일·키를 채팅, Git 또는 로그에 출력하지 않는다.

필수 입력: DB 암호, 운영 R2 bucket·endpoint·S3 키. Google/Kakao ID·secret과 아래 callback은 해당 콘솔 등록 후 입력한다. 로그인 값을 비워두면 해당 제공자가 활성화되지 않는다. `APP_ENV`, 개발 로그인·가짜 AI·insecure cookie는 Compose에서 운영값으로 강제한다.

- Google callback: `https://aimori.kro.kr/api/v1/auth/google/callback`
- Kakao callback: `https://aimori.kro.kr/api/v1/auth/kakao/callback`
- origin/사이트 주소 입력이 필요한 항목: `https://aimori.kro.kr`
- R2 CORS: `deploy/lightsail/r2-cors.json`을 **운영 bucket**에 적용한다. QA CORS를 덮어쓰지 않는다.

`AI_REAL_CALLS_ENABLED=false`를 유지한다. 새 DB의 비용 원장은 QA 누적 사용액을 알지 못한다. 활성화 전에 QA 사용액·unknown 예약을 확인하고 전체 승인 $100/초기 $5에서 이미 사용·예약한 금액을 뺀 운영 할당액을 정한다. 두 환경의 병행 소비도 합산한다. 예산은 초기화하거나 자동 상향하지 않는다.

```bash
sudo bash scripts/lightsail.sh config --quiet
sudo bash scripts/lightsail.sh build web
sudo bash scripts/lightsail.sh up -d postgres
sudo bash scripts/lightsail.sh run --rm migrate
sudo bash scripts/lightsail.sh up -d web worker caddy
sudo bash scripts/lightsail.sh ps
curl -fsS https://aimori.kro.kr/health
```

각 명령이 성공했을 때만 다음 명령을 실행한다. 최초 빌드는 2GB에서 메모리가 부족할 수 있다. 실패하면 반복 빌드 전에 자원을 확인하고 별도 Linux amd64 빌드 환경에서 동일 커밋 이미지를 만들어 전달한다. 실행 중 서버에서 빌드하면 서비스와 자원을 경쟁하므로 업데이트는 사전 빌드 이미지를 권장한다.

Caddy가 80·443을 사용해 인증서를 발급한다. DNS A가 고정 IP와 일치하고 잘못된 AAAA가 없어야 한다. 외부 8000·5432는 열지 않는다. Uvicorn과 Caddy의 요청 access log는 사용하지 않는다. 기본 서버는 브라우저 원본의 HTTPS origin을 사용하므로 proxy trust 범위를 확장하지 않는다.

## 검증과 재시작

```bash
sudo bash scripts/lightsail.sh logs --tail=50 web worker caddy
sudo bash scripts/lightsail.sh stats --no-stream
```

로그를 공유하기 전 비밀값·인증 code·서명 URL이 없는지 확인한다. `/health`는 프로세스 응답 확인이며 DB·R2·OAuth 전체 성공을 의미하지 않는다. Google/Kakao 로그인, 사진 업로드·R2 조회, 예산 정산 후 소량 AI, 글귀 수정·BGM, 모바일 중단/복귀, worker 재시작 복구를 확인한다. `unless-stopped`로 컨테이너는 재부팅 후 재시작하지만 직접 stop한 컨테이너는 `up -d`로 다시 시작해야 한다.

## 백업·업데이트·복구

```bash
sudo bash scripts/lightsail-backup.sh
```

DB의 일관된 custom-format dump를 `.local/backups`에 저장하고 목차 읽기까지 검사한다. 이것은 복원 성공 검증을 대신하지 않는다. 백업에는 개인정보와 비용 원장이 있으므로 암호화된 서버 밖 저장소에 복사하고, 별도 임시 PostgreSQL17 DB에서 `pg_restore --exit-on-error --no-owner --no-privileges`로 복원 후 데이터·비용 장부를 검증한다. 운영 DB를 대상으로 복원 연습하지 않는다. 사용자 데이터를 받기 전에 정기 백업·보존 기간·서버 밖 복사·복원 검증을 완료한다. 스냅샷은 보조 수단이며 별도 비용이 발생한다.

업데이트는 백업 → 코드/이미지 준비 → web·worker 정지 → migration → web·worker 재기동 순서로 진행한다. migration 실패 시 앱을 재기동하지 말고 오류를 확인한다. 호환되는 이전 스키마에서만 `MORI_IMAGE`를 이전 태그로 되돌린다. 파괴적인 migration은 별도 복구 계획이 필요하다. `down -v`, volume 삭제, 비용 장부 초기화는 사용하지 않는다. 백업에는 DB만 포함되고 R2 객체와 `.env.production`은 별도 보호가 필요하다.

## 로컬 검증 결과

- Compose 구문 및 maintenance profile 포함 5개 서비스 해석 통과.
- 운영 프로젝트 분리, web/worker/DB 비공개 포트, HTTPS origin, 개발 인증 금지, AI 기본 비활성, 운영 CORS 검사 통과.
- 배포 wrapper·백업 스크립트 `bash -n` 통과.
- 실제 Lightsail 실행, Caddy 인증서 발급, 운영 자격증명 연동, 백업·복원과 2GB 부하는 미검증.


## 2026-10-18 미디어 v1.6 업데이트 인계

사용자가 기존 배포의 실제 연동과 모바일 접속 성공을 보고했다. 이번 미디어 변경의 배포·실기기 검증은 별도다. 같은 이미지에 frontend/backend를 함께 업데이트해야 새 `preprocessing` 예약 필드를 사용할 수 있다.

기존 `.env.production`의 명시적 `NORMALIZED_WEBP_LOSSLESS=true`는 Compose 기본값보다 우선한다. 새 손실 압축을 적용할 배포에서는 `NORMALIZED_WEBP_LOSSLESS=false`, `NORMALIZED_WEBP_QUALITY=90`, `CONSENT_POLICY_VERSION=media-2026-10-18`을 명시한다. 동의 버전 변경으로 기존 사용자도 새 보관 고지에 동의한 뒤 신규 업로드를 진행한다. 다른 자격증명·예산 설정은 변경하지 않는다. 이미 예약된 업로드와 생성 run은 동결된 기존 설정을 유지한다. 예제와 Compose 파일 갱신은 실행 중 서버 설정을 자동 변경하지 않는다.

새 업로드는 정규화본 확보 후 임시 source를 정리한다. 기존 데이터의 일괄 삭제·migration은 없다. 배포 후 JPEG/PNG/HEIC, 방향·촬영일, 전송 재시도, 생성·뷰어를 확인한다. 클라이언트의 전처리 제한 초과/미지원 파일은 서버 처리로 이어져야 한다. 정책 검증과 측정 결과는 [미디어 전처리 검증](미디어-전처리-검증.md)을 참조한다.

## GitHub Actions 자동 빌드 + 서버 한 명령 배포 (2026-10-18)

현재 준비된 자동화는 **push → 검사·빌드·GHCR 게시**, 운영 반영은 SSH에서 명령 한 번으로 수행한다. GitHub가 서버에 접속하지 않으므로 SSH 방화벽을 추가로 열거나 배포 키를 GitHub에 등록할 필요가 없다. 이 변경 자체는 commit/push/운영 배포하지 않았다.

### 최초 설정

1. 미디어 변경의 추적되지 않은 새 파일까지 포함해 검토·커밋하고 GitHub에 push한다. `.github/workflows/container.yml`, `scripts/lightsail-deploy.sh`, `tests/deploy/test_lightsail_deploy.py`도 함께 올린다. 기존 미디어 수정 내용을 선택적으로 빠뜨린 채 빌드하지 않는다.
2. 저장소 Actions에서 **Build verified container** 성공을 확인한다. 모든 브랜치 push와 수동 실행에 대응한다. 배포 실패경로 검사 → Docker verification stage(프론트 검사 포함) → 임시 PostgreSQL 전체 backend 검사 → runtime 이미지 빌드 → GHCR 게시 순서다. 검사 실패 시 이미지는 게시하지 않는다. runner의 GITHUB_TOKEN만 사용하며 운영 API 키는 전달하지 않는다.
3. GitHub 계정 Packages의 `mori_ai` 설정에서 패키지 접근을 결정한다. 공개 저장소라고 패키지가 자동 공개되지는 않는다. 공개 이미지가 괜찮다면 패키지를 Public으로 설정한다. 이미지에는 공개 코드와 BGM이 포함되므로 음원 배포 권한도 유지되어야 한다. 비공개로 유지하면 서버에서 packages 읽기 권한이 있는 토큰으로 `sudo docker login ghcr.io`를 실행한다. 토큰은 채팅/명령줄 인수/Git에 넣지 않는다.
4. 서버에서 최초 한 번 `git pull --ff-only`로 새 스크립트를 받는다. 로컬 수정된 ZeroSSL Caddyfile과 충돌하면 강제 reset하지 말고 먼저 조정한다.
5. `.env.production`의 미디어 전환값을 확인한다: `NORMALIZED_WEBP_LOSSLESS=false`, `NORMALIZED_WEBP_QUALITY=90`, `CONSENT_POLICY_VERSION=media-2026-10-18`. 자동 배포는 AI 활성화·예산·정책 값을 임의 변경하지 않는다.

### 매번 배포

진행 중인 생성/업로드가 끝난 점검 시간에, Actions에서 성공한 **전체 40자리 commit SHA**를 복사하여 Lightsail에서 실행한다. 아래 자리표시자는 실제 SHA로 바꾼다.

```bash
cd ~/apps/mori_ai
sudo bash scripts/lightsail-deploy.sh <전체40자리커밋SHA>
```

스크립트는 지정 커밋 fetch·fast-forward → `ghcr.io/jimchoi9/mori_ai:sha-<SHA>` 다운로드 → 이미지 revision label 확인 → digest 고정 → 설정검사 → DB백업 → web/worker 정지 → migration → 새 앱 시작·health 확인 → `.env.production`에 성공한 digest 기록을 수행한다. SSH 연결은 완료까지 유지한다.

- Docker build는 서버에서 실행하지 않는다. 동시에 두 배포가 실행되면 두 번째는 중단한다.
- 서버 checkout의 수정은 Caddyfile만 허용한다. 그 외 tracked 변경이나 divergent Git 상태는 먼저 조정한다. fetch/merge가 필요하므로 서버에 GitHub 읽기 네트워크 접근이 필요하다.
- Caddyfile은 서버의 ZeroSSL 설정을 유지하며 Caddy·PostgreSQL 컨테이너를 재생성하지 않는다. upstream Caddy 수정과 충돌하면 앱 중지 전에 실패한다. Caddy/DB 인프라 변경은 이 앱 배포 스크립트의 범위 밖이다.
- 이미지가 없거나 pull/revision/설정검사/백업이 실패하면 앱을 중지하지 않는다. 소스 checkout만 새 커밋으로 이동했을 수 있지만 실행 중 앱은 기존 이미지다.
- migration 또는 시작/health 검사 실패 시 자동 DB rollback은 하지 않는다. 오류에 표시된 단계와 서비스를 확인한다. migration 이후 앱이 정지 상태이거나 새 이미지로 실행 중일 수 있으며, 환경 파일에는 이전 이미지가 남는다. 이때 일반 `up`을 무작정 실행하지 말고 스키마 호환성을 먼저 확인한다.
- 이전 환경 파일은 `.local/env-before-*`, DB dump는 `.local/backups`에 보호된 권한으로 남는다. 환경 백업은 비밀값을 포함한다. 자동 prune/volume 삭제는 없다. 저장공간과 백업 보존·서버 밖 복사는 별도 관리한다.
- 정상 동작 판정은 web health·worker 실행 상태와 HTTPS 응답까지다. worker의 작업 처리 성공이나 모바일 품질까지 보장하지 않으므로 실사진 검증을 이어간다.

### 자동화 검증

`python3 tests/deploy/test_lightsail_deploy.py`: 5개 테스트, 하위 경우 포함. 정상 순서·digest 저장·정책 보존, dirty/merge/pull/revision/backup 실패 시 무중단, migration 실패 시 시작 금지, startup/HTTPS 실패 시 이미지 설정 보존, 잘못된 SHA의 부작용 없음 검증. Git·Docker·curl은 가짜 명령이며 실제 서버를 건드리지 않는다. `bash -n` 및 diff 공백 검사 통과. 실제 GitHub Actions 최초 빌드/GHCR 권한·서버 pull·운영 배포는 아직 미실행이다.
