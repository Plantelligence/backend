# rotas de auth: registro, login, MFA e sessão

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict

from app.core.rate_limit import limiter, login_limit
from app.services.auth_service import (
    complete_first_access,
    complete_mfa,
    confirm_registration_email,
    finalize_registration,
    initiate_mfa_method,
    login_user,
    start_first_access,
    refresh_session,
    register_user,
    request_password_reset,
    reset_password,
    revoke_session,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class FlexiblePayload(BaseModel):
    model_config = ConfigDict(extra="allow")


class ConfirmRegistrationRequest(BaseModel):
    challengeId: str
    code: str


class FinalizeRegistrationRequest(BaseModel):
    otpSetupId: str
    otpCode: str


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    email: str
    password: str


class InitiateMfaRequest(BaseModel):
    sessionId: str
    method: str


class VerifyMfaRequest(BaseModel):
    sessionId: str
    method: str
    code: str
    otpEnrollmentId: str | None = None


class RefreshRequest(BaseModel):
    refreshToken: str


class LogoutRequest(BaseModel):
    refreshToken: str | None = None
    accessJti: str | None = None
    userId: str | None = None


class PasswordResetConfirmRequest(BaseModel):
    token: str
    newPassword: str


class FirstAccessStartRequest(BaseModel):
    token: str


class FirstAccessCompleteRequest(BaseModel):
    token: str
    enrollmentId: str
    newPassword: str
    otpCode: str


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: FlexiblePayload) -> Any:
    try:
        return register_user(payload.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/register/confirm")
def register_confirm(payload: ConfirmRegistrationRequest, request: Request) -> Any:
    try:
        return confirm_registration_email(
            {
                "challengeId": payload.challengeId,
                "code": payload.code,
                "ipAddress": _client_ip(request),
            }
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/register/otp")
def register_otp(payload: FinalizeRegistrationRequest, request: Request) -> dict[str, Any]:
    try:
        user = finalize_registration(
            {
                "otpSetupId": payload.otpSetupId,
                "otpCode": payload.otpCode,
                "ipAddress": _client_ip(request),
            }
        )
        return {"message": "Cadastro finalizado com sucesso.", "user": user}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/login")
@limiter.limit(login_limit)
def login(payload: LoginRequest, request: Request) -> dict[str, Any]:
    try:
        result = login_user({**payload.model_dump(), "ipAddress": _client_ip(request)})
        if result.get("mfaRequired"):
            return result
        # caso futuro sem MFA: normaliza tokens no mesmo formato do mfa/verify
        tokens_raw = result.get("tokens") or {}
        access = tokens_raw.get("access") or {}
        refresh = tokens_raw.get("refresh") or {}
        return {
            "mfaRequired": False,
            "user": result.get("user"),
            "tokens": {
                "accessToken": access.get("token"),
                "accessExpiresAt": access.get("expiresAt"),
                "accessJti": access.get("jti"),
                "refreshToken": refresh.get("token"),
                "refreshExpiresAt": refresh.get("expiresAt"),
                "refreshJti": refresh.get("jti"),
            },
            "passwordExpired": result.get("passwordExpired", False),
        }
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/mfa/initiate")
def mfa_initiate(payload: InitiateMfaRequest, request: Request) -> Any:
    mfa_payload = {"sessionId": payload.sessionId, "method": payload.method, "ipAddress": _client_ip(request)}
    try:
        return initiate_mfa_method(mfa_payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/mfa/verify")
def mfa_verify(payload: VerifyMfaRequest, request: Request) -> dict[str, Any]:
    try:
        result = complete_mfa(
            {
                "sessionId": payload.sessionId,
                "method": payload.method,
                "code": payload.code,
                "otpEnrollmentId": payload.otpEnrollmentId,
                "ipAddress": _client_ip(request),
            }
        )
        return {
            "user": result["user"],
            "tokens": {
                "accessToken": result["tokens"]["access"]["token"],
                "accessExpiresAt": result["tokens"]["access"]["expiresAt"],
                "accessJti": result["tokens"]["access"]["jti"],
                "refreshToken": result["tokens"]["refresh"]["token"],
                "refreshExpiresAt": result["tokens"]["refresh"]["expiresAt"],
                "refreshJti": result["tokens"]["refresh"]["jti"],
            },
            "passwordExpired": result["passwordExpired"],
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/refresh")
def refresh(payload: RefreshRequest) -> dict[str, Any]:
    try:
        result = refresh_session({"refreshToken": payload.refreshToken})
        return {
            "user": result["user"],
            "tokens": {
                "accessToken": result["tokens"]["access"]["token"],
                "accessExpiresAt": result["tokens"]["access"]["expiresAt"],
                "accessJti": result["tokens"]["access"]["jti"],
                "refreshToken": result["tokens"]["refresh"]["token"],
                "refreshExpiresAt": result["tokens"]["refresh"]["expiresAt"],
                "refreshJti": result["tokens"]["refresh"]["jti"],
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: LogoutRequest) -> Response:
    try:
        revoke_session(payload.model_dump())
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/password-reset/request")
def password_reset_request(payload: FlexiblePayload) -> dict[str, Any]:
    # resposta genérica para não vazar se o e-mail existe
    try:
        result = request_password_reset(payload.model_dump())
        return {
            "message": "Se existir uma conta, o e-mail de recuperacao foi enviado.",
            "mock": result,
        }
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/password-reset/confirm")
def password_reset_confirm(payload: PasswordResetConfirmRequest) -> dict[str, str]:
    try:
        reset_password({"token": payload.token, "newPassword": payload.newPassword})
        return {"message": "Senha redefinida com sucesso."}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/first-access/start")
def first_access_start(payload: FirstAccessStartRequest, request: Request) -> dict[str, Any]:
    try:
        return start_first_access({"token": payload.token, "ipAddress": _client_ip(request)})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/first-access/complete")
def first_access_complete(payload: FirstAccessCompleteRequest, request: Request) -> dict[str, str]:
    try:
        complete_first_access(
            {
                "token": payload.token,
                "enrollmentId": payload.enrollmentId,
                "newPassword": payload.newPassword,
                "otpCode": payload.otpCode,
                "ipAddress": _client_ip(request),
            }
        )
        return {"message": "Primeiro acesso concluido com sucesso."}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
