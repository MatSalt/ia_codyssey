"""Safe public errors and request correlation; never echo request secrets."""
from uuid import uuid4
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str = '요청을 처리할 수 없습니다.', *, details=None, retryable=False):
        self.status, self.code, self.message = status, code, message
        self.details, self.retryable = details or {}, retryable


def envelope(request: Request, data):
    return {'data': data, 'request_id': request.state.request_id}


def install_errors(app):
    @app.middleware('http')
    async def correlation(request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        if request.url.path == '/api' or request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Request-ID'] = request.state.request_id
        return response

    @app.exception_handler(APIError)
    async def api_error(request, exc):
        return JSONResponse({'error': {'code': exc.code, 'message': exc.message,
                            'retryable': exc.retryable, 'details': exc.details},
                            'request_id': request.state.request_id}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return await api_error(request, APIError(422, 'VALIDATION_ERROR', '입력값을 확인해주세요.'))

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        if not request.url.path.startswith('/api'):
            return JSONResponse({'detail': exc.detail}, status_code=exc.status_code, headers=exc.headers)
        code = {404: 'RESOURCE_NOT_FOUND', 401: 'AUTH_REQUIRED', 422: 'VALIDATION_ERROR'}.get(exc.status_code, 'VALIDATION_ERROR')
        return await api_error(request, APIError(exc.status_code, code))
