"""Deteccao do pedal inclinado e sorteio de buffs/debuffs do ESP32."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
import time
from typing import Optional


PEDAL_EFFECTS = {
    "shield": {
        "name": "ESCUDO",
        "description": "bloqueia uma colisao por ate 12 segundos",
        "color": (75, 225, 255),
        "kind": "BUFF",
    },
    "slow": {
        "name": "CAMERA LENTA",
        "description": "reduz a velocidade por 5 segundos",
        "color": (105, 155, 255),
        "kind": "BUFF",
    },
    "clear": {
        "name": "EXPLOSAO",
        "description": "limpa os obstaculos da pista",
        "color": (255, 185, 65),
        "kind": "BUFF",
    },
    "turbo": {
        "name": "HIPERVELOCIDADE",
        "description": "acelera os obstaculos por 5 segundos",
        "color": (255, 75, 75),
        "kind": "DEBUFF",
    },
    "storm": {
        "name": "TEMPESTADE",
        "description": "faz surgirem mais obstaculos por 7 segundos",
        "color": (255, 125, 55),
        "kind": "DEBUFF",
    },
    "chaos": {
        "name": "MODO CAOS",
        "description": "pontos x2 e velocidade maior por 8 segundos",
        "color": (235, 105, 255),
        "kind": "RISCO X RECOMPENSA",
    },
}


def _normalize(vector: tuple[float, float, float]) -> Optional[tuple[float, float, float]]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 1e-6:
        return None
    return tuple(value / norm for value in vector)


def _angle_degrees(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> float:
    dot = sum(a * b for a, b in zip(first, second))
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


class PedalTiltInterpreter:
    """Detecta uma pisada pela inclinacao em relacao a posicao solta."""

    def __init__(
        self,
        calibration_seconds: float = 0.8,
        press_threshold_degrees: float = 8.0,
        release_threshold_degrees: float = 4.0,
        press_hold_seconds: float = 0.10,
        release_hold_seconds: float = 0.10,
        smoothing: float = 0.28,
        calibration_tolerance_degrees: float = 3.0,
        minimum_norm: float = 0.62,
        maximum_norm: float = 1.38,
    ):
        self.calibration_seconds = calibration_seconds
        self.press_threshold_degrees = press_threshold_degrees
        self.release_threshold_degrees = release_threshold_degrees
        self.press_hold_seconds = press_hold_seconds
        self.release_hold_seconds = release_hold_seconds
        self.smoothing = smoothing
        self.calibration_tolerance_degrees = calibration_tolerance_degrees
        self.minimum_norm = minimum_norm
        self.maximum_norm = maximum_norm
        self.reset_calibration()

    @property
    def calibrated(self) -> bool:
        return self.rest_vector is not None

    def reset_calibration(self) -> None:
        self.filtered_vector: Optional[tuple[float, float, float]] = None
        self.calibration_vector: Optional[tuple[float, float, float]] = None
        self.calibration_since: Optional[float] = None
        self.calibration_progress = 0.0
        self.rest_vector: Optional[tuple[float, float, float]] = None
        self.angle_degrees = 0.0
        self.pressed = False
        self.press_candidate_since: Optional[float] = None
        self.release_candidate_since: Optional[float] = None

    def _valid_normalized(
        self, ax: float, ay: float, az: float
    ) -> Optional[tuple[float, float, float]]:
        norm = math.sqrt(ax * ax + ay * ay + az * az)
        if not self.minimum_norm <= norm <= self.maximum_norm:
            return None
        return _normalize((ax, ay, az))

    def _update_filter(
        self, current: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        if self.filtered_vector is None:
            self.filtered_vector = current
        else:
            alpha = self.smoothing
            blended = tuple(
                previous * (1.0 - alpha) + value * alpha
                for previous, value in zip(self.filtered_vector, current)
            )
            self.filtered_vector = _normalize(blended) or current
        return self.filtered_vector

    def _calibrate(
        self, current: tuple[float, float, float], now: float
    ) -> None:
        if self.calibration_vector is None:
            self.calibration_vector = current
            self.calibration_since = now
            self.calibration_progress = 0.0
            return

        if _angle_degrees(self.calibration_vector, current) > self.calibration_tolerance_degrees:
            self.calibration_vector = current
            self.calibration_since = now
            self.calibration_progress = 0.0
            return

        averaged = tuple(
            previous * 0.92 + value * 0.08
            for previous, value in zip(self.calibration_vector, current)
        )
        self.calibration_vector = _normalize(averaged) or current
        elapsed = max(0.0, now - self.calibration_since)
        self.calibration_progress = min(1.0, elapsed / self.calibration_seconds)
        if self.calibration_progress >= 1.0:
            self.rest_vector = self.calibration_vector
            self.angle_degrees = 0.0

    def update(
        self,
        ax: float,
        ay: float,
        az: float,
        now: Optional[float] = None,
    ) -> bool:
        """Retorna True uma unica vez quando o pedal cruza o limiar."""
        now = time.monotonic() if now is None else now
        normalized = self._valid_normalized(ax, ay, az)
        if normalized is None:
            self.press_candidate_since = None
            self.release_candidate_since = None
            return False

        current = self._update_filter(normalized)
        if not self.calibrated:
            self._calibrate(current, now)
            return False

        self.angle_degrees = _angle_degrees(self.rest_vector, current)
        if not self.pressed:
            self.release_candidate_since = None
            if self.angle_degrees < self.press_threshold_degrees:
                self.press_candidate_since = None
                return False
            if self.press_candidate_since is None:
                self.press_candidate_since = now
                return False
            if now - self.press_candidate_since >= self.press_hold_seconds:
                self.pressed = True
                self.press_candidate_since = None
                return True
            return False

        self.press_candidate_since = None
        if self.angle_degrees > self.release_threshold_degrees:
            self.release_candidate_since = None
            return False
        if self.release_candidate_since is None:
            self.release_candidate_since = now
            return False
        if now - self.release_candidate_since >= self.release_hold_seconds:
            self.pressed = False
            self.release_candidate_since = None
        return False


@dataclass(frozen=True)
class PedalEffectActivation:
    accepted: bool
    effect_id: str
    name: str
    kind: str
    message: str
    color: tuple[int, int, int]
    clear_track: bool = False


class PedalPowerSystem:
    """Sorteia e aplica efeitos; uma sacola garante variedade no teste."""

    def __init__(
        self,
        cooldown_seconds: float = 6.0,
        random_seed: Optional[int] = None,
    ):
        self.cooldown_seconds = max(0.0, cooldown_seconds)
        self.cooldown_until = 0.0
        self.shield_charges = 0
        self.shield_until = 0.0
        self.slow_until = 0.0
        self.turbo_until = 0.0
        self.storm_until = 0.0
        self.chaos_until = 0.0
        self.last_effect_id: Optional[str] = None
        self.last_message = ""
        self.last_color = (160, 190, 220)
        self.message_until = 0.0
        self._rng = random.Random(random_seed)
        self._effect_bag: list[str] = []

    def cooldown_remaining(self, now: Optional[float] = None) -> float:
        now = time.monotonic() if now is None else now
        return max(0.0, self.cooldown_until - now)

    def ready(self, now: Optional[float] = None) -> bool:
        return self.cooldown_remaining(now) <= 0.0

    def _draw_effect(self) -> str:
        if not self._effect_bag:
            self._effect_bag = list(PEDAL_EFFECTS)
            self._rng.shuffle(self._effect_bag)
            if (
                self.last_effect_id is not None
                and len(self._effect_bag) > 1
                and self._effect_bag[-1] == self.last_effect_id
            ):
                self._effect_bag[0], self._effect_bag[-1] = (
                    self._effect_bag[-1], self._effect_bag[0]
                )
        return self._effect_bag.pop()

    def activate_random(
        self, now: Optional[float] = None
    ) -> PedalEffectActivation:
        now = time.monotonic() if now is None else now
        if not self.ready(now):
            remaining = self.cooldown_remaining(now)
            message = f"PEDAL RECARREGANDO: {remaining:.1f}s"
            self.last_message = message
            self.last_color = (160, 175, 195)
            self.message_until = now + 1.2
            return PedalEffectActivation(
                accepted=False,
                effect_id="",
                name="RECARGA",
                kind="AGUARDE",
                message=message,
                color=self.last_color,
            )
        return self.activate_effect(self._draw_effect(), now)

    def activate_effect(
        self,
        effect_id: str,
        now: Optional[float] = None,
    ) -> PedalEffectActivation:
        now = time.monotonic() if now is None else now
        config = PEDAL_EFFECTS[effect_id]
        self.cooldown_until = now + self.cooldown_seconds
        self.last_effect_id = effect_id
        clear_track = False

        if effect_id == "shield":
            self.shield_charges = 1
            self.shield_until = now + 12.0
            message = "BUFF SORTEADO: ESCUDO"
        elif effect_id == "slow":
            self.slow_until = now + 5.0
            self.turbo_until = 0.0
            message = "BUFF SORTEADO: CAMERA LENTA"
        elif effect_id == "clear":
            clear_track = True
            message = "BUFF SORTEADO: EXPLOSAO"
        elif effect_id == "turbo":
            self.turbo_until = now + 5.0
            self.slow_until = 0.0
            message = "DEBUFF SORTEADO: HIPERVELOCIDADE"
        elif effect_id == "storm":
            self.storm_until = now + 7.0
            message = "DEBUFF SORTEADO: TEMPESTADE"
        else:
            self.chaos_until = now + 8.0
            message = "SORTEADO: MODO CAOS"

        self.last_message = message
        self.last_color = config["color"]
        self.message_until = now + 2.4
        return PedalEffectActivation(
            accepted=True,
            effect_id=effect_id,
            name=config["name"],
            kind=config["kind"],
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
