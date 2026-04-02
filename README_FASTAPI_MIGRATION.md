# Migracao Backend para FastAPI

## Execucao local

1. Criar ambiente virtual Python 3.11+
2. Instalar dependencias:

```bash
pip install -r requirements.txt
```

3. Configurar variaveis no arquivo `.env` (JWT, Firebase, SMTP, etc.)
4. Iniciar API:

```bash
python server.py
```

A API sobe por padrao na porta definida em `PORT` (fallback: `4000`).

## Compatibilidade de contratos

Rotas migradas e mantidas com prefixos legados:

- `/api/auth/*`
- `/api/users/*`
- `/api/admin/*`
- `/api/crypto/*`
- `/api/greenhouse/*`

## Observacoes de seguranca

- Segredos sensiveis **nao** devem ser hardcoded.
- JWT, SMTP e credenciais Firebase devem vir de variaveis de ambiente por conformidade LGPD.

## Proximos passos recomendados

1. Rodar smoke tests de todos os fluxos no frontend.
2. Congelar/remover gradualmente os arquivos Node.js antigos da pasta `backend/` apos validacao completa.
3. Adicionar testes automatizados de API (pytest + httpx).
