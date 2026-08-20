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
- `C`: recalibra a posição neutra da câmera e o ESP32.
- `V`: mostra/oculta a câmera dentro do jogo.
- `Tab`: mostra/oculta a telemetria.

O teclado continua disponível: `A/D` ou setas para as faixas, `W`, seta para cima ou espaço para pular, `S`, seta para baixo ou Shift para agachar. O controle ESP32 existente também foi preservado.

## Correções visuais

- O gameplay agora carrega o cenário completo de Saturno, em vez do fundo vazio de estrelas.
- As três faixas recebem guias de perspectiva ciano/douradas.
- A caixa invisível e o laser provisório foram substituídos por sprites pixel-art transparentes próprios.
- Sprite, hitbox e feixe foram alinhados para o agachamento ficar visualmente justo.

## Execução pelo terminal

```bash
./instalar_dependencias.command
./jogar.command
```

Para rodar apenas os testes dos gestos:

```bash
.venv/bin/python -m unittest -v test_vision_controller.py test_gameplay.py
```
