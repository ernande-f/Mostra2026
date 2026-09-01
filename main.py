import pygame
import random
import math
import sys
import threading
import time
import json
import os

from datetime import datetime
from pathlib import Path

from esp32_power import Esp32PowerController
from vision_controller import VisionController

# ==========================================
# CONFIGURAÇÕES GERAIS E RESOLUÇÃO VIRTUAL
# ==========================================
LARGURA_VIRTUAL = 1280
ALTURA_VIRTUAL = 720
FPS = 60
PASTA_PROJETO = Path(__file__).resolve().parent
ARQUIVO_RANKING = PASTA_PROJETO / "dados" / "ranking.json"
VIDEO_FUNDO_JOGO = PASTA_PROJETO / "videos" / "gif_fundo_saturno.mp4"
SOM_PULO = PASTA_PROJETO / "Sons" / "previas" / "pulo_espacial.wav"
SOM_MORTE = PASTA_PROJETO / "Sons" / "previas" / "morte_power_down.wav"
MUSICA_MENU = PASTA_PROJETO / "Sons" / "previas" / "musica_1_orbita_tranquila.wav"
MUSICA_GAMEPLAY = PASTA_PROJETO / "Sons" / "previas" / "musica_gameplay_acao.wav"
AREA_BOTAO_JOGAR = (230, 390, 440, 54)

# O jogo usa um unico ritmo fixo, sem aceleracao progressiva escondida.
MODO_JOGO = "FACIL"
DIFICULDADES = {
    MODO_JOGO: {
        "velocidade": 0.78,
        "spawn": 64,
    },
}

# O obstaculo nasce junto ao inicio visivel dos aneis.
PROGRESSO_SPAWN = -0.04
PROGRESSO_MINIMO_VISIVEL = -0.04

# ==========================================
# CONSTANTES DA PISTA (ANÉIS DE SATURNO - 3 FAIXAS)
# ==========================================
# Os anéis de Saturno ficam na metade direita da imagem
HORIZON_Y = 220
# A vaca fica mais proxima da borda inferior e continua com espaco para pular.
BASE_Y = 655
PROGRESSO_PLANO_VACA = (
    (BASE_Y - HORIZON_Y)
    / (BASE_Y - HORIZON_Y + 120)
)

# Quatro bordas medidas diretamente no frame do vídeo em resolução virtual.
# Cada tupla representa (y, limite esquerdo, divisória 1, divisória 2, direito).
ROTA_ANEIS = (
    (200, 556.0, 628.0, 700.0, 799.0),
    (240, 599.0, 674.5, 756.0, 849.0),
    (280, 642.0, 721.5, 811.5, 898.5),
    (320, 675.0, 752.5, 862.5, 944.5),
    (380, 707.5, 790.5, 906.0, 1010.5),
    (450, 717.5, 827.0, 942.0, 1066.5),
    (520, 707.0, 841.5, 976.5, 1106.0),
    (580, 683.5, 847.0, 1001.5, 1132.0),
    (640, 646.5, 847.5, 1011.5, 1146.5),
    (700, 613.5, 837.0, 1012.0, 1151.5),
    (720, 604.5, 834.5, 1007.0, 1156.5),
)

# Centros das três lanes entre as quatro bordas acima.
LANE_RATIOS = [1 / 6, 1 / 2, 5 / 6]
NUM_LANES = len(LANE_RATIOS)
NOME_LANES = ["ESQUERDA", "CENTRO", "DIREITA"]

# Dimensões da Vaca nos Anéis
LARGURA_VACA_NORMAL = 105
ALTURA_VACA_NORMAL = 135
LARGURA_VACA_AGACHADA = 105
ALTURA_VACA_AGACHADA = 85

# A camera reconhece o abaixar do tronco e mantem a pose enquanto o jogador
# estiver agachado.
ENABLE_CROUCH = True

# Dimensões dos Obstáculos
TAMANHO_OBSTACULO_MIN = 20
TAMANHO_OBSTACULO_MAX = 74

# O fazendeiro e um encontro raro, mais rapido que os obstaculos comuns.
INTERVALO_FAZENDEIRO_MIN = FPS * 15
INTERVALO_FAZENDEIRO_MAX = FPS * 23


# =========================================================
# RANKING LOCAL PERSISTENTE
# =========================================================
def normalizar_nome_jogador(nome):
    """Limpa o nome exibido e salvo sem impedir letras acentuadas."""
    return limpar_nome_digitado(nome).strip() or "JOGADOR"


def limpar_nome_digitado(nome, limite=12):
    """Filtra a edicao sem transformar um campo vazio em JOGADOR."""
    caracteres = (
        ch for ch in str(nome).upper()
        if ch.isalnum() or ch in "-_ "
    )
    return "".join(caracteres)[:limite]


class RankingPersistente:
    """Mantem o top 5 em JSON, inclusive entre execucoes do jogo."""

    def __init__(self, caminho=ARQUIVO_RANKING, limite=5):
        self.caminho = Path(caminho)
        self.limite = limite
        self.entradas = self._carregar()

    def _carregar(self):
        try:
            dados = json.loads(self.caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []

        if not isinstance(dados, list):
            return []

        entradas_validas = []
        for item in dados:
            if not isinstance(item, dict):
                continue
            try:
                pontos = max(0, int(item.get("pontos", 0)))
            except (TypeError, ValueError):
                continue
            dificuldade = str(item.get("dificuldade", MODO_JOGO)).upper()
            if dificuldade not in DIFICULDADES:
                dificuldade = MODO_JOGO
            entradas_validas.append({
                "nome": normalizar_nome_jogador(item.get("nome", "JOGADOR")),
                "pontos": pontos,
                "dificuldade": dificuldade,
                "data": str(item.get("data", "")),
            })

        entradas_validas.sort(key=lambda item: item["pontos"], reverse=True)
        return entradas_validas[:self.limite]

    def registrar(self, nome, pontos, dificuldade):
        entrada = {
            "nome": normalizar_nome_jogador(nome),
            "pontos": max(0, int(pontos)),
            "dificuldade": dificuldade if dificuldade in DIFICULDADES else MODO_JOGO,
            "data": datetime.now().isoformat(timespec="seconds"),
        }
        candidatas = self.entradas + [entrada]
        candidatas.sort(key=lambda item: item["pontos"], reverse=True)
        self.entradas = candidatas[:self.limite]
        self._salvar()

        # Retorna a colocacao apenas se esta partida permaneceu no top 5.
        for indice, item in enumerate(self.entradas):
            if item is entrada:
                return indice + 1
        return None

    def _salvar(self):
        try:
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            temporario = self.caminho.with_suffix(self.caminho.suffix + ".tmp")
            temporario.write_text(
                json.dumps(self.entradas, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporario, self.caminho)
        except OSError as exc:
            # Uma falha de escrita nao pode derrubar a partida.
            print(f"[RANKING] Nao foi possivel salvar {self.caminho}: {exc}")


# =========================================================
# AUDIO (MUSICA DE MENU, TRILHA DE ACAO E EFEITOS)
# =========================================================
class AudioJogo:
    """Centraliza o audio e deixa o jogo funcionar mesmo sem dispositivo sonoro."""

    def __init__(self):
        self.disponivel = pygame.mixer.get_init() is not None
        self.faixa_atual = None
        self.som_pulo = None
        self.som_morte = None
        if not self.disponivel:
            print("[AUDIO] Mixer indisponivel; seguindo sem som.")
            return

        try:
            self.som_pulo = pygame.mixer.Sound(str(SOM_PULO))
            self.som_pulo.set_volume(0.58)
            self.som_morte = pygame.mixer.Sound(str(SOM_MORTE))
            self.som_morte.set_volume(0.76)
        except (OSError, pygame.error) as exc:
            print(f"[AUDIO] Nao foi possivel carregar os efeitos: {exc}")

    def _tocar_musica(self, caminho, volume):
        if not self.disponivel or not Path(caminho).exists():
            return
        caminho = Path(caminho)
        try:
            if self.faixa_atual != caminho:
                pygame.mixer.music.fadeout(280)
                pygame.mixer.music.load(str(caminho))
                self.faixa_atual = caminho
            if not pygame.mixer.music.get_busy():
                pygame.mixer.music.set_volume(volume)
                pygame.mixer.music.play(-1, fade_ms=420)
            else:
                pygame.mixer.music.set_volume(volume)
        except (OSError, pygame.error) as exc:
            print(f"[AUDIO] Nao foi possivel tocar {caminho.name}: {exc}")

    def tocar_menu(self):
        self._tocar_musica(MUSICA_MENU, 0.28)

    def tocar_gameplay(self):
        self._tocar_musica(MUSICA_GAMEPLAY, 0.32)

    def tocar_pulo(self):
        if self.som_pulo is not None:
            self.som_pulo.play()

    def tocar_morte(self):
        if self.som_morte is not None:
            self.som_morte.play()

    def parar_musica(self, fade_ms=500):
        if self.disponivel:
            pygame.mixer.music.fadeout(fade_ms)
            # Forca o proximo menu/reinicio a recarregar a faixa, mesmo se o
            # jogador apertar uma tecla antes de o fade terminar.
            self.faixa_atual = None

    def desligar(self):
        if self.disponivel:
            pygame.mixer.music.stop()


# =========================================================
# CONTROLADOR DE ENTRADA (VISAO COMPUTACIONAL + TECLADO)
# =========================================================
class InputController:
    """Recebe os gestos da camera; o teclado permanece como fallback."""

    def __init__(self):
        self.jump_event = False    # True quando detecta impulso de salto
        self.lane_shift_event = 0  # -1 esquerda | +1 direita
        self.target_lane_event = None
        self.is_crouching = False
        self.last_control_source = "teclado"
        self._event_lock = threading.Lock()
        self._crouch_sources = {"keyboard": False, "vision": False}
        self.vision_recalibrate_callback = None
        self.show_debug = False    # [TAB] exibe telemetria sem cobrir a pista
        self.show_camera = False   # [V] alterna a pre-visualizacao da webcam

        self.feedback_msg = ""             # Mensagem de notificação na tela
        self.feedback_timer = 0.0          # Timer para apagar a notificação

        # Debounce do teclado
        self.prev_k_up = False
        self.prev_k_left = False
        self.prev_k_right = False
        self.prev_k_c = False

    def trigger_jump(self, source="entrada"):
        """Publica um pulo de forma segura a partir de qualquer thread."""
        with self._event_lock:
            self.jump_event = True
            self.last_control_source = source

    def consume_jump(self):
        with self._event_lock:
            event = self.jump_event
            self.jump_event = False
            return event

    def request_lane_shift(self, direction, source="entrada"):
        with self._event_lock:
            self.lane_shift_event = -1 if direction < 0 else 1
            self.last_control_source = source

    def request_target_lane(self, lane, source="entrada"):
        with self._event_lock:
            self.target_lane_event = max(0, min(NUM_LANES - 1, int(lane)))
            self.last_control_source = source

    def consume_lane_commands(self):
        with self._event_lock:
            target = self.target_lane_event
            shift = self.lane_shift_event
            self.target_lane_event = None
            self.lane_shift_event = 0
            return target, shift

    def set_crouching(self, source, active):
        with self._event_lock:
            self._crouch_sources[source] = bool(active)
            self.is_crouching = any(self._crouch_sources.values()) if ENABLE_CROUCH else False
            if active:
                self.last_control_source = source

    def calibrate_center(self):
        """Solicita uma nova tara da visao computacional."""
        if self.vision_recalibrate_callback:
            self.vision_recalibrate_callback()
        self.feedback_msg = "● RECALIBRANDO CAMERA..."
        self.feedback_timer = time.time() + 2.5
        print("[CALIBRACAO] Camera recalibrada")

    def update_from_keyboard(self, keys):
        """Teclado continua disponivel como fallback e para testes."""
        k_up = keys[pygame.K_UP] or keys[pygame.K_w] or keys[pygame.K_SPACE]

        # Pulo no teclado (disparo único por clique)
        if k_up and not self.prev_k_up:
            self.trigger_jump("teclado")
        self.prev_k_up = k_up

        k_left = keys[pygame.K_LEFT] or keys[pygame.K_a]
        k_right = keys[pygame.K_RIGHT] or keys[pygame.K_d]
        if k_left and not self.prev_k_left:
            self.request_lane_shift(-1, "teclado")
        elif k_right and not self.prev_k_right:
            self.request_lane_shift(1, "teclado")
        self.prev_k_left = k_left
        self.prev_k_right = k_right

        k_down = keys[pygame.K_DOWN] or keys[pygame.K_s] or keys[pygame.K_LSHIFT]
        self.set_crouching("keyboard", k_down)

        # [C] recalibra a posicao neutra da camera.
        k_c = keys[pygame.K_c]
        if k_c and not self.prev_k_c:
            self.calibrate_center()
        self.prev_k_c = k_c


# =========================================================
# CARREGAMENTO E ALINHAMENTO PRECISO DOS SPRITES DA VACA
# =========================================================
def carregar_asset(candidatos, com_alpha=False):
    """Busca a imagem entre vários caminhos possíveis para evitar erros de arquivo não encontrado."""
    import os
    for caminho in candidatos:
        if os.path.exists(caminho):
            try:
                img = pygame.image.load(caminho)
                return img.convert_alpha() if com_alpha else img.convert()
            except Exception as e:
                print(f"[DEBUG] Erro ao carregar {caminho}: {e}")
    # Cria uma superfície reserva segura
    surf = pygame.Surface((1280, 720), pygame.SRCALPHA if com_alpha else 0)
    surf.fill((30, 20, 50))
    return surf


class FundoJogoAnimado:
    """Reproduz um MP4 em loop e usa uma imagem estática como reserva."""

    def __init__(self, caminho_video, imagem_fallback, tamanho):
        self.caminho_video = Path(caminho_video)
        self.tamanho = tuple(tamanho)
        self.imagem_fallback = pygame.transform.scale(imagem_fallback, self.tamanho)
        self.frame_atual = self.imagem_fallback
        self.video_ativo = False
        self._capture = None
        self._cv2 = None
        self._intervalo_frame = 1.0 / 30.0
        self._tempo_acumulado = 0.0
        self._ultimo_instante = None
        self._abrir_video()

    def _abrir_video(self):
        if not self.caminho_video.exists():
            print(f"[FUNDO] Vídeo não encontrado: {self.caminho_video}")
            return

        try:
            import cv2

            capture = cv2.VideoCapture(str(self.caminho_video))
            if not capture.isOpened():
                capture.release()
                print(f"[FUNDO] Não foi possível abrir: {self.caminho_video}")
                return

            fps_video = capture.get(cv2.CAP_PROP_FPS)
            if fps_video and math.isfinite(fps_video) and fps_video > 0:
                self._intervalo_frame = 1.0 / fps_video

            self._cv2 = cv2
            self._capture = capture
            self.video_ativo = self._ler_proximo_frame()
            if self.video_ativo:
                print(f"[FUNDO] Vídeo animado carregado: {self.caminho_video.name}")
            else:
                self.close()
        except Exception as exc:
            print(f"[FUNDO] Erro ao carregar vídeo; usando imagem estática: {exc}")
            self.close()

    def _ler_proximo_frame(self):
        if self._capture is None or self._cv2 is None:
            return False

        ok, frame = self._capture.read()
        if not ok:
            # Ao chegar ao final, volta ao primeiro quadro para manter o loop.
            self._capture.set(self._cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._capture.read()
        if not ok:
            return False

        interpolacao = (
            self._cv2.INTER_AREA
            if frame.shape[1] >= self.tamanho[0] and frame.shape[0] >= self.tamanho[1]
            else self._cv2.INTER_LINEAR
        )
        frame = self._cv2.resize(frame, self.tamanho, interpolation=interpolacao)
        frame_rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        self.frame_atual = pygame.image.frombytes(
            frame_rgb.tobytes(),
            self.tamanho,
            "RGB",
        ).convert()
        return True

    def desenhar(self, canvas):
        if self.video_ativo:
            agora = time.monotonic()
            if self._ultimo_instante is None:
                self._ultimo_instante = agora
            decorrido = agora - self._ultimo_instante
            self._ultimo_instante = agora

            # Uma passagem pelo menu não deve provocar uma leitura acelerada
            # de dezenas de quadros quando a partida recomeçar.
            if decorrido <= 0.5:
                self._tempo_acumulado += max(0.0, decorrido)

            quadros_pendentes = int(self._tempo_acumulado / self._intervalo_frame)
            if quadros_pendentes:
                for _ in range(min(quadros_pendentes, 12)):
                    if not self._ler_proximo_frame():
                        self.video_ativo = False
                        self.frame_atual = self.imagem_fallback
                        break
                self._tempo_acumulado %= self._intervalo_frame

        canvas.blit(self.frame_atual, (0, 0))

    def close(self):
        if self._capture is not None:
            self._capture.release()
        self._capture = None
        self.video_ativo = False


class FundoGifAnimado:
    """Mantem todos os quadros do GIF do menu em memoria e os exibe em loop."""

    def __init__(self, caminho_gif, tamanho):
        self.caminho_gif = Path(caminho_gif)
        self.tamanho = tuple(tamanho)
        self.frames = []
        self.duracoes = []
        self.duracao_total = 0.0
        self._inicio = time.monotonic()
        self._carregar()

    @property
    def frame_count(self):
        return len(self.frames)

    def _ajustar_tamanho(self, frame):
        if frame.get_size() == self.tamanho:
            return frame

        origem_w, origem_h = frame.get_size()
        destino_w, destino_h = self.tamanho
        if origem_w < destino_w or origem_h < destino_h:
            # Vizinho mais proximo preserva as bordas do pixel art ao ampliar.
            return pygame.transform.scale(frame, self.tamanho)
        return pygame.transform.smoothscale(frame, self.tamanho)

    def _carregar(self):
        try:
            from PIL import Image

            with Image.open(self.caminho_gif) as gif:
                for indice in range(getattr(gif, "n_frames", 1)):
                    gif.seek(indice)
                    quadro = gif.convert("RGBA")
                    frame = pygame.image.frombytes(
                        quadro.tobytes(),
                        quadro.size,
                        "RGBA",
                    ).convert_alpha()
                    self.frames.append(self._ajustar_tamanho(frame))
                    duracao_ms = max(20, int(gif.info.get("duration", 100)))
                    self.duracoes.append(duracao_ms / 1000.0)
        except Exception as exc:
            print(f"[FUNDO] Nao foi possivel animar {self.caminho_gif.name}: {exc}")
            try:
                frame = pygame.image.load(str(self.caminho_gif)).convert()
                self.frames.append(self._ajustar_tamanho(frame))
                self.duracoes.append(1.0)
            except Exception as fallback_exc:
                print(f"[FUNDO] Erro ao carregar fundo do menu: {fallback_exc}")
                frame = pygame.Surface(self.tamanho)
                frame.fill((18, 25, 35))
                self.frames.append(frame)
                self.duracoes.append(1.0)

        self.duracao_total = sum(self.duracoes)

    def desenhar(self, canvas):
        decorrido = (time.monotonic() - self._inicio) % self.duracao_total
        acumulado = 0.0
        indice = len(self.frames) - 1
        for candidato, duracao in enumerate(self.duracoes):
            acumulado += duracao
            if decorrido < acumulado:
                indice = candidato
                break
        canvas.blit(self.frames[indice], (0, 0))


def carregar_sprites_vaca():
    """
    Carrega a sprite sheet 'Imagens/sprite1.png' com recorte exato
    das 6 poses, centralizando o centro de massa e alinhando os pés.
    """
    sprite_sheet = carregar_asset(["Imagens/sprite1.png", "sprite1.png"], com_alpha=True)

    boxes_andar = [
        (33, 77, 297, 748),
        (374, 77, 356, 748),
        (720, 77, 292, 748),
    ]
    boxes_agachar = [
        (33, 825, 297, 627),
        (374, 825, 356, 627),
        (720, 825, 292, 627),
    ]

    frames_andar = []
    frames_agachar = []

    for x, y, w, h in boxes_andar:
        sub = sprite_sheet.subsurface(pygame.Rect(x, y, w, h))
        canvas = pygame.Surface((360, 750), pygame.SRCALPHA)
        dest_x = (360 - w) // 2
        dest_y = 750 - h
        canvas.blit(sub, (dest_x, dest_y))
        scaled = pygame.transform.smoothscale(canvas, (LARGURA_VACA_NORMAL, ALTURA_VACA_NORMAL))
        frames_andar.append(scaled)

    for x, y, w, h in boxes_agachar:
        sub = sprite_sheet.subsurface(pygame.Rect(x, y, w, h))
        canvas = pygame.Surface((360, 750), pygame.SRCALPHA)
        dest_x = (360 - w) // 2
        dest_y = 750 - h
        canvas.blit(sub, (dest_x, dest_y))
        # O frame agachado precisa ser realmente baixo; antes ele era escalado
        # quase como a pose em pe e nao correspondia a hitbox reduzida.
        scaled = pygame.transform.smoothscale(canvas, (LARGURA_VACA_AGACHADA, ALTURA_VACA_AGACHADA))
        frames_agachar.append(scaled)

    return frames_andar, frames_agachar


# =========================================================
# FUNÇÕES DE PERSPECTIVA E CURVATURA DOS ANÉIS DE SATURNO
# =========================================================
def _catmull_rom(p0, p1, p2, p3, t):
    """Interpolação suave que atravessa os pontos medidos da arte."""
    t2 = t * t
    t3 = t2 * t
    return 0.5 * (
        2 * p1
        + (-p0 + p2) * t
        + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
        + (-p0 + 3 * p1 - 3 * p2 + p3) * t3
    )


def calcular_limites_aneis(y):
    """Retorna as quatro bordas curvas da pista na altura informada."""
    if y <= ROTA_ANEIS[0][0]:
        atual, seguinte = ROTA_ANEIS[0], ROTA_ANEIS[1]
        t = (y - atual[0]) / (seguinte[0] - atual[0])
        return tuple(atual[i] + (seguinte[i] - atual[i]) * t for i in range(1, 5))

    if y >= ROTA_ANEIS[-1][0]:
        anterior, atual = ROTA_ANEIS[-2], ROTA_ANEIS[-1]
        t = (y - atual[0]) / (atual[0] - anterior[0])
        return tuple(atual[i] + (atual[i] - anterior[i]) * t for i in range(1, 5))

    for indice in range(len(ROTA_ANEIS) - 1):
        ponto_1 = ROTA_ANEIS[indice]
        ponto_2 = ROTA_ANEIS[indice + 1]
        if ponto_1[0] <= y <= ponto_2[0]:
            ponto_0 = ROTA_ANEIS[indice - 1] if indice > 0 else ponto_1
            ponto_3 = ROTA_ANEIS[indice + 2] if indice + 2 < len(ROTA_ANEIS) else ponto_2
            t = (y - ponto_1[0]) / (ponto_2[0] - ponto_1[0])
            return tuple(
                _catmull_rom(ponto_0[i], ponto_1[i], ponto_2[i], ponto_3[i], t)
                for i in range(1, 5)
            )

    return tuple(ROTA_ANEIS[-1][1:])


def calcular_posicao_pista(progresso_y, lane_ratio=0.50):
    """Posiciona um objeto dentro das quatro bordas curvas dos anéis."""
    y = HORIZON_Y + progresso_y * (BASE_Y - HORIZON_Y + 120)
    limites = calcular_limites_aneis(y)

    posicao_transversal = max(0.0, min(1.0, lane_ratio)) * 3.0
    trecho = min(2, int(posicao_transversal))
    fracao = posicao_transversal - trecho
    x = limites[trecho] + (limites[trecho + 1] - limites[trecho]) * fracao

    # A escala deixa de crescer antes do fim da lane. No plano da vaca ela
    # continua igual, mas não explode de tamanho enquanto sai pela tela.
    t_escala = min(0.92, max(0.0, progresso_y))
    profundidade_escala = t_escala ** 1.3
    tamanho = int(
        TAMANHO_OBSTACULO_MIN
        + (TAMANHO_OBSTACULO_MAX - TAMANHO_OBSTACULO_MIN) * profundidade_escala
    )
    if tamanho < TAMANHO_OBSTACULO_MIN:
        tamanho = TAMANHO_OBSTACULO_MIN

    return x, y, tamanho


def criar_obstaculo(velocidade_base=1.0):
    """Gera obstaculo para desviar de faixa, pular ou agachar."""
    lane_idx = random.randrange(NUM_LANES)
    sorteio_tipo = random.random()
    if sorteio_tipo < 0.22:
        tipo = 'bloqueio'
    elif sorteio_tipo < 0.50:
        tipo = 'alto'
    else:
        tipo = 'chao'
    return {
        'tipo': tipo,
        'lane_idx': lane_idx,
        'lane': LANE_RATIOS[lane_idx],
        'progresso_y': PROGRESSO_SPAWN,
        'velocidade': random.uniform(0.010, 0.016) * velocidade_base,
    }


def criar_fazendeiro(lane_idx, velocidade_base=1.0):
    """Cria o perseguidor especial mirando a faixa atual do jogador."""
    lane_idx = max(0, min(NUM_LANES - 1, int(lane_idx)))
    return {
        'tipo': 'fazendeiro',
        'lane_idx': lane_idx,
        'lane': LANE_RATIOS[lane_idx],
        'progresso_y': PROGRESSO_SPAWN,
        'velocidade': 0.021 * velocidade_base,
    }


def recortar_transparencia(imagem):
    """Remove margens transparentes para o sprite encostar no plano da pista."""
    limites = imagem.get_bounding_rect(min_alpha=10)
    if limites.width <= 0 or limites.height <= 0:
        return imagem
    return imagem.subsurface(limites).copy()


def carregar_assets_obstaculos():
    """Carrega os tres desafios e o fazendeiro, removendo folgas transparentes."""
    assets = {
        'bloqueio': carregar_asset([
            "Imagens/ob1.png",
            "Imagens/obstaculos/caixa_energia.png",
            "caixa.png",
        ], com_alpha=True),
        'chao': carregar_asset([
            "Imagens/ob2.png",
            "Imagens/obstaculos/caixa_energia.png",
            "caixa.png",
        ], com_alpha=True),
        'alto': carregar_asset([
            "Imagens/ob3.png",
            "Imagens/obstaculos/portal_agachar.png",
            "p_atras.png",
        ], com_alpha=True),
        'fazendeiro': carregar_asset([
            "Imagens/fazendeiro.png",
        ], com_alpha=True),
    }
    return {
        tipo: recortar_transparencia(imagem)
        for tipo, imagem in assets.items()
    }


LAYOUT_OBSTACULOS = {
    # Multiplicador de altura e proporcao dos recortes opacos de cada arte.
    'bloqueio': (3.80, 323 / 608),  # ob1: alto demais para pular ou agachar
    'chao': (1.76, 1.0),           # ob2: exige pulo
    'alto': (3.12, 361 / 532),     # ob3: exige agachamento
    'fazendeiro': (4.15, 570 / 988),
}


def calcular_rect_obstaculo(obs):
    """Retorna o retangulo visual do sprite respeitando a perspectiva."""
    cx, cy, tamanho = calcular_posicao_pista(obs['progresso_y'], obs['lane'])
    multiplicador_altura, aspecto = LAYOUT_OBSTACULOS[obs['tipo']]
    altura = max(24, int(tamanho * multiplicador_altura))
    largura = max(12, int(altura * aspecto))
    rect = pygame.Rect(0, 0, largura, altura)
    rect.midbottom = (int(cx), int(cy))
    return rect, cx, cy, tamanho


def calcular_hitbox_obstaculo(obs):
    """Hitboxes alinhadas aos recortes baixo, alto ou de faixa bloqueada."""
    rect, _, _, _ = calcular_rect_obstaculo(obs)
    if obs['tipo'] == 'chao':
        return pygame.Rect(
            rect.x + rect.width * 0.13,
            rect.y + rect.height * 0.12,
            rect.width * 0.74,
            rect.height * 0.80,
        )

    if obs['tipo'] == 'alto':
        # A copa do ob3 ocupa a metade superior e deixa passagem para a vaca baixa.
        return pygame.Rect(
            rect.x + rect.width * 0.06,
            rect.y + rect.height * 0.10,
            rect.width * 0.88,
            rect.height * 0.52,
        )

    if obs['tipo'] == 'fazendeiro':
        return pygame.Rect(
            rect.x + rect.width * 0.18,
            rect.y + rect.height * 0.08,
            rect.width * 0.64,
            rect.height * 0.88,
        )

    # ob1 fecha a faixa da copa ate a base: pular ou agachar nao basta.
    return pygame.Rect(
        rect.x + rect.width * 0.10,
        rect.y + rect.height * 0.02,
        rect.width * 0.80,
        rect.height * 0.93,
    )


def vaca_colide_com_obstaculo(vaca, obs):
    """Aplica a regra do desafio alem da aproximacao geometrica da hitbox."""
    # A abertura do ob3 foi feita especificamente para a vaca agachada. Perto
    # do fim da janela de colisao, a perspectiva pode fazer a hitbox do travessao
    # crescer alguns pixels para baixo; isso nunca deve invalidar o agachamento.
    if obs['tipo'] == 'alto' and vaca.is_crouching:
        return False
    return vaca.get_hitbox().colliderect(calcular_hitbox_obstaculo(obs))


def desenhar_guias_faixas(canvas):
    """Desenha três trajetórias tracejadas acompanhando a curva dos anéis."""
    overlay = pygame.Surface((LARGURA_VIRTUAL, ALTURA_VIRTUAL), pygame.SRCALPHA)
    progresso_inicial = PROGRESSO_MINIMO_VISIVEL
    progresso_final = 1.02
    passos = 40

    def ponto(indice, ratio):
        progresso = progresso_inicial + (progresso_final - progresso_inicial) * indice / passos
        return calcular_posicao_pista(progresso, ratio)

    for ratio in LANE_RATIOS:
        for i in range(0, passos, 2):
            p1 = ponto(i, ratio)
            p2 = ponto(i + 1, ratio)
            largura = max(1, int(1 + i / passos * 2))
            pygame.draw.line(overlay, (80, 225, 255, 105), p1[:2], p2[:2], largura)

    canvas.blit(overlay, (0, 0))


def desenhar_obstaculo(canvas, obs, imagens_obstaculos):
    """Renderiza o sprite novo correspondente ao desafio."""
    rect, _, _, tamanho = calcular_rect_obstaculo(obs)
    imagem = imagens_obstaculos[obs['tipo']]

    if obs['tipo'] in ('chao', 'fazendeiro'):
        sombra = pygame.Surface((rect.width, max(4, int(tamanho * 0.25))), pygame.SRCALPHA)
        pygame.draw.ellipse(sombra, (5, 8, 18, 115), sombra.get_rect())
        canvas.blit(sombra, (rect.x, rect.bottom - sombra.get_height() // 2))

    sprite = pygame.transform.smoothscale(imagem, rect.size)
    canvas.blit(sprite, rect)


def obstaculo_em_primeiro_plano(obs):
    """Indica quando o obstaculo ja esta na frente do plano da vaca."""
    _, cy, _ = calcular_posicao_pista(obs['progresso_y'], obs['lane'])
    return cy >= BASE_Y - 10


def desenhar_ranking(canvas, ranking, destaque_posicao=None):
    """Preenche o quadro de ranking que ja faz parte da arte do menu."""
    fonte_nome = pygame.font.SysFont("Arial", 19, bold=True)
    fonte_pontos = pygame.font.SysFont("Arial", 18, bold=True)
    fonte_vazio = pygame.font.SysFont("Arial", 17, italic=True)
    cores_medalha = [(255, 199, 62), (190, 205, 220), (206, 132, 80)]

    painel = pygame.Rect(758, 151, 300, 458)
    for indice in range(ranking.limite):
        y = painel.y + indice * 82
        preenchimento = (255, 250, 205, 205) if destaque_posicao == indice + 1 else (245, 247, 250, 178)
        linha = pygame.Surface((painel.width, 68), pygame.SRCALPHA)
        linha.fill(preenchimento)
        pygame.draw.rect(linha, (95, 104, 118, 210), linha.get_rect(), 2, border_radius=7)
        canvas.blit(linha, (painel.x, y))

        medalha_cor = cores_medalha[indice] if indice < 3 else (135, 145, 160)
        pygame.draw.circle(canvas, (70, 75, 86), (painel.x + 26, y + 34), 20)
        pygame.draw.circle(canvas, medalha_cor, (painel.x + 26, y + 34), 16)
        numero = fonte_pontos.render(str(indice + 1), True, (38, 42, 52))
        canvas.blit(numero, numero.get_rect(center=(painel.x + 26, y + 34)))

        if indice < len(ranking.entradas):
            entrada = ranking.entradas[indice]
            nome = fonte_nome.render(entrada["nome"], True, (35, 40, 52))
            pontos = fonte_pontos.render(f'{entrada["pontos"]} PTS', True, (45, 50, 62))
            canvas.blit(nome, (painel.x + 56, y + 12))
            canvas.blit(pontos, (painel.x + 56, y + 39))
        else:
            vazio = fonte_vazio.render("ESPAÇO LIVRE", True, (118, 124, 136))
            canvas.blit(vazio, (painel.x + 60, y + 24))


# =========================================================
# CLASSE DA VACA (PLAYER COM SISTEMA DE PULO)
# =========================================================
class VacaPlayer:
    def __init__(self, frames_andar, frames_agachar):
        self.frames_andar = frames_andar
        self.frames_agachar = frames_agachar

        # Comeca na faixa central e desliza suavemente entre as tres faixas.
        self.current_lane = 1
        self.target_x = self._calcular_x_da_faixa(self.current_lane)
        self.x = self.target_x
        self.y_base = BASE_Y
        self.is_moving = False

        # Física de Salto (Pulo)
        self.is_jumping = False
        self.jump_y = 0.0          # Deslocamento vertical negativo no ar
        self.vel_y = 0.0           # Velocidade vertical
        self.gravidade = 0.95      # Gravidade do pulo
        self.forca_pulo = -18.0    # Força inicial do salto
        self.is_crouching = False

        self.frame_index = 0.0
        self.anim_speed = 0.22

    def _calcular_x_da_faixa(self, lane_idx):
        cx, _, _ = calcular_posicao_pista(PROGRESSO_PLANO_VACA, LANE_RATIOS[lane_idx])
        return cx - (LARGURA_VACA_NORMAL / 2.0)

    def update(self, input_ctrl):
        pulou_agora = False
        # 1. Camera envia a faixa absoluta; teclado continua como fallback.
        target_lane, shift = input_ctrl.consume_lane_commands()
        if target_lane is not None:
            self.current_lane = target_lane
        elif shift:
            self.current_lane = max(0, min(NUM_LANES - 1, self.current_lane + shift))
        self.target_x = self._calcular_x_da_faixa(self.current_lane)

        diff_x = self.target_x - self.x
        if abs(diff_x) > 1.2:
            self.x += diff_x * 0.26
            self.is_moving = True
        else:
            self.x = self.target_x
            self.is_moving = False

        # 2. Trata comando de PULO
        if input_ctrl.consume_jump() and not self.is_jumping:
            self.is_jumping = True
            self.vel_y = self.forca_pulo
            pulou_agora = True

        # 3. Física do Pulo no ar
        if self.is_jumping:
            self.jump_y += self.vel_y
            self.vel_y += self.gravidade
            # Aterrissagem no chão
            if self.jump_y >= 0.0:
                self.jump_y = 0.0
                self.is_jumping = False
                self.vel_y = 0.0

        # Agachamento e pulo sao mutuamente exclusivos na representacao.
        self.is_crouching = input_ctrl.is_crouching and not self.is_jumping

        # 4. Controle de animação
        self.frame_index = (self.frame_index + self.anim_speed) % len(self.frames_andar)
        return pulou_agora

    def get_hitbox(self):
        """Retorna a hitbox ajustada para o pulo."""
        if self.is_jumping:
            # Hitbox no ar (deslocada para cima pelo jump_y)
            hb_w = LARGURA_VACA_NORMAL * 0.60
            hb_h = ALTURA_VACA_NORMAL * 0.65
            hb_x = self.x + (LARGURA_VACA_NORMAL - hb_w) / 2
            hb_y = self.y_base - ALTURA_VACA_NORMAL + 20 + self.jump_y
            return pygame.Rect(hb_x, hb_y, hb_w, hb_h)
        elif self.is_crouching:
            hb_w = LARGURA_VACA_AGACHADA * 0.68
            hb_h = ALTURA_VACA_AGACHADA * 0.58
            hb_x = self.x + (LARGURA_VACA_AGACHADA - hb_w) / 2
            hb_y = self.y_base - hb_h
            return pygame.Rect(hb_x, hb_y, hb_w, hb_h)
        else:
            # Hitbox normal em pé
            hb_w = LARGURA_VACA_NORMAL * 0.60
            hb_h = ALTURA_VACA_NORMAL * 0.75
            hb_x = self.x + (LARGURA_VACA_NORMAL - hb_w) / 2
            hb_y = self.y_base - hb_h
            return pygame.Rect(hb_x, hb_y, hb_w, hb_h)

    def draw(self, surface):
        # 1. Sombra no chão (diminui de tamanho quando a vaca pula alto)
        shadow_w = int(LARGURA_VACA_NORMAL * 0.75 * max(0.35, 1.0 - abs(self.jump_y) / 200.0))
        shadow_h = 16
        shadow_x = int(self.x + LARGURA_VACA_NORMAL / 2 - shadow_w / 2)
        shadow_y = int(self.y_base - 8)
        shadow_surf = pygame.Surface((shadow_w, shadow_h), pygame.SRCALPHA)
        shadow_alpha = int(140 * max(0.2, 1.0 - abs(self.jump_y) / 220.0))
        pygame.draw.ellipse(shadow_surf, (15, 15, 25, shadow_alpha), (0, 0, shadow_w, shadow_h))
        surface.blit(shadow_surf, (shadow_x, shadow_y))

        # 2. Desenho do Sprite da Vaca
        idx = int(self.frame_index) % 3
        if self.is_jumping:
            # Pose de salto no ar
            img = self.frames_andar[1]
            surface.blit(img, (self.x, self.y_base - ALTURA_VACA_NORMAL + self.jump_y))
        elif self.is_crouching:
            img = self.frames_agachar[idx]
            surface.blit(img, (self.x, self.y_base - img.get_height()))
        else:
            # Pose normal correndo
            img = self.frames_andar[idx]
            surface.blit(img, (self.x, self.y_base - ALTURA_VACA_NORMAL))


# =========================================================
# DESINTEGRACAO ESPECIAL AO COLIDIR COM O FAZENDEIRO
# =========================================================
class DesintegracaoTela:
    """Fragmenta o quadro inteiro em blocos e dissolve tudo para o vazio."""

    def __init__(self, quadro, origem, agora=None, duracao=1.75, bloco=40):
        self.inicio = time.monotonic() if agora is None else agora
        self.duracao = duracao
        self.blocos = []
        origem_x, origem_y = origem
        sorteio = random.Random(26082026)
        distancia_max = math.hypot(LARGURA_VIRTUAL, ALTURA_VIRTUAL)

        for y in range(0, quadro.get_height(), bloco):
            for x in range(0, quadro.get_width(), bloco):
                largura = min(bloco, quadro.get_width() - x)
                altura = min(bloco, quadro.get_height() - y)
                imagem = quadro.subsurface((x, y, largura, altura)).copy()
                centro_x = x + largura / 2.0
                centro_y = y + altura / 2.0
                dx = centro_x - origem_x
                dy = centro_y - origem_y
                distancia = max(1.0, math.hypot(dx, dy))
                direcao_x = dx / distancia
                direcao_y = dy / distancia
                velocidade = sorteio.uniform(95.0, 285.0)
                atraso = min(0.34, distancia / distancia_max * 0.28)
                atraso += sorteio.uniform(0.0, 0.055)
                self.blocos.append({
                    "imagem": imagem,
                    "x": float(x),
                    "y": float(y),
                    "vx": direcao_x * velocidade + sorteio.uniform(-45.0, 45.0),
                    "vy": direcao_y * velocidade + sorteio.uniform(-65.0, 20.0),
                    "atraso": atraso,
                    "fase": sorteio.uniform(0.0, math.tau),
                })

    def desenhar(self, canvas, agora=None):
        agora = time.monotonic() if agora is None else agora
        progresso = max(0.0, min(1.0, (agora - self.inicio) / self.duracao))
        canvas.fill((2, 3, 12))

        for bloco in self.blocos:
            atraso = bloco["atraso"]
            local = max(0.0, min(1.0, (progresso - atraso) / max(0.01, 1.0 - atraso)))
            if local >= 1.0:
                continue
            deslocamento = local * local * self.duracao
            x = bloco["x"] + bloco["vx"] * deslocamento
            y = bloco["y"] + bloco["vy"] * deslocamento
            y += 150.0 * local * local
            x += math.sin(bloco["fase"] + local * 13.0) * 14.0 * local
            bloco["imagem"].set_alpha(int(255 * (1.0 - local) ** 1.65))
            canvas.blit(bloco["imagem"], (int(x), int(y)))

        if progresso < 0.22:
            flash = pygame.Surface((LARGURA_VIRTUAL, ALTURA_VIRTUAL), pygame.SRCALPHA)
            alpha = int(185 * (1.0 - progresso / 0.22))
            flash.fill((125, 245, 255, alpha))
            canvas.blit(flash, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)

        return progresso >= 1.0


# =========================================================
# TELA CHEIA E GERENCIAMENTO DE RESOLUÇÃO (LETTERBOXING)
# =========================================================
class DisplayManager:
    """Gerencia a janela com proporção 16:9 perfeita em qualquer monitor."""
    def __init__(self):
        self.is_fullscreen = False
        self.real_screen = pygame.display.set_mode((LARGURA_VIRTUAL, ALTURA_VIRTUAL), pygame.RESIZABLE)
        pygame.display.set_caption("Cow Abduct - Visao Computacional (IFFar)")
        self.virtual_screen = pygame.Surface((LARGURA_VIRTUAL, ALTURA_VIRTUAL))

    def toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            self.real_screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.real_screen = pygame.display.set_mode((LARGURA_VIRTUAL, ALTURA_VIRTUAL), pygame.RESIZABLE)

    def render(self):
        janela_w, janela_h = self.real_screen.get_size()
        escala = min(janela_w / LARGURA_VIRTUAL, janela_h / ALTURA_VIRTUAL)
        novo_w = int(LARGURA_VIRTUAL * escala)
        novo_h = int(ALTURA_VIRTUAL * escala)
        offset_x = (janela_w - novo_w) // 2
        offset_y = (janela_h - novo_h) // 2

        self.real_screen.fill((0, 0, 0))
        # Ao ampliar, vizinho mais proximo mantem o pixel art nitido. A
        # reducao usa filtragem suave para evitar serrilhado excessivo.
        if escala >= 1.0:
            scaled = pygame.transform.scale(self.virtual_screen, (novo_w, novo_h))
        else:
            scaled = pygame.transform.smoothscale(self.virtual_screen, (novo_w, novo_h))
        self.real_screen.blit(scaled, (offset_x, offset_y))
        pygame.display.flip()

    def map_mouse_pos(self, mouse_pos):
        janela_w, janela_h = self.real_screen.get_size()
        escala = min(janela_w / LARGURA_VIRTUAL, janela_h / ALTURA_VIRTUAL)
        novo_w = int(LARGURA_VIRTUAL * escala)
        novo_h = int(ALTURA_VIRTUAL * escala)
        offset_x = (janela_w - novo_w) // 2
        offset_y = (janela_h - novo_h) // 2

        vx = (mouse_pos[0] - offset_x) / escala
        vy = (mouse_pos[1] - offset_y) / escala
        return vx, vy


# =========================================================
# TABELA / PAINEL DE DEBUG EM TEMPO REAL
# =========================================================
def desenhar_tabela_debug(
    canvas,
    input_ctrl,
    vision_ctrl,
    vaca=None,
    fps=60.0,
    power_ctrl=None,
):
    """Renderiza a leitura da camera e o estado do player em tempo real."""
    if not input_ctrl.show_debug:
        return

    power_snapshot = power_ctrl.snapshot() if power_ctrl is not None else None
    painel_w = 455
    painel_h = 402 if power_snapshot is not None else 330
    painel_x = LARGURA_VIRTUAL - painel_w - 20
    painel_y = 20

    painel_bg = pygame.Surface((painel_w, painel_h), pygame.SRCALPHA)
    painel_bg.fill((12, 16, 28, 230))
    pygame.draw.rect(painel_bg, (0, 180, 255), (0, 0, painel_w, painel_h), 2, border_radius=8)
    canvas.blit(painel_bg, (painel_x, painel_y))

    fonte_tit = pygame.font.SysFont("Courier New", 14, bold=True)
    fonte_txt = pygame.font.SysFont("Courier New", 13, bold=True)
    txt_tit = fonte_tit.render("== VISAO COMPUTACIONAL / CONTROLE CORPORAL ==", True, (255, 220, 80))
    canvas.blit(txt_tit, (painel_x + 15, painel_y + 10))
    pygame.draw.line(canvas, (0, 180, 255), (painel_x + 10, painel_y + 30), (painel_x + painel_w - 10, painel_y + 30), 1)

    if vaca:
        if vaca.is_jumping:
            acao_str, acao_cor = "PULANDO NO AR", (100, 230, 255)
        elif vaca.is_crouching:
            acao_str, acao_cor = "AGACHADO", (255, 220, 80)
        else:
            acao_str, acao_cor = "CORRENDO NA PISTA", (80, 255, 120)
        lane_nome = NOME_LANES[vaca.current_lane]
    else:
        acao_str, acao_cor = "MENU INICIAL", (180, 180, 180)
        lane_nome = "CENTRO"

    linhas = [
        ("Camera:", vision_ctrl.status[:34], (80, 255, 120) if vision_ctrl.connected else (255, 190, 80)),
        ("Detector:", vision_ctrl.engine, (100, 230, 255)),
        ("Gesto lido:", vision_ctrl.action, acao_cor),
        ("Mov. lateral:", f"{vision_ctrl.lateral:+.2f} troncos", (100, 230, 255)),
        ("Mov. vertical:", f"{vision_ctrl.vertical:+.2f} troncos", (255, 200, 80)),
        ("Faixa da vaca:", lane_nome, (255, 255, 100)),
        ("Estado da vaca:", acao_str, acao_cor),
        ("Ultima entrada:", input_ctrl.last_control_source.upper(), (200, 220, 255)),
        ("FPS jogo/camera:", f"{fps:.0f} / {vision_ctrl.fps:.0f}", (180, 220, 255)),
    ]
    if power_snapshot is not None:
        if power_snapshot.shield_active:
            power_state = "ESCUDO ATIVO"
        elif power_snapshot.twist_ready:
            power_state = "GIRE PARA ATIVAR"
        elif power_snapshot.armed:
            power_state = "PARE A CAIXA"
        else:
            power_state = f"CARGA {power_snapshot.charge_ratio * 100:.0f}%"
        esp32_color = (
            (80, 255, 135)
            if power_snapshot.connected
            else (255, 190, 80)
        )
        linhas.extend([
            ("ESP32 Wi-Fi:", power_snapshot.status[:34], esp32_color),
            ("Nucleo:", power_state, (80, 245, 210)),
            (
                "Mov./giro:",
                f"{power_snapshot.motion_intensity:.2f} g / "
                f"{power_snapshot.gyro_speed:.0f} dps",
                (130, 210, 255),
            ),
        ])

    curr_y = painel_y + 38
    for label, val, cor in linhas:
        t_lbl = fonte_txt.render(label, True, (160, 180, 210))
        t_val = fonte_txt.render(val, True, cor)
        canvas.blit(t_lbl, (painel_x + 15, curr_y))
        canvas.blit(t_val, (painel_x + 160, curr_y))
        curr_y += 24

    t_dica = fonte_tit.render("[C] Recalibrar | [V] Camera | [TAB] Painel", True, (120, 145, 175))
    canvas.blit(t_dica, (painel_x + 15, painel_y + painel_h - 22))

    if time.time() < input_ctrl.feedback_timer and input_ctrl.feedback_msg:
        fonte_pop = pygame.font.SysFont("Arial", 22, bold=True)
        t_pop = fonte_pop.render(input_ctrl.feedback_msg, True, (255, 255, 100))
        pop_w = t_pop.get_width() + 30
        pop_h = 44
        pop_x = (LARGURA_VIRTUAL - pop_w) // 2
        pop_y = 35
        pop_bg = pygame.Surface((pop_w, pop_h), pygame.SRCALPHA)
        pop_bg.fill((20, 30, 50, 235))
        pygame.draw.rect(pop_bg, (0, 220, 255), (0, 0, pop_w, pop_h), 2, border_radius=8)
        canvas.blit(pop_bg, (pop_x, pop_y))
        canvas.blit(t_pop, (pop_x + 15, pop_y + 8))


def desenhar_preview_camera(canvas, input_ctrl, vision_ctrl, posicao=(20, 445), tamanho=None):
    """Mostra a camera dentro do jogo, sem abrir uma segunda janela."""
    if not input_ctrl.show_camera:
        return

    preview = vision_ctrl.get_preview()
    x, y = posicao
    width, height = tamanho or vision_ctrl.PREVIEW_SIZE
    pygame.draw.rect(canvas, (10, 16, 28), (x - 5, y - 31, width + 10, height + 36), border_radius=8)
    pygame.draw.rect(canvas, (0, 210, 255), (x - 5, y - 31, width + 10, height + 36), 2, border_radius=8)

    fonte = pygame.font.SysFont("Arial", 16, bold=True)
    titulo = fonte.render("CAMERA IA  |  [V] ocultar", True, (220, 245, 255))
    canvas.blit(titulo, (x + 5, y - 25))

    if preview:
        frame_bytes, size = preview
        surface = pygame.image.frombuffer(frame_bytes, size, "RGB")
        if surface.get_size() != (width, height):
            surface = pygame.transform.smoothscale(surface, (width, height))
        canvas.blit(surface, (x, y))
    else:
        pygame.draw.rect(canvas, (22, 28, 42), (x, y, width, height))
        mensagem = fonte.render(vision_ctrl.status[:35], True, (255, 210, 100))
        canvas.blit(mensagem, (x + 12, y + height // 2 - 8))


def desenhar_poder_esp32(canvas, vaca, snapshot, agora=None):
    """Desenha carga, escudo e impacto ao redor da vaca, sem criar outro HUD."""
    agora = time.monotonic() if agora is None else agora
    if (
        not snapshot.connected
        and not snapshot.shield_active
        and snapshot.activation_flash <= 0.0
        and snapshot.hit_flash <= 0.0
    ):
        return
    if (
        snapshot.charge_ratio <= 0.0
        and not snapshot.shield_active
        and snapshot.activation_flash <= 0.0
        and snapshot.hit_flash <= 0.0
    ):
        return

    hitbox = vaca.get_hitbox()
    center_x, center_y = hitbox.center
    tamanho = 250
    centro = tamanho // 2
    overlay = pygame.Surface((tamanho, tamanho), pygame.SRCALPHA)
    pulso = (math.sin(agora * 7.0) + 1.0) * 0.5

    if snapshot.charge_ratio > 0.0 and not snapshot.shield_active:
        raio = 72 + int(pulso * 4)
        rect = pygame.Rect(
            centro - raio,
            centro - raio,
            raio * 2,
            raio * 2,
        )
        cor = (80, 255, 165, 235 if snapshot.armed else 185)
        inicio = -math.pi / 2
        fim = inicio + math.tau * snapshot.charge_ratio
        pygame.draw.arc(overlay, cor, rect, inicio, fim, 5)

        angulo = fim
        ponto = (
            int(centro + math.cos(angulo) * raio),
            int(centro + math.sin(angulo) * raio),
        )
        pygame.draw.circle(overlay, (205, 255, 235, 245), ponto, 5)

        if snapshot.armed:
            alpha = 80 + int(pulso * 80)
            pygame.draw.circle(
                overlay,
                (75, 255, 190, alpha),
                (centro, centro),
                raio + 8,
                3,
            )

    if snapshot.shield_active:
        raio = 86 + int(pulso * 5)
        pygame.draw.circle(
            overlay,
            (40, 245, 190, 38),
            (centro, centro),
            raio,
        )
        pygame.draw.circle(
            overlay,
            (105, 255, 215, 230),
            (centro, centro),
            raio,
            5,
        )
        pygame.draw.circle(
            overlay,
            (205, 255, 245, 115),
            (centro, centro),
            raio - 9,
            2,
        )
        for indice in range(6):
            angulo = agora * 1.8 + indice * math.tau / 6
            px = int(centro + math.cos(angulo) * (raio + 7))
            py = int(centro + math.sin(angulo) * (raio + 7))
            pygame.draw.circle(overlay, (180, 255, 235, 220), (px, py), 3)

    if snapshot.activation_flash > 0.0:
        progresso = 1.0 - snapshot.activation_flash
        raio = int(78 + progresso * 62)
        alpha = int(210 * snapshot.activation_flash)
        pygame.draw.circle(
            overlay,
            (110, 255, 220, alpha),
            (centro, centro),
            raio,
            6,
        )

    if snapshot.hit_flash > 0.0:
        raio = int(72 + (1.0 - snapshot.hit_flash) * 75)
        alpha = int(255 * snapshot.hit_flash)
        pygame.draw.circle(
            overlay,
            (240, 255, 255, alpha),
            (centro, centro),
            raio,
            9,
        )

    canvas.blit(
        overlay,
        (center_x - centro, center_y - centro),
    )


# =========================================================
# TELA INICIAL
# =========================================================
def desenhar_editor_nome(canvas, nome_digitado):
    """Mostra a entrada de nome apenas depois que o jogador pede para jogar."""
    overlay = pygame.Surface((LARGURA_VIRTUAL, ALTURA_VIRTUAL), pygame.SRCALPHA)
    overlay.fill((5, 9, 16, 190))
    canvas.blit(overlay, (0, 0))

    painel = pygame.Rect(370, 225, 540, 250)
    sombra = pygame.Surface((painel.width + 18, painel.height + 18), pygame.SRCALPHA)
    pygame.draw.rect(sombra, (0, 0, 0, 110), sombra.get_rect(), border_radius=16)
    canvas.blit(sombra, (painel.x + 8, painel.y + 10))

    pygame.draw.rect(canvas, (29, 38, 52), painel, border_radius=14)
    pygame.draw.rect(canvas, (130, 255, 185), painel, 3, border_radius=14)

    fonte_titulo = pygame.font.SysFont("Arial", 30, bold=True)
    fonte_nome = pygame.font.SysFont("Arial", 32, bold=True)
    fonte_dica = pygame.font.SysFont("Arial", 17)
    titulo = fonte_titulo.render("DIGITE SEU NOME", True, (238, 246, 255))
    canvas.blit(titulo, titulo.get_rect(center=(painel.centerx, painel.y + 49)))

    campo = pygame.Rect(painel.x + 55, painel.y + 87, painel.width - 110, 65)
    pygame.draw.rect(canvas, (15, 22, 34), campo, border_radius=8)
    pygame.draw.rect(canvas, (130, 255, 185), campo, 2, border_radius=8)

    cursor = "_" if int(time.monotonic() * 2) % 2 == 0 else ""
    exibido = nome_digitado or "SEU NOME"
    cor_nome = (245, 250, 255) if nome_digitado else (125, 145, 165)
    texto_nome = fonte_nome.render(f"{exibido}{cursor}", True, cor_nome)
    canvas.blit(texto_nome, texto_nome.get_rect(center=campo.center))

    dica = fonte_dica.render(
        "ENTER para jogar   •   ESC para cancelar",
        True,
        (190, 208, 225),
    )
    canvas.blit(dica, dica.get_rect(center=(painel.centerx, painel.bottom - 45)))


def tela_inicial(
    display_mgr,
    input_ctrl,
    vision_ctrl,
    ranking,
    nome_jogador="JOGADOR",
    power_ctrl=None,
    audio=None,
):
    if audio is not None:
        audio.tocar_menu()
    fundo = FundoGifAnimado(
        PASTA_PROJETO / "Imagens" / "fundo_inicio.gif",
        (LARGURA_VIRTUAL, ALTURA_VIRTUAL),
    )

    # O botão cinza já faz parte da arte do menu; só criamos sua área clicável.
    botao_rect = pygame.Rect(AREA_BOTAO_JOGAR)

    clock = pygame.time.Clock()
    nome_confirmado = normalizar_nome_jogador(nome_jogador)
    nome_digitado = nome_confirmado
    nome_anterior = nome_confirmado
    editando_nome = False

    esperando = True
    try:
        while esperando:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()

                if editando_nome:
                    if event.type == pygame.KEYDOWN:
                        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                            nome_confirmado = normalizar_nome_jogador(nome_digitado)
                            esperando = False
                        elif event.key == pygame.K_ESCAPE:
                            nome_digitado = nome_anterior
                            editando_nome = False
                            pygame.key.stop_text_input()
                        elif event.key == pygame.K_BACKSPACE:
                            nome_digitado = nome_digitado[:-1]
                    elif event.type == pygame.TEXTINPUT:
                        nome_digitado = limpar_nome_digitado(
                            nome_digitado + event.text
                        )
                    continue

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_f or event.key == pygame.K_F11:
                        display_mgr.toggle_fullscreen()
                    elif event.key == pygame.K_TAB:
                        input_ctrl.show_debug = not input_ctrl.show_debug
                    elif event.key == pygame.K_v:
                        input_ctrl.show_camera = not input_ctrl.show_camera
                    elif event.key == pygame.K_c:
                        input_ctrl.calibrate_center()
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                        nome_anterior = nome_confirmado
                        nome_digitado = "" if nome_confirmado == "JOGADOR" else nome_confirmado
                        editando_nome = True
                        pygame.key.start_text_input()

                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    vx, vy = display_mgr.map_mouse_pos(event.pos)
                    if botao_rect.collidepoint((vx, vy)):
                        nome_anterior = nome_confirmado
                        nome_digitado = "" if nome_confirmado == "JOGADOR" else nome_confirmado
                        editando_nome = True
                        pygame.key.start_text_input()

            canvas = display_mgr.virtual_screen
            fundo.desenhar(canvas)
            desenhar_ranking(canvas, ranking)

            mouse_virtual = display_mgr.map_mouse_pos(pygame.mouse.get_pos())
            if not editando_nome and botao_rect.collidepoint(mouse_virtual):
                pygame.draw.rect(
                    canvas,
                    (130, 255, 185),
                    botao_rect.inflate(8, 8),
                    2,
                    border_radius=5,
                )

            desenhar_preview_camera(
                canvas,
                input_ctrl,
                vision_ctrl,
                posicao=(20, 105),
                tamanho=(210, 158),
            )
            desenhar_tabela_debug(
                canvas,
                input_ctrl,
                vision_ctrl,
                None,
                clock.get_fps(),
                power_ctrl,
            )

            if editando_nome:
                desenhar_editor_nome(canvas, nome_digitado)

            display_mgr.render()
            clock.tick(FPS)
    finally:
        pygame.key.stop_text_input()

    return nome_confirmado


# =========================================================
# LOOP PRINCIPAL DA GAMEPLAY (VISAO + OBSTACULOS)
# =========================================================
def loop_gameplay(
    display_mgr,
    input_ctrl,
    vision_ctrl,
    frames_andar,
    frames_agachar,
    fundo_cenario,
    imagens_obstaculos,
    ranking,
    nome_jogador,
    power_ctrl=None,
    audio=None,
):
    fonte_hud = pygame.font.SysFont("Arial", 28, bold=True)
    fonte_go_grande = pygame.font.SysFont("Arial", 64, bold=True)
    fonte_go_sub = pygame.font.SysFont("Arial", 26)
    clock = pygame.time.Clock()
    config_dificuldade = DIFICULDADES[MODO_JOGO]

    while True:
        if audio is not None:
            audio.tocar_gameplay()
        if power_ctrl is not None:
            power_ctrl.set_enabled(True, reset=True)
        vaca = VacaPlayer(frames_andar, frames_agachar)
        input_ctrl.consume_jump()
        input_ctrl.consume_lane_commands()
        obstaculos = []
        spawn_timer = 0
        spawn_intervalo = config_dificuldade["spawn"]
        fazendeiro_timer = 0
        proximo_fazendeiro = random.randint(
            INTERVALO_FAZENDEIRO_MIN,
            INTERVALO_FAZENDEIRO_MAX,
        )
        pontuacao = 0.0
        distancia = 0.0
        game_over = False
        posicao_ranking = None
        desintegracao = None
        origem_desintegracao = None

        partida_ativa = True
        while partida_ativa:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return False
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_f or event.key == pygame.K_F11:
                        display_mgr.toggle_fullscreen()
                    elif event.key == pygame.K_TAB:
                        input_ctrl.show_debug = not input_ctrl.show_debug
                    elif event.key == pygame.K_v:
                        input_ctrl.show_camera = not input_ctrl.show_camera
                    elif event.key == pygame.K_ESCAPE:
                        return True
                    elif game_over and event.key in (pygame.K_r, pygame.K_SPACE, pygame.K_RETURN):
                        partida_ativa = False

            input_ctrl.update_from_keyboard(pygame.key.get_pressed())

            if desintegracao is not None:
                canvas = display_mgr.virtual_screen
                if desintegracao.desenhar(canvas):
                    return True
                display_mgr.render()
                clock.tick(FPS)
                continue

            if not game_over:
                velocidade_modo = config_dificuldade["velocidade"]
                pontuacao += velocidade_modo
                distancia += 0.35 * velocidade_modo

                spawn_timer += 1
                if spawn_timer >= spawn_intervalo:
                    obstaculos.append(criar_obstaculo(velocidade_base=velocidade_modo))
                    spawn_timer = 0

                fazendeiro_timer += 1
                fazendeiro_ativo = any(
                    obs['tipo'] == 'fazendeiro'
                    for obs in obstaculos
                )
                if fazendeiro_timer >= proximo_fazendeiro and not fazendeiro_ativo:
                    obstaculos.append(criar_fazendeiro(
                        vaca.current_lane,
                        velocidade_base=velocidade_modo,
                    ))
                    fazendeiro_timer = 0
                    proximo_fazendeiro = random.randint(
                        INTERVALO_FAZENDEIRO_MIN,
                        INTERVALO_FAZENDEIRO_MAX,
                    )

                if vaca.update(input_ctrl) and audio is not None:
                    audio.tocar_pulo()

                for obs in obstaculos:
                    obs['progresso_y'] += obs['velocidade']
                obstaculos = [o for o in obstaculos if o['progresso_y'] < 1.35]

                for obs in obstaculos:
                    _, cy, _ = calcular_posicao_pista(obs['progresso_y'], obs['lane'])
                    if BASE_Y - 45 <= cy <= BASE_Y + 35:
                        if vaca_colide_com_obstaculo(vaca, obs):
                            if obs['tipo'] == 'fazendeiro':
                                rect_fazendeiro, _, _, _ = calcular_rect_obstaculo(obs)
                                origem_desintegracao = rect_fazendeiro.center
                                if audio is not None:
                                    audio.parar_musica(260)
                                    audio.tocar_morte()
                                break
                            escudo_absorveu = (
                                power_ctrl is not None
                                and power_ctrl.absorb_collision()
                            )
                            if escudo_absorveu:
                                obs["removido_pelo_escudo"] = True
                            else:
                                game_over = True
                                if audio is not None:
                                    audio.parar_musica(420)
                                    audio.tocar_morte()
                                posicao_ranking = ranking.registrar(
                                    nome_jogador,
                                    int(pontuacao),
                                    MODO_JOGO,
                                )
                            break
                obstaculos = [
                    obs for obs in obstaculos
                    if not obs.get("removido_pelo_escudo")
                ]

            canvas = display_mgr.virtual_screen
            fundo_cenario.desenhar(canvas)
            desenhar_guias_faixas(canvas)

            obstaculos_visiveis = [
                obs for obs in sorted(
                    obstaculos,
                    key=lambda item: item['progresso_y'],
                )
                if obs['progresso_y'] > PROGRESSO_MINIMO_VISIVEL
            ]
            obstaculos_atras = [
                obs for obs in obstaculos_visiveis
                if not obstaculo_em_primeiro_plano(obs)
            ]
            obstaculos_na_frente = [
                obs for obs in obstaculos_visiveis
                if obstaculo_em_primeiro_plano(obs)
            ]

            for obs in obstaculos_atras:
                desenhar_obstaculo(canvas, obs, imagens_obstaculos)

            vaca.draw(canvas)

            if power_ctrl is not None:
                power_snapshot = power_ctrl.snapshot()
                desenhar_poder_esp32(canvas, vaca, power_snapshot)

            # Portais e demais obstaculos que cruzaram o plano da vaca ficam
            # por cima dela. A transparencia do ob3 revela a vaca agachada na
            # passagem inferior e sua copa encobre a vaca que nao agachou.
            for obs in obstaculos_na_frente:
                desenhar_obstaculo(canvas, obs, imagens_obstaculos)

            hud_bg = pygame.Surface((335, 78), pygame.SRCALPHA)
            hud_bg.fill((20, 20, 35, 190))
            canvas.blit(hud_bg, (20, 20))

            txt_score = fonte_hud.render(f"PONTOS: {int(pontuacao)}", True, (255, 230, 90))
            txt_dist = fonte_hud.render(f"DISTÂNCIA: {int(distancia)}m", True, (255, 255, 255))
            canvas.blit(txt_score, (35, 26))
            canvas.blit(txt_dist, (35, 56))

            desenhar_preview_camera(canvas, input_ctrl, vision_ctrl)
            desenhar_tabela_debug(
                canvas,
                input_ctrl,
                vision_ctrl,
                vaca,
                clock.get_fps(),
                power_ctrl,
            )

            if game_over:
                overlay = pygame.Surface((LARGURA_VIRTUAL, ALTURA_VIRTUAL), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 195))
                canvas.blit(overlay, (0, 0))

                txt_go = fonte_go_grande.render("GAME OVER", True, (255, 60, 60))
                txt_score_final = fonte_hud.render(
                    f"Pontuação Final: {int(pontuacao)}",
                    True,
                    (255, 255, 255),
                )
                txt_sub1 = fonte_go_sub.render(
                    "Pressione [R] ou [ESPAÇO] para Jogar Novamente",
                    True,
                    (240, 240, 240),
                )
                txt_sub2 = fonte_go_sub.render(
                    "Pressione [ESC] para Voltar ao Menu Inicial",
                    True,
                    (180, 180, 180),
                )

                if posicao_ranking is not None:
                    txt_ranking = fonte_go_sub.render(
                        f"NOVO #{posicao_ranking} DO RANKING!",
                        True,
                        (255, 220, 80),
                    )
                else:
                    txt_ranking = fonte_go_sub.render(
                        "Continue tentando para entrar no TOP 5!",
                        True,
                        (190, 205, 220),
                    )

                canvas.blit(txt_go, (LARGURA_VIRTUAL // 2 - txt_go.get_width() // 2, 220))
                canvas.blit(txt_score_final, (LARGURA_VIRTUAL // 2 - txt_score_final.get_width() // 2, 310))
                canvas.blit(txt_ranking, (LARGURA_VIRTUAL // 2 - txt_ranking.get_width() // 2, 355))
                canvas.blit(txt_sub1, (LARGURA_VIRTUAL // 2 - txt_sub1.get_width() // 2, 415))
                canvas.blit(txt_sub2, (LARGURA_VIRTUAL // 2 - txt_sub2.get_width() // 2, 460))

            if origem_desintegracao is not None:
                desintegracao = DesintegracaoTela(
                    canvas.copy(),
                    origem_desintegracao,
                )
                desintegracao.desenhar(canvas)
                origem_desintegracao = None

            display_mgr.render()
            clock.tick(FPS)


# =========================================================
# PONTO DE ENTRADA PRINCIPAL
# =========================================================
def main():
    pygame.mixer.pre_init(44_100, -16, 2, 512)
    pygame.init()
    pygame.font.init()

    display_mgr = DisplayManager()

    input_ctrl = InputController()
    vision_ctrl = VisionController(input_ctrl)
    input_ctrl.vision_recalibrate_callback = vision_ctrl.request_calibration
    vision_ctrl.start()
    power_ctrl = Esp32PowerController()
    power_ctrl.start()
    ranking = RankingPersistente()
    audio = AudioJogo()
    nome_jogador = "JOGADOR"
    fundo_cenario = None

    try:
        # Carrega o cenario, os obstaculos e o personagem.
        imagem_cenario = carregar_asset([
            "Imagens/fundo_jogo/caminho.png",
            "Imagens/fundo_jogo/caminho1.png",
            "Imagens/caminho.png",
            "Imagens/caminho1.png",
            "Imagens/fundo_jogo/listra.png"
        ])
        fundo_cenario = FundoJogoAnimado(
            VIDEO_FUNDO_JOGO,
            imagem_cenario,
            (LARGURA_VIRTUAL, ALTURA_VIRTUAL),
        )

        imagens_obstaculos = carregar_assets_obstaculos()
        frames_andar, frames_agachar = carregar_sprites_vaca()

        while True:
            power_ctrl.set_enabled(False)
            nome_jogador = tela_inicial(
                display_mgr,
                input_ctrl,
                vision_ctrl,
                ranking,
                nome_jogador,
                power_ctrl,
                audio,
            )
            continuar = loop_gameplay(
                display_mgr,
                input_ctrl,
                vision_ctrl,
                frames_andar,
                frames_agachar,
                fundo_cenario,
                imagens_obstaculos,
                ranking,
                nome_jogador,
                power_ctrl,
                audio,
            )
            if not continuar:
                break
    finally:
        if fundo_cenario is not None:
            fundo_cenario.close()
        power_ctrl.stop()
        vision_ctrl.stop()
        audio.desligar()
        pygame.quit()


if __name__ == "__main__":
    main()
