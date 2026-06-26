# 📘 Complete Setup Guide — IIoT Sorting Station

## Table of Contents
1. [System Architecture](#1-system-architecture)
2. [Factory IO Configuration](#2-factory-io-configuration)
3. [PLC Program (Schneider MEB)](#3-plc-program-schneider-meb)
4. [Node-RED Configuration](#4-node-red-configuration)
5. [AI Vision Detector (Python)](#5-ai-vision-detector-python)
6. [Modbus Address Table](#6-modbus-address-table)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. System Architecture

```
    ┌──────────────┐         ┌──────────────┐
    │  Factory IO  │◄───────►│ Schneider    │
    │  (Sorting    │ Modbus  │ Machine      │
    │   Station)   │  TCP    │ Expert Basic │
    └──────────────┘  :502   └──────┬───────┘
                                     │ Modbus TCP
                                     ▼
                              ┌──────────────┐
                              │   Node-RED   │ ← Port 1880
                              │  (Middleware) │
                              └──┬───┬───┬───┘
                                 │   │   │
              ┌──────────────────┘   │   └──────────────────┐
              ▼                      ▼                      ▼
     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
     │  Dashboard   │     │  Telegram    │     │  Python +    │
     │  Web (/ui)   │     │  Alerts      │     │  OpenCV/AI   │
     └──────────────┘     └──────────────┘     │  (MQTT)      │
                                                └──────────────┘
```

**Data Flow:**
1. Factory IO simulates the physical plant and connects to the PLC via Modbus TCP.
2. The PLC (Schneider M221 virtual) executes the control logic.
3. Node-RED reads/writes PLC variables via Modbus TCP.
4. The web dashboard displays data and provides remote control.
5. Telegram alerts notify operators of critical states or alarms.
6. The AI vision module processes camera images and classifies parts, sending results via MQTT.

---

## 2. Factory IO Configuration

### 2.1 Load the Scene
1. Open **Factory IO**.
2. Go to **File → Open**.
3. Select the default **Sorting Station** scene (or your custom scene).

### 2.2 Configure the Driver
1. Go to **File → Drivers** (or press F4).
2. Select **Modbus TCP/IP Client**.
3. Configure:
   - ✅ **Auto connect**: Checked
   - **Host**: `127.0.0.1`
   - **Port**: `502`
   - **Slave ID**: `1`

### 2.3 Modify I/O Points (IMPORTANT!)

> **⚠️ REQUIRED CONFIGURATION**: In Factory I/O's **Configuration** screen, enter the following offsets and counts to align variables with the PLC and avoid addressing conflicts:

| I/O Points Field     | Default Value        | **Correct Value**                | Description                          |
|----------------------|----------------------|----------------------------------|--------------------------------------|
| **Digital Inputs**   | Offset: 0, Count: 8 | **Offset: 0**, Count: 7         | PLC Inputs (Sensors/Buttons FIO → PLC) |
| **Digital Outputs**  | Offset: 0, Count: 12| **Offset: 10**, Count: 12       | PLC Outputs (Actuators/Motors PLC → FIO) |
| **Register Inputs**  | Offset: 0, Count: 1 | **Offset: 0**, Count: 1         | PLC Input Reg (FIO Vision Sensor → PLC) |
| **Register Outputs** | Offset: 0, Count: 3 | **Offset: 10**, Count: 3        | PLC Holding Reg (FIO Displays ← PLC) |

With these changes applied, the connection mapping is as follows:

#### Sensors (Factory IO → PLC) — Coils 0–6
| Coil | Factory IO Tag      | PLC Variable | Description           |
|------|---------------------|--------------|-----------------------|
| **0**| At exit             | `%M0`        | Exit sensor           |
| **1**| Start               | `%M1`        | Start button          |
| **2**| Reset               | `%M2`        | Reset button          |
| **3**| Stop                | `%M3`        | Stop button           |
| **4**| Emergency stop      | `%M4`        | Emergency mushroom    |
| **5**| Auto                | `%M5`        | Automatic mode        |
| **6**| FACTORY I/O Running | `%M6`        | FIO running status    |

#### Vision Sensor (Factory IO → PLC) — Holding Register 0
| Holding Reg | Factory IO Tag | PLC Variable | Values                              |
|-------------|----------------|--------------|-------------------------------------|
| **0**       | Vision Sensor  | `%MW0`       | 0=none, 1=blue, 4=green, 7=metallic |

#### Actuators (PLC → Factory IO) — Coils 10–21
| Coil (Output) | Factory IO Tag      | PLC Variable | Description          |
|---------------|---------------------|--------------|-----------------------|
| **10**        | Entry conveyor      | `%M10`       | Entry conveyor belt  |
| **11**        | Stop blade          | `%M11`       | Pneumatic stop blade |
| **12**        | Exit conveyor       | `%M12`       | Exit conveyor belt   |
| **13**        | Sorter 1 turn       | `%M13`       | Sorter 1 (turn arm)  |
| **14**        | Sorter 1 belt       | `%M14`       | Sorter 1 (belt)      |
| **15**        | Sorter 2 turn       | `%M15`       | Sorter 2 (turn arm)  |
| **16**        | Sorter 2 belt       | `%M16`       | Sorter 2 (belt)      |
| **17**        | Sorter 3 turn       | `%M17`       | Sorter 3 (turn arm)  |
| **18**        | Sorter 3 belt       | `%M18`       | Sorter 3 (belt)      |
| **19**        | Start light         | `%M19`       | Green panel light    |
| **20**        | Reset light         | `%M20`       | Blue panel light     |
| **21**        | Stop light          | `%M21`       | Red panel light      |

#### Counters (PLC → Factory IO) — Holding Registers 10–12
| Holding Reg | Factory IO Tag | PLC Variable | Description            |
|-------------|----------------|--------------|------------------------|
| **10**      | Counter 1      | `%MW10`      | Blue parts counter     |
| **11**      | Counter 2      | `%MW11`      | Green parts counter    |
| **12**      | Counter 3      | `%MW12`      | Metallic parts counter |

---

## 3. PLC Program (Schneider MEB)

### 3.1 Create New Project
1. Open **Machine Expert Basic** (EcoStruxure)
2. New project → Select controller **M221** (TM221CE16R or similar)
3. Configure communication:
   - Go to **Communication → Ethernet**
   - Verify that Modbus TCP Server is enabled
   - IP: `127.0.0.1`, Port: `502`

### 3.2 Program Structure

The program has these sections in Ladder (LD):

#### Section 1: Mode Management

The system supports LOCAL control (Factory IO panel) and REMOTE control (Node-RED dashboard).

```
RUNG 1 - START:
  [%M1 OR %M30] AND NOT %M4 AND NOT %M34 → SET %MW20 = 1
  (FIO Start OR Remote Start) AND NOT Emergency → RUNNING

RUNG 2 - STOP:
  [%M3 OR %M31] → SET %MW20 = 0
  (FIO Stop OR Remote Stop) → STOPPED

RUNG 3 - PAUSE:
  [%M32] AND %MW20=1 → SET %MW20 = 2
  Remote Pause when running → PAUSED

RUNG 4 - EMERGENCY:
  [%M4 OR %M34] → SET %MW20 = 3, RESET all actuators %M10-%M21
  Local or remote emergency → everything stops

RUNG 5 - RESET:
  [%M2 OR %M33] AND %MW20=3 → SET %MW20 = 0, reset counters
  Reset when in emergency → return to STOPPED
```

#### Section 2: Process Logic (when %MW20 = 1 RUNNING)
```
RUNG 5 - CONVEYORS:
  %MW20 = 1 → %M10 (Entry Conveyor ON), %M12 (Exit Conveyor ON)

RUNG 6-10 - BLUE CLASSIFICATION (Sorter 1, Latch/Delay/Activate/Pulse/Reset pattern):
  Latch:   %M0 AND %MW0=1 AND %MW1<>1 → SET %M41 (Blue Active)
  Delay:   %M41 → %TM0 TON (0.3s) — travel time to sorter
  Activate:%TM0.Q → SET %M13, SET %M14
  Pulse:   %TM0.Q → %TM10 TP (1.0s) — activation duration
  Reset:   %TM0.Q AND NOT %TM10.Q → RESET %M13, %M14, %M41

RUNG 11-15 - GREEN CLASSIFICATION (Sorter 2, same pattern):
  Latch:   %M0 AND %MW0=4 AND %MW1<>4 → SET %M42 (Green Active)
  Delay:   %M42 → %TM1 TON (2.2s)
  Pulse:   %TM1.Q → %TM11 TP (1.0s)
  Reset:   RESET %M15, %M16, %M42

RUNG 16-20 - METALLIC CLASSIFICATION (Sorter 3, same pattern):
  Latch:   %M0 AND %MW0=7 AND %MW1<>7 → SET %M43 (Metal Active)
  Delay:   %M43 → %TM2 TON (4.0s)
  Pulse:   %TM2.Q → %TM12 TP (1.0s)
  Reset:   RESET %M17, %M18, %M43

RUNG 21 - TOTAL COUNTER:
  Rising edge %M0 → %MW21 = %MW21 + 1

RUNG 22 - COUNTERS BY COLOR:
  Rising edge %M0 + If %MW0=1 → %MW22++ → %MW10 = %MW22 (Counter 1 FIO)
                     If %MW0=4 → %MW23++ → %MW11 = %MW23 (Counter 2 FIO)
                     If %MW0=7 → %MW24++ → %MW12 = %MW24 (Counter 3 FIO)
```

#### Section 3: Panel Lights
```
RUNG 11 - LIGHTS:
  %MW20 = 1 → SET %M19 (Start light green)
  %MW20 = 0 → SET %M21 (Stop light red)
  %MW20 = 3 → SET %M21 blinking (500ms timer toggle)
  %MW20 = 2 → Blink %M19 (pause = flashing green light)
```

#### Section 4: Conveyor Speed
```
RUNG 12 - SPEED:
  Read %MW30 (remote setpoint from Node-RED)
  If %MW30 > 0 → %MW25 = %MW30 (copy speed to read register)
  If %MW30 = 0 → %MW25 = 50 (default speed 50%)
```

### 3.3 Modbus Variables Summary

See the complete table in [Section 6](#6-modbus-address-table).

### 3.4 Download to Simulator
1. Connect to the controller (simulated or real).
2. In Machine Expert Basic, go to the **Commissioning** tab.
3. Click **Launch Simulator** (if not using a physical PLC).
4. Click **PC to Controller (Download)** to transfer the program.
5. Switch to **RUN** mode.
6. Verify that Factory IO connects successfully (the circular Modbus icon in Factory IO will turn green).

---

## 4. Node-RED Configuration

### 4.1 Install Required Palettes
Open a terminal and run:
```bash
cd %USERPROFILE%\.node-red
npm install node-red-dashboard
npm install node-red-contrib-modbus
```

Then restart Node-RED:
```bash
node-red
```

### 4.2 Import the Flows
1. Open Node-RED in your browser: `http://localhost:1880`
2. Click the menu ☰ (top right)
3. **Import → Clipboard**
4. Click **"select a file to import"**
5. Navigate to: `nodered/flows.json`
6. Click **Import**
7. The flows will appear in 5 tabs

### 4.3 Configure Connections

#### Modbus (PLC):
1. Double-click any Modbus node (blue)
2. Click the pencil ✏️ next to the server
3. Verify:
   - **Host**: `127.0.0.1` (or the PLC's IP address)
   - **Port**: `502`
   - **Unit Id**: `1`
4. Click "Update" → "Done"

#### MQTT (Mosquitto):
1. Double-click any MQTT node (purple)
2. Click the pencil ✏️ next to the broker
3. Verify:
   - **Server**: `127.0.0.1`
   - **Port**: `1883`
4. Click "Update" → "Done"

### 4.4 Deploy
1. Click the red **Deploy** button (top right)
2. Verify that no nodes have errors (they should not appear red)
3. Open the dashboard: `http://localhost:1880/ui`

---

## 5. AI Vision Detector (Python)

### 5.1 Install Dependencies
```bash
cd vision/
pip install -r requirements.txt
```

### 5.2 Run
```bash
python detector.py --mode hands
```

Available options:
```bash
python detector.py --broker 127.0.0.1 --port 1883 --camera 0
python detector.py --no-images        # Don't send images via MQTT (data only)
python detector.py --camera 1         # Use second camera
python detector.py --width 320 --height 240  # Lower resolution
```

### 5.3 Runtime Controls
- **q**: Quit the detector
- **r**: Reset counters

### 5.4 Calibrate Colors
If color detection isn't accurate, you can adjust the HSV ranges from Node-RED:
1. Go to the "5. AI Vision" tab in Node-RED
2. Use the dashboard controls to enable/disable image streaming

Or send configuration via MQTT:
```bash
mosquitto_pub -t "planta/vision/config" -m '{"AZUL": {"lower": [100, 80, 50], "upper": [130, 255, 255]}}'
```

### 5.5 Manual HSV Calibration
To find the correct HSV ranges for your lighting conditions, you can create a helper script with OpenCV trackbars. Default values:

| Color    | H min | H max | S min | S max | V min | V max |
|----------|-------|-------|-------|-------|-------|-------|
| Blue     | 100   | 130   | 80    | 255   | 50    | 255   |
| Green    | 35    | 85    | 80    | 255   | 50    | 255   |
| Metallic | 0     | 180   | 0     | 50    | 120   | 220   |

---

## 6. Modbus Address Table

### Coils (Bits - Function Code 01/05/15)

| Address  | PLC Variable | Description / Factory IO Tag        | Type           |
|----------|-------------|--------------------------------------|----------------|
| **0**    | `%M0`       | At exit (Exit sensor)                | PLC Input      |
| **1**    | `%M1`       | Start Button (FIO Panel)             | PLC Input      |
| **2**    | `%M2`       | Reset Button (FIO Panel)             | PLC Input      |
| **3**    | `%M3`       | Stop Button (FIO Panel)              | PLC Input      |
| **4**    | `%M4`       | Emergency stop (Mushroom button)     | PLC Input      |
| **5**    | `%M5`       | Auto (Automatic mode)                | PLC Input      |
| **6**    | `%M6`       | FACTORY I/O Running (Status)         | PLC Input      |
| **10**   | `%M10`      | Entry conveyor                       | PLC Output     |
| **11**   | `%M11`      | Stop blade (Pneumatic stop)          | PLC Output     |
| **12**   | `%M12`      | Exit conveyor                        | PLC Output     |
| **13**   | `%M13`      | Sorter 1 turn (Arm 1 rotation)       | PLC Output     |
| **14**   | `%M14`      | Sorter 1 belt (Arm 1 belt)           | PLC Output     |
| **15**   | `%M15`      | Sorter 2 turn (Arm 2 rotation)       | PLC Output     |
| **16**   | `%M16`      | Sorter 2 belt (Arm 2 belt)           | PLC Output     |
| **17**   | `%M17`      | Sorter 3 turn (Arm 3 rotation)       | PLC Output     |
| **18**   | `%M18`      | Sorter 3 belt (Arm 3 belt)           | PLC Output     |
| **19**   | `%M19`      | Start light (Green light)            | PLC Output     |
| **20**   | `%M20`      | Reset light (Blue light)             | PLC Output     |
| **21**   | `%M21`      | Stop light (Red light)               | PLC Output     |
| **30**   | `%M30`      | CMD: Remote Start (Node-RED)         | Remote Write   |
| **32**   | `%M32`      | CMD: Remote Pause (Node-RED)         | Remote Write   |
| **33**   | `%M33`      | CMD: Remote Reset (Node-RED)         | Remote Write   |
| **34**   | `%M34`      | CMD: Remote Emergency                | Remote Write   |

### Holding Registers (16-bit - Function Code 03/06/16)

| Address  | PLC Variable | Description / Factory IO Tag                                   | Type / R-W      |
|----------|-------------|----------------------------------------------------------------|-----------------|
| **0**    | `%MW0`      | Vision Sensor Value (0-3)                                      | Input (Read)    |
| **1**    | `%MW1`      | Bypass Color QR (0=None, 1=Blue, 4=Green, 7=Metallic)         | Input (Write from Node-RED) |
| **10**   | `%MW10`     | Counter 1 (FIO Display 1)                                      | Output (PLC Read) |
| **11**   | `%MW11`     | Counter 2 (FIO Display 2)                                      | Output (PLC Read) |
| **12**   | `%MW12`     | Counter 3 (FIO Display 3)                                      | Output (PLC Read) |
| **20**   | `%MW20`     | System State (0=Stop, 1=Run, 2=Pause, 3=Emergency)            | Remote Read     |
| **21**   | `%MW21`     | Total Count                                                     | Remote Read     |
| **22**   | `%MW22`     | Blue Count                                                      | Remote Read     |
| **23**   | `%MW23`     | Green Count                                                     | Remote Read     |
| **24**   | `%MW24`     | Metallic Count                                                  | Remote Read     |
| **25**   | `%MW25`     | Conveyor Speed Actual (%)                                       | Remote Read     |
| **30**   | `%MW30`     | Remote Speed Setpoint                                           | Remote Write    |

### System State Values (%MW20)
| Value | State        | Description                                       |
|-------|-------------|---------------------------------------------------|
| **0** | STOPPED      | Plant stopped, conveyors off.                     |
| **1** | RUNNING      | Plant operating automatically.                    |
| **2** | PAUSED       | Conveyors temporarily stopped (pause).            |
| **3** | EMERGENCY    | Emergency stop active, all outputs disabled.      |

### Vision Sensor Values (%MW0)
| Value | Part Type  |
|-------|-----------|
| **0** | None       |
| **1** | Blue       |
| **4** | Green      |
| **7** | Metallic   |

---

## 7. Troubleshooting

### Factory IO won't connect to the PLC
- Verify the virtual PLC is in RUN mode
- Verify the Modbus TCP driver is configured with the correct IP
- Verify port 502 is not blocked by the firewall

### Node-RED can't read PLC data
- Verify the IP and port in the Modbus node configuration
- Verify Modbus addresses match those in the PLC program
- Open the Debug tab in Node-RED to check for errors

### Telegram alerts aren't arriving
- Verify the Telegram API key is correct
- Verify the phone number format includes country code
- Test with the manual injection node "Manual Alert Test"
- Verify the `delay` node isn't blocking (anti-flooding)

### The vision detector can't detect colors
- Check the lighting (HSV detection is sensitive to light conditions)
- Adjust the HSV ranges in the script or via MQTT
- Use `--camera 1` if you have multiple cameras

### The dashboard doesn't look right on mobile
- Make sure you're accessing via the LAN IP, not `localhost`
- Verify the firewall allows connections on port 1880
- Example: `http://192.168.1.100:1880/ui`

### Mosquitto won't start
```bash
# Check status
net start mosquitto
# Or start manually
mosquitto -v
```

### "ECONNREFUSED" error in Node-RED
- The PLC/Mosquitto isn't running
- Verify all services are active before clicking Deploy
