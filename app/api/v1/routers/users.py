from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.core.dependencies import get_current_user
from app.services.auth_service import (
    change_password,
    complete_user_otp_enrollment,
    get_user_profile,
    request_data_deletion,
    start_user_otp_enrollment,
    update_user_profile,
)
from app.services.mfa_service import create_mfa_challenge
from app.services.security_logger import ADMIN_RELEVANT_ACTIONS, get_security_logs

router = APIRouter(prefix="/api/users", tags=["users"])


class UpdateProfileRequest(BaseModel):
    fullName: str | None = None
    phone: str | None = None
    consentGiven: bool | None = None
    organizationName: str | None = None


class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str
    mfaCode: str | None = None
    challengeId: str | None = None
    verification: dict | None = None

    def resolved_verification(self) -> dict:
        # aceita tanto {verification: {...}} quanto os campos avulsos mfaCode/challengeId
        if self.verification:
            return self.verification
        if self.challengeId:
            return {"challengeId": self.challengeId, "code": self.mfaCode or ""}
        if self.mfaCode:
            return {"otpCode": self.mfaCode}
        return {}


class DeletionRequest(BaseModel):
    reason: str | None = None


class ConfirmOtpEnrollmentRequest(BaseModel):
    enrollmentId: str
    code: str | None = None
    otpCode: str | None = None

    def resolved_code(self) -> str:
        return (self.code or self.otpCode or "").strip()


@router.get("/me")
async def me(request: Request, user: dict = Depends(get_current_user)) -> dict:
    try:
        profile = get_user_profile(user["id"])
        return {"user": profile, "requiresPasswordReset": bool(user.get("requiresPasswordReset"))}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/me")
async def update_me(payload: UpdateProfileRequest, user: dict = Depends(get_current_user)) -> dict:
    try:
        updated = update_user_profile(
            {
                "userId": user["id"],
                "fullName": payload.fullName,
                "phone": payload.phone,
                "consentGiven": payload.consentGiven,
                "organizationName": payload.organizationName,
            }
        )
        return {"user": updated}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/change-password")
async def change_password_endpoint(payload: ChangePasswordRequest, request: Request, user: dict = Depends(get_current_user)) -> dict:
    try:
        change_password(
            {
                "userId": user["id"],
                "currentPassword": payload.currentPassword,
                "newPassword": payload.newPassword,
                "verification": payload.resolved_verification(),
                "ipAddress": request.client.host if request.client else None,
            }
        )
        return {"message": "Senha alterada com sucesso."}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/change-password/challenge")
async def create_password_challenge(user: dict = Depends(get_current_user)) -> dict:
    try:
        challenge = create_mfa_challenge(get_user_profile(user["id"]), metadata={"action": "password_change"})
        return {
            "challengeId": challenge["challengeId"],
            "expiresAt": challenge["expiresAt"],
            "debugCode": challenge.get("debugCode"),
        }
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/deletion-request")
async def deletion_request(payload: DeletionRequest, user: dict = Depends(get_current_user)) -> dict:
    try:
        request_data_deletion({"userId": user["id"], "reason": payload.reason})
        return {"message": "Solicitacao de exclusao registrada."}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/me/mfa/otp/start")
async def otp_start(request: Request, user: dict = Depends(get_current_user)) -> dict:
    try:
        return start_user_otp_enrollment({"userId": user["id"], "ipAddress": request.client.host if request.client else None})
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/me/mfa/otp/confirm")
async def otp_confirm(payload: ConfirmOtpEnrollmentRequest, request: Request, user: dict = Depends(get_current_user)) -> dict:
    try:
        profile = complete_user_otp_enrollment(
            {
                "userId": user["id"],
                "enrollmentId": payload.enrollmentId,
                "code": payload.resolved_code(),
                "ipAddress": request.client.host if request.client else None,
            }
        )
        return {"user": profile}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/logs")
async def logs(limit: int = 500, user: dict = Depends(get_current_user)) -> dict:
    # admin vê tudo; usuário comum só vê os próprios eventos
    try:
        filter_user_id = None if user.get("role") == "Admin" else user["id"]
        return {
            "logs": get_security_logs(
                limit,
                user_id=filter_user_id,
                allowed_actions=ADMIN_RELEVANT_ACTIONS,
            )
        }
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
