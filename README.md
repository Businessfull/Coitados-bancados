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

## Importante sobre a fonte
O coletor consulta as páginas públicas configuradas em `config.json`. O site oficial DeusOLD pode bloquear requisições automatizadas ou alterar o HTML. O coletor registra erros nos logs e precisa ser validado após a primeira implantação. A página pública de XP diário do Tibia Watch pode ser usada como fonte complementar; ela não substitui o ranking oficial para o XP dos últimos 5 minutos.

## Segurança e acesso
O painel é público e não exige cadastro. A rota de ingestão manual exige `X-Ingest-Key`; a chave nunca deve ser colocada no frontend.
