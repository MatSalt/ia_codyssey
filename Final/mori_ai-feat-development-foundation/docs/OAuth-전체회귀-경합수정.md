# OAuth 전체 회귀 PID fixture 경합 수정

2026-10-16, task_4e34d86ed258 / ctx_9ade5f70f97d.

## RED 근거와 원인

총괄의 `/tmp/mori-oauth-final-db.log`를 확인했다. 전체 회귀 결과는 `1 failed, 481 passed, 1 warning in 254.84s`이며 유일한 실패는 `test_real_entrypoint_sigterm_cancels_and_reaps_media_child`의 기존 654행 `int(marker.read_text())`에서 빈 문자열로 발생한 `ValueError`다.

테스트 helper의 자식 스크립트는 최종 PID 파일에 직접 `Path.write_text()`를 호출했다. 파일 생성·열기와 내용 쓰기·닫기는 별도 단계이므로 consumer의 `exists()`가 참이어도 쓰기가 끝나기 전에는 빈 내용을 읽을 수 있다. 이는 테스트 fixture의 게시 경합이며 OAuth 또는 제품 pipeline 실패를 나타내는 근거가 아니다.

## 변경

`backend/tests/integration/test_generation_pipeline.py`의 entrypoint helper만 수정했다. PID를 같은 디렉터리의 `child_pid.tmp`에 완전히 쓰고 닫은 뒤 `Path.replace(marker)`로 최종 파일을 원자적으로 게시한다. 테스트 consumer의 존재 확인과 정수 변환, SIGTERM 전송, 부모 종료 코드 0 및 자식 PID 소멸 검사는 그대로 유지했다. sleep·timeout 증가, skip, consumer retry는 추가하지 않았다.

제품 코드·설정·의존성·계약 변경 및 기존 서비스 코드 재사용은 없다.

## GREEN 검증

기존 최종 OAuth 이미지 기본값 `mori-ai:verify-tests`를 사용하는 다음 명령으로 지정 테스트만 실행했다.

```sh
bash scripts/verify-db.sh backend/tests/integration/test_generation_pipeline.py::test_real_entrypoint_sigterm_cancels_and_reaps_media_child
```

결과: `1 passed in 3.58s`. PostgreSQL 17.11에서 기존 스크립트의 fresh DB, migration upgrade/downgrade/upgrade 및 schema check를 통과했다. 기존 `/dev/null` compose 환경과 읽기 전용 source bind mount를 사용했다. 최초 sandbox 실행은 Docker socket 접근 제한으로 테스트 실행 전에 종료되어, 승인된 권한으로 동일 명령을 실행했다.

전체 suite 재실행은 총괄 소유이며 이 작업에서는 수행하지 않았다. 실제 OAuth 공급자 인증이나 외부 AI·R2 연동을 이 테스트 결과로 검증한 것은 아니다.
