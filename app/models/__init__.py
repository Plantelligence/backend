# importar este módulo registra todos os modelos no mapper do SQLAlchemy

from app.models.alertas import Alertas
from app.models.dispositivo import Dispositivo
from app.models.estufa import Estufa
from app.models.greenhouse import Greenhouse
from app.models.historico import Historico
from app.models.login_session import LoginSession
from app.models.mfa_challenge import MfaChallenge
from app.models.otp_enrollment import OtpEnrollment
from app.models.preset import Preset
from app.models.registration_challenge import RegistrationChallenge
from app.models.security_log import SecurityLog
from app.models.token import Token
from app.models.user import User

__all__ = [
    "Alertas",
    "Dispositivo",
    "Estufa",
    "Greenhouse",
    "Historico",
    "LoginSession",
    "MfaChallenge",
    "OtpEnrollment",
    "Preset",
    "RegistrationChallenge",
    "SecurityLog",
    "Token",
    "User",
]