from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime

# Schema basico para estabelecer limites
class Faixas(BaseModel):
    min: float = Field(..., description="Minimo aceitavel para a faixa")
    max: float = Field(..., description="Maximo aceitavel para a faixa")

# Estrutura JSON espelhada em modelo Pydantic para interagir com o Model do PostgreSQL
# Agrupa os 5 parametros de avaliacao da seguranca da planta (baixo a alto)
class FaixasMetricas(BaseModel):
    critico_baixo: Faixas
    alerta_baixo: Faixas
    ideal: Faixas
    alerta_alto: Faixas
    critico_alto: Faixas

# Payload esperado na hora de criar um novo preset
class CriarPreset(BaseModel):
    # Field(...) indica que a variavel e obrigatoria (sem default).
    sistema: bool = Field(..., description="verifica se e um preset do sistema")
    user_id: str | None = Field(default=None, description="ID do usuario caso seja um preset do usuario")
    
    # Valida direto do payload para impedir que nomes de cultura vazios cheguem ao backend
    nome_cultura: str = Field(..., min_length=2, description="Nome da cultura")
    tipo_cultura: str = Field(..., min_length=2, description="Tipo da cultura")
    descricao: str | None = Field(default=None, description="Descricao do preset")
    
    # Insere blocos JSON validados
    temperatura: FaixasMetricas = Field(..., description="Faixas de temperatura")
    umidade: FaixasMetricas = Field(..., description="Faixas de umidade")
    luminosidade: FaixasMetricas = Field(..., description="Faixas de luminosidade")


# Para atualizacoes (PUT/PATCH), tudo pode ser opcional.
# Isso garante que so enviemos os dados que queremos sobrepor no banco.
class AtualizarPreset(BaseModel):
    sistema: bool | None = Field(default=None, description="verifica se e um preset do sistema")
    user_id: str | None = Field(default=None, description="ID do usuario")
    nome_cultura: str | None = Field(default=None, description="Nome da cultura")
    tipo_cultura: str | None = Field(default=None, description="Tipo da cultura")
    descricao: str | None = Field(default=None, description="Descricao do preset")
    temperatura: FaixasMetricas | None = Field(default=None, description="Faixas de temperatura")
    umidade: FaixasMetricas | None = Field(default=None, description="Faixas de umidade")
    luminosidade: FaixasMetricas | None = Field(default=None, description="Faixas de luminosidade")


# O que a API devolve para o front: igual ao Criar, mas com IDs e Timestamps para controle
class PresetResposta(BaseModel):
    id: str = Field(..., description="ID do preset")
    sistema: bool = Field(..., description="verifica se e um preset do sistema")
    user_id: str | None = Field(default=None, description="ID do usuario caso seja um preset do usuario")
    nome_cultura: str = Field(..., description="Nome da cultura")
    tipo_cultura: str = Field(..., description="Tipo da cultura")
    descricao: str | None = Field(default=None, description="Descricao do preset")
    temperatura: FaixasMetricas = Field(..., description="Faixas de temperatura")
    umidade: FaixasMetricas = Field(..., description="Faixas de umidade")
    luminosidade: FaixasMetricas = Field(..., description="Faixas de luminosidade")
    created_at: datetime = Field(..., description="Data e hora da criacao")
    updated_at: datetime = Field(..., description="Data e hora da atualizacao")

    # Isso diz ao Pydantic para espelhar a leitura se eu enviar diretamente
    # as consultas SQL do SQLAlchemy. Nao e necessario converter pra dict().
    model_config = ConfigDict(from_attributes=True)
