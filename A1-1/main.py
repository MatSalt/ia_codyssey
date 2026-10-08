"""리스트와 딕셔너리로 관리하는 메모리 기반 프롬프트 보관함."""


CATEGORIES = ['텍스트 생성', '이미지 생성', '영상 생성', '페르소나', '자동화', '기타']


def create_initial_prompts() -> list[dict]:
    """사용자 요청으로 작성한 예시 데이터. 실행할 때마다 새로 만든다."""
    return [
        {
            'title': '파이썬 학습 내용 요약',
            'content': (
                '당신은 파이썬 입문자를 가르치는 튜터입니다. 내가 제공하는 학습 내용을 '
                '핵심 개념 3개, 쉬운 코드 예제, 확인 문제 2개로 정리해주세요. '
                '어려운 용어는 풀어서 설명하고 제공되지 않은 사실은 추측하지 마세요.'
            ),
            'category': '텍스트 생성',
            'favorite': False,
        },
        {
            'title': '독서 앱 홍보 이미지',
            'content': (
                '독서 기록 앱의 홍보용 정사각형 이미지를 만들어주세요. 따뜻한 크림색 배경에 '
                '펼친 책과 작은 화분을 배치하고 부드러운 자연광을 표현해주세요. '
                '위쪽에는 제목을 넣을 여백을 남기고 이미지 안에는 글자를 넣지 마세요.'
            ),
            'category': '이미지 생성',
            'favorite': False,
        },
        {
            'title': '친절한 모의 면접관',
            'content': (
                '당신은 주니어 개발자 면접관입니다. 먼저 지원 직무를 물어보고, '
                '답변을 받은 뒤 관련 질문을 한 번에 하나씩 해주세요. 각 답변마다 '
                '잘한 점 한 가지와 개선할 점 한 가지를 구체적으로 알려주세요. '
                '모르는 내용은 함께 확인할 수 있도록 안내해주세요.'
            ),
            'category': '페르소나',
            'favorite': False,
        },
    ]


def read_required_text(label: str) -> str:
    while True:
        value = input(label).strip()
        if value:
            return value
        print('빈 값은 입력할 수 없습니다. 다시 입력해주세요.')


def select_category() -> str:
    print('카테고리 선택:')
    for number, category in enumerate(CATEGORIES, start=1):
        print(f'{number}) {category}')
    while True:
        choice = input('선택: ').strip()
        # 문자열로 비교해 숫자가 아닌 입력도 예외 없이 처리한다.
        for number, category in enumerate(CATEGORIES, start=1):
            if choice == str(number):
                return category
        print('잘못된 카테고리 번호입니다. 다시 선택해주세요.')


def add_prompt(prompts: list[dict]) -> None:
    print('\n=== 프롬프트 추가 ===')
    title = read_required_text('제목: ')
    content = read_required_text('내용: ')
    category = select_category()
    prompts.append({
        'title': title,
        'content': content,
        'category': category,
        'favorite': False,
    })
    print('프롬프트가 추가되었습니다!')


def print_prompt_list(items: list[tuple[int, dict]]) -> None:
    if not items:
        print('프롬프트가 없습니다.')
        return
    for number, prompt in items:
        star = ' ⭐' if prompt['favorite'] else ''
        print(f"{number}. [{prompt['category']}] {prompt['title']}{star}")
    print(f'총 {len(items)}개의 프롬프트')


def show_list(prompts: list[dict]) -> None:
    print('\n=== 프롬프트 목록 ===')
    print_prompt_list(list(enumerate(prompts, start=1)))


def show_by_category(prompts: list[dict]) -> None:
    print('\n=== 카테고리별 조회 ===')
    category = select_category()
    items = []
    for number, prompt in enumerate(prompts, start=1):
        if prompt['category'] == category:
            items.append((number, prompt))
    print(f'[{category}] 카테고리 프롬프트:')
    print_prompt_list(items)


def search_prompts(prompts: list[dict]) -> None:
    print('\n=== 프롬프트 검색 ===')
    keyword = read_required_text('검색어: ').casefold()
    items = []
    for number, prompt in enumerate(prompts, start=1):
        if keyword in prompt['title'].casefold() or keyword in prompt['content'].casefold():
            items.append((number, prompt))
    print('검색 결과:')
    print_prompt_list(items)


def select_prompt(prompts: list[dict]) -> dict | None:
    if not prompts:
        print('프롬프트가 없습니다.')
        return None
    choice = input('프롬프트 번호 입력: ').strip()
    for number, prompt in enumerate(prompts, start=1):
        if choice == str(number):
            return prompt
    print('잘못된 프롬프트 번호입니다.')
    return None


def show_detail(prompts: list[dict]) -> None:
    print('\n=== 프롬프트 상세 보기 ===')
    prompt = select_prompt(prompts)
    if prompt is None:
        return
    print('-' * 40)
    print(f"제목: {prompt['title']}")
    print(f"카테고리: {prompt['category']}")
    favorite = '⭐' if prompt['favorite'] else '미등록'
    print(f'즐겨찾기: {favorite}')
    print('내용:')
    print(prompt['content'])
    print('-' * 40)


def toggle_favorite(prompts: list[dict]) -> None:
    print('\n=== 즐겨찾기 관리 ===')
    prompt = select_prompt(prompts)
    if prompt is None:
        return
    prompt['favorite'] = not prompt['favorite']
    action = '추가' if prompt['favorite'] else '해제'
    print(f"'{prompt['title']}' 즐겨찾기를 {action}했습니다!")


def show_favorites(prompts: list[dict]) -> None:
    print('\n=== 즐겨찾기 목록 ===')
    items = []
    for number, prompt in enumerate(prompts, start=1):
        if prompt['favorite']:
            items.append((number, prompt))
    print_prompt_list(items)


def show_menu() -> None:
    print('\n=== 나만의 프롬프트 관리 ===')
    print('1. 프롬프트 추가')
    print('2. 프롬프트 목록')
    print('3. 카테고리별 조회')
    print('4. 프롬프트 검색')
    print('5. 프롬프트 상세 보기')
    print('6. 즐겨찾기 관리')
    print('7. 즐겨찾기 목록')
    print('0. 종료')


def main() -> None:
    prompts = create_initial_prompts()
    while True:
        show_menu()
        choice = input('선택: ').strip()
        if choice == '0':
            print('프로그램을 종료합니다.')
            break
        elif choice == '1':
            add_prompt(prompts)
        elif choice == '2':
            show_list(prompts)
        elif choice == '3':
            show_by_category(prompts)
        elif choice == '4':
            search_prompts(prompts)
        elif choice == '5':
            show_detail(prompts)
        elif choice == '6':
            toggle_favorite(prompts)
        elif choice == '7':
            show_favorites(prompts)
        else:
            print('잘못된 메뉴 번호입니다. 다시 선택해주세요.')


if __name__ == '__main__':
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print('\n입력이 중단되어 프로그램을 종료합니다.')
