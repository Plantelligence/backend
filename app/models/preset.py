import uuid
from sqlalchemy import Column, String, JSON, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.db.postgres import Base

class Preset(Base):
    # criando a tabela "presets" no banco de dados PostgreSQL passando a classe Base como parametro
    __tablename__ = "presets"

    # colunas da tabela preset
    # primary_key com uuid gerado para nao depender de autoincrement do banco
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Flag para saber se e um preset criado pelo desenvolvedor (True) ou futuramente por IA pelo usuario (False)
    sistema = Column(Boolean, nullable=False)
    
    # Pode ser nulo pois presets de sistema nao possuem donos. Sera usado quando for gerado por IA para o usuario.
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    
    nome_cultura = Column(String, nullable=False)
    tipo_cultura = Column(String, nullable=False)
    descricao = Column(String, nullable=True)
    
    # Usamos o tipo JSON em vez de dezenas de colunas Float porque presets
    # precisam guardar 5 faixas (critico min/max, alerta min/max, ideal min/max).
    # Uma coluna JSON escala melhor e evita estourar os limites de colunas do banco relacional.
    temperatura = Column(JSON, nullable=False)
    umidade = Column(JSON, nullable=False)
    luminosidade = Column(JSON, nullable=False)
    
    # relacionamento reverso com a tabela estufa
    # Permite navegar de preset -> estufas para saber quais estufas usam esse preset
    estufas = relationship("Estufa", back_populates="preset")
