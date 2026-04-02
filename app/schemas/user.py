from pydantic import BaseModel, Field, ConfigDict, EmailStr
from datetime import datetime

# Schema para endpoint de criar usuario (registro inicial da conta)
class CriarUser(BaseModel):
    # O pydantic ja valida aqui se tem um @, se termina com ".algo" e 
    # barra lixo antes mesmo de tentar jogar no banco de dados.
    email: EmailStr = Field(..., description="E-mail do usuario")
    
    # Campo opcional que pode iniciar nao preenchido
    full_name: str | None = Field(default=None, description="Nome completo")
    phone: str | None = Field(default=None, description="Telefone")
    
    # Filtro primario da senha p/ ser no minimo razoavel de forte
    password: str = Field(..., min_length=8, description="Senha minima de 8")
    
    # Checkbox que o usuario clica dizendo q aceita as LGPD padroes
    consent_given: bool = Field(..., description="Consentimento de dados")

# Schema de Endpoint separado para Edicao de coisas apenas como telefone/nome.
# Email tem um fluxo inteiro (verificacao e senha tbm, entao essas coisas ficam de fora daqui)
class AtualizarUser(BaseModel):
    full_name: str | None = Field(default=None, description="Nome completo")
    phone: str | None = Field(default=None, description="Telefone")

# O response model que devolve a conta do usuario na tela MEU PERFIL (exemplo) do app.
# Note que a password (nem sequer o seu hash gerado) nunca volta na response model 
# porque o front end simplesmente nao pode (e nao deve) ter acesso a esse hash para seguranca de ataque
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

    # Como sempre, do alchemy -> pydantic json = True
    model_config = ConfigDict(from_attributes=True)
