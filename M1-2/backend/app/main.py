from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .config import get_settings
from .ports import DuplicateRecord, GenerationUnavailable, NotFound, StorageUnavailable


ERRORS = {
    DuplicateRecord: (409, 'A record already exists for this date.'),
    NotFound: (404, 'The requested resource was not found.'),
    StorageUnavailable: (503, 'Storage is temporarily unavailable.'),
    GenerationUnavailable: (502, 'Answer generation is temporarily unavailable.'),
}


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title='Story Reading Analytics', debug=False)
    @application.middleware('http')
    async def protect_unexpected_errors(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception:
            return JSONResponse(status_code=500, content={'detail': 'An unexpected error occurred.'})

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=['GET', 'POST', 'PUT', 'DELETE'],
        allow_headers=['Content-Type'],
    )

    async def safe_error(request: Request, exc: Exception):
        status, detail = ERRORS.get(type(exc), (500, 'An unexpected error occurred.'))
        return JSONResponse(status_code=status, content={'detail': detail})

    for error_type in (*ERRORS, Exception):
        application.add_exception_handler(error_type, safe_error)
    from .summary.router import router as summary_router
    from .data.router import router as data_router
    application.include_router(summary_router)
    application.include_router(data_router)
    from .chat.router import router as chat_router
    application.include_router(chat_router)
    from .conversations.router import router as conversation_router
    application.include_router(conversation_router)
    return application


app = create_app()
