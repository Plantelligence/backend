from pydantic import BaseModel, ConfigDict
from typing import Optional


class CriarRelatorio(BaseModel):
    periodo_inicio: str
    periodo_fim: str
    avg_temperatura: Optional[str] = None
    avg_umidade: Optional[str] = None
    avg_umidade_solo: Optional[str] = None
    avg_luminosidade: Optional[str] = None
    resumo: Optional[str] = None


class GerarRelatorioRequest(BaseModel):
    periodo_inicio: str
    periodo_fim: str


class RelatorioResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    estufa_id: str
    periodo_inicio: str
    periodo_fim: str
    avg_temperatura: Optional[str] = None
    avg_umidade: Optional[str] = None
    avg_umidade_solo: Optional[str] = None
    avg_luminosidade: Optional[str] = None
    resumo: Optional[str] = None
    criado_em: str
    criado_por_id: Optional[str] = None
    auto_generated: bool = False
    alert_count: int = 0
