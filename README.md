# Coitados Bancados — monitor Vitoriosos / Memorium

Painel público e responsivo para celular e computador.

## Coleta automática
- Fonte única: Highscore oficial do DeusOLD em https://www.deusold.com/ranking.
- O coletor percorre até 30 páginas do ranking com `?page=N`, sem abrir páginas de guild bloqueadas e sem usar Tibia Watch.
- Os nomes são cruzados com `seed_vitoriosos.json` e `config.json` → `invited`.
- Level e XP total vêm do Highscore oficial.
- XP recente é a diferença entre duas leituras consecutivas, coletadas a cada 5 minutos.
- XP diário é a diferença entre a primeira leitura e a última após o Server Save das 10:00 (America/Sao_Paulo).
- A primeira coleta após o Server Save é a linha de base; o XP diário começa a acumular a partir da leitura seguinte.

## Limites importantes
O painel só consegue atualizar personagens que aparecem nas páginas públicas de Highscore consultadas. Se o Highscore oficial bloquear o acesso automatizado, o erro aparece no status do coletor; o sistema não tenta contornar a proteção.

## Publicação
O Render executa a API e o coletor continuamente. O disco persistente mantém o histórico SQLite entre reinicializações. O painel é público e não exige cadastro.
