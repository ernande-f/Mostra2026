"""Controle da vaca pela camera usando OpenCV e MediaPipe.

O modulo mantem toda a captura/processamento em uma thread separada. Assim,
uma camera lenta ou a inicializacao do MediaPipe nunca congela o loop do Pygame.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import median
import os
import sys
import tempfile
import threading
import time
from typing import Optional


@dataclass(frozen=True)
class GestureResult:
    """Resultado de um frame ja normalizado pelo tamanho do corpo."""

    jump: bool = False
    crouching: bool = False
    target_lane: Optional[int] = None
    lateral: float = 0.0
    vertical: float = 0.0
    calibrated: bool = False
    calibration_progress: float = 0.0


class PoseGestureInterpreter:
    """Converte o centro do corpo em gestos estaveis e discretos.

    As distancias sao divididas pelo tamanho do tronco. Isso faz os mesmos
    limiares funcionarem mesmo quando a pessoa esta mais perto ou longe da
    camera.
    """

    def __init__(
        self,
        calibration_frames: int = 36,
        lateral_threshold: float = 0.28,
        jump_threshold: float = 0.14,
        crouch_threshold: float = 0.11,
    ):
        self.calibration_frames = calibration_frames
        self.lateral_threshold = lateral_threshold
        self.jump_threshold = jump_threshold
        self.crouch_threshold = crouch_threshold
        self.reset_calibration()

    def reset_calibration(self) -> None:
        self._samples: list[tuple[float, float, float]] = []
        self.base_x: Optional[float] = None
        self.base_y: Optional[float] = None
        self.base_scale: Optional[float] = None
        self.smooth_x: Optional[float] = None
        self.smooth_y: Optional[float] = None
        self.current_lane = 1
        self.crouching = False
        self.jump_armed = True
        self.last_jump_time = -10.0

    @property
    def calibrated(self) -> bool:
        return self.base_x is not None

    def update(self, x: float, y: float, scale: float, now: Optional[float] = None) -> GestureResult:
        now = time.monotonic() if now is None else now
        scale = max(0.06, scale)

        if not self.calibrated:
            self._samples.append((x, y, scale))
            progress = min(1.0, len(self._samples) / self.calibration_frames)
            if len(self._samples) < self.calibration_frames:
                return GestureResult(calibration_progress=progress)

            # A mediana ignora pequenos movimentos acidentais durante a tara.
            self.base_x = median(sample[0] for sample in self._samples)
            self.base_y = median(sample[1] for sample in self._samples)
            self.base_scale = max(0.06, median(sample[2] for sample in self._samples))
            self.smooth_x = self.base_x
            self.smooth_y = self.base_y
            return GestureResult(
                target_lane=1,
                calibrated=True,
                calibration_progress=1.0,
            )

        # Um filtro exponencial tira o tremor sem atrasar demais um pulo.
        alpha = 0.42
        self.smooth_x = (1.0 - alpha) * self.smooth_x + alpha * x
        self.smooth_y = (1.0 - alpha) * self.smooth_y + alpha * y

        lateral = (self.smooth_x - self.base_x) / self.base_scale
        vertical = (self.base_y - self.smooth_y) / self.base_scale

        target_lane: Optional[int] = None
        next_lane = self.current_lane
        rearm = self.lateral_threshold * 0.55

        # Histerese: perto das bordas, a vaca nao fica alternando de faixa.
        if self.current_lane == 1:
            if lateral <= -self.lateral_threshold:
                next_lane = 0
            elif lateral >= self.lateral_threshold:
                next_lane = 2
        elif self.current_lane == 0 and lateral >= -rearm:
            next_lane = 1
        elif self.current_lane == 2 and lateral <= rearm:
            next_lane = 1

        if next_lane != self.current_lane:
            self.current_lane = next_lane
            target_lane = next_lane

        jump = False
        if vertical < self.jump_threshold * 0.38:
            self.jump_armed = True
        if (
            self.jump_armed
            and vertical >= self.jump_threshold
            and now - self.last_jump_time >= 0.70
        ):
            jump = True
            self.jump_armed = False
            self.last_jump_time = now

        # Dois limiares diferentes evitam piscar entre agachado/em pe.
        if not self.crouching and vertical <= -self.crouch_threshold:
            self.crouching = True
        elif self.crouching and vertical >= -(self.crouch_threshold * 0.50):
            self.crouching = False

        return GestureResult(
            jump=jump,
            crouching=self.crouching,
            target_lane=target_lane,
            lateral=lateral,
            vertical=vertical,
            calibrated=True,
            calibration_progress=1.0,
        )


class VisionController:
    """Captura a webcam e envia gestos ao ``InputController`` do jogo."""

    PREVIEW_SIZE = (320, 240)

    def __init__(self, input_controller, camera_index: int = 0):
        self.input_controller = input_controller
        self.camera_index = camera_index
        self.interpreter = PoseGestureInterpreter()
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._capture = None

        self.connected = False
        self.pose_visible = False
        self.status = "Camera iniciando..."
        self.engine = "OpenCV"
        self.action = "AGUARDANDO"
        self.lateral = 0.0
        self.vertical = 0.0
        self.fps = 0.0
        self.calibration_progress = 0.0

        self._frame_lock = threading.Lock()
        self._preview: Optional[tuple[bytes, tuple[int, int]]] = None
        self._recalibration_lock = threading.Lock()
        self._recalibration_requested = False

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return

        # O AVFoundation exige que a primeira abertura/autorizacao da webcam
        # aconteca na thread principal do macOS. O processamento dos frames
        # continua em segundo plano depois que a captura foi autorizada.
        try:
            import cv2
        except ImportError:
            self.status = "OpenCV nao instalado: rode instalar_dependencias.command"
            self.action = "SEM OPENCV"
            return

        self._capture = self._open_camera(cv2)
        if self._capture is None:
            self.status = "Camera indisponivel ou sem permissao no macOS"
            self.action = "SEM CAMERA"
            return

        self.connected = True
        self.running = True
        self.thread = threading.Thread(target=self._worker, name="camera-pose", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False
        self.input_controller.set_crouching("vision", False)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def request_calibration(self) -> None:
        with self._recalibration_lock:
            self._recalibration_requested = True
        self.status = "Recalibrando: fique no centro e em pe"

    def get_preview(self) -> Optional[tuple[bytes, tuple[int, int]]]:
        """Retorna uma copia imutavel segura para virar Surface no Pygame."""
        with self._frame_lock:
            return self._preview

    def _take_recalibration_request(self) -> bool:
        with self._recalibration_lock:
            requested = self._recalibration_requested
            self._recalibration_requested = False
            return requested

    def _open_camera(self, cv2):
        backends = []
        if sys.platform == "darwin" and hasattr(cv2, "CAP_AVFOUNDATION"):
            backends.append(cv2.CAP_AVFOUNDATION)
        else:
            backends.append(cv2.CAP_ANY)

        for backend in backends:
            cap = cv2.VideoCapture(self.camera_index, backend)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                return cap
            cap.release()
        return None

    @staticmethod
    def _pose_signal(landmarks) -> Optional[tuple[float, float, float, float]]:
        # Indices padrao do MediaPipe Pose: ombros 11/12 e quadris 23/24.
        selected = [landmarks[i] for i in (11, 12, 23, 24)]
        # A API Solutions garante ``visibility``; algumas builds antigas deixam
        # ``presence`` zerado mesmo com a pose valida, entao nao dependemos dele.
        confidence = min(p.visibility for p in selected)
        if confidence < 0.45:
            return None

        shoulder_x = (landmarks[11].x + landmarks[12].x) * 0.5
        shoulder_y = (landmarks[11].y + landmarks[12].y) * 0.5
        hip_x = (landmarks[23].x + landmarks[24].x) * 0.5
        hip_y = (landmarks[23].y + landmarks[24].y) * 0.5
        center_x = (shoulder_x + hip_x) * 0.5
        # Ombros recebem mais peso: agachar aparece antes e com mais clareza.
        center_y = shoulder_y * 0.68 + hip_y * 0.32
        torso_scale = ((shoulder_x - hip_x) ** 2 + (shoulder_y - hip_y) ** 2) ** 0.5
        return center_x, center_y, torso_scale, confidence

    @staticmethod
    def _face_signal(cv2, cascade, frame) -> Optional[tuple[float, float, float, float, tuple]]:
        """Fallback OpenCV puro para Macs onde o grafo do MediaPipe nao abre."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.12,
            minNeighbors=5,
            minSize=(55, 55),
        )
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda rect: rect[2] * rect[3])
        frame_h, frame_w = frame.shape[:2]
        center_x = (x + w * 0.5) / frame_w
        center_y = (y + h * 0.55) / frame_h
        body_scale = max(0.08, (h / frame_h) * 3.2)
        return center_x, center_y, body_scale, 0.65, (x, y, w, h)

    def _apply_gesture(self, result: GestureResult) -> None:
        self.lateral = result.lateral
        self.vertical = result.vertical
        self.calibration_progress = result.calibration_progress

        if result.target_lane is not None:
            self.input_controller.request_target_lane(result.target_lane, "camera")
        if result.jump:
            self.input_controller.trigger_jump("camera")
        self.input_controller.set_crouching("vision", result.crouching)

        if not result.calibrated:
            self.action = f"CALIBRANDO {int(result.calibration_progress * 100):d}%"
        elif result.jump:
            self.action = "PULO"
        elif result.crouching:
            self.action = "AGACHADO"
        elif result.target_lane == 0:
            self.action = "FAIXA ESQUERDA"
        elif result.target_lane == 2:
            self.action = "FAIXA DIREITA"
        else:
            self.action = "CORRENDO"

    def _draw_guides(self, cv2, frame) -> None:
        height, width = frame.shape[:2]
        if not self.interpreter.calibrated:
            progress_w = int(width * 0.72 * self.calibration_progress)
            cv2.rectangle(frame, (int(width * 0.14), height - 30), (int(width * 0.86), height - 16), (55, 55, 55), -1)
            cv2.rectangle(frame, (int(width * 0.14), height - 30), (int(width * 0.14) + progress_w, height - 16), (50, 220, 255), -1)
            return

        base_x = int(self.interpreter.base_x * width)
        base_y = int(self.interpreter.base_y * height)
        scale_x = self.interpreter.base_scale * width
        scale_y = self.interpreter.base_scale * height
        left = int(base_x - self.interpreter.lateral_threshold * scale_x)
        right = int(base_x + self.interpreter.lateral_threshold * scale_x)
        jump_y = int(base_y - self.interpreter.jump_threshold * scale_y)
        crouch_y = int(base_y + self.interpreter.crouch_threshold * scale_y)
        cv2.line(frame, (left, 0), (left, height), (80, 220, 255), 2)
        cv2.line(frame, (right, 0), (right, height), (80, 220, 255), 2)
        cv2.line(frame, (0, jump_y), (width, jump_y), (90, 255, 90), 2)
        cv2.line(frame, (0, crouch_y), (width, crouch_y), (255, 190, 70), 2)

    def _publish_preview(self, cv2, frame) -> None:
        self._draw_guides(cv2, frame)
        color = (70, 255, 100) if self.pose_visible else (80, 190, 255)
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 38), (12, 18, 30), -1)
        cv2.putText(
            frame,
            f"{self.engine} | {self.action}",
            (12, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            color,
            2,
            cv2.LINE_AA,
        )
        preview = cv2.resize(frame, self.PREVIEW_SIZE, interpolation=cv2.INTER_AREA)
        preview_rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
        with self._frame_lock:
            self._preview = (preview_rgb.tobytes(), self.PREVIEW_SIZE)

    def _worker(self) -> None:
        # Evita que o Matplotlib (importado internamente pelo MediaPipe) tente
        # escrever configuracoes no diretorio pessoal do usuario.
        mpl_cache = Path(tempfile.gettempdir()) / "mostra2026-matplotlib"
        mpl_cache.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR", str(mpl_cache))

        try:
            import cv2
        except ImportError:
            self.status = "OpenCV nao instalado: rode o script instalar_dependencias"
            self.action = "SEM OPENCV"
            return

        cap = self._capture
        if cap is None:
            self.status = "Camera indisponivel ou sem permissao no macOS"
            self.action = "SEM CAMERA"
            return

        self.connected = True
        face_cascade = cv2.CascadeClassifier(
            str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
        )

        mp = None
        pose = None
        drawing = None
        pose_connections = None
        try:
            import mediapipe as mp_module

            mp = mp_module
            # O modelo completo vem dentro do pacote; nao faz download no boot.
            pose = mp.solutions.pose.Pose(
                static_image_mode=False,
                model_complexity=1,
                smooth_landmarks=True,
                min_detection_confidence=0.55,
                min_tracking_confidence=0.55,
            )
            drawing = mp.solutions.drawing_utils
            pose_connections = mp.solutions.pose.POSE_CONNECTIONS
            self.engine = "MediaPipe Pose"
        except Exception as exc:
            # O OpenCV continua controlando pelo rosto se o MediaPipe/GPU falhar.
            self.engine = "OpenCV Face"
            self.status = f"MediaPipe indisponivel; fallback OpenCV ({type(exc).__name__})"

        previous_time = time.monotonic()
        smoothed_fps = 0.0

        try:
            while self.running:
                ok, frame = cap.read()
                if not ok:
                    self.status = "Falha ao ler a camera"
                    time.sleep(0.05)
                    continue

                # Espelho natural: mover o corpo para a direita move a vaca para a direita.
                frame = cv2.flip(frame, 1)
                signal = None
                landmarks = None

                if pose is not None:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    rgb.flags.writeable = False
                    pose_result = pose.process(rgb)
                    if pose_result.pose_landmarks:
                        landmarks = pose_result.pose_landmarks
                        signal = self._pose_signal(landmarks.landmark)
                        if signal is not None:
                            self.engine = "MediaPipe Pose"

                face_rect = None
                if signal is None:
                    face = self._face_signal(cv2, face_cascade, frame)
                    if face is not None:
                        signal = face[:4]
                        face_rect = face[4]
                        self.engine = "OpenCV Face"

                if self._take_recalibration_request():
                    self.interpreter.reset_calibration()
                    self.input_controller.request_target_lane(1, "camera")
                    self.input_controller.set_crouching("vision", False)

                if signal is not None:
                    self.pose_visible = True
                    result = self.interpreter.update(signal[0], signal[1], signal[2])
                    self._apply_gesture(result)
                    if result.calibrated:
                        self.status = "Controle corporal ativo"
                    else:
                        self.status = "Fique no centro e em pe para calibrar"
                else:
                    self.pose_visible = False
                    self.input_controller.set_crouching("vision", False)
                    self.action = "CORPO NAO DETECTADO"
                    self.status = "Afaste-se um pouco e apareca da cintura para cima"

                if landmarks is not None and drawing is not None:
                    drawing.draw_landmarks(
                        frame,
                        landmarks,
                        pose_connections,
                        landmark_drawing_spec=drawing.DrawingSpec(color=(80, 255, 120), thickness=2, circle_radius=2),
                        connection_drawing_spec=drawing.DrawingSpec(color=(255, 190, 70), thickness=2),
                    )
                elif face_rect is not None:
                    x, y, w, h = face_rect
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (80, 255, 120), 2)

                current_time = time.monotonic()
                instantaneous_fps = 1.0 / max(0.001, current_time - previous_time)
                previous_time = current_time
                smoothed_fps = instantaneous_fps if not smoothed_fps else smoothed_fps * 0.88 + instantaneous_fps * 0.12
                self.fps = smoothed_fps
                self._publish_preview(cv2, frame)
        except Exception as exc:
            self.status = f"Erro na visao: {type(exc).__name__}: {exc}"
            self.action = "ERRO NA CAMERA"
        finally:
            self.connected = False
            self.pose_visible = False
            self.input_controller.set_crouching("vision", False)
            cap.release()
            self._capture = None
            if pose is not None:
                pose.close()
