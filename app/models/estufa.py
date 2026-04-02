import uuid
from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db.postgres import Base

class Estufa(Base):
    # criando a tabela "estufas" no banco de dados PostgreSQL passando a classe Base como parâmetro
    # herdando os atributos created_at e updated_at da classe Base
    __tablename__ = "estufas"

    # colunas da tabela estufa
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    nome = Column(String, nullable=False)
    estado = Column(String(2), nullable=False)
    cidade = Column(String, nullable=False)

    # Vincula a estufa a um usuário
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Vincula a estufa a um preset através de uma chave estrangeira preset_id
    preset_id = Column(String, ForeignKey("presets.id", ondelete="SET NULL"), nullable=True)

    # relacionamento com a tabela user
    user = relationship("User", back_populates="estufas")

    # relacionamento com a tabela dispositivo
    # cascade="all, delete-orphan" para que quando uma estufa for deletada,
    # todos os dispositivos dela sejam deletados também
    dispositivos = relationship("Dispositivo", back_populates="estufa", cascade="all, delete-orphan")

    # relacionamento com a tabela preset
    preset = relationship("Preset", back_populates="estufas")

    # relacionamento com a tabela alertas
    alertas = relationship("Alertas", back_populates="estufa", cascade="all, delete-orphan")

    # relacionamento com a tabela historico
    historicos = relationship("Historico", back_populates="estufa", cascade="all, delete-orphan")

    