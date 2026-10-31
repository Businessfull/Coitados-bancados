# Coitados-bancados — Monitor da guild Vitoriosos

Painel web responsivo para celular e computador, com acesso público sem cadastro. Escopo: XP diário, XP individual, XP dos últimos 5 minutos, histórico após Server Save e mortes/horários/envolvidos. O painel consulta `/api/dashboard` a cada 5 minutos.

## Rodar localmente
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Acesse `http://127.0.0.1:8000`.

## API
- `GET /api/health` — status.
- `GET /api/dashboard` — dados do painel.
- `POST /api/ingest` — recebe snapshots e mortes. Exige o header `X-Ingest-Key`.

Configure a variável de ambiente `INGEST_KEY` no servidor. Nunca coloque essa chave no JavaScript público.

## Integração DeusOLD
A interface e a API receptora estão preparadas, mas a coleta automática ainda precisa ser ligada às páginas públicas do DeusOLD. O projeto ainda não coleta nem publica dados reais. O coletor deverá consultar ranking/histórico a cada 5 minutos, calcular a diferença entre snapshots e reiniciar o acumulado diário no Server Save.

## Publicação
Hospede como serviço Python (Render ou Railway, por exemplo). GitHub Pages sozinho não executa a API Python nem mantém o coletor em segundo plano. Comando: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
