"""외부 패키지 없이 실행하는 콘솔 프로그램 회귀 테스트."""
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_app():
    spec = importlib.util.spec_from_file_location('prompt_manager', ROOT / 'main.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke(function, *args, inputs=()):
    output = io.StringIO()
    with patch('builtins.input', side_effect=inputs), contextlib.redirect_stdout(output):
        result = function(*args)
    return result, output.getvalue()


class MenuTests(unittest.TestCase):
    def test_invalid_choices_return_to_menu_and_zero_exits(self):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'main.py')],
                                input='9\ntext\n\n-1\n0\n', text=True,
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count('=== 나만의 프롬프트 관리 ==='), 5)
        self.assertIn('잘못된 메뉴', result.stdout)
        self.assertIn('종료합니다', result.stdout)


class DataTests(unittest.TestCase):
    def test_initial_data_is_complete_and_fresh_each_run(self):
        app = load_app()
        self.assertTrue(hasattr(app, 'create_initial_prompts'))
        prompts = app.create_initial_prompts()
        self.assertGreaterEqual(len(prompts), 3)
        for prompt in prompts:
            self.assertTrue(prompt['title'].strip())
            self.assertTrue(prompt['content'].strip())
            self.assertIn(prompt['category'], app.CATEGORIES)
            self.assertIsInstance(prompt['favorite'], bool)
        prompts[0]['title'] = 'changed'
        prompts[0]['favorite'] = True
        fresh = app.create_initial_prompts()
        self.assertNotEqual(fresh[0]['title'], 'changed')
        self.assertFalse(fresh[0]['favorite'])


class InputTests(unittest.TestCase):
    def test_required_text_retries_whitespace(self):
        app = load_app()
        self.assertTrue(hasattr(app, 'read_required_text'))
        result, output = invoke(app.read_required_text, '제목: ', inputs=['', '  ', ' 제목 '])
        self.assertEqual(result, '제목')
        self.assertIn('입력', output)

    def test_category_retries_invalid_choices(self):
        app = load_app()
        self.assertTrue(hasattr(app, 'select_category'))
        result, output = invoke(app.select_category, inputs=['x', '1.5', '-1', '0', '7', '²', '2'])
        self.assertEqual(result, '이미지 생성')
        self.assertIn('카테고리', output)


class AddTests(unittest.TestCase):
    def test_add_preserves_existing_data_and_defaults_favorite_false(self):
        app = load_app()
        self.assertTrue(hasattr(app, 'add_prompt'))
        prompts = app.create_initial_prompts()
        original = [dict(prompt) for prompt in prompts]
        invoke(app.add_prompt, prompts, inputs=[' ', '새 제목', '', '새 내용', '1'])
        self.assertEqual(prompts[:-1], original)
        self.assertEqual(prompts[-1], {'title': '새 제목', 'content': '새 내용',
                                       'category': '텍스트 생성', 'favorite': False})


def sample_prompts():
    return [
        {'title': '첫 제목', 'content': '첫 내용', 'category': '텍스트 생성', 'favorite': False},
        {'title': '둘째 제목', 'content': '둘째 내용', 'category': '이미지 생성', 'favorite': True},
        {'title': 'Python 튜터', 'content': '학습 요약', 'category': '텍스트 생성', 'favorite': False},
    ]


class ListTests(unittest.TestCase):
    def test_list_shows_numbers_categories_and_favorites(self):
        app = load_app()
        self.assertTrue(hasattr(app, 'show_list'))
        _, output = invoke(app.show_list, sample_prompts())
        self.assertIn('1. [텍스트 생성] 첫 제목', output)
        self.assertIn('2. [이미지 생성] 둘째 제목 ⭐', output)
        self.assertIn('3. [텍스트 생성] Python 튜터', output)
        self.assertIn('총 3개', output)

    def test_empty_list_reports_no_prompts(self):
        app = load_app()
        self.assertTrue(hasattr(app, 'show_list'))
        _, output = invoke(app.show_list, [])
        self.assertIn('없습니다', output)


class CategoryTests(unittest.TestCase):
    def test_category_filter_preserves_original_numbers(self):
        app = load_app()
        self.assertTrue(hasattr(app, 'show_by_category'))
        _, output = invoke(app.show_by_category, sample_prompts(), inputs=['1'])
        self.assertIn('1. [텍스트 생성] 첫 제목', output)
        self.assertIn('3. [텍스트 생성] Python 튜터', output)
        self.assertNotIn('둘째 제목', output)
        self.assertIn('총 2개', output)

    def test_empty_category_reports_no_prompts(self):
        app = load_app()
        self.assertTrue(hasattr(app, 'show_by_category'))
        _, output = invoke(app.show_by_category, sample_prompts(), inputs=['6'])
        self.assertIn('없습니다', output)


class SearchTests(unittest.TestCase):
    def test_search_matches_title_or_content_case_insensitively(self):
        app = load_app()
        self.assertTrue(hasattr(app, 'search_prompts'))
        for query, expected, absent in [('pYtHoN', '3. [텍스트 생성] Python 튜터', '첫 제목'),
                                        ('둘째 내용', '2. [이미지 생성] 둘째 제목', 'Python 튜터')]:
            with self.subTest(query=query):
                _, output = invoke(app.search_prompts, sample_prompts(), inputs=[query])
                self.assertIn(expected, output)
                self.assertNotIn(absent, output)

    def test_blank_search_retries_and_no_match_is_reported(self):
        app = load_app()
        self.assertTrue(hasattr(app, 'search_prompts'))
        _, output = invoke(app.search_prompts, sample_prompts(), inputs=[' ', '없는키워드'])
        self.assertIn('없습니다', output)
        self.assertNotIn('첫 제목', output)


class DetailTests(unittest.TestCase):
    def test_detail_displays_all_fields_and_entire_multiline_content(self):
        app = load_app()
        self.assertTrue(hasattr(app, 'show_detail'))
        prompts = sample_prompts()
        prompts[2]['content'] = '첫 줄\n둘째 줄\n마지막 줄'
        for choice, expected in [('1', '첫 제목'), ('3', '첫 줄\n둘째 줄\n마지막 줄')]:
            _, output = invoke(app.show_detail, prompts, inputs=[choice])
            self.assertIn(expected, output)
            self.assertIn('텍스트 생성', output)
            self.assertIn('즐겨찾기:', output)
        _, output = invoke(app.show_detail, prompts, inputs=['2'])
        self.assertIn('⭐', output)

    def test_invalid_detail_numbers_do_not_select_a_prompt(self):
        app = load_app()
        self.assertTrue(hasattr(app, 'show_detail'))
        for value in ['', 'abc', '1.5', '-1', '0', '4', '²', '9' * 5000]:
            with self.subTest(value=value[:20]):
                _, output = invoke(app.show_detail, sample_prompts(), inputs=[value])
                self.assertIn('잘못된', output)
                self.assertNotIn('첫 내용', output)
        _, output = invoke(app.show_detail, [], inputs=['1'])
        self.assertIn('없습니다', output)


class ToggleTests(unittest.TestCase):
    def test_toggle_twice_restores_state_and_updates_other_views(self):
        app = load_app()
        self.assertTrue(hasattr(app, 'toggle_favorite'))
        prompts = sample_prompts()
        invoke(app.toggle_favorite, prompts, inputs=['3'])
        self.assertTrue(prompts[2]['favorite'])
        _, output = invoke(app.show_list, prompts)
        self.assertIn('3. [텍스트 생성] Python 튜터 ⭐', output)
        _, output = invoke(app.show_detail, prompts, inputs=['3'])
        self.assertIn('즐겨찾기: ⭐', output)
        invoke(app.toggle_favorite, prompts, inputs=['3'])
        self.assertFalse(prompts[2]['favorite'])
        self.assertEqual(prompts, sample_prompts())

    def test_invalid_favorite_number_does_not_change_data(self):
        app = load_app()
        self.assertTrue(hasattr(app, 'toggle_favorite'))
        prompts = sample_prompts()
        for choice in ['0', '-1', '4', 'x', '1.5', '']:
            _, output = invoke(app.toggle_favorite, prompts, inputs=[choice])
            self.assertIn('잘못된', output)
            self.assertEqual(prompts, sample_prompts())


class FavoriteListTests(unittest.TestCase):
    def test_favorite_list_filters_and_preserves_numbers(self):
        app = load_app()
        self.assertTrue(hasattr(app, 'show_favorites'))
        prompts = sample_prompts()
        _, output = invoke(app.show_favorites, prompts)
        self.assertIn('2. [이미지 생성] 둘째 제목 ⭐', output)
        self.assertNotIn('첫 제목', output)
        self.assertNotIn('Python 튜터', output)
        invoke(app.toggle_favorite, prompts, inputs=['3'])
        _, output = invoke(app.show_favorites, prompts)
        self.assertIn('총 2개', output)
        invoke(app.toggle_favorite, prompts, inputs=['2'])
        invoke(app.toggle_favorite, prompts, inputs=['3'])
        _, output = invoke(app.show_favorites, prompts)
        self.assertIn('없습니다', output)


class ConsoleFlowTests(unittest.TestCase):
    def run_console(self, text):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'main.py')],
                                input=text, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_all_menus_share_data_and_restart_resets_it(self):
        output = self.run_console(
            '1\n스크린샷용 프롬프트\n회의 내용을 세 문장으로 요약해주세요.\n1\n'
            '2\n3\n1\n4\n세 문장\n5\n4\n6\n4\n7\n5\n4\n6\n4\n7\n0\n'
        )
        self.assertIn('프롬프트가 추가되었습니다', output)
        self.assertIn('총 4개의 프롬프트', output)
        self.assertIn('4. [텍스트 생성] 스크린샷용 프롬프트', output)
        self.assertIn('내용:\n회의 내용을 세 문장으로 요약해주세요.', output)
        favorite_section = output.split('=== 즐겨찾기 목록 ===')[1]
        self.assertIn('4. [텍스트 생성] 스크린샷용 프롬프트 ⭐', favorite_section)
        self.assertIn('즐겨찾기: ⭐', favorite_section)
        last_favorites = output.split('=== 즐겨찾기 목록 ===')[2]
        self.assertIn('프롬프트가 없습니다', last_favorites)
        fresh = self.run_console('2\n7\n0\n')
        self.assertIn('총 3개의 프롬프트', fresh)
        self.assertNotIn('스크린샷용 프롬프트', fresh)
        self.assertIn('프롬프트가 없습니다', fresh.split('=== 즐겨찾기 목록 ===')[1])

    def test_eof_at_menu_or_during_add_exits_without_traceback(self):
        for text in ['', '1\n제목\n']:
            with self.subTest(text=text):
                output = self.run_console(text)
                self.assertIn('종료합니다', output)
