# -*- coding: utf-8 -*-
"""
RotorWeb — pilotes de contrôleurs de rotor.

Chaque pilote parle à un type de contrôleur et expose la même interface :
    open() / close()
    goto(az, el=None)      az = azimut du rotor (0–359, sans le décalage d'antenne)
    manual(axis, d)        axis 'az' | 'el', d = +1 (horaire / haut) ou -1
    stop(axis='all')       'all' | 'az' | 'el'
    poll() -> (az, el)     position actuelle (az peut dépasser 360 en chevauchement)
    tick()                 appelé ~20 fois/s (boucle de régulation des pilotes « bidouille »)
    info() -> dict         valeurs brutes, course, calibration (pour l'interface)

Avec --simulate, chaque pilote parle à un simulateur de SON protocole.
"""
import math
import re
import socket
import struct
import time

# --------------------------------------------------------------------------
# Catalogue (affiché dans l'interface et l'installateur)
# --------------------------------------------------------------------------
DRIVERS = [
    {"key": "gs232b", "label": "Yaesu GS-232B (K3NG, GS-232B, ERC…)", "kind": "serial", "baud": 9600},
    {"key": "gs232a", "label": "Yaesu GS-232A (anciens contrôleurs)", "kind": "serial", "baud": 9600},
    {"key": "easycomm", "label": "Easycomm II (SatNOGS, montages Arduino)", "kind": "serial", "baud": 9600},
    {"key": "rot2prog", "label": "SPID Rot2Prog (MD-01/02/03 en mode Rot2Prog)", "kind": "serial", "baud": 600},
    {"key": "dcu1", "label": "Hy-Gain DCU-1 (DCU-2/3, RT-21, Rotor-EZ…)", "kind": "serial", "baud": 4800},
    {"key": "hamlib", "label": "Hamlib rotctld (une centaine de modèles)", "kind": "tcp", "baud": 0},
    {"key": "arduino", "label": "Bidouille : Arduino RotorWeb (potentiomètre + relais)", "kind": "serial", "baud": 115200},
    {"key": "gpio", "label": "Bidouille : GPIO du Raspberry Pi (relais + ADS1115)", "kind": "gpio", "baud": 0},
]
DRIVER_MAP = {d["key"]: d for d in DRIVERS}
DIY_DRIVERS = ("arduino", "gpio")


class NotCalibrated(Exception):
    pass


def parse_position(text):
    """Réponse GS-232A ou B → (az, el)."""
    for line in reversed(re.split(r"[\r\n]+", text or "")):
        m = re.search(r"AZ\s*=\s*([+-]?\d+)", line, re.I)
        if m:
            e = re.search(r"EL\s*=\s*([+-]?\d+)", line, re.I)
            return int(m.group(1)), (int(e.group(1)) if e else None)
        nums = re.findall(r"[+-]?\d+", line)
        if nums:
            return int(nums[0]), (int(nums[1]) if len(nums) > 1 else None)
    return None


# --------------------------------------------------------------------------
# Simulateurs (option --simulate)
# --------------------------------------------------------------------------
class SimMotor:
    """Rotor physique simulé : course 0..range, vitesse 6°/s, potentiomètre un peu non linéaire."""
    SPEED = 6.0

    def __init__(self, rng=450, stop_at=0):
        self.range, self.stop_at = rng, stop_at
        self.t = 180.0          # position dans la course (degrés depuis la butée gauche)
        self.e = 0.0            # élévation
        self.d_az = self.d_el = 0
        self.target_t = self.target_e = None
        self.last = time.time()

    def update(self):
        now = time.time()
        step = self.SPEED * (now - self.last)
        self.last = now
        if self.target_t is not None:
            err = self.target_t - self.t
            self.t = self.target_t if abs(err) <= step else self.t + math.copysign(step, err)
            if self.t == self.target_t:
                self.target_t = None
        elif self.d_az:
            self.t += self.d_az * step
        self.t = min(self.range, max(0.0, self.t))      # butées mécaniques
        if self.target_e is not None:
            err = self.target_e - self.e
            self.e = self.target_e if abs(err) <= step else self.e + math.copysign(step, err)
            if self.e == self.target_e:
                self.target_e = None
        elif self.d_el:
            self.e = min(180.0, max(0.0, self.e + self.d_el * step))

    # azimut tel qu'un contrôleur le rapporte (0..450 en butée Nord)
    def az(self):
        return self.t if self.stop_at == 0 else (self.stop_at + self.t) % 360

    def goto_az(self, az):
        az %= 360
        t0 = (az - self.stop_at) % 360
        self.target_t, self.d_az = t0, 0

    def raw_az(self):  # potentiomètre 10 bits simulé, légèrement courbé
        x = self.t / self.range
        return int(round(140 + 760 * x + 18 * math.sin(math.pi * x)))

    def raw_el(self):
        return int(round(100 + 800 * self.e / 180))


class SimSerialBase:
    def __init__(self, motor):
        self.m = motor
        self.out = b""
        self.timeout = 0.05
        self.inbuf = b""

    def read(self, n):
        self.m.update()
        if not self.out:
            time.sleep(min(self.timeout, 0.02))
            return b""
        r, self.out = self.out[:n], self.out[n:]
        return r

    def readline(self):
        self.m.update()
        if b"\n" in self.out:
            i = self.out.index(b"\n") + 1
            r, self.out = self.out[:i], self.out[i:]
            return r
        time.sleep(0.01)
        r, self.out = self.out, b""
        return r

    def reset_input_buffer(self):
        self.out = b""

    def close(self):
        pass


class SimGS232(SimSerialBase):
    def write(self, data):
        self.m.update()
        for c in data.decode("ascii", "replace").replace("\n", "\r").split("\r"):
            c = c.strip().upper()
            az, el = int(round(self.m.az())), int(round(self.m.e))
            if c == "C":
                self.out += f"AZ={az:03d}\r\n".encode()
            elif c == "C2":
                self.out += f"AZ={az:03d} EL={el:03d}\r\n".encode()
            elif c == "B":
                self.out += f"EL={el:03d}\r\n".encode()
            elif re.fullmatch(r"M\d{1,3}", c):
                self.m.goto_az(int(c[1:]))
            elif re.fullmatch(r"W\d{1,3} \d{1,3}", c):
                a, e = c[1:].split()
                self.m.goto_az(int(a))
                self.m.target_e, self.m.d_el = float(e), 0
            elif c in ("R", "L"):
                self.m.target_t, self.m.d_az = None, (1 if c == "R" else -1)
            elif c in ("U", "D"):
                self.m.target_e, self.m.d_el = None, (1 if c == "U" else -1)
            elif c in ("S", "A"):
                self.m.target_t, self.m.d_az = None, 0
                if c == "S":
                    self.m.target_e, self.m.d_el = None, 0
            elif c == "E":
                self.m.target_e, self.m.d_el = None, 0
        return len(data)


class SimEasycomm(SimSerialBase):
    def write(self, data):
        self.m.update()
        for c in re.split(r"[\r\n]+", data.decode("ascii", "replace")):
            c = c.strip().upper()
            if not c:
                continue
            if c == "AZ EL":
                self.out += f"AZ{self.m.az() % 360:.1f} EL{self.m.e:.1f}\n".encode()
                continue
            for tok in c.split():
                if re.fullmatch(r"AZ-?\d+(\.\d+)?", tok):
                    self.m.goto_az(float(tok[2:]))
                elif re.fullmatch(r"EL-?\d+(\.\d+)?", tok):
                    self.m.target_e, self.m.d_el = float(tok[2:]), 0
                elif tok in ("ML", "MR"):
                    self.m.target_t, self.m.d_az = None, (1 if tok == "MR" else -1)
                elif tok in ("MU", "MD"):
                    self.m.target_e, self.m.d_el = None, (1 if tok == "MU" else -1)
                elif tok == "SA":
                    self.m.target_t, self.m.d_az = None, 0
                elif tok == "SE":
                    self.m.target_e, self.m.d_el = None, 0
        return len(data)


class SimRot2Prog(SimSerialBase):
    PH = 2

    def write(self, data):
        self.m.update()
        if len(data) != 13 or data[0] != 0x57 or data[12] != 0x20:
            return len(data)
        k = data[11]
        if k == 0x2F:  # SET
            h = int(data[1:5].decode("ascii"))
            v = int(data[6:10].decode("ascii"))
            ph = data[5] or 1
            pv = data[10] or 1
            self.m.goto_az(h / ph - 360)
            self.m.target_e, self.m.d_el = v / pv - 360, 0
            return len(data)
        if k == 0x0F:  # STOP
            self.m.target_t = self.m.target_e = None
            self.m.d_az = self.m.d_el = 0
        az = self.m.az() % 360
        h = int(round((az + 360) * 10))
        v = int(round((self.m.e + 360) * 10))
        hd = [h // 1000, h // 100 % 10, h // 10 % 10, h % 10]
        vd = [v // 1000, v // 100 % 10, v // 10 % 10, v % 10]
        self.out += bytes([0x57] + hd + [self.PH] + vd + [self.PH, 0x20])
        return len(data)


class SimDCU1(SimSerialBase):
    pending = None

    def write(self, data):
        self.m.update()
        self.inbuf += data
        while True:
            m = re.search(rb"AP1(\d{1,3})[;\r]|AM1;|AI1[;\r]|;", self.inbuf)
            if not m:
                break
            tok = m.group(0)
            self.inbuf = self.inbuf[m.end():]
            if tok.startswith(b"AP1"):
                self.pending = int(m.group(1))
            elif tok == b"AM1;":
                if self.pending is not None:
                    self.m.goto_az(self.pending)
            elif tok.startswith(b"AI1"):
                self.out += f";{int(round(self.m.az() % 360)):03d}".encode()
            elif tok == b";":
                self.m.target_t, self.m.d_az = None, 0
        return len(data)


class SimArduinoDIY(SimSerialBase):
    def write(self, data):
        self.m.update()
        for c in data.decode("ascii", "replace").split("\n"):
            c = c.strip().upper()
            if c == "P":
                self.out += f"P {self.m.raw_az()} {self.m.raw_el()}\n".encode()
            elif c in ("AZ+", "AZ-", "AZ0"):
                self.m.target_t, self.m.d_az = None, {"AZ+": 1, "AZ-": -1, "AZ0": 0}[c]
                self.out += b"OK\n"
            elif c in ("EL+", "EL-", "EL0"):
                self.m.target_e, self.m.d_el = None, {"EL+": 1, "EL-": -1, "EL0": 0}[c]
                self.out += b"OK\n"
            elif c == "S":
                self.m.d_az = self.m.d_el = 0
                self.out += b"OK\n"
            elif c == "V":
                self.out += b"RWDIY 1.0\n"
        return len(data)


class SimRotctld:
    """Faux rotctld (protocole texte de Hamlib) côté transport."""

    def __init__(self, motor):
        self.m = motor
        self.out = b""

    def sendall(self, data):
        self.m.update()
        for line in data.decode().splitlines():
            p = line.split()
            if not p:
                continue
            if p[0] in ("p", "\\get_pos"):
                self.out += f"{self.m.az() % 360:.6f}\n{self.m.e:.6f}\n".encode()
            elif p[0] in ("P", "\\set_pos"):
                self.m.goto_az(float(p[1]))
                self.m.target_e = float(p[2])
                self.out += b"RPRT 0\n"
            elif p[0] in ("S", "\\stop"):
                self.m.target_t = self.m.target_e = None
                self.m.d_az = self.m.d_el = 0
                self.out += b"RPRT 0\n"
            elif p[0] in ("M", "\\move"):
                d = int(p[1])
                if d in (8, 16):
                    self.m.target_t, self.m.d_az = None, (1 if d == 16 else -1)
                elif d in (2, 4):
                    self.m.target_e, self.m.d_el = None, (1 if d == 2 else -1)
                self.out += b"RPRT 0\n"

    def recv(self, n):
        self.m.update()
        if not self.out:
            time.sleep(0.02)
            return b""
        r, self.out = self.out[:n], self.out[n:]
        return r

    def settimeout(self, t):
        pass

    def close(self):
        pass


class SimGPIOBackend:
    """Relais + ADS1115 simulés."""

    def __init__(self, motor):
        self.m = motor

    def relay(self, axis, d):
        self.m.update()
        if axis == "az":
            self.m.target_t, self.m.d_az = None, d
        else:
            self.m.target_e, self.m.d_el = None, d

    def read(self):
        self.m.update()
        return self.m.raw_az() * 32, self.m.raw_el() * 32  # échelle ADS1115 (16 bits)

    def close(self):
        pass


# --------------------------------------------------------------------------
# Pilotes
# --------------------------------------------------------------------------
class Driver:
    native_manual = True
    tick_interval = 0.05

    def __init__(self, ctrl, simulate=False, motor=None):
        self.ctrl = ctrl
        self.simulate = simulate
        self.motor = motor
        self.port = None
        self.last_az = None

    @property
    def rc(self):
        return self.ctrl.cfg["rotor"]

    @property
    def elevation(self):
        return bool(self.ctrl.cfg.get("elevation"))

    def serial_port(self):
        return self.rc.get("serial_port") or self.ctrl.cfg.get("serial_port") or "/dev/rotor"

    def baud(self):
        return int(self.rc.get("baud") or DRIVER_MAP[self.key]["baud"] or 9600)

    def log(self, direction, text, poll=False):
        self.ctrl.tlog("k3ng", direction, text, poll=poll)

    def open_serial(self, sim_cls, settle=2.0, **kw):
        if self.simulate:
            self.port = sim_cls(self.motor)
            return
        import serial
        self.port = serial.Serial(self.serial_port(), self.baud(), timeout=0.05, **kw)
        time.sleep(settle)  # certains Arduino redémarrent à l'ouverture du port
        self.port.reset_input_buffer()

    def close(self):
        if self.port:
            try:
                self.port.close()
            except Exception:
                pass

    def tick(self):
        pass

    def info(self):
        return {}

    def calibrate_controller(self, which):
        raise ValueError("Ce contrôleur se calibre sur lui-même (voir son manuel)")

    # Pour les contrôleurs sans commande de rotation manuelle : on vise la butée
    def _manual_by_goto(self, axis, d):
        if axis == "az":
            stop_at = int(self.rc.get("stop_at", 0))
            self.goto((stop_at - 1) % 360 if d > 0 else stop_at % 360, None)


class GS232Driver(Driver):
    def __init__(self, ctrl, simulate=False, motor=None, variant="B"):
        super().__init__(ctrl, simulate, motor)
        self.key = "gs232b" if variant == "B" else "gs232a"

    def open(self):
        self.open_serial(SimGS232)

    def _xfer(self, cmd, want_reply=False, poll=False):
        self.port.write((cmd + "\r").encode("ascii"))
        self.log("tx", cmd, poll)
        buf, deadline = b"", time.time() + (0.7 if want_reply else 0.12)
        while time.time() < deadline:
            chunk = self.port.read(256)
            if chunk:
                buf += chunk
                if want_reply and re.search(rb"\d", buf) and re.search(rb"[\r\n]", buf):
                    break
        text = buf.decode("ascii", "replace").strip()
        if text:
            self.log("rx", text, poll)
        return text

    def goto(self, az, el=None):
        az = int(round(az)) % 360
        if el is not None and self.elevation:
            self._xfer(f"W{az:03d} {int(round(el)):03d}")
        else:
            self._xfer(f"M{az:03d}")

    def manual(self, axis, d):
        self._xfer({("az", 1): "R", ("az", -1): "L", ("el", 1): "U", ("el", -1): "D"}[(axis, d)])

    def stop(self, axis="all"):
        self._xfer({"all": "S", "az": "A", "el": "E"}[axis])

    def poll(self):
        return parse_position(self._xfer("C2" if self.elevation else "C", True, poll=True))

    def calibrate_controller(self, which):
        # Yaesu GS-232 : O = calibration butée gauche, F = pleine échelle (butée droite)
        cmd = {"O": "O", "F": "F", "O2": "O2", "F2": "F2"}[which]
        self._xfer(cmd)


class EasycommDriver(Driver):
    key = "easycomm"

    def open(self):
        self.open_serial(SimEasycomm)

    def _send(self, cmd, poll=False):
        self.port.write((cmd + "\n").encode("ascii"))
        self.log("tx", cmd, poll)

    def goto(self, az, el=None):
        cmd = f"AZ{az % 360:.1f}"
        if el is not None and self.elevation:
            cmd += f" EL{float(el):.1f}"
        self._send(cmd)

    def manual(self, axis, d):
        self._send({("az", 1): "MR", ("az", -1): "ML", ("el", 1): "MU", ("el", -1): "MD"}[(axis, d)])

    def stop(self, axis="all"):
        self._send({"all": "SA SE", "az": "SA", "el": "SE"}[axis])

    def poll(self):
        self._send("AZ EL", poll=True)
        buf, deadline = b"", time.time() + 0.6
        while time.time() < deadline:
            chunk = self.port.read(128)
            if chunk:
                buf += chunk
                if re.search(rb"AZ\s*-?\d", buf, re.I) and re.search(rb"[\r\n]", buf):
                    break
        text = buf.decode("ascii", "replace").strip()
        if text:
            self.log("rx", text, True)
        m = re.search(r"AZ\s*(-?\d+(?:\.\d+)?)", text, re.I)
        if not m:
            return None
        e = re.search(r"EL\s*(-?\d+(?:\.\d+)?)", text, re.I)
        return round(float(m.group(1))), (round(float(e.group(1))) if e else None)


class Rot2ProgDriver(Driver):
    key = "rot2prog"
    native_manual = False

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.ph = self.pv = 0
        self.last_el = 0.0

    def open(self):
        self.open_serial(SimRot2Prog, settle=0.3)

    def _frame(self, k, az=0.0, el=0.0):
        ph = self.ph or int(self.rc.get("rot2prog_ph") or 2)
        pv = self.pv or ph
        h = int(round(ph * (360 + az)))
        v = int(round(pv * (360 + el)))
        return b"W" + f"{h:04d}".encode() + bytes([ph]) + f"{v:04d}".encode() + bytes([pv, k, 0x20])

    def _xfer(self, frame, want=True, poll=False):
        self.port.write(frame)
        self.log("tx", frame.hex(" "), poll)
        if not want:
            return None
        buf, deadline = b"", time.time() + 0.8
        while time.time() < deadline and len(buf) < 12:
            buf += self.port.read(12 - len(buf))
        if buf:
            self.log("rx", buf.hex(" "), poll)
        if len(buf) == 12 and buf[0] == 0x57 and buf[11] == 0x20:
            h1, h2, h3, h4, ph, v1, v2, v3, v4, pv = buf[1:11]
            self.ph, self.pv = ph or self.ph, pv or self.pv
            az = h1 * 100 + h2 * 10 + h3 + h4 / 10 - 360
            el = v1 * 100 + v2 * 10 + v3 + v4 / 10 - 360
            self.last_el = el
            return round(az), round(el)
        return None

    def goto(self, az, el=None):
        if el is None or not self.elevation:
            el = self.last_el or 0.0
        self._xfer(self._frame(0x2F, az % 360, float(el)), want=False)

    def manual(self, axis, d):
        self._manual_by_goto(axis, d)

    def stop(self, axis="all"):
        self._xfer(self._frame(0x0F))

    def poll(self):
        return self._xfer(self._frame(0x1F), poll=True)


class DCU1Driver(Driver):
    key = "dcu1"
    native_manual = False

    def open(self):
        self.open_serial(SimDCU1, settle=0.3)

    def _send(self, cmd, poll=False):
        self.port.write(cmd.encode("ascii"))
        self.log("tx", cmd, poll)

    def goto(self, az, el=None):
        self._send(f"AP1{int(round(az)) % 360:03d};")
        time.sleep(0.05)
        self._send("AM1;")

    def manual(self, axis, d):
        self._manual_by_goto(axis, d)

    def stop(self, axis="all"):
        self._send(";")

    def poll(self):
        self._send("AI1;", poll=True)
        buf, deadline = b"", time.time() + 0.6
        while time.time() < deadline:
            chunk = self.port.read(32)
            if chunk:
                buf += chunk
                if re.search(rb";\s*\d{3}", buf):
                    break
        text = buf.decode("ascii", "replace").strip()
        if text:
            self.log("rx", text, True)
        m = re.search(r";\s*(\d{1,3})", text)
        return (int(m.group(1)), None) if m else None


class HamlibDriver(Driver):
    """Client d'un rotctld (Hamlib) qui tourne à part : rotctld -m MODÈLE -r PORT -t 4534."""
    key = "hamlib"

    def open(self):
        if self.simulate:
            self.port = SimRotctld(self.motor)
            return
        host = self.rc.get("tcp_host") or "127.0.0.1"
        port = int(self.rc.get("tcp_port") or 4534)
        self.port = socket.create_connection((host, port), timeout=3)
        self.port.settimeout(1.0)

    def _cmd(self, cmd, lines=1, poll=False):
        self.port.sendall((cmd + "\n").encode())
        self.log("tx", cmd, poll)
        buf, deadline = b"", time.time() + 1.5
        while time.time() < deadline and buf.count(b"\n") < lines:
            try:
                chunk = self.port.recv(256)
            except socket.timeout:
                break
            if chunk == b"" and not self.simulate:
                raise ConnectionError("rotctld a fermé la connexion")
            buf += chunk
        text = buf.decode(errors="replace").strip()
        if text:
            self.log("rx", text.replace("\n", " | "), poll)
        return text

    def goto(self, az, el=None):
        self._cmd(f"P {az % 360:.1f} {float(el or 0) if self.elevation else 0.0:.1f}")

    def manual(self, axis, d):
        code = {("az", 1): 16, ("az", -1): 8, ("el", 1): 2, ("el", -1): 4}[(axis, d)]
        self._cmd(f"M {code} 50")

    def stop(self, axis="all"):
        self._cmd("S")

    def poll(self):
        t = self._cmd("p", 2, poll=True)
        nums = re.findall(r"-?\d+(?:\.\d+)?", t)
        if len(nums) >= 1 and "RPRT" not in t:
            return round(float(nums[0])), (round(float(nums[1])) if len(nums) > 1 else None)
        return None


# --------------------------------------------------------------------------
# Pilotes « bidouille » : régulation faite par RotorWeb
# --------------------------------------------------------------------------
def interpolate(points, raw):
    """Calibration multi-points : [[brut, degrés], ...] → degrés (linéaire par morceaux)."""
    pts = sorted({int(p[0]): float(p[1]) for p in points}.items())
    if len(pts) < 2:
        raise NotCalibrated()
    for i in range(len(pts) - 1):
        (r0, d0), (r1, d1) = pts[i], pts[i + 1]
        if raw <= r1 or i == len(pts) - 2:
            if r1 == r0:
                return d0
            return d0 + (raw - r0) * (d1 - d0) / (r1 - r0)
    return pts[-1][1]


class Axis:
    def __init__(self, name):
        self.name = name
        self.cur = 0            # sens actuel des relais (-1, 0, +1)
        self.want = 0           # sens demandé
        self.target = None      # cible (degrés de course)
        self.switch_t = 0.0
        self.pos = None
        self.raw = None


class DIYDriver(Driver):
    """Base commune Arduino / GPIO : lit le brut, applique la calibration, pilote les relais."""
    tick_interval = 0.05

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.ax = {"az": Axis("az"), "el": Axis("el")}

    # --- à fournir par les sous-classes
    def _relay(self, axis, d):
        raise NotImplementedError

    def _read_raw(self):
        raise NotImplementedError

    # --- calibration
    def calibrated(self, axis="az"):
        pts = self.rc.get("cal_az" if axis == "az" else "cal_el") or []
        return len({int(p[0]) for p in pts}) >= 2

    def _deg(self, axis, raw):
        return interpolate(self.rc.get("cal_az" if axis == "az" else "cal_el") or [], raw)

    def _limits(self, axis):
        if axis == "az":
            return 0.0, float(self.rc.get("range", 450))
        return 0.0, float(self.rc.get("el_range", 180))

    def travel_to_az(self, t):
        stop_at = float(self.rc.get("stop_at", 0))
        base = (stop_at + t) % 360
        return base + (360 if t >= 360 else 0)

    def plan_travel(self, az):
        """Azimut du rotor → position de course, selon le chemin choisi."""
        stop_at = float(self.rc.get("stop_at", 0))
        lo, hi = self._limits("az")
        t0 = (az - stop_at) % 360
        cands = [t for t in (t0, t0 + 360) if lo <= t <= hi]
        if not cands:
            cands = [min(max(t0, lo), hi)]
        cur = self.ax["az"].pos
        if self.rc.get("path") == "avoid_overlap" or cur is None:
            return cands[0]
        return min(cands, key=lambda t: abs(t - cur))

    # --- interface pilote
    def goto(self, az, el=None):
        if not self.calibrated("az"):
            raise NotCalibrated()
        a = self.ax["az"]
        a.target, a.want = self.plan_travel(az), 0
        if el is not None and self.elevation:
            if not self.calibrated("el"):
                raise NotCalibrated()
            e = self.ax["el"]
            lo, hi = self._limits("el")
            e.target, e.want = min(max(float(el), lo), hi), 0

    def manual(self, axis, d):
        a = self.ax[axis]
        a.target, a.want = None, d

    def stop(self, axis="all"):
        for name in (("az", "el") if axis == "all" else (axis,)):
            a = self.ax[name]
            a.target, a.want = None, 0
            self._drive(a, 0, force=True)

    def _drive(self, a, d, force=False):
        now = time.time()
        if force:
            self._relay(a.name, 0)
            if a.cur != 0:
                a.switch_t = now
            a.cur = 0
            return
        if d == a.cur:
            return
        if a.cur != 0:                       # toujours couper avant de changer de sens
            self._relay(a.name, 0)
            a.cur, a.switch_t = 0, now
            if d == 0:
                return
        deadtime = float(self.rc.get("deadtime", 0.5))
        if now - a.switch_t >= deadtime:     # temps mort : protège le moteur et les relais
            self._relay(a.name, d)
            a.cur = d

    def tick(self):
        raw = self._read_raw()
        if raw is None:
            return
        for name, r in zip(("az", "el"), raw):
            a = self.ax[name]
            a.raw = r
            if name == "el" and not self.elevation:
                continue
            a.pos = self._deg(name, r) if (r is not None and self.calibrated(name)) else None
            lo, hi = self._limits(name)
            d = 0
            if a.want:
                d = a.want
                if a.pos is not None and ((d > 0 and a.pos >= hi - 0.5) or (d < 0 and a.pos <= lo + 0.5)):
                    d, a.want = 0, 0           # limite logicielle de course
                    self.ctrl.tlog("system", "info", f"Limite de course atteinte ({name})", blocked=True)
            elif a.target is not None and a.pos is not None:
                err = a.target - a.pos
                antic = float(self.rc.get("anticipation", 2))
                if abs(err) <= antic:
                    a.target = None           # arrêt anticipé (inertie du rotor)
                else:
                    d = 1 if err > 0 else -1
            self._drive(a, d)

    def poll(self):
        a, e = self.ax["az"], self.ax["el"]
        if a.pos is None:
            return None
        return round(self.travel_to_az(a.pos)), (round(e.pos) if e.pos is not None else None)

    def info(self):
        a, e = self.ax["az"], self.ax["el"]
        return {"raw_az": a.raw, "raw_el": e.raw if self.elevation else None,
                "travel": None if a.pos is None else round(a.pos, 1),
                "calibrated": self.calibrated("az"),
                "calibrated_el": self.calibrated("el") if self.elevation else True,
                "relay_az": a.cur, "relay_el": e.cur}

    def close(self):
        try:
            self._relay("az", 0)
            self._relay("el", 0)
        except Exception:
            pass
        super().close()


class ArduinoDIYDriver(DIYDriver):
    key = "arduino"

    def open(self):
        self.open_serial(SimArduinoDIY, settle=2.0)
        self.port.write(b"V\n")
        time.sleep(0.2)
        v = self.port.read(64).decode(errors="replace").strip()
        if "RWDIY" not in v:
            self.ctrl.tlog("system", "info", f"Croquis RotorWeb DIY non détecté (réponse : {v or 'aucune'})", blocked=True)
        else:
            self.log("rx", v)

    def _relay(self, axis, d):
        cmd = ("AZ" if axis == "az" else "EL") + {1: "+", -1: "-", 0: "0"}[d]
        self.port.write((cmd + "\n").encode())
        self.log("tx", cmd)

    def _read_raw(self):
        # La demande de position sert aussi de « battement de cœur » : sans elle, l'Arduino coupe tout après 2 s
        self.port.write(b"P\n")
        buf, deadline = b"", time.time() + 0.3
        while time.time() < deadline:
            chunk = self.port.read(64)
            if chunk:
                buf += chunk
                m = re.search(rb"P (\d+) (\d+)\r?\n", buf)
                if m:
                    return int(m.group(1)), int(m.group(2))
        return None


class ADS1115:
    """Lecture directe d'un ADS1115 sur le bus I2C (sans bibliothèque lourde)."""
    def __init__(self, address=0x48, bus=1):
        from smbus2 import SMBus
        self.bus = SMBus(bus)
        self.addr = address

    def read(self, ch):
        mux = 0x4 + ch                       # entrée simple AINx contre GND
        # OS=1, MUX, PGA=±4,096 V, mode un coup, 860 éch./s, comparateur désactivé
        cfg = (1 << 15) | (mux << 12) | (0b001 << 9) | (1 << 8) | (0b111 << 5) | 0b11
        self.bus.write_i2c_block_data(self.addr, 0x01, [cfg >> 8, cfg & 0xFF])
        time.sleep(0.002)
        hi, lo = self.bus.read_i2c_block_data(self.addr, 0x00, 2)
        v = struct.unpack(">h", bytes([hi, lo]))[0]
        return max(0, v)

    def close(self):
        self.bus.close()


class GPIODIYDriver(DIYDriver):
    key = "gpio"

    def open(self):
        g = self.rc.get("gpio") or {}
        if self.simulate:
            self.backend = SimGPIOBackend(self.motor)
            return
        from gpiozero import OutputDevice
        active_high = not bool(g.get("active_low", True))
        self.pins = {
            ("az", 1): OutputDevice(int(g.get("cw", 17)), active_high=active_high, initial_value=False),
            ("az", -1): OutputDevice(int(g.get("ccw", 27)), active_high=active_high, initial_value=False),
        }
        if self.elevation:
            self.pins[("el", 1)] = OutputDevice(int(g.get("up", 22)), active_high=active_high, initial_value=False)
            self.pins[("el", -1)] = OutputDevice(int(g.get("down", 23)), active_high=active_high, initial_value=False)
        self.ads = ADS1115(int(g.get("ads_address", 0x48)))
        self.backend = None

    def _relay(self, axis, d):
        self.log("tx", f"relais {axis} {'+' if d > 0 else ('-' if d < 0 else '0')}")
        if self.backend:
            self.backend.relay(axis, d)
            return
        for sgn in (1, -1):
            dev = self.pins.get((axis, sgn))
            if dev:
                (dev.on if d == sgn else dev.off)()

    def _read_raw(self):
        if self.backend:
            return self.backend.read()
        g = self.rc.get("gpio") or {}
        az = self.ads.read(int(g.get("ads_ch_az", 0)))
        el = self.ads.read(int(g.get("ads_ch_el", 1))) if self.elevation else None
        return az, el

    def close(self):
        super().close()
        if getattr(self, "backend", None) is None:
            for dev in getattr(self, "pins", {}).values():
                try:
                    dev.off()
                    dev.close()
                except Exception:
                    pass
            try:
                self.ads.close()
            except Exception:
                pass


def make_driver(ctrl, simulate=False):
    rc = ctrl.cfg["rotor"]
    key = rc.get("driver", "gs232b")
    motor = SimMotor(int(rc.get("range", 450)), int(rc.get("stop_at", 0))) if simulate else None
    if key == "gs232b":
        return GS232Driver(ctrl, simulate, motor, "B")
    if key == "gs232a":
        return GS232Driver(ctrl, simulate, motor, "A")
    cls = {"easycomm": EasycommDriver, "rot2prog": Rot2ProgDriver, "dcu1": DCU1Driver,
           "hamlib": HamlibDriver, "arduino": ArduinoDIYDriver, "gpio": GPIODIYDriver}.get(key)
    if not cls:
        raise ValueError(f"Pilote inconnu : {key}")
    return cls(ctrl, simulate, motor)
