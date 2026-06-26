# 폴더 구조

```
B1-1/
├── mission.md                        # 과제 명세서
├── docs/                             # 작업 과정 문서
│   ├── plan/
│   │   └── llm_model_comparison_plan.md          # 모델 비교 계획
│   ├── prompt/
│   │   ├── system_prompt.md                      # 시스템 프롬프트 초안
│   │   └── v1_prompt_question_list.md            # v1 질문 목록
│   ├── src/
│   │   └── 0621_meta_ad_report.csv               # 입력 데이터 (Meta 광고 보고서)
│   ├── model_outputs/
│   │   ├── gpt_output.md                         # GPT 결과
│   │   ├── claude_output.md                      # Claude 결과
│   │   └── gemini_output.md                      # Gemini 결과
│   ├── log/
│   │   ├── conversation_log_v1.md                # 대화 로그 v1
│   │   └── conversation_log_v2.md                # 대화 로그 v2
│   ├── ad_report_answer_key.md                   # 정답 키
│   ├── generate_ad_report_answer_key.py          # 정답 키 생성 스크립트
│   ├── folder_structure.md                       # 폴더 구조 문서 (이 파일)
│   ├── llm_model_comparison_report.md            # 모델 비교 보고서 초안
│   └── model_output_evaluation_against_answer_key.md  # 정답 대비 평가
└── submit/                           # 최종 제출물
    ├── llm_model_comparison_report.md            # 제출용 모델 비교 보고서
    ├── system_design.md                          # 제출용 시스템 설계 문서
    └── conversation_log.md                       # 제출용 대화 로그
```

## 규칙

- `docs/` — 작업 과정에서 생성되는 모든 중간 산출물을 저장
- `submit/` — 최종 제출물만 저장 (과제 명세 기준 3개 파일)
- `docs/src/` — 원본 입력 데이터
- `docs/model_outputs/` — 각 LLM 모델의 원본 출력 결과
- `docs/log/` — 대화 로그 버전 관리
