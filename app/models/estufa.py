import uuid
from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db.postgres.Base import Base

class Estufa(Base):
    # criando a tabela "estufas" no banco de dados PostgreSQL passando a classe Base como parametro
    # herdando os atributos created_at e updated_at da classe Base
    __tablename__ = "estufas"

    # colunas da tabela estufa
    # UUID e gerado no Python em vez do banco para garantir unicidade imediata antes do commit
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    nome = Column(String, nullable=False)
    
    # String(2) restringe no nivel do banco para garantir que estados sejam sempre siglas (ex: SP, RJ)
    estado = Column(String(2), nullable=False)
    cidade = Column(String, nullable=False)

    # Vincula a estufa a um usuario
    # ondelete="CASCADE" garante que, se o usuario for excluido do sistema, 
    # as estufas dele sumam do banco automaticamente (evita dados orfaos)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Vincula a estufa a um preset atraves de uma chave estrangeira preset_id
    # nullable=True: a estufa pode ser criada sem preset e configurada mais tarde
    # ondelete="SET NULL": se o preset deixar de existir, a estufa nao e apagada, o campo apenas fica vazio
    preset_id = Column(String, ForeignKey("presets.id", ondelete="SET NULL"), nullable=True)

    # relacionamento com a tabela user (permite acessar estufa.user no codigo)
    user = relationship("User", back_populates="estufas")

    # relacionamento bidirecional com as tabelas dependentes
    # cascade="all, delete-orphan" entra acao quando UMA ESTUFA e deletada:
    # todos os dispositivos, historicos e alertas pertencentes a ela serao deletados junto (integridade relacional completa)
    dispositivos = relationship("Dispositivo", back_populates="estufa", cascade="all, delete-orphan")
    
    # relacionamento com a tabela preset
    preset = relationship("Preset", back_populates="estufas")
    
    # relacionamento com a tabela alertas
    alertas = relationship("Alertas", back_populates="estufa", cascade="all, delete-orphan")
    
    # relacionamento com a tabela historico
    historicos = relationship("Historico", back_populates="estufa", cascade="all, delete-orphan")