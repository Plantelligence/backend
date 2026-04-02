from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import TYPE_CHECKING, Optional

# Estrutura do typescript: resolvemos importar apenas num ambiente de verificacao padrao
# Evita loop de referencia circular na tentativa de rodar as schemas e travar o backend.
if TYPE_CHECKING:
    from app.schemas.preset import PresetResposta

# A Criacao permite receber os componentes que o front-end solicita nativamente
class CriarEstufa(BaseModel):
    nome: str = Field(..., description="Nome da estufa")
    
    # Campo validado limitando o parametro exatamente entre MIN=2 e MAX=2  (ex. MG)
    estado: str = Field(..., description="Estado da estufa", min_length=2, max_length=2)
    cidade: str = Field(..., description="Cidade da estufa")
    
    # Permite anexar a estufa ja rodando pre set de cara, 
    # mas tambem e aceito "None" em uma adicao futura
    preset_id: str | None = Field(default=None, description="ID do preset")

# Model parcial para Put de forma que qualquer dado alterado sobrepoe ao atual
# Se nome vier default=none, ele ignora. O que houver, ele atualiza no sql
class AtualizarEstufa(BaseModel):
    nome: str = Field(description="Nome da estufa", default=None)
    estado: str = Field(description="Estado da estufa", default=None, min_length=2, max_length=2)
    cidade: str = Field(description="Cidade da estufa", default=None)
    preset_id: str | None = Field(default=None, description="ID do preset")
    
# Padrao de visualizacao final da Request 
class EstufaResposta(BaseModel):
    id: str = Field(..., description="ID da estufa")
    nome: str = Field(..., description="Nome da estufa")
    estado: str = Field(..., description="Estado da estufa", min_length=2, max_length=2)
    cidade: str = Field(..., description="Cidade da estufa")
    created_at: datetime = Field(..., description="Data e hora da criacao")
    updated_at: datetime = Field(..., description="Data e hora da atualizacao")
    user_id: str = Field(..., description="ID do usuario")
    preset_id: str | None = Field(default=None, description="ID do preset")
    
    # Anexacao do esquema do PresetResposta para o front end poder listar os
    # presets de uma Estufa especificos chamando GET/Estufas num endpoint so, 
    # sem precisar ir buscar id a id via id na resposta
    preset: Optional[PresetResposta] = Field(default=None, description="Preset vinculado (se houver)")

    # Conversor SQLAlchemy base -> JSON Pydantic
    model_config = ConfigDict(from_attributes=True)
