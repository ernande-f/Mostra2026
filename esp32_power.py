"""Carregador de energia e escudo usando ESP32 + MPU6050 por UDP/Wi-Fi."""

from __future__ import annotations

from dataclasses import dataclass
import math
import socket
import threading
import time
from typing import Optional


ESP32_UDP_PORT = 4210
ESP32_NETWORK_NAME = "ESP32_COW_GAME"


@dataclass(frozen=True)
class SensorSample:
    """Uma leitura do MPU6050 em g e graus por segundo."""

    ax: float
    ay: float
    az: float
    gx: float = 0.0
    gy: float = 0.0
    gz: float = 0.0
    sequence: Optional[int] = None


@dataclass(frozen=True)
class PowerSnapshot:
    """Estado imutavel que pode ser consultado pela thread do jogo."""

    connected: bool
    status: str
    source_ip: str
    packets_received: int
    charge_ratio: float
    armed: bool
    twist_ready: bool
    shield_active: bool
    motion_intensity: float
    gyro_speed: float
    activation_flash: float
    hit_flash: float


def parse_sensor_packet(payload: bytes | str) -> Optional[SensorSample]:
    """Aceita o protocolo COW1 atual e o pacote antigo apenas com aceleracao."""
    if isinstance(payload, bytes):
        text = payload.decode("utf-8", errors="ignore").strip()
    else:
        text = str(payload).strip()
    if not text:
        return None

    parts = [part.strip() for part in text.split(",")]
    sequence = None
    try:
        if parts[0] == "COW1":
            if len(parts) != 8:
                return None
            sequence = int(parts[1])
            values = [float(part) for part in parts[2:]]
        elif len(parts) in (3, 6):
            values = [float(part) for part in parts]
        else:
            return None
    except (TypeError, ValueError):
        return None

    if len(values) == 3:
        values.extend((0.0, 0.0, 0.0))
    if not all(math.isfinite(value) for value in values):
        return None

    ax, ay, az, gx, gy, gz = values
    # Limites acima das escalas configuradas no firmware, mas baixos o bastante
    # para descartar datagramas aleatorios recebidos na mesma porta.
    if max(abs(ax), abs(ay), abs(az)) > 8.0:
        return None
    if max(abs(gx), abs(gy), abs(gz)) > 2200.0:
        return None
    return SensorSample(ax, ay, az, gx, gy, gz, sequence)


class MotionPowerSystem:
    """Transforma chacoalhadas em carga e um giro separado em escudo."""

    def __init__(
        self,
        charge_per_shake: float = 0.08,
        shake_threshold: float = 0.55,
        shake_release_threshold: float = 0.24,
        twist_threshold_dps: float = 180.0,
        settle_gyro_dps: float = 40.0,
        settle_seconds: float = 0.28,
        shield_seconds: float = 12.0,
    ):
        self.charge_per_shake = max(0.01, float(charge_per_shake))
        self.shake_threshold = max(0.05, float(shake_threshold))
        self.shake_release_threshold = max(0.01, float(shake_release_threshold))
        self.twist_threshold_dps = max(10.0, float(twist_threshold_dps))
        self.settle_gyro_dps = max(1.0, float(settle_gyro_dps))
        self.settle_seconds = max(0.0, float(settle_seconds))
        self.shield_seconds = max(0.5, float(shield_seconds))
        self.reset_round()

    def reset_round(self, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        self.charge_ratio = 0.0
        self.armed = False
        self.twist_ready = False
        self.shield_charges = 0
        self.shield_until = 0.0
        self.motion_intensity = 0.0
        self.gyro_speed = 0.0
        self.last_activation_at = -math.inf
        self.last_hit_at = -math.inf
        self.last_charge_at = now
        self._previous_accel: Optional[tuple[float, float, float]] = None
        self._shake_latched = False
        self._quiet_since: Optional[float] = None

    def update(
        self,
        sample: SensorSample,
        now: Optional[float] = None,
    ) -> tuple[str, ...]:
        """Processa uma amostra e retorna eventos: charge, ready ou shield."""
        now = time.monotonic() if now is None else now
        accel = (sample.ax, sample.ay, sample.az)
        accel_norm = math.sqrt(sum(value * value for value in accel))
        self.gyro_speed = math.sqrt(
            sample.gx * sample.gx
            + sample.gy * sample.gy
            + sample.gz * sample.gz
        )

        if self._previous_accel is None:
            accel_delta = 0.0
        else:
            accel_delta = math.sqrt(sum(
                (current - previous) ** 2
                for current, previous in zip(accel, self._previous_accel)
            ))
        self._previous_accel = accel
        self.motion_intensity = max(abs(accel_norm - 1.0), accel_delta)

        if self.shield_active(now):
            return ()

        events: list[str] = []
        if not self.armed:
            if self.motion_intensity <= self.shake_release_threshold:
                self._shake_latched = False
            elif (
                self.motion_intensity >= self.shake_threshold
                and not self._shake_latched
            ):
                self._shake_latched = True
                self.charge_ratio = min(
                    1.0,
                    self.charge_ratio + self.charge_per_shake,
                )
                self.last_charge_at = now
                events.append("charge")
                if self.charge_ratio >= 1.0:
                    self.charge_ratio = 1.0
                    self.armed = True
                    self.twist_ready = False
                    self._quiet_since = None
                    events.append("ready")
            return tuple(events)

        # O giro so e aceito depois que a caixa para por um instante. Isso
        # separa a ativacao das chacoalhadas usadas para completar a carga.
        if self.twist_ready and self.gyro_speed >= self.twist_threshold_dps:
            self.charge_ratio = 0.0
            self.armed = False
            self.twist_ready = False
            self.shield_charges = 1
            self.shield_until = now + self.shield_seconds
            self.last_activation_at = now
            self._quiet_since = None
            self._shake_latched = True
            return ("shield",)

        quiet = (
            self.motion_intensity <= self.shake_release_threshold
            and self.gyro_speed <= self.settle_gyro_dps
        )
        if not quiet:
            self._quiet_since = None
        elif self._quiet_since is None:
            self._quiet_since = now
        elif now - self._quiet_since >= self.settle_seconds:
            self.twist_ready = True
        return tuple(events)

    def shield_active(self, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        return self.shield_charges > 0 and now < self.shield_until

    def absorb_collision(self, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        if not self.shield_active(now):
            if now >= self.shield_until:
                self.shield_charges = 0
            return False
        self.shield_charges = 0
        self.last_hit_at = now
        return True


class Esp32PowerController:
    """Escuta o broadcast do ESP32 sem bloquear o loop do Pygame."""

    def __init__(
        self,
        host: str = "",
        port: int = ESP32_UDP_PORT,
        connected_timeout: float = 1.2,
        power_system: Optional[MotionPowerSystem] = None,
    ):
        self.host = host
        self.port = int(port)
        self.connected_timeout = max(0.2, float(connected_timeout))
        self.power_system = power_system or MotionPowerSystem()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._socket: Optional[socket.socket] = None
        self._bound_port = 0
        self._enabled = False
        self._last_packet_at = -math.inf
        self._last_source_ip = ""
        self._packets_received = 0
        self._listen_error = ""

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._listen_loop,
            name="esp32-power-udp",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            sock = self._socket
            self._socket = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=1.5)
        self._thread = None

    def set_enabled(self, enabled: bool, reset: bool = False) -> None:
        with self._lock:
            self._enabled = bool(enabled)
            if reset:
                self.power_system.reset_round()

    @property
    def listening_port(self) -> int:
        with self._lock:
            return self._bound_port

    def reset_round(self) -> None:
        with self._lock:
            self.power_system.reset_round()

    def process_datagram(
        self,
        payload: bytes | str,
        source_ip: str = "",
        now: Optional[float] = None,
    ) -> bool:
        """Entrada publica usada tanto pelo socket quanto pelos testes."""
        sample = parse_sensor_packet(payload)
        if sample is None:
            return False
        now = time.monotonic() if now is None else now
        with self._lock:
            self._last_packet_at = now
            self._last_source_ip = source_ip
            self._packets_received += 1
            if self._enabled:
                self.power_system.update(sample, now)
        return True

    def absorb_collision(self, now: Optional[float] = None) -> bool:
        with self._lock:
            return self.power_system.absorb_collision(now)

    def snapshot(self, now: Optional[float] = None) -> PowerSnapshot:
        now = time.monotonic() if now is None else now
        with self._lock:
            connected = now - self._last_packet_at <= self.connected_timeout
            if self._listen_error:
                status = f"ERRO UDP: {self._listen_error}"
            elif connected:
                status = "CONECTADO"
            elif self._packets_received:
                status = "SINAL PERDIDO"
            else:
                status = f"AGUARDANDO {ESP32_NETWORK_NAME}"

            system = self.power_system
            activation_flash = max(
                0.0,
                1.0 - (now - system.last_activation_at) / 0.65,
            )
            hit_flash = max(
                0.0,
                1.0 - (now - system.last_hit_at) / 0.50,
            )
            return PowerSnapshot(
                connected=connected,
                status=status,
                source_ip=self._last_source_ip,
                packets_received=self._packets_received,
                charge_ratio=system.charge_ratio,
                armed=system.armed,
                twist_ready=system.twist_ready,
                shield_active=system.shield_active(now),
                motion_intensity=system.motion_intensity,
                gyro_speed=system.gyro_speed,
                activation_flash=activation_flash,
                hit_flash=hit_flash,
            )

    def _listen_loop(self) -> None:
        while not self._stop_event.is_set():
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.bind((self.host, self.port))
                sock.settimeout(0.25)
                with self._lock:
                    self._socket = sock
                    self._bound_port = sock.getsockname()[1]
                    self._listen_error = ""

                while not self._stop_event.is_set():
                    try:
                        data, address = sock.recvfrom(512)
                    except socket.timeout:
                        continue
                    self.process_datagram(data, address[0])
            except OSError as exc:
                if not self._stop_event.is_set():
                    with self._lock:
                        self._listen_error = str(exc)[:50]
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
                with self._lock:
                    if self._socket is sock:
                        self._socket = None

            self._stop_event.wait(1.0)
