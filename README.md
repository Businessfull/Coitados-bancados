# Coitados Bancados — monitor Vitoriosos / Memorium

Painel público e responsivo para celular e computador.

## Coleta automática
- Fonte do coletor: página pública de highscores do Tibia Watch: https://tibiawatch.com/deusold/highscores
- O coletor NÃO consulta páginas de guild ou ranking bloqueadas do DeusOLD e não tenta contornar Cloudflare.
- Os personagens do ranking são cruzados com a lista local `seed_vitoriosos.json` e os nomes adicionais de `config.json` → `invited`.
- Level, XP total e posição vêm do ranking público.
- XP recente é a diferença entre duas leituras consecutivas.
- XP diário é a diferença entre a primeira e a última leitura após o server save das 10:00 (America/Sao_Paulo).
- A coleta roda a cada 5 minutos (`POLL_SECONDS=300`).

## Limites importantes
O ranking público pode mostrar somente os personagens dentro da profundidade publicada pelo site. O painel não pode mostrar personagens ausentes da fonte. O XP diário começa na primeira leitura bem-sucedida depois do server save; não é possível reconstruir retroativamente o XP anterior à primeira leitura. A frequência de execução do coletor não garante que a origem atualize o ranking a cada cinco minutos.

Se o Render receber HTTP 403 do Tibia Watch, a origem está recusando a conexão automatizada desse serviço. É necessário que a origem permita o acesso ou forneça um endpoint/API público autorizado. O coletor registra esse erro claramente e não tenta contornar a proteção.

## Publicar
O arquivo `render.yaml` configura o serviço web Python e o disco persistente para o banco SQLite. O Render publica automaticamente após cada commit na branch conectada.

## Segurança
O painel é público e não exige cadastro. A rota de ingestão manual exige `X-Ingest-Key`; a chave nunca deve ser colocada no frontend.
