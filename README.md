# Coitados Bancados — monitor Vitoriosos / DeusOLD

Painel público e responsivo para celular e computador. Mostra apenas os membros oficiais da guild Vitoriosos (guild ID 871) e os convidados configurados separadamente.

## Dados monitorados
- XP total diário por personagem e total da equipe.
- XP individual e XP ganho nos últimos 5 minutos.
- Ranking e evolução de level.
- Atividade inferida pela variação de experiência entre leituras.
- Histórico de mortes: preparado na API, mas depende de uma fonte pública de mortes disponível no DeusOLD.
- Server Save diário às 10:00 (America/Sao_Paulo).
- Coleta automática a cada 5 minutos.

## Publicar
O arquivo `render.yaml` configura um serviço web Python com disco persistente para o banco SQLite. Abra o repositório no Render e escolha **New > Blueprint**, conecte o GitHub e selecione este repositório. O Render lê o Blueprint e cria o serviço. O plano Starter e o disco persistente são pagos; a implantação exige autorização da conta Render.

## Fonte ativa e limites
O coletor usa como fonte principal a página pública [Top exp do dia no DeusOld](https://tibiawatch.com/deusold/exp-de-hoje), filtrando os nomes contra `seed_vitoriosos.json`. O acesso automatizado ao site do DeusOLD pode retornar HTTP 403; o coletor não tenta contornar essa proteção. Personagens ausentes no ranking diário mantêm o último valor conhecido, nunca são zerados por ausência.

A página pública informa XP acumulada entre as leituras do Tibia Watch, não uma medição garantida a cada cinco minutos. Portanto, `recent_xp` é a diferença entre leituras dessa fonte e pode permanecer zerado enquanto ela não publicar uma nova leitura. Para XP realmente exata a cada cinco minutos e histórico completo de mortes, é necessário que o DeusOLD forneça uma API/feed público ou autorize acesso automatizado.

## Segurança e acesso
O painel é público e não exige cadastro. A rota de ingestão manual exige `X-Ingest-Key`; a chave nunca deve ser colocada no frontend.


## Fallback de coleta

Quando o DeusOLD retorna HTTP 403, o coletor tenta a página pública de XP diário do Tibia Watch (`daily_url`), sem contornar a proteção do servidor. Nesse modo, ele atualiza somente personagens explicitamente listados em `config.json` → `invited`. A coleta complementar usa a lista completa de personagens registrada em `seed_vitoriosos.json`, além dos convidados de `config.json`, comparando nomes sem diferenciar maiúsculas, espaços ou acentos. A página pública de XP diário pode não incluir todos os personagens em todas as leituras; por isso, personagens ausentes não devem ser interpretados automaticamente como zero. A variação recente representa a diferença entre leituras da fonte pública, não uma garantia de atualização exata a cada cinco minutos.

A lista de personagens pode ser ampliada editando `invited` com os nomes exatos. Não inclua nomes sem confirmar que pertencem à guild.
