# Cow Abduct com visão computacional

O jogo usa **OpenCV + MediaPipe Pose** para transformar o movimento do corpo em comandos da vaquinha. A câmera é processada em uma thread separada e o teclado permanece disponível como fallback.

O ESP32 está temporariamente fora do jogo: o programa não abre conexão Wi-Fi, não procura porta USB, não lê acelerômetro e não mostra poderes ou painéis de sensor.

## Como abrir no macOS

1. Na primeira vez, dê dois cliques em `instalar_dependencias.command`.
2. Depois, dê dois cliques em `jogar.command`.
3. Quando o macOS perguntar, permita o acesso do Python/Terminal à câmera.
4. Fique no centro e em pé durante a calibração inicial, por cerca de 1–2 segundos.

Se a câmera já tiver sido negada, abra **Ajustes do Sistema → Privacidade e Segurança → Câmera** e habilite o Terminal ou o aplicativo usado para executar o jogo.

O projeto usa Python 3.12 porque essa é a versão compatível com o MediaPipe. O Python 3.14 global não deve ser usado para executá-lo.

## Controles corporais

- Mover o tronco para a esquerda ou direita: troca entre as três faixas.
- Subir o corpo: pula.
- Baixar ou agachar o corpo: agacha a vaquinha.
- `C`: recalibra a posição neutra da câmera.
- `V`: mostra ou oculta a câmera dentro do jogo.
- `Tab`: mostra ou oculta a telemetria.
- `F` ou `F11`: alterna a tela cheia.

O teclado continua disponível: `A/D` ou setas para trocar de faixa, `W`, seta para cima ou espaço para pular, e `S`, seta para baixo ou Shift para agachar.

## Obstáculos e ranking

- O menu inicial usa `Imagens/fundo_inicio.gif` animado em sua resolução nativa de 1280×720 e mostra apenas **JOGAR** e o ranking.
- Clique em **JOGAR** ou pressione espaço para abrir a entrada de nome.
- Digite um nome de até 12 caracteres e pressione `Enter` para iniciar; `Esc` cancela e volta ao menu.
- A câmera fica oculta por padrão. Pressione `V` quando quiser mostrar ou ocultar sua prévia.
- As cinco melhores pontuações ficam salvas em `dados/ranking.json` e reaparecem quando o jogo é aberto novamente.
- A dificuldade não é exibida na interface; o ritmo atual da partida foi mantido sem alterações.
- `ob1` bloqueia a faixa e exige desvio lateral.
- `ob2` é baixo e exige pulo.
- `ob3` deixa uma passagem inferior e exige agachamento.
- Uma colisão encerra a partida e registra a pontuação no ranking.

## Execução pelo terminal

```bash
./instalar_dependencias.command
./jogar.command
```

Para executar a suíte de testes:

```bash
.venv/bin/python -m unittest -v test_vision_controller.py test_gameplay.py
```
