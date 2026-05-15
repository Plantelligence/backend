import uuid
from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db.postgres.Base import Base


class Relatorio(Base):
    # Relatório periódico de condições e ações realizadas na estufa.
    __tablename__ = "relatorios"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    estufa_id = Column(String, ForeignKey("estufas.id", ondelete="CASCADE"), nullable=False)

    # Período coberto pelo relatório.
    periodo_inicio = Column(String, nullable=False)
    periodo_fim = Column(String, nullable=False)

    # Médias coletadas/estimadas no período.
    avg_temperatura = Column(String, nullable=True)
    avg_umidade = Column(String, nullable=True)
    avg_umidade_solo = Column(String, nullable=True)
    avg_luminosidade = Column(String, nullable=True)
    avg_substrato = Column(String, nullable=True)  # legado — mantido para compatibilidade

    # Texto livre com resumo do operador.
    resumo = Column(String, nullable=True)

    # Metadados de criação.
    criado_em = Column(String, nullable=False)
    criado_por_id = Column(String, nullable=True)

    estufa = relationship("Estufa", back_populates="relatorios")
