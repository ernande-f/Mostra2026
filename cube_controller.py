"""Reconhecimento das faces e poderes do cubo ESP32/MPU6050.

O acelerometro mede a gravidade quando o cubo esta parado. A face superior e
determinada pelo eixo dominante (+X, -X, +Y, -Y, +Z ou -Z). O filtro e o tempo
de estabilidade impedem que faces intermediarias sejam aceitas durante o giro.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Optional


CUBE_FACE_POWERS = {
    "+X": {
        "id": "shield",
        "name": "ESCUDO",
        "description": "absorve a proxima colisao",
        "color": (75, 225, 255),
    },
    "-X": {
        "id": "slow",
        "name": "CAMERA LENTA",
        "description": "reduz a velocidade por 5 segundos",
        "color": (105, 155, 255),
    },
    "+Y": {
        "id": "clear",
        "name": "EXPLOSAO",
        "description": "limpa os obstaculos da pista",
        "color": (255, 130, 70),
    },
    "-Y": {
        "id": "turbo",
        "name": "HIPERVELOCIDADE",
        "description": "acelera os obstaculos por 5 segundos",
        "color": (255, 75, 75),
    },
    "+Z": {
        "id": "storm",
        "name": "TEMPESTADE",
        "description": "faz surgirem mais obstaculos por 7 segundos",
        "color": (255, 145, 70),
    },
    "-Z": {
        "id": "chaos",
        "name": "MODO CAOS",
        "description": "pontos x2, mas aumenta a velocidade por 8 segundos",
        "color": (235, 105, 255),
    },
}


class CubeOrientationInterpreter:
    """Converte aceleracao em uma das seis faces estaveis do cubo."""

    def __init__(
        self,
        stable_seconds: float = 0.45,
        smoothing: float = 0.24,
        minimum_axis: float = 0.68,
        minimum_dominance: float = 0.14,
        minimum_norm: float = 0.62,
        maximum_norm: float = 1.38,
    ):
        self.stable_seconds = stable_seconds
        self.smoothing = smoothing
        self.minimum_axis = minimum_axis
        self.minimum_dominance = minimum_dominance
        self.minimum_norm = minimum_norm
        self.maximum_norm = maximum_norm
        self.reset()

    def reset(self) -> None:
        self.filtered: Optional[tuple[float, float, float]] = None
        self.candidate_face: Optional[str] = None
        self.candidate_since: Optional[float] = None
        self.stable_face: Optional[str] = None
        self.stability_progress = 0.0
        self.norm = 0.0

    def _classify(self, ax: float, ay: float, az: float) -> Optional[str]:
        values = (ax, ay, az)
        absolutes = [abs(value) for value in values]
        self.norm = math.sqrt(ax * ax + ay * ay + az * az)

        if not self.minimum_norm <= self.norm <= self.maximum_norm:
            return None

        dominant_index = max(range(3), key=absolutes.__getitem__)
        ordered = sorted(absolutes, reverse=True)
        if ordered[0] < self.minimum_axis:
            return None
        if ordered[0] - ordered[1] < self.minimum_dominance:
            return None

        axis = "XYZ"[dominant_index]
        sign = "+" if values[dominant_index] >= 0.0 else "-"
        return sign + axis

    def update(
        self,
        ax: float,
        ay: float,
        az: float,
        now: Optional[float] = None,
    ) -> Optional[str]:
        """Atualiza o filtro e retorna uma face apenas quando ela muda."""
        now = time.monotonic() if now is None else now

        if self.filtered is None:
            self.filtered = (ax, ay, az)
        else:
            alpha = self.smoothing
            self.filtered = tuple(
                previous * (1.0 - alpha) + current * alpha
                for previous, current in zip(self.filtered, (ax, ay, az))
            )

        face = self._classify(*self.filtered)
        if face is None:
            self.candidate_face = None
            self.candidate_since = None
            self.stability_progress = 0.0
            return None

        if face != self.candidate_face:
            self.candidate_face = face
            self.candidate_since = now
            self.stability_progress = 0.0
            return None

        elapsed = max(0.0, now - self.candidate_since)
        self.stability_progress = min(1.0, elapsed / self.stable_seconds)
        if self.stability_progress >= 1.0 and face != self.stable_face:
            self.stable_face = face
            return face
        return None


@dataclass(frozen=True)
class CubePowerActivation:
    accepted: bool
    face: str
    power_id: str
    name: str
    message: str
    color: tuple[int, int, int]
    clear_track: bool = False


class CubePowerSystem:
    """Carrega o cubo e mantem buffs/debuffs temporarios da face sorteada."""

    def __init__(self, required_obstacles: int = 5):
        self.required_obstacles = max(1, int(required_obstacles))
        self.charge = 0
        self.armed = False
        self.shield_charges = 0
        self.shield_until = 0.0
        self.slow_until = 0.0
        self.turbo_until = 0.0
        self.storm_until = 0.0
        self.chaos_until = 0.0
        self.last_message = ""
        self.last_color = (160, 190, 220)
        self.message_until = 0.0

    @property
    def charge_ratio(self) -> float:
        return min(1.0, self.charge / self.required_obstacles)

    def register_obstacle_passed(self, now: Optional[float] = None) -> bool:
        """Carrega uma etapa e retorna True quando o cubo fica disponivel."""
        if self.armed:
            return False

        now = time.monotonic() if now is None else now
        self.charge = min(self.required_obstacles, self.charge + 1)
        if self.charge < self.required_obstacles:
            return False

        self.armed = True
        self.last_message = "CUBO PRONTO: GIRE E APOIE UMA NOVA FACE"
        self.last_color = (90, 245, 145)
        self.message_until = now + 3.0
        return True

    def activate_face(
        self,
        face: str,
        now: Optional[float] = None,
    ) -> Optional[CubePowerActivation]:
        config = CUBE_FACE_POWERS.get(face)
        if config is None:
            return None

        now = time.monotonic() if now is None else now
        power_id = config["id"]
        if not self.armed:
            message = "CUBO AINDA CARREGANDO"
            return CubePowerActivation(
                accepted=False,
                face=face,
                power_id=power_id,
                name=config["name"],
                message=message,
                color=config["color"],
            )

        self.armed = False
        self.charge = 0
        clear_track = False

        if power_id == "shield":
            self.shield_charges = 1
            self.shield_until = now + 12.0
            message = "BUFF: ESCUDO POR 12s OU UMA COLISAO"
        elif power_id == "slow":
            self.slow_until = now + 5.0
            self.turbo_until = 0.0
            message = "BUFF: CAMERA LENTA POR 5s"
        elif power_id == "clear":
            clear_track = True
            message = "BUFF: EXPLOSAO LIMPOU A PISTA"
        elif power_id == "turbo":
            self.turbo_until = now + 5.0
            self.slow_until = 0.0
            message = "DEBUFF: HIPERVELOCIDADE POR 5s"
        elif power_id == "storm":
            self.storm_until = now + 7.0
            message = "DEBUFF: TEMPESTADE POR 7s"
        else:
            self.chaos_until = now + 8.0
            message = "CAOS: PONTOS X2 + VELOCIDADE POR 8s"

        self.last_message = message
        self.last_color = config["color"]
        self.message_until = now + 2.2
        return CubePowerActivation(
            accepted=True,
            face=face,
            power_id=power_id,
            name=config["name"],
            message=message,
            color=config["color"],
            clear_track=clear_track,
        )

    def obstacle_speed_multiplier(self, now: Optional[float] = None) -> float:
        now = time.monotonic() if now is None else now
        if now < self.slow_until:
            return 0.55
        if now < self.turbo_until:
            return 1.65
        if now < self.chaos_until:
            return 1.35
        return 1.0

    def spawn_interval_multiplier(self, now: Optional[float] = None) -> float:
        now = time.monotonic() if now is None else now
        return 0.52 if now < self.storm_until else 1.0

    def score_multiplier(self, now: Optional[float] = None) -> float:
        now = time.monotonic() if now is None else now
        return 2.0 if now < self.chaos_until else 1.0

    def absorb_collision(self, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        if self.shield_charges > 0 and now < self.shield_until:
            self.shield_charges -= 1
            return True
        if now >= self.shield_until:
            self.shield_charges = 0
        return False

    def active_effects(self, now: Optional[float] = None) -> list[str]:
        now = time.monotonic() if now is None else now
        effects = []
        if self.shield_charges and now < self.shield_until:
            effects.append(f"ESCUDO {self.shield_until - now:.1f}s")
        if now < self.slow_until:
            effects.append(f"LENTO {self.slow_until - now:.1f}s")
        if now < self.turbo_until:
            effects.append(f"RAPIDO {self.turbo_until - now:.1f}s")
        if now < self.storm_until:
            effects.append(f"TEMPESTADE {self.storm_until - now:.1f}s")
        if now < self.chaos_until:
            effects.append(f"CAOS {self.chaos_until - now:.1f}s")
        return effects
