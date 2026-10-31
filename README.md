# Coitados Bancados — monitor Vitoriosos / Memorium

Painel público e responsivo para celular e computador. A coleta usa exclusivamente fontes públicas do Tibia Watch derivadas dos highscores do Memorium. O coletor **não acessa o site do DeusOLD**.

## Dados monitorados
- Personagens cruzados com a lista local `seed_vitoriosos.json` e os convidados em `config.json`.
- Level e XP diário quando publicados no feed público de XP.
- Variação entre leituras sucessivas da fonte, quando a fonte publica novos dados.
- XP total e ranking quando disponíveis no quadro público de highscores.
- Server Save diário às 10:00 (America/Sao_Paulo).
- Tentativa automática a cada 5 minutos.

## Fontes e limites
1. Principal: `https://tibiawatch.com/deusold/exp-de-hoje`, feed público derivado das leituras de highscores.
2. Fallback: `https://tibiawatch.com/deusold/memorium`, quadro público de highscores do mundo Memorium.

O feed diário pode atualizar em intervalos definidos pela fonte; portanto, a coleta do painel roda a cada cinco minutos, mas isso não garante que o site publique números novos a cada cinco minutos. A variação recente só muda quando a fonte disponibiliza uma leitura nova. O fallback da página de mundo pode mostrar apenas uma parte do ranking; não é usado para inventar dados de personagens ausentes.

A lista de membros é local e funciona como filtro. Para incluir todos os integrantes, os nomes precisam estar cadastrados em `seed_vitoriosos.json` ou em `config.json` → `invited`. O coletor não consulta a página da guild para descobrir membros.

## Publicar
O arquivo `render.yaml` configura o serviço web Python com disco persistente para o banco SQLite. O Render lê o Blueprint e cria o serviço.

## Segurança
O painel é público e não exige cadastro. A rota de ingestão manual exige `X-Ingest-Key`; a chave nunca deve ser colocada no frontend.
