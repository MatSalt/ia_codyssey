"""Python Vercel Function, also used unchanged by the local Flask server."""
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from services.coach import CoachError, rewrite_text, validate_input

PUBLIC = Path(__file__).resolve().parents[1] / 'public'
app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 24000
app.json.ensure_ascii = False


@app.post('/api/rewrite')
def rewrite():
    text = validate_input(request.get_json(silent=True))
    return jsonify(rewrite_text(text))


@app.errorhandler(CoachError)
def coach_error(error):
    return jsonify(error={'code': error.code, 'message': error.message}), error.status


@app.errorhandler(HTTPException)
def http_error(error):
    messages = {404: '요청한 페이지를 찾을 수 없어요.', 405: '지원하지 않는 요청 방식이에요.',
                413: '입력한 내용이 너무 커요. 1,500자 이내로 줄여 주세요.'}
    return jsonify(error={'code': f'HTTP_{error.code}', 'message': messages.get(error.code, '요청을 확인해 주세요.')}), error.code


@app.after_request
def response_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/')
def home():
    return send_from_directory(PUBLIC, 'index.html')


@app.get('/css/<path:filename>')
def css(filename):
    return send_from_directory(PUBLIC / 'css', filename)


@app.get('/js/<path:filename>')
def javascript(filename):
    return send_from_directory(PUBLIC / 'js', filename)


@app.get('/favicon.svg')
def favicon():
    return send_from_directory(PUBLIC, 'favicon.svg')
