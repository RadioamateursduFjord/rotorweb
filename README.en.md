![RotorWeb — Web-based amateur radio antenna control](logo/banniere-github-1280x640.jpg)

# RotorWeb v2.1 — Installation and user guide

Web control of an antenna rotor on a Raspberry Pi: K3NG / Yaesu GS-232, Easycomm, SPID Rot2Prog, Hy-Gain DCU-1, Hamlib, or a home build (Arduino, GPIO).

> 📘 This guide is also a PDF: **GUIDE-RotorWeb-v2.1-EN.pdf** (en français : **GUIDE-RotorWeb-v2.1-FR.pdf**).
> 🔄 Updating from an older version: **UPDATE-RotorWeb-v2.1-EN.pdf** and **CHANGELOG.md**.

```
 PC (PowerSDR, WSJT-X, GridTracker, Gpredict…)              Phone / PC
        │  virtual COM (TCP 4001) · rotctld (4533) · WSJT-X UDP    │ browser or app
        └──────────────────────────┬───────────────────────────────┘
                 Raspberry Pi — RotorWeb (sole owner of the serial port)
                                   │ USB
                         Controller (K3NG…) ──► Rotor
```

## 1. What's new
**v2.1**
- **New visual identity**: “Azimuth” logo (app icon, favicon, login page, menu, Home Assistant card), redrawn menu icons, PDF guide covers.

**v2.0**
- **Online updates** from the page: “A new version is available — Update”, signature checked, automatic return on trouble.
- **Encrypted backup** of every setting, downloadable, and **restore** (page, reinstallation, terminal).

**v1.7**
- **Modular dashboard**, customizable per user, separately for the computer and the phone.
- **Point to a callsign or a city** (HamQTH, QRZ, prefix, Open-Meteo), on top of the grid.
- **Satellite passes**: every satellite usable in your bands, with frequencies (SatNOGS), sheet and link to the group page, alerts.
- **Change the controller** after installation (automatic detection), **rotor profiles**.
- **Shut down / reboot the Raspberry Pi** from the page.
- **French or English**, chosen by each user.
- The **Automatic mode (WSJT-X) is removed**; the “Last WSJT-X DX” module remains, with a Point button.

Details: `CHANGELOG.md`.

## 2. Installation
1. Copy the `rotorweb-v2.1` folder to the Raspberry Pi (USB stick, `scp`…). Raspberry Pi OS Bookworm or newer recommended.
2. Plug the rotor controller into USB.
3. Run:
   ```bash
   cd rotorweb-v2.1
   sudo ./install.sh
   ```
4. Choose the **language** (Français / English). **Reinstalling?** Give the path of your `.rwbackup` backup and its password: everything is restored and already-set questions are skipped. Otherwise choose the controller: **d) Detect automatically** (default) or a model from the list, or **s) Simulation** if you don't have the hardware yet.
5. Answer the questions: callsign, station grid, time zone, web page port (**80** = address without a number), elevation, first login account.
6. Open the address shown at the end, e.g. `http://192.168.1.50:8080`.

The script gives the controller the fixed name `/dev/rotor`, creates the service that starts at boot and enables the Pi power buttons.

**Already installed?** Don't use `install.sh`: since v2.0, updates are done in the page (section 14). To go from v1.6 or v1.7 to v2.1: `sudo ./update.sh` one last time by hand (see the update guide).

## 3. Accounts and language
```bash
sudo /opt/rotorweb/users.sh list            # list accounts
sudo /opt/rotorweb/users.sh add julie       # add an account
sudo /opt/rotorweb/users.sh passwd julie    # change a password
sudo /opt/rotorweb/users.sh del julie       # delete an account
```
- A session stays open 30 days; 5 failed attempts lock for 2 minutes.
- **Interface language**: Settings ▸ **Account** → Français or English. Each user has their own. The login page has an English / Français link.
- **Station language** (emails, Home Assistant entity names): Settings ▸ **Station**.

## 4. The Operation page (dashboard)
Always shown: the **mode selector**, the **compass** (click to point, Go, hold Left/Right, STOP, Rest) and the red **EMERGENCY STOP** button at the top of every page (or the Esc key).

**✎ Customize** picks the other modules, their order (↑ ↓) and size (full, half, third width). The layout is kept **for your account and for the device type**: one for the computer, another one for the phone (e.g. only the compass and the traffic on the phone). “Default” brings back the original layout.

| Module | Content |
|---|---|
| Control | **Operating** switch and summary (mode, time slot, wind, tracking, DX) |
| Point to… | Grid, callsign or city → short and long path bearing, distance, history |
| Presets | Named positions |
| Last WSJT-X DX | Call, grid, bearing of the station selected in WSJT-X, **Point** button |
| Next passes | The next 6 satellite passes in your bands, Track button |
| Traffic | Three versions: **last line**, **compact** (5 to 10 lines), **full** (scrolling) |
| Wind | Wind, gusts, direction, lock status |
| Current schedule | Running or next time slot |
| Controller | Connection, model, profile, port |
| Raspberry Pi | Restart RotorWeb, reboot or shut down the Pi |

On the phone: bottom bar (Operation, Schedules, Traffic, Menu), azimuth and emergency stop always visible.

**Install as an app**: iPhone → Share ⬆ → “Add to Home Screen”. Android → menu ⋮ → “Add to Home screen”; for a real full-screen app, Chrome requires HTTPS (e.g. Tailscale: `sudo tailscale cert NAME.ts.net`, then `https_cert` and `https_key` in `config.json`).

## 5. Point to a grid, a callsign or a city
Type in the **Point to…** box then Enter (or 🔎):
- **Grid** (FN46, JN18du): immediate, no Internet needed.
- **Callsign** (VE2XYZ, JA1ABC, F4ABC/P, VE2/F4ABC): station location from **HamQTH** or **QRZ.com** if an account is set, otherwise the **prefix** gives the country (approximate for large countries).
- **City** (Tokyo, Lima, Rimouski): **Open-Meteo** geocoding; if several cities share the name, tap the right one in the list.

Then **Point short** or **Point long**. The grid of the result goes into the history.

**Settings ▸ Callsign lookup**: source (HamQTH then QRZ, QRZ then HamQTH, one only, or prefix only) and credentials. HamQTH is free (account on hamqth.com); QRZ.com needs an XML subscription for locations.

## 6. Modes
| Mode | Who moves the rotor |
|---|---|
| ✋ Manual | You (page, presets, grid), the PC (virtual COM, rotctld), Home Assistant |
| 🕒 Schedule | The programmed time slots (+ manual commands) |
| 🛰 Tracking | The chosen target, planned passes and automatic tracking (+ manual commands) |

A **manual command** in Schedule or Tracking mode **switches back to Manual**. The **emergency stop**, “**Operating**” and the **wind lock** always have priority.

WSJT-X no longer turns the rotor by itself (v1.7): the **Last WSJT-X DX** module shows the selected station and the **Point** button turns the antenna when you need it.

## 7. Satellite passes
**Satellite passes** page (☰ menu):
- **My bands**: tick the station bands (10 m, 6 m, 2 m, 70 cm, 23 cm, 13 cm, 9 cm, 5 cm, 3 cm). Only satellites with an active amateur transmitter in these bands are listed.
- **12, 24 or 48 hours**, **minimum elevation**, **Uplink also in my bands** (to make contacts, not only listen), **hide passes through a no-go zone**.
- For each pass: day, rise, satellite, max elevation, set, duration, azimuths, **frequencies** (↓ downlink, ↑ uplink, mode, CTCSS tone, “inverted” for linear transponders), **Track** and **Schedule** buttons.
- Tap the **satellite name**: sheet with all its transmitters, links to the **group web page** and the **SatNOGS page** (new tab).
- **Alerts before a good pass**: minutes before rise, minimum max elevation, by email and/or Home Assistant.

Data: **CelesTrak** orbits and **SatNOGS** frequencies, downloaded once a day (“Update the frequencies and orbits” button). The Raspberry Pi needs Internet. Always check a frequency before transmitting.

## 8. Tracking a target (Moon, Sun, ISS, satellite)
**Tracking (target)** page and **🛰 Tracking** mode: live position, sky map, passes, “Track now”, planning, automatic tracking above an elevation, satellites added by hand (3 TLE lines). Options: movement threshold, pre-positioning, flip (0–180° elevation), rest after the pass, notifications. Also works with an azimuth-only rotor.

## 9. Schedules
**Schedules** page → **+ Add a time slot**: start, end, days, direction (region/country, grid, fixed azimuth or Tracking). Local time (time zone in Settings ▸ Station). At the end of a time slot, the antenna goes to **rest** (fixed azimuth or in line with the wind). A time slot that cannot start sends an alert and points as soon as possible.

## 10. Gmail emails
1. On the sending Gmail account, enable **2-step verification**.
2. Create an **app password** on myaccount.google.com/apppasswords (16 letters).
3. Settings ▸ **Emails**: address, app password, recipient → **Send a test**.

Emails: antenna arrived / not arrived, impossible time slot, wind lock on / off / overridden, stalled rotor, tracking start and end, pass alerts. They are written in the **station language**.

## 11. Wind protection
Wind and gusts read every 5 minutes from Open-Meteo (or an anemometer through Home Assistant). Above the limits: rest and lock of every movement; unlocked after the chosen calm period. **Override the lock** for 15/30/60 minutes for manual commands. Open-Meteo is an estimate, not a measurement on your roof: keep safe limits.

## 12. Controller, travel and calibration
### Change or re-detect the controller (v1.7)
**Settings ▸ Controller → Change / re-detect the controller**:
1. Plug the new controller into USB, tap **Search the USB ports**, pick the port.
2. **Detect the model**: RotorWeb tries the common protocols and speeds (GS-232, Easycomm, RotorWeb Arduino, DCU-1, Rot2Prog). It **only sends position queries**, never movement. “All speeds” also tries rare speeds (slower).
3. Check the model, speed and elevation; choose to **keep the travel and calibration or not**.
4. **Use this controller** → reconnection, then **test**: position read and a small movement with Left/Right.

The old configuration is kept in the **↩ Previous** profile (load it to go back) and in a `config.json.bak-…` file.

**In a terminal** (if the page does not answer): `sudo /opt/rotorweb/detect.sh` — same wizard, in French or English.

**Rotor profiles**: save the current configuration under a name (e.g. “HF rotor”), and switch profiles in one click. A profile keeps the controller, travel, calibration and elevation.

### Models
| Driver | For | Default speed |
|---|---|---|
| Yaesu GS-232B | K3NG, Yaesu GS-232B, ERC and compatibles | 9600 |
| Yaesu GS-232A | Older GS-232A controllers | 9600 |
| Easycomm II | SatNOGS, Arduino builds | 9600 |
| SPID Rot2Prog | MD-01/02/03 in Rot2Prog mode | 600 |
| Hy-Gain DCU-1 | DCU-1/2/3, RT-21, Rotor-EZ | 4800 |
| Hamlib rotctld | About a hundred models | — |
| DIY Arduino | `firmware/rotorweb_diy` sketch: potentiometer + relays | 115200 |
| DIY GPIO | Relays on the Pi GPIO + ADS1115 | — |

**Travel** (North or South stop, 360/450/540°, path), **no-go zones**, **antenna offset**, **calibration** (wizard for DIY builds, O/F commands for GS-232), **stall detection**: Settings ▸ Rotor travel and Calibration. DIY wiring: `firmware/CABLAGE.md`.

## 13. System: shut down or reboot the Raspberry Pi
Settings ▸ **System** (or the Raspberry Pi module): **Restart RotorWeb**, **Reboot the Raspberry Pi**, **Shut down the Raspberry Pi**, with confirmation. Every user can use them. **Rest before shutdown** option: if the station is operating, the antenna goes to rest first.
After “Shut down”, wait until the green LED stops blinking before cutting the power; to turn it back on, unplug and plug the power back in.

## 14. Online updates (v2.0)
RotorWeb checks **once a day** for a new version on GitHub (`RadioamateursduFjord/rotorweb`). When there is one:
- a banner shows at the top of the page: **“New version available: v2.1 — See what's new / Update”**;
- an **email** is sent (if emails are set up) and Home Assistant shows the update (“RotorWeb update” entity, also installable from HA).

**Settings ▸ System ▸ Updates**: installed version, latest version, what's new, **🔄 Check for updates** and **⬆ Update**. Every user can start the update; it always asks for confirmation and **never runs by itself**.

During the update (1 to 3 minutes):
1. download of the new version;
2. **signature check**: a modified or damaged version is refused, nothing is installed;
3. the antenna goes to rest (if operating), the rotor stops;
4. installation by `update.sh` (backup of the old version) and restart;
5. the page reloads by itself on the new version.

If the new version **does not start**, the Raspberry Pi **automatically** goes back to the old one and says so in the page and by email. Detailed log: `/var/log/rotorweb-update.log`.

The Raspberry Pi must reach github.com. Without Internet nothing breaks: the manual update with `sudo ./update.sh` always works. “Update source” lets you use another repository or a mirror.

## 15. Backup and restore (v2.0)
**Settings ▸ System ▸ Settings backup**: choose a password (twice) → **💾 Download the backup**. The `rotorweb-CALLSIGN-date.rwbackup` file holds **everything**: settings, controller, calibration, travel, profiles, schedules, presets, wind, emails, Home Assistant, callsign lookup, satellites, accounts, languages and layouts. It is **encrypted** (AES-256): without the password it cannot be read or restored. Backups are manual: make one after every big change and keep it off the Pi.

**Restore** (replaces every current setting; a copy of the current ones is kept on the Pi):
- **in the page**: Restore a backup → file + password → **Open the backup** (content preview) → **Replace the current settings** → RotorWeb restarts;
- **when reinstalling** (new SD card, new Pi): `sudo ./install.sh` asks for the file at the start;
- **in a terminal**: `sudo /opt/rotorweb/restore.sh file.rwbackup` (and `sudo /opt/rotorweb/restore.sh --create file.rwbackup` to create one).

Not included: HTTPS certificates and the Raspberry Pi's own settings (network, Wi-Fi). Open a backup by hand: `openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in file.rwbackup | gunzip`.

## 16. Publishing a new version (publisher)
On the VPS (gh logged in, key `~/.rotorweb-release/rotorweb-signing.key`):
```bash
unzip rotorweb-vX.Y.zip && cd rotorweb-vX.Y
./tools/release.sh --dry-run     # trial: package + signature, nothing published
./tools/release.sh               # publishes on GitHub (key passphrase asked)
```
The script checks the version number and the CHANGELOG, builds the zip, `release.json` and its signature, pushes the code to `main` and creates the vX.Y “Release”. Stations see it within 24 h.

The `logo/` folder (logo sources, 300 dpi covers, banner) goes into the GitHub repository but **not** into the stations' zip. The repository preview image is uploaded by hand, once: GitHub ▸ repository ▸ **Settings** ▸ **Social preview** ▸ `logo/banniere-github-1280x640.jpg`. To regenerate the icons: `python3 tools/make_logo.py --font space-grotesk-700.woff`.

## 17. Home Assistant
See `homeassistant/LISEZMOI-HA.md`. Settings ▸ **Home Assistant**: MQTT broker, user, password. The RotorWeb device appears with 26 entities (27 with elevation), including in v1.7 **Next good satellite pass**, **Time of the next good pass** and the `passage_sat` event. Compass card: copy `rotorweb-compass-card.js` to `/config/www/` (`passes: 4` option for the pass list); it shows French or English following the HA language.

## 18. PC setup
- **Virtual COM port**: HW VSP3 (or com0com + com2tcp) → Pi IP, port **4001**; in the software: Yaesu GS-232B, 9600 baud.
- **rotctld** (Gpredict, Log4OM, PstRotator): “Hamlib NET rotctl”, `Pi_IP:4533`.
- **WSJT-X** (Last DX module): Settings → Reporting → UDP Server **224.0.0.1**, port **2237**, network interface ticked, TTL 1. GridTracker: same multicast address.

## 19. Files and commands
| Location | Role |
|---|---|
| `/opt/rotorweb/config.json` | Settings (ports, grid, controller, profiles, accounts…) |
| `/opt/rotorweb/state.json` | Presets, schedules, user layouts and languages |
| `/opt/rotorweb/tle.txt`, `satnogs.json` | Downloaded orbits and frequencies |
| `/opt/rotorweb/config.json.bak-…` | Copies before a controller change |
| `/opt/rotorweb-backup-v…` | Copies before an update (last 3) |
| `/etc/udev/rules.d/99-rotorweb.rules` | Fixed name `/dev/rotor` |
| `/usr/local/sbin/rotorweb-helper` | The only allowed system actions (shutdown, reboot, signed update) |
| `/usr/local/share/rotorweb/release.pub` | Public key that checks updates |
| `/var/log/rotorweb-update.log` | Online update log |
| `/opt/rotorweb/*.avant-restauration-…` | Settings from before a restore |

```bash
sudo systemctl status rotorweb                 # status
journalctl -u rotorweb -f                      # live log (q to quit)
sudo /opt/rotorweb/detect.sh                   # change / re-detect the controller
sudo ./update.sh                               # update (from the new version's folder)
sudo /opt/rotorweb/update.sh --rollback        # go back to the previous version
sudo /opt/rotorweb/restore.sh file.rwbackup    # restore a backup
sudo /opt/rotorweb/uninstall.sh                # uninstall
```

## 20. Troubleshooting
- **The service does not start, “permission denied” on port 80**: run `sudo ./update.sh` again (v1.7 gives the service that right).
- **“Controller missing”**: `sudo /opt/rotorweb/detect.sh`, or Settings ▸ Controller → Change / re-detect.
- **Position does not move**: tick “RPi ↔ controller” in the traffic console to see the raw answers.
- **Callsign not found**: without a HamQTH/QRZ account, only the country is given; check the credentials in Settings ▸ Callsign lookup.
- **Empty pass list**: tick other bands, lower the minimum elevation, or update the frequencies and orbits (Internet needed).
- **Pi power buttons: “System command not installed”**: run `sudo ./update.sh` again.
- **The old version is still shown** (browser or app): reload the page (Ctrl+F5, or pull down on the phone).
- **Test email fails**: 16-letter app password and 2-step verification.
- **Home Assistant “Connecting…”**: HA IP, port 1883, Mosquitto started, MQTT credentials.
- **“Check failed”**: the Pi cannot reach github.com (Internet, firewall, DNS).
- **“Invalid signature: version refused”**: the published version is not signed with the right key; don't install, tell the publisher.
- **Update failed**: RotorWeb went back to the old version; details in `/var/log/rotorweb-update.log`.
- **Forgotten backup password**: the backup cannot be opened (that is the point of encryption); make a new one.
- **Forgotten password**: `sudo /opt/rotorweb/users.sh passwd NAME`.
- **Access from the Internet**: use a VPN (Tailscale, WireGuard), not a port forward.

73!
