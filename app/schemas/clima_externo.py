from datetime import datetime

from pydantic import BaseModel, Field


class ClimaExternoResposta(BaseModel):
    """Resumo do clima externo atual para exibicao no dashboard da estufa."""

    cidade: str = Field(..., description="Cidade consultada")
    estado: str = Field(..., description="Estado consultado (UF)")
    temperatura: float = Field(..., description="Temperatura ambiente em graus Celsius")
    umidade: int = Field(..., description="Umidade relativa do ar em porcentagem")
    descricao: str = Field(..., description="Descricao textual da condicao do clima")
    condicao: str = Field(..., description="Categoria geral da condicao climatica")
    atualizado_em: datetime = Field(..., description="Data/hora UTC da atualizacao")
