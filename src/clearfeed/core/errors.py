"""Application errors and the handlers that render them.

Every error response has the shape {"error": {"code": ..., "message": ...}}.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message)


# Fields whose validation errors have their own code instead of VALIDATION_ERROR.
FIELD_ERROR_CODES = {
    ("body", "timezone"): "INVALID_TIMEZONE",
}


def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    # e.g. "body.start: Input should be in a valid time format"
    message = "; ".join(
        f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in errors
    )
    codes = {FIELD_ERROR_CODES.get(tuple(err["loc"][:2]), "VALIDATION_ERROR") for err in errors}
    code = codes.pop() if len(codes) == 1 else "VALIDATION_ERROR"
    return error_response(422, code, message)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
