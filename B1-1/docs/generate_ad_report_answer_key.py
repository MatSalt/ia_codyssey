#!/usr/bin/env python3
"""Generate the Meta ad report answer key from the original CSV."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Iterable


BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "0621_meta_ad_report.csv"
OUTPUT_PATH = BASE_DIR / "ad_report_answer_key.md"

SUM_METRICS = [
    "도달",
    "노출",
    "지출 금액 (KRW)",
    "링크 클릭",
    "랜딩 페이지 조회",
    "제품 맞춤 주문",
    "웹사이트 등록 완료",
    "웹사이트 구매",
]

CHECK_METRICS = [
    "지출 금액 (KRW)",
    "노출",
    "링크 클릭",
    "랜딩 페이지 조회",
    "제품 맞춤 주문",
    "웹사이트 등록 완료",
    "웹사이트 구매",
]

KEY_ROWS = [
    ("03_100books_ad1", "35-44", "female"),
    ("01_edu_ad1", "35-44", "female"),
    ("03_100books_ad1", "35-44", "male"),
    ("02_memory_ad1", "35-44", "female"),
    ("03_100books_ad1", "25-34", "female"),
    ("02_memory_ad1", "25-34", "female"),
    ("03_100books_ad1", "25-34", "male"),
    ("01_edu_ad1", "25-34", "male"),
    ("01_edu_ad1", "25-34", "female"),
    ("01_edu_ad1", "45-54", "female"),
    ("03_100books_ad1", "45-54", "female"),
    ("02_memory_ad1", "45-54", "female"),
]


def number(value: str) -> float:
    return 0.0 if value == "" else float(value)


def original_cell(value: str) -> str:
    return "빈 셀" if value == "" else format_number(number(value))


def format_number(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "-"
    if digits:
        return f"{value:,.{digits}f}"
    return f"{int(round(value)):,}"


def format_percent(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}%"


def format_money(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{value:,.{digits}f}"


def load_rows() -> list[dict[str, str]]:
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def aggregate(rows: Iterable[dict[str, str]], fields: tuple[str, ...]) -> dict[tuple[str, ...], dict[str, float]]:
    groups: dict[tuple[str, ...], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        key = tuple(row[field] for field in fields)
        for metric in SUM_METRICS:
            groups[key][metric] += number(row[metric])
    return groups


def ctr(values: dict[str, float]) -> float | None:
    impressions = values["노출"]
    return values["링크 클릭"] / impressions * 100 if impressions else None


def cpc(values: dict[str, float]) -> float | None:
    clicks = values["링크 클릭"]
    return values["지출 금액 (KRW)"] / clicks if clicks else None


def assert_internal_consistency(overall: dict[str, str], detail_rows: list[dict[str, str]]) -> None:
    detail_total = defaultdict(float)
    for row in detail_rows:
        for metric in CHECK_METRICS:
            detail_total[metric] += number(row[metric])

    mismatches = []
    for metric in CHECK_METRICS:
        if detail_total[metric] != number(overall[metric]):
            mismatches.append((metric, detail_total[metric], number(overall[metric])))

    if mismatches:
        details = ", ".join(
            f"{metric}: detail={detail}, overall={overall_value}"
            for metric, detail, overall_value in mismatches
        )
        raise AssertionError(f"Detail rows do not match the overall row: {details}")


def row_for_group(name: str, values: dict[str, float]) -> str:
    return (
        f"| {name} | {format_number(values['지출 금액 (KRW)'])} | "
        f"{format_number(values['노출'])} | {format_number(values['링크 클릭'])} | "
        f"{format_percent(ctr(values))} | {format_money(cpc(values))} | "
        f"{format_number(values['랜딩 페이지 조회'])} | "
        f"{format_number(values['제품 맞춤 주문'])} | "
        f"{format_number(values['웹사이트 등록 완료'])} | "
        f"{format_number(values['웹사이트 구매'])} |"
    )


def row_for_segment(age: str, gender: str, values: dict[str, float]) -> str:
    return (
        f"| {age} | {gender} | {format_number(values['지출 금액 (KRW)'])} | "
        f"{format_number(values['노출'])} | {format_number(values['링크 클릭'])} | "
        f"{format_percent(ctr(values))} | {format_money(cpc(values))} | "
        f"{format_number(values['랜딩 페이지 조회'])} | "
        f"{format_number(values['제품 맞춤 주문'])} | "
        f"{format_number(values['웹사이트 등록 완료'])} | "
        f"{format_number(values['웹사이트 구매'])} |"
    )


def row_for_raw(row: dict[str, str]) -> str:
    return (
        f"| {row['광고 이름']} | {row['연령']} | {row['성']} | "
        f"{format_number(number(row['지출 금액 (KRW)']))} | "
        f"{format_number(number(row['노출']))} | "
        f"{format_number(number(row['링크 클릭']))} | "
        f"{format_percent(number(row['CTR(링크 클릭률)']))} | "
        f"{format_money(number(row['CPC(링크 클릭당 비용)'])) if row['CPC(링크 클릭당 비용)'] else '-'} | "
        f"{format_number(number(row['랜딩 페이지 조회'])) if row['랜딩 페이지 조회'] else '빈 셀'} | "
        f"{original_cell(row['제품 맞춤 주문'])} | "
        f"{original_cell(row['웹사이트 등록 완료'])} | "
        f"{original_cell(row['웹사이트 구매'])} |"
    )


def generate_markdown(rows: list[dict[str, str]]) -> str:
    overall = rows[0]
    detail_rows = rows[1:]
    assert_internal_consistency(overall, detail_rows)

    by_ad = aggregate(detail_rows, ("광고 이름",))
    by_segment = aggregate(detail_rows, ("연령", "성"))
    raw_by_key = {(row["광고 이름"], row["연령"], row["성"]): row for row in detail_rows}

    segment_rows = sorted(
        by_segment.items(),
        key=lambda item: item[1]["지출 금액 (KRW)"],
        reverse=True,
    )
    segment_rows = [item for item in segment_rows if item[1]["지출 금액 (KRW)"] > 0][:15]

    lines = [
        "# 0621 메타 광고 성과 기준표",
        "",
        "이 문서는 `0621_meta_ad_report.csv`를 LLM 모델들이 정확히 읽었는지 판단하기 위한 정답 기준표입니다.",
        "표의 숫자는 아래 생성 스크립트가 원본 CSV를 직접 읽어 계산한 결과입니다.",
        "",
        "- 원본 파일: `B1-1/docs/0621_meta_ad_report.csv`",
        "- 생성 스크립트: `B1-1/docs/generate_ad_report_answer_key.py`",
        "- 보고 기간: 2026-06-01 ~ 2026-06-21",
        "- 첫 번째 데이터 행은 전체 합계 행입니다.",
        "- 이후 행은 광고 이름, 연령, 성별 기준 세부 행입니다.",
        "",
        "## 1. 재생성 및 검증 방법",
        "",
        "```bash",
        "python3 B1-1/docs/generate_ad_report_answer_key.py --write",
        "```",
        "",
        "스크립트는 하드코딩된 정답값을 사용하지 않습니다. 원본 CSV를 읽어 기준표를 다시 만들고, 세부 행 합산이 전체 합계 행과 일치하는지만 내부 검증합니다.",
        "",
        "## 2. 집계 기준",
        "",
        "- 전체 성과는 CSV 첫 번째 데이터 행의 값을 기준 정답으로 사용합니다.",
        "- 광고 소재별 합산값은 세부 행을 광고 이름 기준으로 합산했습니다.",
        "- 주요 세그먼트별 합산값은 세부 행을 연령/성별 기준으로 합산했습니다.",
        "- CTR은 `링크 클릭 / 노출 * 100`으로 계산했습니다.",
        "- CPC는 `지출 금액 / 링크 클릭`으로 계산했습니다.",
        "- 빈 셀은 행 단위에서는 0으로 단정하지 않습니다. 다만 합산표에서는 숫자가 입력된 셀만 합산했습니다.",
        "- 도달은 중복 제거 범위에 따라 달라질 수 있어 전체 합계와 세부 합산이 반드시 일치하는 검증 지표로 쓰지 않습니다.",
        "",
        "## 3. 전체 성과 기준값",
        "",
        "| 항목 | 기준값 |",
        "| --- | ---: |",
        f"| 총 지출 | {format_number(number(overall['지출 금액 (KRW)']))} KRW |",
        f"| 노출 | {format_number(number(overall['노출']))} |",
        f"| 링크 클릭 | {format_number(number(overall['링크 클릭']))} |",
        f"| CTR | {format_percent(number(overall['CTR(링크 클릭률)']))} |",
        f"| CPC | {format_money(number(overall['CPC(링크 클릭당 비용)']))} KRW |",
        f"| 랜딩 페이지 조회 | {format_number(number(overall['랜딩 페이지 조회']))} |",
        f"| 제품 맞춤 주문 | {format_number(number(overall['제품 맞춤 주문']))} |",
        f"| 웹사이트 등록 완료 | {format_number(number(overall['웹사이트 등록 완료']))} |",
        f"| 웹사이트 구매 | {format_number(number(overall['웹사이트 구매']))} |",
        "",
        "세부 행 합산 검증:",
        "",
        "| 항목 | 세부 행 합산 | 전체 합계 행 | 일치 여부 |",
        "| --- | ---: | ---: | --- |",
    ]

    detail_total = aggregate(detail_rows, tuple())[()]
    for metric in CHECK_METRICS:
        detail_value = detail_total[metric]
        overall_value = number(overall[metric])
        status = "일치" if detail_value == overall_value else "불일치"
        lines.append(
            f"| {metric} | {format_number(detail_value)} | {format_number(overall_value)} | {status} |"
        )

    lines.extend(
        [
            "",
            "## 4. 광고 소재별 합산 기준값",
            "",
            "| 광고 소재 | 지출 | 노출 | 링크 클릭 | CTR | CPC | 랜딩 조회 | 제품 맞춤 주문 | 등록 완료 | 구매 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for ad_name in sorted(by_ad):
        lines.append(row_for_group(ad_name[0], by_ad[ad_name]))

    lines.extend(
        [
            "",
            "## 5. 연령/성별 주요 세그먼트 기준값",
            "",
            "지출이 있는 주요 연령/성별 세그먼트를 지출 기준으로 정렬했습니다.",
            "",
            "| 연령 | 성별 | 지출 | 노출 | 링크 클릭 | CTR | CPC | 랜딩 조회 | 제품 맞춤 주문 | 등록 완료 | 구매 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for (age, gender), values in segment_rows:
        lines.append(row_for_segment(age, gender, values))

    lines.extend(
        [
            "",
            "## 6. 광고 소재 x 연령/성별 핵심 세그먼트",
            "",
            "모델 출력의 세부 수치 검증에 자주 사용할 핵심 행입니다. 이 표는 원본 행 값을 그대로 표시하므로 빈 셀은 `빈 셀`로 유지합니다.",
            "",
            "| 광고 소재 | 연령 | 성별 | 지출 | 노출 | 클릭 | CTR | CPC | 랜딩 조회 | 제품 맞춤 주문 | 등록 완료 | 구매 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for key in KEY_ROWS:
        lines.append(row_for_raw(raw_by_key[key]))

    lines.extend(
        [
            "",
            "## 7. 모델 채점 시 수치 오류 체크리스트",
            "",
            "모델 출력에서 아래 항목이 맞는지 확인합니다.",
            "",
            f"- 총 지출은 {format_number(number(overall['지출 금액 (KRW)']))}원입니다.",
            f"- 전체 링크 클릭은 {format_number(number(overall['링크 클릭']))}건입니다.",
            f"- 전체 CTR은 약 {format_percent(number(overall['CTR(링크 클릭률)']), 2)}입니다.",
            f"- 전체 CPC는 약 {format_money(number(overall['CPC(링크 클릭당 비용)']))}원입니다.",
            f"- 전체 랜딩 페이지 조회는 {format_number(number(overall['랜딩 페이지 조회']))}건입니다.",
            f"- 전체 웹사이트 등록 완료는 {format_number(number(overall['웹사이트 등록 완료']))}건입니다.",
            f"- 전체 웹사이트 구매는 {format_number(number(overall['웹사이트 구매']))}건입니다.",
            "- 빈 셀을 무조건 0건이라고 단정하면 감점 대상입니다.",
            "- 구매가 없는 것처럼 보이는 소재/세그먼트도 원본에서는 대부분 빈 셀이므로 \"구매 값이 기록되지 않음\"처럼 표현하는 것이 더 안전합니다.",
            "",
        ]
    )

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write the generated answer key markdown")
    args = parser.parse_args()

    markdown = generate_markdown(load_rows())
    if args.write:
        OUTPUT_PATH.write_text(markdown, encoding="utf-8")
        print(f"Wrote {OUTPUT_PATH}")
    else:
        print(markdown)


if __name__ == "__main__":
    main()
