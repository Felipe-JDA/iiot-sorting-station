"""
╔══════════════════════════════════════════════════════════════╗
║  MQTT COLOR DETECTOR — IIoT Sorting Station                ║
║  Edge AI Vision System                                      ║
╚══════════════════════════════════════════════════════════════╝

Captures video from webcam, detects objects by color, QR codes,
or HAND GESTURES (MediaPipe) and publishes results via MQTT
for Node-RED to display on the web dashboard.

Operating modes:
  - camera  → Scan QR codes with webcam
  - screen  → Detect colors on screen (Factory IO)
  - hands   → Detect raised fingers with webcam
              1 finger = BLUE, 2 fingers = GREEN, 3+ = METALLIC

MQTT Topics:
  - planta/vision/resultado  → Detection result JSON
  - planta/vision/imagen     → Processed image in base64 (JPEG)
  - planta/vision/estado     → Detector status (online/offline)
  - planta/vision/config     → Receives config from Node-RED

Usage:
  python detector.py --mode hands [--broker 127.0.0.1] [--camera 0]
"""

import cv2
import numpy as np
import json
import base64
import time
import argparse
import threading
import sys
from datetime import datetime

# Try to import paho-mqtt
try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("ERROR: paho-mqtt is not installed.")
    print("Run: pip install paho-mqtt")
    sys.exit(1)

# Try to import mediapipe (required only for "hands" mode)
try:
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
except ImportError:
    mp = None


# ═══════════════════════════════════════════════════════════════
# COLOR CONFIGURATION (HSV)
# ═══════════════════════════════════════════════════════════════
# Cada color se define por un rango en el espacio HSV.
# H: 0-179, S: 0-255, V: 0-255 (en OpenCV)

COLOR_RANGES = {
    "BLUE": {
        "lower": np.array([100, 80, 50]),
        "upper": np.array([130, 255, 255]),
        "bgr": (255, 100, 0),       # Color para dibujar (BGR)
        "min_area": 3000,            # Minimum area in pixels to consider detection
        "label": "🔵 BLUE"
    },
    "GREEN": {
        "lower": np.array([35, 80, 50]),
        "upper": np.array([85, 255, 255]),
        "bgr": (0, 255, 100),
        "min_area": 3000,
        "label": "🟢 GREEN"
    },
    "METALICO": {
        "lower": np.array([0, 0, 120]),
        "upper": np.array([180, 50, 220]),
        "bgr": (180, 180, 180),
        "min_area": 3000,
        "label": "⚪ METALLIC"
    }
}

# ═══════════════════════════════════════════════════════════════
# TÓPICOS MQTT
# ═══════════════════════════════════════════════════════════════
TOPIC_RESULTADO = "planta/vision/resultado"
TOPIC_IMAGEN    = "planta/vision/imagen"
TOPIC_ESTADO    = "planta/vision/estado"
TOPIC_CONFIG    = "planta/vision/config"
TOPIC_QR_COLOR  = "planta/vision/qr_color"

# ═══════════════════════════════════════════════════════════════
# MAPEO DE DEDOS → COLOR (para modo "hands")
# ═══════════════════════════════════════════════════════════════
FINGER_MAP = {
    0: "NINGUNO",
    1: "BLUE",
    2: "GREEN",
    3: "METALICO",
    4: "METALICO",   # 4 fingers also count as metallic
}


class ColorDetector:
    """Color detector with MQTT publishing."""

    def __init__(self, broker="127.0.0.1", port=1883, camera_id=0, mode="camera"):
        self.broker = broker
        self.port = port
        self.camera_id = camera_id
        self.mode = mode  # "camera", "screen", o "hands"
        self.running = False
        self.send_images = True
        self.detection_enabled = True
        self.image_interval = 0.5       # Send image every 0.5 seconds
        self.detection_interval = 0.3   # Evaluate detection every 0.3 seconds
        self.last_image_time = 0
        self.last_detection_time = 0
        self.frame_width = 640
        self.frame_height = 480

        # Detection counters
        self.counters = {"BLUE": 0, "GREEN": 0, "METALICO": 0, "TOTAL": 0}
        self.last_detection = "NINGUNO"
        self.last_detection_stable = "NINGUNO"
        self.detection_buffer = []  # Buffer to stabilize detection
        self.buffer_size = 5        # Number of frames to confirm detection

        # QR code reader configuration
        self.qr_detector = cv2.QRCodeDetector()
        self.bypass_color = 0
        self.bypass_color_name = "NINGUNO"
        self.last_qr_text = ""
        self.cap = None

        # ── MediaPipe Hands (for "hands" mode) ──
        self.mp_hands_detector = None
        if mp is not None:
            try:
                import os
                current_dir = os.path.dirname(os.path.abspath(__file__))
                model_path = os.path.join(current_dir, 'hand_landmarker.task')
                base_options = python.BaseOptions(model_asset_path=model_path)
                options = vision.HandLandmarkerOptions(
                    base_options=base_options,
                    running_mode=vision.RunningMode.VIDEO,
                    num_hands=1)
                self.mp_hands_detector = vision.HandLandmarker.create_from_options(options)
            except Exception as e:
                print("  ❌ ERROR: No se pudo cargar el modelo de IA (hand_landmarker.task) -", e)

        # MQTT Client
        self.client = mqtt.Client(client_id="detector_vision_iiot", protocol=mqtt.MQTTv311)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        self.client.will_set(TOPIC_ESTADO, payload=json.dumps({
            "status": "offline",
            "timestamp": datetime.now().isoformat()
        }), qos=1, retain=True)

    def _on_connect(self, client, userdata, flags, rc):
        """Callback cuando se conecta al broker MQTT."""
        if rc == 0:
            print(f"  ✅ Conectado al broker MQTT ({self.broker}:{self.port})")
            # Subscribe to configuration
            client.subscribe(TOPIC_CONFIG, qos=1)
            # Publish online status
            client.publish(TOPIC_ESTADO, json.dumps({
                "status": "online",
                "timestamp": datetime.now().isoformat(),
                "camera": self.camera_id,
                "mode": self.mode
            }), qos=1, retain=True)
        else:
            print(f"  ❌ MQTT connection error, code: {rc}")

    def _on_message(self, client, userdata, msg):
        """Callback when a configuration message is received."""
        try:
            config = json.loads(msg.payload.decode())
            print(f"  📩 Configuration received: {config}")

            if "send_images" in config:
                self.send_images = bool(config["send_images"])
                print(f"     Envío de imágenes: {'ON' if self.send_images else 'OFF'}")

            if "detection_enabled" in config:
                self.detection_enabled = bool(config["detection_enabled"])
                print(f"     Detección: {'ON' if self.detection_enabled else 'OFF'}")

            if "image_interval" in config:
                self.image_interval = max(0.1, float(config["image_interval"]))
                print(f"     Intervalo de imagen: {self.image_interval}s")

            if "reset_counters" in config and config["reset_counters"]:
                self.counters = {"BLUE": 0, "GREEN": 0, "METALICO": 0, "TOTAL": 0}
                print("     🔄 Counters reset")

            # Update color ranges dynamically
            for color_name in ["BLUE", "GREEN", "METALICO"]:
                if color_name in config:
                    color_cfg = config[color_name]
                    if "lower" in color_cfg:
                        COLOR_RANGES[color_name]["lower"] = np.array(color_cfg["lower"])
                    if "upper" in color_cfg:
                        COLOR_RANGES[color_name]["upper"] = np.array(color_cfg["upper"])
                    if "min_area" in color_cfg:
                        COLOR_RANGES[color_name]["min_area"] = int(color_cfg["min_area"])
                    print(f"     🎨 Rango de {color_name} actualizado")

        except json.JSONDecodeError:
            print(f"  ⚠️ Configuration message is not valid JSON")
        except Exception as e:
            print(f"  ⚠️ Error processing configuration: {e}")

    def _on_disconnect(self, client, userdata, rc):
        """Callback cuando se desconecta del broker MQTT."""
        if rc != 0:
            print(f"  ⚠️ Unexpected disconnection from MQTT broker (rc={rc})")

    def detect_colors(self, frame):
        """
        Detects colors in the frame and returns the classification.

        Args:
            frame: Frame BGR de OpenCV

        Returns:
            tuple: (detected_color, results_dict, annotated_frame)
        """
        # Convertir a HSV
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        annotated = frame.copy()

        # Aplicar desenfoque para reducir ruido
        hsv_blurred = cv2.GaussianBlur(hsv, (11, 11), 0)

        results = {}
        max_area = 0
        dominant_color = "NINGUNO"

        for color_name, color_config in COLOR_RANGES.items():
            # Create mask
            mask = cv2.inRange(hsv_blurred, color_config["lower"], color_config["upper"])

            # Morphological operations to clean the mask
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

            # Encontrar contornos
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            # Filter by minimum area
            valid_contours = [c for c in contours if cv2.contourArea(c) >= color_config["min_area"]]

            total_area = sum(cv2.contourArea(c) for c in valid_contours)
            detected = len(valid_contours) > 0

            results[color_name] = {
                "detected": detected,
                "cantidad": len(valid_contours),
                "area_total": int(total_area)
            }

            # Dibujar contornos y bounding boxes
            for contour in valid_contours:
                x, y, w, h = cv2.boundingRect(contour)
                cv2.rectangle(annotated, (x, y), (x + w, y + h), color_config["bgr"], 3)
                cv2.putText(annotated, color_config["label"],
                           (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                           color_config["bgr"], 2)

            # Determine dominant color (largest area)
            if total_area > max_area and detected:
                max_area = total_area
                dominant_color = color_name

        # Draw general information on the frame
        status_text = f"Detected: {dominant_color}"
        cv2.putText(annotated, status_text, (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)

        # Draw counters
        y_offset = 60
        for color_name, count in self.counters.items():
            if color_name != "TOTAL":
                color_bgr = COLOR_RANGES[color_name]["bgr"]
                cv2.putText(annotated, f"{color_name}: {count}",
                           (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                           color_bgr, 2)
                y_offset += 25
        cv2.putText(annotated, f"TOTAL: {self.counters['TOTAL']}",
                   (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                   (255, 255, 255), 2)

        # Timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(annotated, timestamp, (10, annotated.shape[0] - 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        return dominant_color, results, annotated

    def _stabilize_detection(self, current_detection):
        """
        Estabiliza la detección usando un buffer para evitar conteos falsos.
        Solo cuenta una pieza nueva si la detección es consistente por N frames
        y luego cambia a NINGUNO.
        """
        self.detection_buffer.append(current_detection)
        if len(self.detection_buffer) > self.buffer_size:
            self.detection_buffer.pop(0)

        # Check if the majority of the buffer matches
        if len(self.detection_buffer) >= self.buffer_size:
            from collections import Counter
            most_common = Counter(self.detection_buffer).most_common(1)[0]
            if most_common[1] >= self.buffer_size * 0.8:  # 80% de coincidencia
                new_stable = most_common[0]

                # If transition from NONE to a color → new part detected
                if (self.last_detection_stable == "NINGUNO" and
                    new_stable != "NINGUNO" and
                    new_stable in self.counters):
                    self.counters[new_stable] += 1
                    self.counters["TOTAL"] += 1
                    print(f"  🎯 Nueva pieza: {new_stable} "
                          f"(Total: {self.counters['TOTAL']})")

                self.last_detection_stable = new_stable

        return self.last_detection_stable

    def _count_fingers(self, hand_landmarks):
        tip_ids = [8, 12, 16, 20]
        pip_ids = [6, 10, 14, 18]
        count = 0
        for tip, pip in zip(tip_ids, pip_ids):
            if hand_landmarks[tip].y < hand_landmarks[pip].y:
                count += 1
        return count

    def _frame_to_base64(self,
                         frame: np.ndarray,
                         quality: int = 50) -> str:
        """Encodes an OpenCV frame as base64 JPEG."""
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
        _, buffer = cv2.imencode(".jpg", frame, encode_params)
        b64_str = base64.b64encode(buffer).decode("utf-8")
        return f"data:image/jpeg;base64,{b64_str}"

    def start(self):
        """Starts the detector: connects MQTT, opens camera/screen, and processes frames."""
        print("╔══════════════════════════════════════════════════╗")
        print("║  COLOR & QR DETECTOR — IIoT Sorting Station        ║")
        print("║  Edge AI Vision System     ║")
        print("╚══════════════════════════════════════════════════╝")
        print(f"  Modo activo: {self.mode.upper()}")
        print()

        # ── Verificar MediaPipe si modo "hands" ──
        if self.mode == "hands":
            if mp is None:
                print("  ❌ ERROR: mediapipe no está instalado.")
                print("  ➡️  Run: pip install mediapipe")
                return
            if self.mp_hands_detector is None:
                print("  ❌ ERROR: No se pudo cargar el modelo hand_landmarker.task.")
                print("  Asegúrese de que el archivo existe en la misma carpeta que detector.py")
                return
            print("  🖐️  MediaPipe Hands cargado correctamente")

        # ── Conectar MQTT ──
        print(f"  🔌 Conectando a MQTT broker {self.broker}:{self.port}...")
        try:
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()
            time.sleep(1)  # Wait for connection
        except Exception as e:
            print(f"  ❌ No se pudo conectar al broker MQTT: {e}")
            print(f"     Asegúrese de que Mosquitto esté ejecutándose.")
            return

        # ── Inicializar Fuente de Captura ──
        if self.mode == "screen":
            print("  📷 Iniciando captura de pantalla...")
            try:
                import mss
            except ImportError:
                print("  ❌ ERROR: Falta la librería mss para capturar la pantalla.")
                print("  ➡️ Por favor, instala la librería ejecutando: pip install mss")
                self.client.loop_stop()
                self.client.disconnect()
                return

            self.sct = mss.mss()
            self.monitor = self.sct.monitors[1]  # Monitor principal
            print(f"  ✅ Captura de pantalla iniciada: {self.monitor['width']}x{self.monitor['height']}")
        else:
            # Modos "camera" y "hands" usan la webcam
            print(f"  📷 Iniciando webcam (ID: {self.camera_id})...")
            self.cap = cv2.VideoCapture(self.camera_id)
            if not self.cap.isOpened():
                print(f"  ❌ ERROR: No se pudo abrir la webcam con ID {self.camera_id}")
                self.client.loop_stop()
                self.client.disconnect()
                return
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
            print("  ✅ Webcam iniciada con éxito.")

        print()
        if self.mode == "hands":
            print("  ─── MODO DEDOS ACTIVO ───")
            print("  ☝️  1 dedo  = BLUE")
            print("  ✌️  2 dedos = GREEN")
            print("  🤟 3+ dedos = METALLIC")
            print("  ✊ 0 dedos  = Sin pieza")
            print()
        print("  ─── Press 'q' to quit, 'r' to reset ───")
        print()

        self.running = True

        try:
            while self.running:
                current_time = time.time()

                if self.mode == "screen":
                    # Capturar pantalla con mss
                    screenshot = self.sct.grab(self.monitor)
                    frame_bgra = np.array(screenshot)
                    frame = cv2.cvtColor(frame_bgra, cv2.COLOR_BGRA2BGR)
                    frame = cv2.resize(frame, (self.frame_width, self.frame_height))
                else:
                    # Capture from physical webcam (camera and hands)
                    ret, frame = self.cap.read()
                    if not ret:
                        print("  ⚠️ Error leyendo frame de la webcam.")
                        time.sleep(0.1)
                        continue

                annotated = frame.copy()

                if self.detection_enabled:
                    if self.mode == "screen":
                        # ── Color Detection Mode (Screen) ──
                        detected_color, results, annotated = self.detect_colors(frame)
                        stable_color = self._stabilize_detection(detected_color)

                        # Publish result
                        if current_time - self.last_detection_time >= self.detection_interval:
                            self.last_detection_time = current_time
                            result = {
                                "detected_color": stable_color,
                                "color_instantaneo": detected_color,
                                "detalles": results,
                                "counters": self.counters.copy(),
                                "timestamp": datetime.now().isoformat(),
                                "deteccion_activa": True
                            }
                            self.client.publish(TOPIC_RESULTADO, json.dumps(result), qos=0)

                    elif self.mode == "hands":
                        # ══════════════════════════════════════════
                        # ── Finger Detection Mode (MediaPipe) ──
                        # ══════════════════════════════════════════
                        # Voltear horizontalmente para efecto espejo
                        frame_flipped = cv2.flip(frame, 1)
                        annotated = frame_flipped.copy()

                        rgb = cv2.cvtColor(frame_flipped, cv2.COLOR_BGR2RGB)
                        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                        
                        try:
                            hand_results = self.mp_hands_detector.detect_for_video(mp_image, int(current_time * 1000))
                        except Exception as e:
                            hand_results = None

                        finger_count = 0
                        finger_color = "NINGUNO"

                        if hand_results and hand_results.hand_landmarks:
                            hand_lm = hand_results.hand_landmarks[0]

                            # Dibujar puntos en la mano
                            for lm in hand_lm:
                                x, y = int(lm.x * self.frame_width), int(lm.y * self.frame_height)
                                cv2.circle(annotated, (x, y), 6, (0, 210, 255), -1)

                            finger_count = self._count_fingers(hand_lm)
                            finger_color = FINGER_MAP.get(finger_count, "METALICO")

                        # Stabilize detection
                        stable_color = self._stabilize_detection(finger_color)

                        # ── Dibujar HUD (interfaz visual sobre el video) ──
                        # Barra superior semi-transparente
                        overlay = annotated.copy()
                        cv2.rectangle(overlay, (0, 0), (self.frame_width, 95), (15, 15, 30), -1)
                        annotated = cv2.addWeighted(overlay, 0.75, annotated, 0.25, 0)

                        # Title
                        cv2.putText(annotated, "HAND GESTURE DETECTOR - IIoT",
                                    (15, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 210, 255), 2)

                        # Visual color based on detection
                        color_bgr_map = {
                            "BLUE": (255, 100, 0),
                            "GREEN": (0, 255, 100),
                            "METALICO": (200, 200, 200),
                            "NINGUNO": (80, 80, 80)
                        }
                        det_bgr = color_bgr_map.get(finger_color, (255, 255, 255))

                        # Display finger count and classification
                        cv2.putText(annotated, f"Dedos: {finger_count}",
                                    (15, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                        cv2.putText(annotated, f"-> {finger_color}",
                                    (180, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.8, det_bgr, 2)

                        # Indicador de color estable
                        stable_bgr = color_bgr_map.get(stable_color, (255, 255, 255))
                        cv2.putText(annotated, f"Pieza estable: {stable_color}",
                                    (15, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.6, stable_bgr, 2)

                        # Indicador LED circular grande (esquina superior derecha)
                        led_x = self.frame_width - 50
                        led_y = 45
                        cv2.circle(annotated, (led_x, led_y), 25, det_bgr, -1)
                        cv2.circle(annotated, (led_x, led_y), 27, (0, 210, 255), 2)

                        # Bottom bar with counters
                        overlay2 = annotated.copy()
                        cv2.rectangle(overlay2, (0, self.frame_height - 55),
                                      (self.frame_width, self.frame_height), (15, 15, 30), -1)
                        annotated = cv2.addWeighted(overlay2, 0.75, annotated, 0.25, 0)

                        # Counters in the bottom bar
                        x_pos = 15
                        for cn in ["BLUE", "GREEN", "METALICO"]:
                            c_bgr = COLOR_RANGES[cn]["bgr"]
                            label = f"{cn}: {self.counters[cn]}"
                            cv2.putText(annotated, label, (x_pos, self.frame_height - 30),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, c_bgr, 2)
                            x_pos += 150

                        cv2.putText(annotated, f"TOTAL: {self.counters['TOTAL']}",
                                    (x_pos, self.frame_height - 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

                        # Timestamp
                        ts = datetime.now().strftime("%H:%M:%S")
                        cv2.putText(annotated, ts,
                                    (self.frame_width - 100, self.frame_height - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)


                        # ── Publish MQTT result ──
                        if current_time - self.last_detection_time >= self.detection_interval:
                            self.last_detection_time = current_time
                            result = {
                                "detected_color": stable_color,
                                "dedos": finger_count,
                                "color_instantaneo": finger_color,
                                "counters": self.counters.copy(),
                                "timestamp": datetime.now().isoformat(),
                                "deteccion_activa": True
                            }
                            self.client.publish(TOPIC_RESULTADO, json.dumps(result), qos=0)
                            
                            # Also send the command to the PLC (Modbus Bypass)
                            new_bypass_color = 0
                            if stable_color == "BLUE": new_bypass_color = 1
                            elif stable_color == "GREEN": new_bypass_color = 4
                            elif stable_color == "METALICO": new_bypass_color = 7
                            
                            if new_bypass_color != self.bypass_color:
                                self.bypass_color = new_bypass_color
                                self.bypass_color_name = stable_color
                                payload = {
                                    "bypass_color": self.bypass_color,
                                    "color_name": self.bypass_color_name,
                                    "qr_text": "hands_mode",
                                    "timestamp": datetime.now().isoformat()
                                }
                                self.client.publish(TOPIC_QR_COLOR, json.dumps(payload), qos=1, retain=True)
                                print(f"  🤖 PLC Bypass Actualizado: {self.bypass_color_name} ({self.bypass_color})")


                    else:
                        # ── QR Code Scanning Mode (Camera) ──
                        val, pts, _ = self.qr_detector.detectAndDecode(frame)
                        
                        if val:
                            text_clean = val.strip().lower()
                            new_bypass_color = self.bypass_color
                            new_bypass_name = self.bypass_color_name

                            # Clasificar contenido del QR
                            if any(word in text_clean for word in ["azul", "blue", "1"]):
                                new_bypass_color = 1
                                new_bypass_name = "BLUE"
                            elif any(word in text_clean for word in ["verde", "green", "4"]):
                                new_bypass_color = 4
                                new_bypass_name = "GREEN"
                            elif any(word in text_clean for word in ["metal", "gris", "gray", "silver", "7"]):
                                new_bypass_color = 7
                                new_bypass_name = "METALICO"
                            elif any(word in text_clean for word in ["ninguno", "none", "clear", "0"]):
                                new_bypass_color = 0
                                new_bypass_name = "NINGUNO"

                            # If changed, publish and notify
                            if new_bypass_color != self.bypass_color or val != self.last_qr_text:
                                self.bypass_color = new_bypass_color
                                self.bypass_color_name = new_bypass_name
                                self.last_qr_text = val
                                
                                # Publish QR bypass code to MQTT
                                payload = {
                                    "bypass_color": self.bypass_color,
                                    "color_name": self.bypass_color_name,
                                    "qr_text": val,
                                    "timestamp": datetime.now().isoformat()
                                }
                                self.client.publish(TOPIC_QR_COLOR, json.dumps(payload), qos=1, retain=True)
                                print(f"  🎯 QR Detected: '{val}' ➔ Bypass Color: {self.bypass_color_name} ({self.bypass_color})")

                        # Draw QR polygon if detected
                        if pts is not None and len(pts) > 0:
                            pts = np.int32(pts[0])
                            for i in range(4):
                                cv2.line(annotated, tuple(pts[i]), tuple(pts[(i + 1) % 4]), (0, 255, 0), 3)

                        # Draw visual interface on camera
                        cv2.rectangle(annotated, (0, 0), (self.frame_width, 60), (40, 40, 40), -1)
                        cv2.putText(annotated, "LECTOR DE CODIGO QR — IIOT", (15, 25),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                        
                        # Obtener color correspondiente para el texto
                        text_color = (255, 255, 255)
                        if self.bypass_color_name == "BLUE":
                            text_color = COLOR_RANGES["BLUE"]["bgr"]
                        elif self.bypass_color_name == "GREEN":
                            text_color = COLOR_RANGES["GREEN"]["bgr"]
                        elif self.bypass_color_name == "METALICO":
                            text_color = COLOR_RANGES["METALICO"]["bgr"]

                        cv2.putText(annotated, f"Bypass FIO Activo: {self.bypass_color_name}", (15, 50),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_color, 2)

                        # Timestamp
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        cv2.putText(annotated, timestamp, (self.frame_width - 180, 50),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

                    # ── Publish base64 image to dashboard (rate limiting) ──
                    if (self.send_images and
                        current_time - self.last_image_time >= self.image_interval):
                        self.last_image_time = current_time

                        img_b64 = self._frame_to_base64(annotated)
                        self.client.publish(
                            TOPIC_IMAGEN,
                            img_b64,
                            qos=0
                        )
                else:
                    cv2.putText(annotated, "DETECCION PAUSADA", (10, 30),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)

                # ── Show local window ──
                cv2.imshow("Vision Sorting Station - IIoT", annotated)

                # ── Comprobar tecla 'q' para salir o 'r' para reset ──
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    print("\n  🛑 Deteniendo detector...")
                    break
                elif key == ord('r'):
                    if self.mode in ("screen", "hands"):
                        self.counters = {"BLUE": 0, "GREEN": 0, "METALICO": 0, "TOTAL": 0}
                        self.last_detection_stable = "NINGUNO"
                        self.detection_buffer.clear()
                        print("  🔄 Counters reset (tecla 'r')")
                    else:
                        self.bypass_color = 0
                        self.bypass_color_name = "NINGUNO"
                        self.last_qr_text = ""
                        self.client.publish(TOPIC_QR_COLOR, json.dumps({
                            "bypass_color": 0,
                            "color_name": "NINGUNO",
                            "qr_text": "reset",
                            "timestamp": datetime.now().isoformat()
                        }), qos=1, retain=True)
                        print("  🔄 Bypass QR reiniciado a NINGUNO (tecla 'r')")

        except KeyboardInterrupt:
            print("\n  🛑 Interrupción por teclado, cerrando...")

        finally:
            # ── Limpieza ──
            self.running = False

            # Cerrar MediaPipe si estaba activo
            if self.mp_hands_detector is not None:
                self.mp_hands_detector.close()

            if self.cap is not None and self.cap.isOpened():
                self.cap.release()
            cv2.destroyAllWindows()

            # Publish offline status
            self.client.publish(TOPIC_ESTADO, json.dumps({
                "status": "offline",
                "timestamp": datetime.now().isoformat(),
                "final_counters": self.counters if self.mode in ("screen", "hands") else {},
                "bypass_final": self.bypass_color_name
            }), qos=1, retain=True)

            self.client.loop_stop()
            self.client.disconnect()

            print("  ✅ Detector cerrado correctamente")
            if self.mode in ("screen", "hands"):
                print(f"  📊 Estadísticas finales: {self.counters}")
            else:
                print(f"  📊 Final bypass status: {self.bypass_color_name}")


def main():
    parser = argparse.ArgumentParser(
        description="MQTT-based color/QR/hand-gesture detector for IIoT Sorting Station"
    )
    parser.add_argument(
        "--broker", type=str, default="127.0.0.1",
        help="MQTT broker address (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=1883,
        help="MQTT broker port (default: 1883)"
    )
    parser.add_argument(
        "--camera", type=int, default=0,
        help="ID de la cámara (default: 0)"
    )
    parser.add_argument(
        "--mode", type=str, default="hands", choices=["camera", "screen", "hands"],
        help="Modo: 'camera' (QR), 'screen' (color pantalla), 'hands' (dedos=color) (default: hands)"
    )
    parser.add_argument(
        "--no-images", action="store_true",
        help="Don't send images via MQTT (results only)"
    )
    parser.add_argument(
        "--width", type=int, default=640,
        help="Ancho del frame (default: 640)"
    )
    parser.add_argument(
        "--height", type=int, default=480,
        help="Alto del frame (default: 480)"
    )

    args = parser.parse_args()

    detector = ColorDetector(
        broker=args.broker,
        port=args.port,
        camera_id=args.camera,
        mode=args.mode
    )
    detector.send_images = not args.no_images
    detector.frame_width = args.width
    detector.frame_height = args.height

    detector.start()


if __name__ == "__main__":
    main()
