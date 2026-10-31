# Coitados Bancados — monitor Vitoriosos / Memorium

Painel público e responsivo para celular e computador.

## Coleta automática
- Fontes públicas do coletor: highscores (https://tibiawatch.com/deusold/highscores) para level/XP total e Exp do Dia (https://tibiawatch.com/deusold/exp-de-hoje) para XP diário.
- O coletor NÃO consulta páginas de guild ou ranking bloqueadas do DeusOLD e não tenta contornar Cloudflare.
- Os personagens do ranking são cruzados com a lista local `seed_vitoriosos.json` e os nomes adicionais de `config.json` → `invited`.
- Level, XP total e posição vêm do ranking público.
- XP recente é a diferença entre duas leituras consecutivas.
- XP diário prioriza a tabela pública Exp do Dia do Tibia Watch. Se ela estiver indisponível, o serviço calcula a diferença entre snapshots de XP total desde as 10h (America/Sao_Paulo). A fonte diária não garante captura exatamente às 10h nem fornece XP minuto a minuto.
- A coleta roda a cada 5 minutos (`POLL_SECONDS=300`).

## Limites importantes
O ranking público pode mostrar somente os personagens dentro da profundidade publicada pelo site. O painel não pode mostrar personagens ausentes da fonte. A página Exp do Dia lista os personagens medidos pela fonte (atualmente limitada aos primeiros colocados). Personagens fora da lista podem não ter um valor diário disponível. O XP recente usa a diferença entre leituras de XP total quando o highscore está acessível. A frequência de execução do coletor não garante que a origem atualize o ranking a cada cinco minutos.

Se o Render receber HTTP 403 do Tibia Watch, a origem está recusando a conexão automatizada desse serviço. É necessário que a origem permita o acesso ou forneça um endpoint/API público autorizado. O coletor registra esse erro claramente e não tenta contornar a proteção.

## Publicar
O arquivo `render.yaml` configura o serviço web Python e o disco persistente para o banco SQLite. O Render publica automaticamente após cada commit na branch conectada.

## Segurança
O painel é público e não exige cadastro. A rota de ingestão manual exige `X-Ingest-Key`; a chave nunca deve ser colocada no frontend.
