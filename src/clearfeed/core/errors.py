"""Application errors and the handlers that render them.

Every error response has the shape {"error": {"code": ..., "message": ...}}.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_response(
    status_code: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )


def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message)


# Framework errors such as unknown routes or wrong methods.
HTTP_ERROR_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


def _handle_http_error(_: Request, exc: HTTPException) -> JSONResponse:
    code = HTTP_ERROR_CODES.get(exc.status_code, "HTTP_ERROR")
    return error_response(exc.status_code, code, str(exc.detail), exc.headers)


# Fields whose validation errors have their own code instead of VALIDATION_ERROR.
FIELD_ERROR_CODES = {
    ("body", "timezone"): "INVALID_TIMEZONE",
    ("path", "ticket_id"): "INVALID_TICKET_ID",
}


def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    # e.g. "body.start: time must be a string in HH:MM format"
    message = "; ".join(
        f"{'.'.join(str(part) for part in err['loc'])}: {err['msg'].removeprefix('Value error, ')}"
        for err in errors
    )
    codes = {FIELD_ERROR_CODES.get(tuple(err["loc"][:2]), "VALIDATION_ERROR") for err in errors}
    code = codes.pop() if len(codes) == 1 else "VALIDATION_ERROR"
    return error_response(422, code, message)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(HTTPException, _handle_http_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
