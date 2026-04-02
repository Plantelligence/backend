from sqlalchemy.orm import Session
from app.models.estufa import Estufa
from app.schemas.estufa import CriarEstufa, AtualizarEstufa

# Funcao de validacao de Ownership global no service da estufa
# Impede um ator X de mandar uma requisicao pro back com o ID
# da estufa do cara Y tentando ler ou apagar a estufa que nao e dele
def _verificar_ownership(estufa: Estufa | None, user_id: str) -> None:
    if estufa is None:
        raise FileNotFoundError("Estufa nao encontrada.")
    if estufa.user_id != user_id:
        raise PermissionError("Voce nao tem permissao para acessar esta estufa.")

def listar_estufas(db: Session, user_id: str) -> list[Estufa]:
    # a rota manda o jwt auth parseado "user_id". Dai ele pega so as estufas que = o ID da pessoa na tela atual
    return db.query(Estufa).filter(Estufa.user_id == user_id).all()

def criar_estufa(db: Session, user_id: str, dados: CriarEstufa) -> Estufa:
    # Insere dados no SQL, incluindo o id user do Auth jwt
    nova_estufa = Estufa(
        nome=dados.nome,
        cidade=dados.cidade,
        estado=dados.estado,
        preset_id=dados.preset_id,
        user_id=user_id,
    )
    db.add(nova_estufa)
    db.commit()
    # refresh busca do banco novamente e traz os auto generados tipo creation time
    db.refresh(nova_estufa)
    return nova_estufa

def buscar_estufa(db: Session, estufa_id: str, user_id: str) -> Estufa:
    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    _verificar_ownership(estufa, user_id)
    return estufa

def atualizar_estufa(db: Session, estufa_id: str, user_id: str, dados: AtualizarEstufa) -> Estufa:
    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    _verificar_ownership(estufa, user_id)

    # model_dump(exclude_none=True) faz um mapeamento dinamico. Se voce passar so 
    # o { nome: "X"  } ele atualiza apenas o X e as outras configuracoes da estufa ficam onde estao intocadas.
    campos_para_atualizar = dados.model_dump(exclude_none=True)
    for campo, valor in campos_para_atualizar.items():
        # metodo built-in do python q e quase o mesmo de fazer estufa.name = ... estufa.preset_id = ... so num loop dinamico
        setattr(estufa, campo, valor)

    db.commit()
    db.refresh(estufa)
    return estufa

def deletar_estufa(db: Session, estufa_id: str, user_id: str) -> dict:
    # Delecao e super fragil entao o user_id checa dnv se nao e de outro cara random 
    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    _verificar_ownership(estufa, user_id)

    db.delete(estufa)
    db.commit()
    # como a estufa foi deletada nao posso usar dict ou retornar a estufa. tem que ser so um id hardcoded memo.
    return {"deletado_id": estufa_id}
