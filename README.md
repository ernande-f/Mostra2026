# Cow Abduct com visão computacional

O jogo usa **OpenCV + MediaPipe Pose** para transformar o movimento do corpo em comandos da vaquinha. A câmera é processada em uma thread separada, portanto não reduz o FPS do loop principal. Se o MediaPipe não puder iniciar no Mac, há um fallback por detecção facial do OpenCV.

## Como abrir no macOS

1. Na primeira vez, dê dois cliques em `instalar_dependencias.command`.
2. Depois, dê dois cliques em `jogar.command`.
3. Quando o macOS perguntar, permita o acesso do Python/Terminal à câmera.
4. Fique no centro e em pé durante a calibração inicial (cerca de 1–2 segundos).

Se a câmera já tiver sido negada, abra **Ajustes do Sistema → Privacidade e Segurança → Câmera** e habilite o Terminal ou o Codex (o aplicativo a partir do qual o jogo for executado).

O projeto usa Python 3.12 porque essa é a versão compatível com o MediaPipe usado pelo jogo. O Python 3.14 global não deve ser usado para executá-lo.

## Controles corporais

- Mover o tronco para a esquerda/direita: troca entre as três faixas.
- Subir o corpo: pula.
- Baixar/agachar o corpo: agacha a vaquinha.
- Cinta ESP32/MPU6050: incline para os lados para trocar de faixa, dê o impulso vertical para pular e incline para frente para agachar.
- `C`: recalibra a posição neutra da câmera e o ESP32.
- `V`: mostra/oculta a câmera dentro do jogo.
- `Tab`: mostra/oculta a telemetria.

O teclado continua disponível: `A/D` ou setas para as faixas, `W`, seta para cima ou espaço para pular, `S`, seta para baixo ou Shift para agachar. O controle ESP32 existente também foi preservado.

## Ranking e dificuldade

- Clique em **JOGADOR** no menu para escrever um nome de até 12 caracteres.
- Escolha **Fácil**, **Normal** ou **Difícil** clicando nos cartões ou usando `1`, `2` e `3`.
- Cada dificuldade altera a velocidade de aproximação e o intervalo dos obstáculos. A velocidade atual aparece no HUD durante a partida.
- As cinco melhores pontuações ficam salvas em `dados/ranking.json` e reaparecem quando o jogo é aberto novamente.
- Os obstáculos agora entram pela parte superior da pista, antes do horizonte, dando mais tempo para enxergá-los.

## Correções visuais

- O gameplay agora carrega o cenário completo de Saturno, em vez do fundo vazio de estrelas.
- As três faixas recebem guias de perspectiva ciano/douradas.
- A caixa invisível e o laser provisório foram substituídos por sprites pixel-art transparentes próprios.
- Sprite, hitbox e feixe foram alinhados para o agachamento ficar visualmente justo.
- O menu recebeu medalhas, planetas, estrela e asteroide desenhados em tempo real para identificar ranking e dificuldades.

## Execução pelo terminal

```bash
./instalar_dependencias.command
./jogar.command
```

Para rodar apenas os testes dos gestos:

```bash
.venv/bin/python -m unittest -v test_vision_controller.py test_gameplay.py
```
