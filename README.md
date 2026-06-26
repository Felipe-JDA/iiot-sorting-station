# 🏭 IIoT Sorting Station — Industrial IoT with Edge AI

<div align="center">

![Node-RED](https://img.shields.io/badge/Node--RED-8F0000?style=for-the-badge&logo=nodered&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![MQTT](https://img.shields.io/badge/MQTT-660066?style=for-the-badge&logo=eclipse-mosquitto&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-5C3EE8?style=for-the-badge&logo=opencv&logoColor=white)
![MediaPipe](https://img.shields.io/badge/MediaPipe-0097A7?style=for-the-badge&logo=google&logoColor=white)

**A full-stack Industrial IoT system that classifies factory parts using AI hand-gesture recognition, real-time dashboards, WhatsApp alerts, and PLC communication over Modbus TCP.**

[Features](#-features) · [Architecture](#-architecture) · [Quick Start](#-quick-start) · [Screenshots](#-screenshots) · [Tech Stack](#-tech-stack)

</div>

---

## 📖 About

This project implements a complete **Industry 4.0** solution for a simulated Sorting Station. Parts travel on a conveyor belt and are classified by color (blue, green, metallic) using pneumatic actuators controlled by a Schneider M221 PLC.

What makes this project unique is the **Edge AI** layer: a computer vision system powered by Google's MediaPipe detects the operator's hand gestures via webcam and translates finger counts into sorting commands — bypassing the physical sensor entirely and controlling the factory through MQTT and Modbus TCP protocols.

> **1 finger = Blue** · **2 fingers = Green** · **3+ fingers = Metallic**

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🎛️ **Remote Dashboard** | Real-time web HMI with dark industrial theme, live counters, LED indicators, and trend charts |
| 🤖 **AI Hand Detection** | MediaPipe-powered finger counting that maps gestures to sorting commands |
| 📡 **MQTT + Modbus TCP** | Full IT/OT convergence — Python → MQTT → Node-RED → Modbus → PLC |
| 📲 **WhatsApp Alerts** | Automatic notifications when production thresholds or emergency stops are triggered |
| 📊 **CSV Report Generation** | One-click export of production history with timestamps, counters, and sensor states |
| 🎮 **Dual Control** | Operate from the physical Factory IO panel OR the web dashboard simultaneously |
| 🔴 **Emergency System** | Safety-compliant emergency stop with lockout/reset sequence |
| 🌐 **Mobile Responsive** | Dashboard accessible from any device on the network |

---

## 🏗️ Architecture

```
┌─────────────────────┐     Modbus TCP      ┌─────────────────────┐
│  Schneider M221     │◄──────────────────►│     Factory I/O      │
│  (PLC - Ladder)     │     Port 502        │  (Sorting Station)   │
└─────────┬───────────┘                     └─────────────────────┘
          │ Modbus TCP (R/W Registers)
          ▼
┌─────────────────────┐       MQTT          ┌─────────────────────┐
│     Node-RED         │◄─────────────────►│   Python + OpenCV    │
│   (IIoT Middleware)  │    Port 1883       │  + MediaPipe (AI)    │
└──┬────┬────┬────┬───┘                     └─────────────────────┘
   │    │    │    │                                    ▲
   ▼    ▼    ▼    ▼                                    │
  Web  WhatsApp CSV  Modbus                         Webcam
 Dashboard Alerts Reports Write                    (Real-time)
```

### Data Flow (Hand Gesture → Factory Action)

1. **Webcam** captures operator's hand in real-time
2. **MediaPipe AI** detects 21 hand landmarks and counts raised fingers
3. **Python** publishes gesture result to MQTT topic `planta/vision/qr_color`
4. **Node-RED** receives the message and writes the bypass value to PLC memory via Modbus TCP
5. **PLC** reads the register and activates the corresponding pneumatic actuator
6. **Factory I/O** pushes the part to the correct sorting ramp

---

## 🚀 Quick Start

### Prerequisites

- [Node.js](https://nodejs.org/) (v18+)
- [Python](https://www.python.org/) (3.10+)
- [Mosquitto MQTT Broker](https://mosquitto.org/)
- [Factory I/O](https://factoryio.com/) (with Sorting Station scene)
- [Schneider Machine Expert Basic](https://www.se.com/) (for PLC programming)

### 1. Install Node-RED and required palettes

```bash
npm install -g node-red

cd ~/.node-red
npm install node-red-dashboard
npm install node-red-contrib-modbus
npm install node-red-contrib-image-output
```

### 2. Import the flows

1. Start Node-RED: `node-red`
2. Open `http://localhost:1880`
3. Menu ☰ → **Import** → Select `nodered/flows.json`
4. Configure the Modbus server IP in the connection nodes
5. Click **Deploy**

### 3. Install Python dependencies

```bash
cd vision/
pip install -r requirements.txt
```

> **Note:** The `hand_landmarker.task` model file (~7.5 MB) is required for hand detection mode. Download it from [MediaPipe Models](https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task) and place it in the `vision/` directory.

### 4. Run the AI detector

```bash
# Hand gesture mode (default)
python detector.py

# QR code mode
python detector.py --mode camera

# Screen color detection mode
python detector.py --mode screen
```

### 5. Access the Dashboard

- **Local:** `http://localhost:1880/ui`
- **Mobile/Tablet:** `http://<YOUR_PC_IP>:1880/ui`

---

## 📸 Screenshots

> *Add screenshots of your dashboard, Factory IO scene, and hand detection in action here.*

<!-- Uncomment and replace with your actual screenshots:
![Dashboard](docs/screenshots/dashboard.png)
![Hand Detection](docs/screenshots/hand_detection.png)
![Factory IO](docs/screenshots/factory_io.png)
-->

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Simulation** | Factory I/O | 3D industrial plant simulation |
| **PLC** | Schneider M221 (Machine Expert Basic) | Ladder logic, actuator control |
| **Communication** | Modbus TCP / MQTT | Industrial & IoT protocols |
| **Middleware** | Node-RED | Flow-based integration platform |
| **Frontend** | Node-RED Dashboard | Web-based HMI |
| **AI/Vision** | Python, OpenCV, MediaPipe | Hand landmark detection |
| **Alerts** | Telegram Bot API | Telegram notifications |
| **Broker** | Eclipse Mosquitto | MQTT message broker |

---

## 📁 Project Structure

```
iiot-sorting-station/
├── nodered/
│   └── flows.json                 # Node-RED flows (import into editor)
├── vision/
│   ├── detector.py                # AI vision detector (hands/QR/color)
│   ├── requirements.txt           # Python dependencies
│   └── hand_landmarker.task       # MediaPipe AI model (see Quick Start)
├── plc/
│   └── Control banda.smbp        # Schneider Machine Expert Basic project
├── docs/
│   └── setup_guide.md             # Full setup guide
├── factoryio/
│   └── Sorting_Station.factoryio  # Factory I/O scene file
├── .gitignore
├── LICENSE
└── README.md
```

---

## 🔑 Key MQTT Topics

| Topic | Direction | Description |
|-------|-----------|-------------|
| `planta/vision/resultado` | Python → Node-RED | Detection result JSON |
| `planta/vision/imagen` | Python → Node-RED | Base64-encoded camera frame |
| `planta/vision/estado` | Python → Node-RED | Detector status (online/offline) |
| `planta/vision/config` | Node-RED → Python | Runtime configuration |
| `planta/vision/qr_color` | Python → Node-RED → PLC | Bypass color command for Modbus |

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## 👨🏻‍💻 Author

**Jhoan Felipe Delgado Acevedo** — Industrial Networks & Communications Engineering Student

* GitHub: [@Felipe-JDA](https://github.com/Felipe-JDA)
* LinkedIn: [Jhoan Felipe Delgado Acevedo](https://www.linkedin.com/) *(Añade aquí tu link real)*

---

<div align="center">
  <sub>Built with ❤️ by Félex</sub>
</div>
