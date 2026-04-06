from pydantic import BaseModel, Field, ConfigDict, EmailStr
from datetime import datetime

class CriarUser(BaseModel):
    email: EmailStr = Field(..., description="E-mail do usuario")

    full_name: str | None = Field(default=None, description="Nome completo")
    phone: str | None = Field(default=None, description="Telefone")

    password: str = Field(..., min_length=8, description="Senha minima de 8")

    consent_given: bool = Field(..., description="Consentimento de dados")

class AtualizarUser(BaseModel):
    full_name: str | None = Field(default=None, description="Nome completo")
    phone: str | None = Field(default=None, description="Telefone")

class UserResposta(BaseModel):
    id: str = Field(..., description="ID unico")
    email: str = Field(..., description="Email")
    role: str = Field(..., description="User ou admin role flag")
    full_name: str | None = Field(default=None, description="Nome")
    phone: str | None = Field(default=None, description="Numero")
    consent_given: bool = Field(..., description="Check do LGPD")
    mfa_enabled: bool = Field(..., description="Seguranca duas etapas ligada")
    created_at: datetime = Field(..., description="quando criou a conta")
    updated_at: datetime = Field(..., description="Quando atualizou as configs")

    model_config = ConfigDict(from_attributes=True)
