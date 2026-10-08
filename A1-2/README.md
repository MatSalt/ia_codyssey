# 국내 여행지 추천 프로그램

여행 날짜를 입력하면 OpenAI가 국내 여행 지역·일반적인 날씨·행사 후보를 추천하고, Kakao Local이 해당 지역의 맛집을 검색합니다. 추천 JSON과 맛집 목록을 OpenAI에 보내 최종 Markdown 여행 리포트를 생성합니다.

Python 3.10 이상을 사용하며, 표준 라이브러리만으로 실행하므로 추가 패키지 설치가 필요 없습니다.

## 팀원 공유본

이 압축에는 설정된 `.env`와 Git 제외용 `.gitignore`가 함께 들어 있습니다. 압축을 풀고 `B2-2` 폴더에서 바로 실행할 수 있습니다. 실제 키가 포함되어 있으므로 팀원에게만 전달합니다.

`.gitignore`는 일반적인 `git add`에서 `.env`를 제외합니다. `git check-ignore .env`로 적용 여부를 확인할 수 있습니다. 기존 저장소가 이미 `.env`를 추적하고 있다면 `git rm --cached .env`로 추적을 해제하세요.

## 실행

`B2-2` 폴더에서 실행합니다. 기본값은 **실제 API(live)**입니다.

```sh
python3 travel_planner.py -date "2026-10-15"
```

`--date`도 지원합니다. 날짜 형식이나 실제 달력 날짜가 잘못되면 사용법을 출력하고 종료합니다. 이 컴퓨터에서는 Python 3.13으로 검증했으며 `python3.13` 명령을 사용할 수 있습니다.

## API 키 설정

```sh
cp -n .env.example .env
```

로컬 `.env`에 두 키를 입력합니다.

```dotenv
OPENAI_API_KEY=
KAKAO_REST_API_KEY=
OPENAI_MODEL=gpt-5-mini
```

OpenAI API 키와 사용 가능한 모델·쿼터를 준비하고, Kakao Developers 앱의 REST API 키를 사용합니다. Kakao 앱의 **[카카오맵] > [사용 설정]**을 ON으로 설정합니다. [OpenAI 공식 안내](https://developers.openai.com/api/docs/quickstart) · [Kakao 공식 안내](https://developers.kakao.com/docs/ko/kakaomap/common)

환경변수를 사용해도 되며, 같은 이름의 환경변수가 `.env`보다 우선합니다. 다른 설정 파일은 `--env-file PATH`, 모델은 `--model NAME`으로 지정합니다. `.env`의 기본 위치는 프로그램과 같은 폴더입니다.

실제 키를 코드·README·로그·결과에 넣지 않습니다. `.env`는 Git에서 제외하고, Git에는 키가 비어 있는 `.env.example`만 포함합니다. 키를 교체할 때 소스를 수정할 필요가 없습니다.

## 결과 확인

터미널에 추천 생성 → 맛집 검색 → 리포트 생성의 진행 로그와 저장 경로를 출력합니다. 프로그램을 실행하면 `results/` 폴더를 자동 생성하고 **실행 날짜·시각**을 파일명으로 저장합니다. 입력한 여행 날짜는 JSON의 `travel_date`와 리포트 제목에 기록합니다.

원본 데이터는 `YYYY-MM-DD_HHMMSS_ffffff_raw.json`, 최종 리포트는 `YYYY-MM-DD_HHMMSS_ffffff_travel_plan.md`로 저장합니다. 터미널에 안내된 경로에서 결과를 확인합니다.

JSON에는 `recommendation`, `restaurants`, `errors`와 단계별 원본 응답이 있습니다. 리포트는 추천 지역·추천 이유·날씨·행사 목록·맛집·오전/오후/저녁 일정과 오류 요약을 포함합니다. 날씨는 일반적인 계절 정보이며 행사는 후보입니다. 정확한 예보나 확정된 행사 일정으로 사용하지 않습니다.

## mock 시연

API 키 없이 테스트하려면 mock을 명시합니다. mock의 식당·주소·행사는 합성 데이터이며 결과는 `results/mock/<scenario>/`에 저장됩니다. mock 결과는 Git 제출 대상에서 제외합니다.

```sh
python3 travel_planner.py -date "2026-10-15" --backend mock
python3 travel_planner.py -date "2026-10-15" --backend mock --scenario auth-error
```

지원 상황은 `success`, `empty`, `auth-error`, `quota-error`, `network-error`, `invalid-json`, `retry-exhausted`, `report-error`입니다. mock은 외부 API를 호출하지 않습니다.

## 오류 처리

| 상황 | 처리 |
| --- | --- |
| 키 미설정 | API 호출 전 설정 방법을 안내하고 종료 코드 1 |
| 지도 인증·쿼터·네트워크 오류 또는 검색 0건 | 빈 맛집 목록과 `데이터 없음`으로 리포트 생성 계속 |
| LLM JSON 파싱·스키마 오류 | 수정 프롬프트로 최대 1회 재요청, 재실패 시 오류 JSON을 남기고 종료 코드 1 |
| 최종 LLM 리포트 생성·형식 오류 | 실패를 표시한 대체 리포트와 오류 JSON을 저장하고 종료 코드 1 |
| 날짜·옵션 오류 | 사용법 출력 후 종료 코드 2 |

API 호출·파싱은 `try-except`로 처리하고, 오류를 JSON의 `errors` 배열과 Markdown의 `오류 요약(errors)`에 기록합니다. 지도 오류 후 리포트가 완성되면 종료 코드 0입니다. 실제 실행 실패 시 mock으로 자동 전환하지 않습니다.

## 파일 구성

```text
B2-2/
├── travel_planner.py
├── README.md
└── .env.example
```

공통 [.gitignore](.gitignore)는 이 공유 폴더에 있습니다. `results/`는 실행 시 생성됩니다. 선택 보너스인 복수 지역 추천과 캐싱은 구현하지 않았습니다.
