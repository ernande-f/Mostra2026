# Cow Abduct com visão computacional

O jogo usa **OpenCV + MediaPipe Pose** para transformar o movimento do corpo em comandos da vaquinha. A câmera é processada em uma thread separada e o teclado permanece disponível como fallback.

O **ESP32 + MPU6050** funciona como Núcleo de Abdução sem substituir a visão computacional: chacoalhar a caixa carrega energia e um giro rápido ativa um escudo contra uma colisão. A comunicação é feita por Wi-Fi/UDP e não exige LEDs, botões ou outros componentes.

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

## Núcleo de Abdução ESP32 + MPU6050

O firmware fica em `esp32_sensor/esp32_sensor.ino` e usa somente as bibliotecas `Wire`, `WiFi` e `WiFiUdp` que acompanham o pacote ESP32 da Arduino IDE.

Ligação usada pelo firmware:

- `MPU6050 VCC` → `ESP32 3V3`
- `MPU6050 GND` → `ESP32 GND`
- `MPU6050 SDA` → `ESP32 GPIO 21`
- `MPU6050 SCL` → `ESP32 GPIO 22`

Para usar:

1. Grave `esp32_sensor.ino` no ESP32 pela Arduino IDE.
2. No Mac, conecte-se à rede **ESP32_COW_GAME** com a senha **12345678**. O aviso “sem internet” é esperado.
3. Abra o jogo normalmente. Ele passa a escutar automaticamente a porta UDP `4210`.
4. Durante a partida, chacoalhe a caixa até o círculo de energia ao redor da vaca completar.
5. Pare a caixa por um instante e faça um giro rápido com o pulso.
6. O escudo permanece por até 12 segundos ou desaparece ao impedir uma colisão.

O menu continua limpo. Pressione `Tab` somente quando quiser conferir conexão, carga, intensidade do movimento e velocidade de giro. Para diagnosticar os pacotes sem abrir o jogo, execute `.venv/bin/python test_esp32.py`; feche o monitor antes de iniciar o jogo porque ambos usam a mesma porta UDP.

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
- O fazendeiro aparece ocasionalmente mirando a faixa atual da vaca. Uma
  colisão com ele desintegra toda a cena e devolve o jogo diretamente ao menu.
- Uma colisão encerra a partida e registra a pontuação no ranking.

## Áudio

- O menu usa uma música espacial tranquila.
- Ao começar a partida, a trilha muda para uma versão mais rápida e pulsante.
- Cada pulo toca seu próprio efeito e uma colisão fatal toca o efeito de morte.
- O áudio é carregado de forma segura: se o computador estiver sem saída de
  som disponível, o jogo continua funcionando normalmente.

## Execução pelo terminal

```bash
./instalar_dependencias.command
./jogar.command
```

Para executar a suíte de testes:

```bash
.venv/bin/python -m unittest -v test_vision_controller.py test_gameplay.py test_esp32_power.py
```
