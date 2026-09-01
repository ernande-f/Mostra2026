"""Gera propostas sonoras originais para aprovacao antes da integracao.

Os arquivos WAV usam apenas sintese local, sem samples ou musicas de terceiros.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


TAXA = 44_100
RAIZ = Path(__file__).resolve().parents[1]
PASTA_SAIDA = RAIZ / "Sons" / "previas"
RNG = np.random.default_rng(20260825)


def midi_para_hz(nota: float) -> float:
    return 440.0 * (2.0 ** ((nota - 69.0) / 12.0))


def envelope_adsr(
    quantidade: int,
    ataque: float,
    queda: float,
    sustentacao: float,
    soltura: float,
) -> np.ndarray:
    env = np.full(quantidade, sustentacao, dtype=np.float64)
    tamanhos = [
        min(quantidade, max(1, int(ataque * TAXA))),
        min(quantidade, max(1, int(queda * TAXA))),
        min(quantidade, max(1, int(soltura * TAXA))),
    ]
    a, d, r = tamanhos
    env[:a] = np.linspace(0.0, 1.0, a, endpoint=False)
    fim_queda = min(quantidade, a + d)
    if fim_queda > a:
        env[a:fim_queda] = np.linspace(1.0, sustentacao, fim_queda - a, endpoint=False)
    inicio_soltura = max(fim_queda, quantidade - r)
    if inicio_soltura < quantidade:
        env[inicio_soltura:] *= np.linspace(1.0, 0.0, quantidade - inicio_soltura)
    return env


def escrever_wav(caminho: Path, audio: np.ndarray, pico: float = 0.88) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    audio = np.nan_to_num(audio)
    maior = float(np.max(np.abs(audio)))
    if maior > 0:
        audio = audio * (pico / maior)
    audio = np.tanh(audio * 1.08) / np.tanh(1.08)
    pcm = np.clip(audio * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(2)
        arquivo.setsampwidth(2)
        arquivo.setframerate(TAXA)
        arquivo.writeframes(pcm.T.reshape(-1).tobytes())


def gerar_pulo() -> np.ndarray:
    duracao = 0.46
    n = int(duracao * TAXA)
    t = np.arange(n) / TAXA
    frequencia = 270.0 * ((1_080.0 / 270.0) ** (t / duracao))
    frequencia *= 1.0 + 0.018 * np.sin(2.0 * np.pi * 18.0 * t)
    fase = 2.0 * np.pi * np.cumsum(frequencia) / TAXA
    env = (1.0 - np.exp(-70.0 * t)) * np.exp(-4.6 * t / duracao)
    brilho = np.sin(fase) + 0.28 * np.sin(2.0 * fase + 0.15)
    brilho += 0.10 * np.sin(3.0 * fase + 0.8)

    ruido = RNG.normal(0.0, 1.0, n)
    ruido = np.concatenate(([0.0], np.diff(ruido)))
    ruido *= np.exp(-18.0 * t) * 0.025
    centro = 0.52 * brilho * env + ruido
    esquerda = centro + 0.04 * np.sin(fase * 1.006) * env
    direita = centro + 0.04 * np.sin(fase * 0.994 + 0.2) * env
    return np.vstack((esquerda, direita))


def gerar_morte() -> np.ndarray:
    duracao = 1.55
    n = int(duracao * TAXA)
    t = np.arange(n) / TAXA
    frequencia = 510.0 * ((62.0 / 510.0) ** (t / duracao))
    frequencia *= 1.0 + 0.035 * np.sin(2.0 * np.pi * 7.2 * t)
    fase = 2.0 * np.pi * np.cumsum(frequencia) / TAXA
    env = (1.0 - np.exp(-85.0 * t)) * np.exp(-2.45 * t)
    power_down = np.sin(fase) + 0.32 * np.sin(1.51 * fase + 0.3)
    power_down += 0.18 * np.sin(0.5 * fase)

    impacto_env = np.exp(-12.0 * t)
    impacto = np.sin(2.0 * np.pi * (86.0 * t - 20.0 * t * t)) * impacto_env
    estalo = RNG.normal(0.0, 1.0, n) * np.exp(-22.0 * t)
    centro = 0.46 * power_down * env + 0.24 * impacto + 0.06 * estalo

    atraso = int(0.018 * TAXA)
    eco = np.zeros(n)
    eco[atraso:] = centro[:-atraso] * 0.23
    esquerda = centro + eco
    direita = centro - 0.08 * impacto + np.roll(eco, int(0.008 * TAXA))
    return np.vstack((esquerda, direita))


def adicionar_nota(
    trilha: np.ndarray,
    inicio: float,
    duracao: float,
    midi: float,
    volume: float,
    timbre: str,
    panorama: float = 0.0,
) -> None:
    primeiro = max(0, int(inicio * TAXA))
    ultimo = min(trilha.shape[1], int((inicio + duracao) * TAXA))
    n = ultimo - primeiro
    if n <= 1:
        return
    t = np.arange(n) / TAXA
    hz = midi_para_hz(midi)
    vibrato = 1.0 + 0.0022 * np.sin(2.0 * np.pi * 0.22 * t + midi)
    fase = 2.0 * np.pi * hz * np.cumsum(vibrato) / TAXA

    if timbre == "pad":
        onda = np.sin(fase) + 0.27 * np.sin(2.0 * fase + 0.25)
        onda += 0.10 * np.sin(3.0 * fase + 1.1)
        onda *= 0.88 + 0.12 * np.sin(2.0 * np.pi * 0.10 * t + midi)
        env = envelope_adsr(n, 0.68, 0.55, 0.72, 1.05)
    elif timbre == "sino":
        onda = np.sin(fase) + 0.34 * np.sin(2.01 * fase + 0.4)
        onda += 0.13 * np.sin(3.97 * fase + 0.9)
        env = envelope_adsr(n, 0.012, 0.18, 0.28, min(0.8, duracao * 0.55))
        env *= np.exp(-1.0 * t)
    elif timbre == "pluc":
        onda = np.sin(fase) + 0.22 * np.sin(2.0 * fase)
        onda += 0.08 * np.sin(4.0 * fase + 0.1)
        env = envelope_adsr(n, 0.008, 0.10, 0.18, min(0.5, duracao * 0.45))
        env *= np.exp(-2.2 * t)
    else:  # baixo macio
        onda = np.sin(fase) + 0.18 * np.sin(2.0 * fase + 0.2)
        env = envelope_adsr(n, 0.05, 0.18, 0.62, min(0.45, duracao * 0.3))

    sinal = onda * env * volume
    ganho_esq = np.sqrt((1.0 - panorama) * 0.5)
    ganho_dir = np.sqrt((1.0 + panorama) * 0.5)
    trilha[0, primeiro:ultimo] += sinal * ganho_esq
    trilha[1, primeiro:ultimo] += sinal * ganho_dir


def aplicar_ambiencia(trilha: np.ndarray, intensidade: float) -> np.ndarray:
    seca = trilha.copy()
    for atraso_s, ganho, cruzado in (
        (0.19, 0.18, False),
        (0.31, 0.12, True),
        (0.47, 0.075, False),
    ):
        atraso = int(atraso_s * TAXA)
        origem = seca[::-1] if cruzado else seca
        trilha[:, atraso:] += origem[:, :-atraso] * ganho * intensidade
    return trilha


def adicionar_percussao(
    trilha: np.ndarray,
    inicio: float,
    tipo: str,
    volume: float,
    panorama: float = 0.0,
) -> None:
    duracao = 0.34 if tipo == "bumbo" else 0.20
    primeiro = max(0, int(inicio * TAXA))
    ultimo = min(trilha.shape[1], primeiro + int(duracao * TAXA))
    n = ultimo - primeiro
    if n <= 1:
        return
    t = np.arange(n) / TAXA
    if tipo == "bumbo":
        frequencia = 132.0 * ((48.0 / 132.0) ** (t / duracao))
        fase = 2.0 * np.pi * np.cumsum(frequencia) / TAXA
        sinal = np.sin(fase) * np.exp(-14.0 * t)
    elif tipo == "caixa":
        ruido = RNG.normal(0.0, 1.0, n)
        ruido = np.concatenate(([0.0], np.diff(ruido)))
        sinal = ruido * np.exp(-22.0 * t)
        sinal += 0.24 * np.sin(2.0 * np.pi * 172.0 * t) * np.exp(-18.0 * t)
    else:  # chimbal macio
        ruido = RNG.normal(0.0, 1.0, n)
        ruido = np.concatenate(([0.0], np.diff(ruido)))
        sinal = ruido * np.exp(-34.0 * t)

    sinal *= volume
    ganho_esq = np.sqrt((1.0 - panorama) * 0.5)
    ganho_dir = np.sqrt((1.0 + panorama) * 0.5)
    trilha[0, primeiro:ultimo] += sinal * ganho_esq
    trilha[1, primeiro:ultimo] += sinal * ganho_dir


def compor_musica(estilo: int) -> np.ndarray:
    bpm = {1: 72.0, 2: 80.0, 3: 102.0}[estilo]
    beat = 60.0 / bpm
    compassos = 8
    periodo = compassos * 4.0 * beat
    duracao_trabalho = periodo * 3.0
    trilha = np.zeros((2, int(duracao_trabalho * TAXA)), dtype=np.float64)

    if estilo == 1:
        acordes = [
            (48, 52, 55, 59),  # Cmaj7
            (45, 48, 52, 55),  # Am7
            (41, 45, 48, 52),  # Fmaj7
            (43, 47, 50, 52),  # G6
            (48, 52, 55, 59),
            (40, 43, 47, 50),  # Em7
            (41, 45, 48, 52),
            (43, 47, 50, 52),
        ]
        pad_volume = 0.060
        sino_volume = 0.105
        pad_pan = (-0.45, -0.16, 0.16, 0.45)
    elif estilo == 2:
        acordes = [
            (50, 53, 57, 60),  # Dm7
            (46, 50, 53, 57),  # Bbmaj7
            (43, 46, 50, 53),  # Gm7
            (48, 52, 55, 59),  # Cmaj7
            (50, 53, 57, 60),
            (45, 48, 52, 55),  # Am7
            (46, 50, 53, 57),
            (48, 52, 55, 59),
        ]
        pad_volume = 0.052
        sino_volume = 0.095
        pad_pan = (-0.38, -0.12, 0.12, 0.38)
    else:
        acordes = [
            (40, 43, 47, 50),  # Em7
            (36, 40, 43, 47),  # Cmaj7
            (43, 47, 50, 52),  # G6
            (38, 42, 45, 49),  # Dmaj7
            (40, 43, 47, 50),
            (36, 40, 43, 47),
            (45, 48, 52, 55),  # Am7
            (38, 42, 45, 49),
        ]
        pad_volume = 0.044
        sino_volume = 0.082
        pad_pan = (-0.42, -0.14, 0.14, 0.42)

    padroes = (
        (0, 2, 1, 3, 2, 1, 0, 2),
        (0, 1, 2, 1, 3, 2, 1, 2),
    )
    for ciclo in range(3):
        base_ciclo = ciclo * periodo
        for compasso, acorde in enumerate(acordes):
            inicio = base_ciclo + compasso * 4.0 * beat
            for indice, nota in enumerate(acorde):
                adicionar_nota(
                    trilha,
                    inicio - 0.18 * beat,
                    4.55 * beat,
                    nota,
                    pad_volume,
                    "pad",
                    pad_pan[indice],
                )

            raiz = acorde[0] - 12
            adicionar_nota(trilha, inicio, 1.8 * beat, raiz, 0.105, "baixo", -0.04)
            adicionar_nota(trilha, inicio + 2.0 * beat, 1.7 * beat, raiz + 7, 0.075, "baixo", 0.04)

            padrao = padroes[(compasso + estilo) % len(padroes)]
            for passo, indice_nota in enumerate(padrao):
                comeco = inicio + passo * 0.5 * beat
                oitava = 12 + (12 if passo in (3, 7) and estilo == 1 else 0)
                timbre = "sino" if estilo == 1 else "pluc"
                pan = -0.48 + (passo / 7.0) * 0.96
                adicionar_nota(
                    trilha,
                    comeco,
                    0.82 * beat,
                    acorde[indice_nota] + oitava,
                    sino_volume,
                    timbre,
                    pan,
                )

            if compasso % 2 == 0:
                adicionar_nota(
                    trilha,
                    inicio + 3.5 * beat,
                    1.35 * beat,
                    acorde[3] + 24,
                    0.040 if estilo == 1 else 0.032,
                    "sino",
                    0.60,
                )

            if estilo == 3:
                for pulso in range(4):
                    adicionar_percussao(
                        trilha,
                        inicio + pulso * beat,
                        "bumbo" if pulso in (0, 2) else "caixa",
                        0.105 if pulso in (0, 2) else 0.036,
                    )
                    adicionar_percussao(
                        trilha,
                        inicio + (pulso + 0.5) * beat,
                        "chimbal",
                        0.018,
                        0.24 if pulso % 2 else -0.24,
                    )
                    adicionar_nota(
                        trilha,
                        inicio + pulso * beat,
                        0.72 * beat,
                        raiz + (7 if pulso == 3 else 0),
                        0.055,
                        "baixo",
                        0.0,
                    )

    ambiencia = 1.0 if estilo == 1 else (0.72 if estilo == 2 else 0.48)
    trilha = aplicar_ambiencia(trilha, ambiencia)
    inicio_recorte = int(periodo * TAXA)
    fim_recorte = inicio_recorte + int(periodo * TAXA)
    recorte = trilha[:, inicio_recorte:fim_recorte].copy()

    # Um sopro quase imperceptivel evita silencio digital e da textura ao espaco.
    ruido = RNG.normal(0.0, 1.0, recorte.shape[1])
    ruido = np.convolve(ruido, np.ones(120) / 120.0, mode="same") * 0.006
    recorte[0] += ruido
    recorte[1] += np.roll(ruido, 41)
    return recorte


def main() -> None:
    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    arquivos = {
        "pulo_espacial.wav": gerar_pulo(),
        "morte_power_down.wav": gerar_morte(),
        "musica_1_orbita_tranquila.wav": compor_musica(1),
        "musica_2_passeio_nos_aneis.wav": compor_musica(2),
        "musica_gameplay_acao.wav": compor_musica(3),
    }
    for nome, audio in arquivos.items():
        caminho = PASTA_SAIDA / nome
        escrever_wav(caminho, audio)
        print(caminho.relative_to(RAIZ))


if __name__ == "__main__":
    main()
