"""
THE PIT WALL v3.1 - Professional Racing Dashboard
==================================================
FIXED: UI visibility, data display, mode switching, tire temps

Two dashboards:
🟢 LIVE - Real-time driving data
🔵 COACH - Session analysis
"""

import ac
import acsys
import os
import json
import math
from collections import deque
from datetime import datetime


# ============================================================================
# PATHS
# ============================================================================
APP_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(APP_DIR, 'data')
REPORTS_DIR = os.path.join(APP_DIR, 'reports')

for d in [DATA_DIR, REPORTS_DIR]:
    try:
        if not os.path.exists(d):
            os.makedirs(d)
    except:
        pass


# ============================================================================
# GLOBALS
# ============================================================================
app_window = 0
MODE_LIVE = 0
MODE_COACH = 1
current_mode = MODE_LIVE

# UI dictionaries - SEPARATE for each mode
ui_live = {}
ui_coach = {}
ui_shared = {}

# Track/Session
current_track = ""
current_car = ""
profile_id = ""

# Data
live_buffer = deque(maxlen=6000)
optimal_lap = []
corners = []

# State
best_lap = float('inf')
session_best = float('inf')
lap_times = []
lap_count = 0
last_lap_count = -1
consistency = 0.0
frame = 0

# Live telemetry
current_speed = 0.0
current_pos = 0.0
current_corner = None
corner_score = 5.0
live_delta = 0.0

# Tires
tires = {'FL': 0.0, 'FR': 0.0, 'RL': 0.0, 'RR': 0.0}
tire_status = "---"

# Braking
brake_events = {}
is_braking = False
brake_start_pos = 0.0

# Advice
advice_text = ""
advice_cooldown = 0


# ============================================================================
# DATA PERSISTENCE
# ============================================================================
def get_data_path():
    return os.path.join(DATA_DIR, "{0}_optimal.json".format(profile_id))


def load_optimal():
    # ALWAYS put global at the very top of the function
    global optimal_lap, best_lap 
    
    path = get_data_path()
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                data = json.load(f)
                optimal_lap = data.get('telemetry', [])
                if optimal_lap is None:
                    optimal_lap = []
                    best_lap = data.get('lap_time', float('inf'))
                
                if optimal_lap and len(optimal_lap) > 100:
                    # Sort by position to ensure delta math works
                    optimal_lap.sort(key=lambda x: x['norm_pos'])
                    detect_corners()
                    ac.console("PitWall: Loaded PB {0:.3f}s".format(best_lap))
                    return True
    except Exception as e:
        ac.console("PitWall: Load error - " + str(e))
    
    return False

def save_optimal(lap_data, lap_time):
    # Declare globals first
    global optimal_lap, best_lap
    
    # Now you can safely use them in logic
    if lap_time >= best_lap:
        return False
    
    path = get_data_path()
    try:
        # We use lap_data directly since we've already formatted the dicts in acUpdate
        data = {
            'lap_time': lap_time,
            'track': current_track,
            'car': current_car,
            'timestamp': datetime.now().isoformat(),
            'telemetry': lap_data
        }
        
        with open(path, 'w') as f:
            json.dump(data, f)
        
        optimal_lap = lap_data
        best_lap = lap_time
        detect_corners()
        ac.console("PitWall: Saved new PB {0:.3f}s".format(lap_time))
        return True
    except Exception as e:
        ac.console("PitWall: Save error - " + str(e))
    return False

# ============================================================================
# CORNER DETECTION
# ============================================================================
def detect_corners():
    """Detect corners from optimal lap speed data"""
    global corners
    corners = []
    
    if not optimal_lap or len(optimal_lap) < 100:
        ac.console("PitWall: Not enough data for corner detection")
        return
    
    # Sort by position
    sorted_lap = sorted(optimal_lap, key=lambda x: x['norm_pos'])
    
    speeds = [p['speed'] for p in sorted_lap]
    positions = [p['norm_pos'] for p in sorted_lap]
    
    # Smooth speeds
    smooth = []
    window = 8
    for i in range(len(speeds)):
        start = max(0, i - window)
        end = min(len(speeds), i + window + 1)
        smooth.append(sum(speeds[start:end]) / (end - start))
    
    # Find local minima (apex points)
    corner_num = 0
    last_pos = -0.1
    
    for i in range(20, len(smooth) - 20):
        # Is this a local minimum?
        is_min = True
        for j in range(1, 15):
            if smooth[i] > smooth[i - j] or smooth[i] > smooth[i + j]:
                is_min = False
                break
        
        if not is_min:
            continue
        
        # Check for significant speed drop
        nearby_max = max(smooth[max(0, i-40):min(len(smooth), i+40)])
        speed_drop = nearby_max - smooth[i]
        
        if speed_drop < max(18, nearby_max * 0.18):  # Not a real corner
            continue
        
        pos = positions[i]
        
        # Minimum gap between corners
        if pos - last_pos < 0.05:
            continue
        
        corner_num += 1
        last_pos = pos
        
        # Find entry and exit
        entry = pos
        exit_pos = pos
        
        for j in range(i, max(0, i - 60), -1):
            if smooth[j] > smooth[i] + speed_drop * 0.6:
                entry = positions[j]
                break
        
        for j in range(i, min(len(smooth), i + 60)):
            if smooth[j] > smooth[i] + speed_drop * 0.6:
                exit_pos = positions[j]
                break
        
        # Classify
        apex_speed = smooth[i]
        if apex_speed < 70:
            ctype = "Hairpin"
        elif apex_speed < 110:
            ctype = "Slow"
        elif apex_speed < 160:
            ctype = "Medium"
        else:
            ctype = "Fast"
        
        corners.append({
            'id': corner_num,
            'name': "T{0}".format(corner_num),
            'type': ctype,
            'entry': entry,
            'apex': pos,
            'exit': exit_pos,
            'apex_speed': apex_speed,
            'entry_speed': nearby_max,
            'scores': deque(maxlen=10)
        })
    
    ac.console("PitWall: Found {0} corners".format(len(corners)))


def get_corner_at(pos):
    """Get corner at position (if any)"""
    for c in corners:
        # Handle wrap-around
        entry = c['entry']
        exit_p = c['exit']
        
        if entry < exit_p:
            if entry <= pos <= exit_p:
                return c
        else:
            if pos >= entry or pos <= exit_p:
                return c
    return None


def get_next_corner(pos):
    """Get next upcoming corner"""
    best = None
    best_dist = 2.0
    
    for c in corners:
        dist = c['entry'] - pos
        if dist < 0:
            dist += 1.0
        if 0 < dist < best_dist:
            best_dist = dist
            best = c
    
    return best, best_dist


def get_corner_phase(pos, corner):
    """Get phase: approach/entry/apex/exit"""
    if not corner:
        return ""
    
    length = corner['exit'] - corner['entry']
    if length < 0:
        length += 1.0
    
    progress = pos - corner['entry']
    if progress < 0:
        progress += 1.0
    
    pct = progress / length if length > 0 else 0
    
    if pct < 0.2:
        return "ENTRY"
    elif pct < 0.5:
        return "APEX"
    else:
        return "EXIT"


def score_corner(corner, speed):
    """Score current corner performance"""
    if not corner:
        return 5.0
    
    target = corner['apex_speed']
    diff = speed - target
    
    if diff < -20:
        return max(0, 3 + diff / 10)
    elif diff < -10:
        return max(0, 6 + diff / 5)
    elif diff < 10:
        return min(10, 8 + diff / 10)
    else:
        return max(5, 9 - diff / 15)


# ============================================================================
# ANALYSIS FUNCTIONS
# ============================================================================
def get_optimal_speed(pos):
    """Get optimal speed at position"""
    if not optimal_lap:
        return 0
    
    for p in optimal_lap:
        if p['norm_pos'] >= pos:
            return p['speed']
    return optimal_lap[-1]['speed'] if optimal_lap else 0


def get_optimal_time(pos):
    if not optimal_lap:
        return 0.0

    for i in range(len(optimal_lap) - 1):
        a = optimal_lap[i]
        b = optimal_lap[i + 1]
        if a['norm_pos'] <= pos <= b['norm_pos']:
            t = (pos - a['norm_pos']) / (b['norm_pos'] - a['norm_pos'])
            return (a['lap_time'] + t * (b['lap_time'] - a['lap_time'])) / 1000.0

    return optimal_lap[-1]['lap_time'] / 1000.0

def update_tires():
    """Update tire temperatures"""
    global tire_status, tires
    
    try:
        # Try different methods
        try:
            temps = ac.getCarState(0, acsys.CS.CurrentTyresCoreTemp)
            if temps and len(temps) >= 4:
                tires['FL'] = temps[0]
                tires['FR'] = temps[1]
                tires['RL'] = temps[2]
                tires['RR'] = temps[3]
        except:
            try:
                tires['FL'] = ac.getCarState(0, acsys.CS.TyreCoreTemperature, 0)
                tires['FR'] = ac.getCarState(0, acsys.CS.TyreCoreTemperature, 1)
                tires['RL'] = ac.getCarState(0, acsys.CS.TyreCoreTemperature, 2)
                tires['RR'] = ac.getCarState(0, acsys.CS.TyreCoreTemperature, 3)
            except:
                pass
    except:
        pass
    
    all_t = [tires['FL'], tires['FR'], tires['RL'], tires['RR']]
    
    if all(t < 1 for t in all_t):
        tire_status = "N/A"
        return
    
    avg = sum(all_t) / 4
    front = (tires['FL'] + tires['FR']) / 2
    rear = (tires['RL'] + tires['RR']) / 2
    
    if avg < 50:
        tire_status = "COLD!"
    elif avg < 70:
        tire_status = "Warming"
    elif avg > 105:
        tire_status = "HOT!"
    elif front > rear + 10:
        tire_status = "F.Hot"
    elif rear > front + 10:
        tire_status = "R.Hot"
    elif 75 <= avg <= 95:
        tire_status = "Optimal"
    else:
        tire_status = "OK"


def update_advice(telem):
    """Generate contextual advice"""
    global advice_text, advice_cooldown
    
    if advice_cooldown > 0:
        advice_cooldown -= 1
        return
    
    new_advice = ""
    
    # Tire warnings
    if tire_status == "COLD!":
        new_advice = "⚠ Tires cold!"
    elif tire_status == "HOT!":
        new_advice = "🔥 Overheating!"
    elif current_corner:
        # Speed feedback
        opt_speed = get_optimal_speed(telem['norm_pos'])
        diff = telem['speed'] - opt_speed
        if diff < -15:
            new_advice = "{0:.0f} km/h slow".format(abs(diff))
    else:
        # Next corner preview
        next_c, dist = get_next_corner(telem['norm_pos'])
        if next_c and dist < 0.08:
            new_advice = "▶ {0} {1} ({2:.0f})".format(
                next_c['name'], next_c['type'], next_c['apex_speed'])
    
    if new_advice and new_advice != advice_text:
        advice_text = new_advice
        advice_cooldown = 120


# ============================================================================
# MODE SWITCHING
# ============================================================================
def on_mode_click(*args):
    global current_mode
    if current_mode == MODE_LIVE:
        current_mode = MODE_COACH
    else:
        current_mode = MODE_LIVE
    apply_mode()


def on_report_click(*args):
    generate_report()


def apply_mode():
    """Show/hide UI elements based on mode"""
    if current_mode == MODE_LIVE:
        ac.setSize(app_window, 340, 240)
        for key, elem in ui_live.items():
            ac.setVisible(elem, 1)
        for key, elem in ui_coach.items():
            ac.setVisible(elem, 0)
        ac.setText(ui_shared['mode_btn'], "📊 Coach")
    else:
        ac.setSize(app_window, 380, 520)
        for key, elem in ui_live.items():
            ac.setVisible(elem, 0)
        for key, elem in ui_coach.items():
            ac.setVisible(elem, 1)
        ac.setText(ui_shared['mode_btn'], "🏎 Live")


# ============================================================================
# UI CREATION
# ============================================================================
def create_ui():
    """Create all UI elements"""
    
    # === SHARED: Mode button ===
    ui_shared['mode_btn'] = ac.addButton(app_window, "📊 Coach")
    ac.setPosition(ui_shared['mode_btn'], 250, 28)
    ac.setSize(ui_shared['mode_btn'], 80, 24)
    ac.addOnClickedListener(ui_shared['mode_btn'], on_mode_click)
    
    # =========================================
    # LIVE MODE UI
    # =========================================
    
    # Lap time (big)
    ui_live['time'] = ac.addLabel(app_window, "0:00.000")
    ac.setPosition(ui_live['time'], 15, 28)
    ac.setFontSize(ui_live['time'], 26)
    ac.setFontColor(ui_live['time'], 1, 1, 1, 1)
    
    # Delta
    ui_live['delta'] = ac.addLabel(app_window, "")
    ac.setPosition(ui_live['delta'], 15, 58)
    ac.setFontSize(ui_live['delta'], 16)
    
    # PB reference
    ui_live['pb'] = ac.addLabel(app_window, "PB: --:--.---")
    ac.setPosition(ui_live['pb'], 180, 58)
    ac.setFontSize(ui_live['pb'], 11)
    ac.setFontColor(ui_live['pb'], 0.6, 0.6, 0.6, 1)
    
    # Speed
    ui_live['speed_label'] = ac.addLabel(app_window, "SPEED")
    ac.setPosition(ui_live['speed_label'], 15, 85)
    ac.setFontSize(ui_live['speed_label'], 9)
    ac.setFontColor(ui_live['speed_label'], 0.5, 0.5, 0.5, 1)
    
    ui_live['speed'] = ac.addLabel(app_window, "0 km/h")
    ac.setPosition(ui_live['speed'], 15, 97)
    ac.setFontSize(ui_live['speed'], 15)
    ac.setFontColor(ui_live['speed'], 1, 1, 1, 1)
    
    ui_live['speed_diff'] = ac.addLabel(app_window, "")
    ac.setPosition(ui_live['speed_diff'], 110, 99)
    ac.setFontSize(ui_live['speed_diff'], 12)
    
    # Corner info
    ui_live['corner'] = ac.addLabel(app_window, "— Straight —")
    ac.setPosition(ui_live['corner'], 15, 125)
    ac.setFontSize(ui_live['corner'], 14)
    ac.setFontColor(ui_live['corner'], 0.3, 0.85, 1, 1)
    
    ui_live['phase'] = ac.addLabel(app_window, "")
    ac.setPosition(ui_live['phase'], 200, 127)
    ac.setFontSize(ui_live['phase'], 11)
    ac.setFontColor(ui_live['phase'], 0.6, 0.6, 0.6, 1)
    
    ui_live['score'] = ac.addLabel(app_window, "")
    ac.setPosition(ui_live['score'], 15, 145)
    ac.setFontSize(ui_live['score'], 12)
    
    # Pedals
    ui_live['thr_label'] = ac.addLabel(app_window, "THR")
    ac.setPosition(ui_live['thr_label'], 15, 172)
    ac.setFontSize(ui_live['thr_label'], 9)
    ac.setFontColor(ui_live['thr_label'], 0.2, 0.9, 0.3, 1)
    
    ui_live['thr_bar'] = ac.addLabel(app_window, "")
    ac.setPosition(ui_live['thr_bar'], 45, 172)
    ac.setFontSize(ui_live['thr_bar'], 9)
    ac.setFontColor(ui_live['thr_bar'], 0.2, 0.9, 0.3, 1)
    
    ui_live['brk_label'] = ac.addLabel(app_window, "BRK")
    ac.setPosition(ui_live['brk_label'], 175, 172)
    ac.setFontSize(ui_live['brk_label'], 9)
    ac.setFontColor(ui_live['brk_label'], 0.9, 0.2, 0.2, 1)
    
    ui_live['brk_bar'] = ac.addLabel(app_window, "")
    ac.setPosition(ui_live['brk_bar'], 205, 172)
    ac.setFontSize(ui_live['brk_bar'], 9)
    ac.setFontColor(ui_live['brk_bar'], 0.9, 0.2, 0.2, 1)
    
    # Tires
    ui_live['tire_label'] = ac.addLabel(app_window, "TIRES")
    ac.setPosition(ui_live['tire_label'], 15, 192)
    ac.setFontSize(ui_live['tire_label'], 9)
    ac.setFontColor(ui_live['tire_label'], 0.5, 0.5, 0.5, 1)
    
    ui_live['tire_status'] = ac.addLabel(app_window, "---")
    ac.setPosition(ui_live['tire_status'], 55, 190)
    ac.setFontSize(ui_live['tire_status'], 11)
    
    ui_live['tire_temps'] = ac.addLabel(app_window, "")
    ac.setPosition(ui_live['tire_temps'], 120, 192)
    ac.setFontSize(ui_live['tire_temps'], 9)
    ac.setFontColor(ui_live['tire_temps'], 0.5, 0.5, 0.5, 1)
    
    # Advice
    ui_live['advice'] = ac.addLabel(app_window, "")
    ac.setPosition(ui_live['advice'], 15, 215)
    ac.setFontSize(ui_live['advice'], 12)
    ac.setFontColor(ui_live['advice'], 1, 0.85, 0.2, 1)
    
    # =========================================
    # COACH MODE UI
    # =========================================
    
    # Title
    ui_coach['title'] = ac.addLabel(app_window, "📊 COACH DASHBOARD")
    ac.setPosition(ui_coach['title'], 15, 28)
    ac.setFontSize(ui_coach['title'], 15)
    ac.setFontColor(ui_coach['title'], 0.7, 0.4, 1, 1)
    
    # Session stats
    ui_coach['session_label'] = ac.addLabel(app_window, "─── SESSION ───")
    ac.setPosition(ui_coach['session_label'], 15, 58)
    ac.setFontSize(ui_coach['session_label'], 10)
    ac.setFontColor(ui_coach['session_label'], 0.4, 0.4, 0.4, 1)
    
    ui_coach['laps'] = ac.addLabel(app_window, "Laps: 0")
    ac.setPosition(ui_coach['laps'], 15, 78)
    ac.setFontSize(ui_coach['laps'], 12)
    ac.setFontColor(ui_coach['laps'], 0.8, 0.8, 0.8, 1)
    
    ui_coach['best'] = ac.addLabel(app_window, "Best: --:--.---")
    ac.setPosition(ui_coach['best'], 100, 78)
    ac.setFontSize(ui_coach['best'], 12)
    ac.setFontColor(ui_coach['best'], 0.2, 1, 0.4, 1)
    
    ui_coach['avg'] = ac.addLabel(app_window, "Avg: --:--.---")
    ac.setPosition(ui_coach['avg'], 230, 78)
    ac.setFontSize(ui_coach['avg'], 12)
    ac.setFontColor(ui_coach['avg'], 0.8, 0.8, 0.8, 1)
    
    ui_coach['consistency'] = ac.addLabel(app_window, "Consistency: --%")
    ac.setPosition(ui_coach['consistency'], 15, 100)
    ac.setFontSize(ui_coach['consistency'], 12)
    ac.setFontColor(ui_coach['consistency'], 0.8, 0.8, 0.8, 1)
    
    # Corner analysis
    ui_coach['corner_label'] = ac.addLabel(app_window, "─── CORNER ANALYSIS ───")
    ac.setPosition(ui_coach['corner_label'], 15, 128)
    ac.setFontSize(ui_coach['corner_label'], 10)
    ac.setFontColor(ui_coach['corner_label'], 0.4, 0.4, 0.4, 1)
    
    ui_coach['corners'] = []
    for i in range(8):
        lbl = ac.addLabel(app_window, "")
        ac.setPosition(lbl, 15, 150 + i * 20)
        ac.setFontSize(lbl, 11)
        ui_coach['corners'].append(lbl)
    
    # Braking
    ui_coach['brake_label'] = ac.addLabel(app_window, "─── BRAKING ───")
    ac.setPosition(ui_coach['brake_label'], 15, 320)
    ac.setFontSize(ui_coach['brake_label'], 10)
    ac.setFontColor(ui_coach['brake_label'], 0.4, 0.4, 0.4, 1)
    
    ui_coach['brakes'] = []
    for i in range(4):
        lbl = ac.addLabel(app_window, "")
        ac.setPosition(lbl, 15, 342 + i * 18)
        ac.setFontSize(lbl, 11)
        ui_coach['brakes'].append(lbl)
    
    # Improvements
    ui_coach['improve_label'] = ac.addLabel(app_window, "─── IMPROVE ───")
    ac.setPosition(ui_coach['improve_label'], 15, 420)
    ac.setFontSize(ui_coach['improve_label'], 10)
    ac.setFontColor(ui_coach['improve_label'], 0.4, 0.4, 0.4, 1)
    
    ui_coach['improves'] = []
    for i in range(3):
        lbl = ac.addLabel(app_window, "")
        ac.setPosition(lbl, 15, 440 + i * 18)
        ac.setFontSize(lbl, 11)
        ac.setFontColor(lbl, 1, 0.85, 0.2, 1)
        ui_coach['improves'].append(lbl)
    
    # Report button
    ui_coach['report_btn'] = ac.addButton(app_window, "📄 Generate Report")
    ac.setPosition(ui_coach['report_btn'], 15, 495)
    ac.setSize(ui_coach['report_btn'], 130, 26)
    ac.addOnClickedListener(ui_coach['report_btn'], on_report_click)
    
    # Hide coach UI initially
    for key, elem in ui_coach.items():
        if key == 'corners' or key == 'brakes' or key == 'improves':
            for lbl in elem:
                ac.setVisible(lbl, 0)
        else:
            ac.setVisible(elem, 0)


# ============================================================================
# UI UPDATES
# ============================================================================
def update_live_ui(telem):
    """Update live dashboard"""
    global current_corner, corner_score
    
    # Lap time
    lap_ms = telem['lap_time']
    lap_s = lap_ms / 1000.0
    mins = int(lap_s // 60)
    secs = lap_s % 60
    ac.setText(ui_live['time'], "{0}:{1:06.3f}".format(mins, secs))
    
    # Delta
    if best_lap < float('inf'):
        opt_time = get_optimal_time(telem['norm_pos'])
        delta = lap_s - opt_time
        
        if delta <= 0:
            ac.setBackgroundColor(ui_live['delta'], 0, 1, 0, 0.2) 
        else:
            ac.setBackgroundColor(ui_live['delta'], 1, 0, 0, 0.2)
            
        bg_color = [0, 1, 0, 0.2] if delta <= 0 else [1, 0, 0, 0.2]
        ac.setBackgroundColor(ui_live['delta'], bg_color[0], bg_color[1], bg_color[2], bg_color[3])
        # PB display
        pb_m = int(best_lap // 60)
        pb_s = best_lap % 60
        ac.setText(ui_live['pb'], "PB: {0}:{1:05.2f}".format(pb_m, pb_s))
    else:
        ac.setText(ui_live['delta'], "BASELINE")
        ac.setFontColor(ui_live['delta'], 0.3, 0.85, 1, 1)
        ac.setText(ui_live['pb'], "PB: --:--.--")
    # Drop into update_live_ui under the delta section:
    if delta <= 0:
    # Green shift for gaining time
        ac.setBackgroundColor(ui_live['delta'], 0, 1, 0, 0.2) 
    else:
    # Red shift for losing time
        ac.setBackgroundColor(ui_live['delta'], 1, 0, 0, 0.2)
    # Speed
    speed = telem['speed']
    ac.setText(ui_live['speed'], "{0:.0f} km/h".format(speed))
    
    
    
    opt_speed = get_optimal_speed(telem['norm_pos'])
    if opt_speed > 0:
        diff = speed - opt_speed
        if diff > 5:
            ac.setText(ui_live['speed_diff'], "+{0:.0f} ▲".format(diff))
            ac.setFontColor(ui_live['speed_diff'], 0.2, 1, 0.4, 1)
        elif diff < -5:
            ac.setText(ui_live['speed_diff'], "{0:.0f} ▼".format(diff))
            ac.setFontColor(ui_live['speed_diff'], 1, 0.4, 0.2, 1)
        else:
            ac.setText(ui_live['speed_diff'], "≈")
            ac.setFontColor(ui_live['speed_diff'], 0.6, 0.6, 0.6, 1)
    else:
        ac.setText(ui_live['speed_diff'], "")
    
    # Corner
    pos = telem['norm_pos']
    current_corner = get_corner_at(pos)
    
    if current_corner:
        ac.setText(ui_live['corner'], "{0} • {1}".format(
            current_corner['name'], current_corner['type']))
        ac.setFontColor(ui_live['corner'], 0.3, 0.85, 1, 1)
        
        phase = get_corner_phase(pos, current_corner)
        ac.setText(ui_live['phase'], phase)
        
        corner_score = score_corner(current_corner, speed)
        filled = int(corner_score)
        bar = "█" * filled + "░" * (10 - filled)
        ac.setText(ui_live['score'], "{0} {1:.1f}".format(bar, corner_score))
        
        if corner_score >= 7:
            ac.setFontColor(ui_live['score'], 0.2, 1, 0.4, 1)
        elif corner_score >= 4:
            ac.setFontColor(ui_live['score'], 1, 0.85, 0.2, 1)
        else:
            ac.setFontColor(ui_live['score'], 1, 0.4, 0.2, 1)
    else:
        next_c, dist = get_next_corner(pos)
        if next_c and dist < 0.1:
            ac.setText(ui_live['corner'], "▶ {0} • {1}".format(
                next_c['name'], next_c['type']))
            ac.setFontColor(ui_live['corner'], 0.6, 0.6, 0.6, 1)
            ac.setText(ui_live['phase'], "{0:.0f} km/h".format(next_c['apex_speed']))
        else:
            ac.setText(ui_live['corner'], "— Straight —")
            ac.setFontColor(ui_live['corner'], 0.4, 0.4, 0.4, 1)
            ac.setText(ui_live['phase'], "")
        ac.setText(ui_live['score'], "")
    
    # Pedals
    thr = telem['throttle']
    brk = telem['brake']
    ac.setText(ui_live['thr_bar'], "█" * int(thr * 12) + "░" * (12 - int(thr * 12)))
    ac.setText(ui_live['brk_bar'], "█" * int(brk * 12) + "░" * (12 - int(brk * 12)))
    
    # Tires
    ac.setText(ui_live['tire_status'], tire_status)
    if tire_status in ["COLD!", "HOT!"]:
        ac.setFontColor(ui_live['tire_status'], 1, 0.3, 0.2, 1)
    elif tire_status == "Optimal":
        ac.setFontColor(ui_live['tire_status'], 0.2, 1, 0.4, 1)
    else:
        ac.setFontColor(ui_live['tire_status'], 1, 0.85, 0.2, 1)
    
    ac.setText(ui_live['tire_temps'], "{0:.0f} {1:.0f} {2:.0f} {3:.0f}".format(
        tires['FL'], tires['FR'], tires['RL'], tires['RR']))
    
    # Advice
    ac.setText(ui_live['advice'], advice_text)

def record_brake(telem):
    global brake_events, is_braking, brake_start_pos
    pos = telem['norm_pos']
    
    if telem['brake'] > 0.1 and not is_braking:
        is_braking = True
        brake_start_pos = pos
    elif telem['brake'] < 0.05 and is_braking:
        is_braking = False
        corner = get_corner_at(brake_start_pos)
        if corner:
            cid = corner['id']
            if cid not in brake_events: brake_events[cid] = {'points': []}
            
            # Normalize distance relative to corner entry
            dist = pos - corner['entry']
            if dist < 0: dist += 1.0
            brake_events[cid]['points'].append({'distance': dist})

def update_coach_ui():
    """Update coach dashboard"""
    
    # Session stats
    ac.setText(ui_coach['laps'], "Laps: {0}".format(len(lap_times)))
    
    if session_best < float('inf'):
        m = int(session_best // 60)
        s = session_best % 60
        ac.setText(ui_coach['best'], "Best: {0}:{1:05.2f}".format(m, s))
    
    if lap_times:
        avg = sum(lap_times) / len(lap_times)
        m = int(avg // 60)
        s = avg % 60
        ac.setText(ui_coach['avg'], "Avg: {0}:{1:05.2f}".format(m, s))
    
    ac.setText(ui_coach['consistency'], "Consistency: {0:.0f}%".format(consistency))
    
    # Corners
    for i, lbl in enumerate(ui_coach['corners']):
        if i < len(corners):
            c = corners[i]
            if c['scores']:
                avg = sum(c['scores']) / len(c['scores'])
                bar = "█" * int(avg) + "░" * (10 - int(avg))
                ac.setText(lbl, "{0} {1:7} {2} {3:.1f}".format(
                    c['name'], c['type'], bar, avg))
                
                if avg >= 7:
                    ac.setFontColor(lbl, 0.2, 1, 0.4, 1)
                elif avg >= 4:
                    ac.setFontColor(lbl, 1, 0.85, 0.2, 1)
                else:
                    ac.setFontColor(lbl, 1, 0.4, 0.2, 1)
            else:
                ac.setText(lbl, "{0} {1:7} [no data]".format(c['name'], c['type']))
                ac.setFontColor(lbl, 0.5, 0.5, 0.5, 1)
        else:
            ac.setText(lbl, "")
    
    # Braking
    # Braking
    brake_list = list(brake_events.items())[:4]
    for i, lbl in enumerate(ui_coach['brakes']):
        if i < len(brake_list):
            cid, data = brake_list[i]
            points = [p['distance'] for p in data['points']] 
            if len(points) >= 2:
                avg_b = sum(points) / len(points)
                var = sum((p - avg_b)**2 for p in points) / len(points)
                std = math.sqrt(var)
            
            if std < 0.012:
                status = "Excellent"
                ac.setFontColor(lbl, 0.2, 1, 0.4, 1)
            elif std < 0.025:
                status = "Good"
                ac.setFontColor(lbl, 0.8, 0.8, 0.8, 1)
            else:
                status = "Inconsistent"
                ac.setFontColor(lbl, 1, 0.5, 0.2, 1)
            
            ac.setText(lbl, "T{0}: {1} (±{2:.3f})".format(cid, status, std))
        else:
            ac.setText(lbl, "T{0}: Need data".format(cid))
            ac.setFontColor(lbl, 0.5, 0.5, 0.5, 1)
    else:
        ac.setText(lbl, "")
    
    # Improvements
    suggestions = []
    
    # Worst corners
    scored = [(c, sum(c['scores'])/len(c['scores'])) for c in corners if c['scores']]
    scored.sort(key=lambda x: x[1])
    
    for c, score in scored[:2]:
        if score < 6:
            suggestions.append("Focus: {0} ({1:.1f}/10)".format(c['name'], score))
    
    # Braking consistency
    for cid, data in brake_events.items():
        if len(data['points']) >= 3:
            avg = sum(data['points']) / len(data['points'])
            var = sum((p - avg)**2 for p in data['points']) / len(data['points'])
            if math.sqrt(var) > 0.03:
                suggestions.append("Brake marker: T{0}".format(cid))
    
    if not suggestions:
        suggestions.append("Good job! Keep practicing.")
    
    for i, lbl in enumerate(ui_coach['improves']):
        if i < len(suggestions):
            ac.setText(lbl, "→ " + suggestions[i])
        else:
            ac.setText(lbl, "")


# ============================================================================
# REPORT
# ============================================================================
def generate_report():
    if not lap_times:
        ac.console("PitWall: No data")
        return
    
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    fname = "pitwall_{0}_{1}.html".format(current_track.replace(' ', '_'), ts)
    fpath = os.path.join(REPORTS_DIR, fname)
    
    avg = sum(lap_times) / len(lap_times)
    
    corner_html = ""
    for c in corners:
        if c['scores']:
            avg_s = sum(c['scores']) / len(c['scores'])
            corner_html += "<tr><td>{0}</td><td>{1}</td><td>{2:.0f}</td><td>{3:.1f}</td></tr>".format(
                c['name'], c['type'], c['apex_speed'], avg_s)
    
    lap_html = ""
    for i, t in enumerate(lap_times):
        d = t - session_best
        lap_html += "<tr><td>{0}</td><td>{1:.3f}</td><td>{2}</td></tr>".format(
            i+1, t, "PB" if d < 0.001 else "+{0:.2f}".format(d))
    
    html = """<!DOCTYPE html>
<html>
<head>
<title>PitWall Report</title>
<style>
body{{font-family:system-ui;background:#1a1a2e;color:#eee;padding:30px}}
h1{{color:#00d4ff}}h2{{color:#ff6b6b;border-bottom:2px solid #ff6b6b}}
.stats{{display:flex;gap:20px;margin:20px 0}}
.stat{{background:rgba(255,255,255,0.1);padding:15px 25px;border-radius:8px;text-align:center}}
.stat b{{font-size:1.8em;color:#00d4ff;display:block}}
table{{width:100%;border-collapse:collapse;margin:15px 0}}
th,td{{padding:8px 12px;border-bottom:1px solid #333;text-align:left}}
th{{background:rgba(255,255,255,0.1)}}
</style>
</head>
<body>
<h1>🏁 PIT WALL REPORT</h1>
<p>{track} | {car} | {date}</p>
<div class="stats">
<div class="stat"><b>{lap_count}</b>Laps</div>
<div class="stat"><b>{best:.2f}s</b>Best</div>
<div class="stat"><b>{avg:.2f}s</b>Average</div>
<div class="stat"><b>{cons:.0f}%</b>Consistency</div>
</div>
<h2>Corners</h2>
<table><tr><th>Corner</th><th>Type</th><th>Apex</th><th>Score</th></tr>{corner_rows}</table>
<h2>Laps</h2>
<table><tr><th>#</th><th>Time</th><th>Delta</th></tr>{lap_rows}</table>
<p style="color:#666;margin-top:30px">Generated by PitWall v3.1</p>
</body>
</html>""".format(
        track=current_track, car=current_car,
        date=datetime.now().strftime('%Y-%m-%d %H:%M'),
        lap_count=len(lap_times), best=session_best, avg=avg, cons=consistency,
        corner_rows=corner_html, lap_rows=lap_html
    )
    
    try:
        with open(fpath, 'w') as f:
            f.write(html)
        ac.console("PitWall: Report saved")
    except Exception as e:
        ac.console("PitWall: Error - " + str(e))


# ============================================================================
# AC CALLBACKS
# ============================================================================
def acMain(ac_version):
    global app_window, current_track, current_car, profile_id
    
    app_window = ac.newApp("PitWall")
    ac.setSize(app_window, 340, 240)
    ac.setTitle(app_window, "🏁 PIT WALL")
    
    # 1. IDENTIFY TRACK AND CAR (Fixes "Track not identified")
    current_track = ac.getTrackName(0)
    current_car = ac.getCarName(0)
    profile_id = "{0}_{1}".format(current_track, current_car).replace(" ", "_")
    
    # 2. INITIALIZE
    create_ui()
    load_optimal() # Try to load existing PB data
    apply_mode()
    
    ac.console("PitWall: Initialized for {0} on {1}".format(current_car, current_track))
    return "PitWall"


def on_lap_done():
    global session_best, consistency
    
    if len(live_buffer) < 100:
        return
    
    lap_time = ac.getCarState(0, acsys.CS.LastLap) / 1000.0
    
    if lap_time < 20 or lap_time > 600:
        return
    
    lap_data = list(live_buffer)
    lap_times.append(lap_time)
    
    if lap_time < session_best:
        session_best = lap_time
    
    # Consistency
    if len(lap_times) > 1:
        mean = sum(lap_times) / len(lap_times)
        variance = sum((x - mean) ** 2 for x in lap_times) / len(lap_times)
        std_dev = math.sqrt(variance)
        # 0.5s deviation results in ~85% consistency
        consistency = max(0, min(100, 100 - (std_dev * 30))) 
        ac.setText(ui_coach['consistency'], "Consistency: {0:.1f}%".format(consistency))
    
    # Save if PB
    if lap_time < best_lap or optimal_lap is None:
        save_optimal(lap_data, lap_time)
    
    live_buffer.clear()
    ac.console("PitWall: {0:.3f}s".format(lap_time))


def acShutdown():
    ac.console("PitWall: Bye!")

def acUpdate(delta_t):
    global frame, last_lap_count, lap_count, session_best, consistency, lap_times
    
    frame += 1
    # Refresh every 2nd frame to save CPU
    if frame % 2 != 0: return 

    # 3. GATHER LIVE TELEMETRY (Fixes "0 speed")
    try:
        telem = {
            'speed': ac.getCarState(0, acsys.CS.SpeedKMH),
            'norm_pos': ac.getCarState(0, acsys.CS.NormalizedSplinePosition),
            'throttle': ac.getCarState(0, acsys.CS.Gas),
            'brake': ac.getCarState(0, acsys.CS.Brake),
            'lap_time': ac.getCarState(0, acsys.CS.LapTime)
        }
        
        # Run background logic
        update_tires()
        update_advice(telem)
        record_brake(telem)
        
        # 4. PUSH TO UI
        if current_mode == MODE_LIVE:
            update_live_ui(telem)
        elif frame % 30 == 0: # Update coach dashboard once per second
            update_coach_ui()

        # 5. LAP CROSSING LOGIC
        lap_count = ac.getCarState(0, acsys.CS.Laps)
        if lap_count > last_lap_count:
            if last_lap_count != -1:
                # Calculate consistency and save lap
                last_time = ac.getCarState(0, acsys.CS.LastLap) / 1000.0
                if last_time > 10.0: # Filter out resets
                    lap_times.append(last_time)
                    if last_time < session_best: session_best = last_time
                    save_optimal(list(live_buffer), last_time) # This triggers detect_corners()
            
            last_lap_count = lap_count
            live_buffer.clear()
        
        live_buffer.append(telem)
        
    except Exception as e:
        ac.console("PitWall Update Error: " + str(e))