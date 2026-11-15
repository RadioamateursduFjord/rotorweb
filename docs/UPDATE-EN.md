# RotorWeb — Update guide to v2.1

This guide explains how to go to **v2.1** without losing your settings, whatever your current version, and how to update every part. What's new is described in **CHANGELOG.md**.

**v2.1 only changes the visuals**: new logo, app icons, menu icons, guide covers. No setting changes and there is nothing to redo.

## 0. Which method?
| Installed version | Method |
|---|---|
| **v2.0** | In the page: “New version available” banner or Settings ▸ System ▸ Updates → **⬆ Update** (section 9). Nothing to copy to the Pi. |
| **v1.6 or v1.7** | By hand with `update.sh` (sections 1 to 3), **one last time**. Going straight to v2.1 is supported: no need to install v2.0 first. |

Updates can skip versions: `update.sh` redoes every needed change since v1.6.

**What is kept**: configuration (`config.json`), accounts, schedules, presets, rest position, calibration, travel, no-go zones, email and Home Assistant settings.

## 1. Before you start
- Note the current version: it is shown at the bottom of the web page menu (“RotorWeb v1.6”), or:
  ```bash
  grep '^VERSION' /opt/rotorweb/rotorweb/server.py
  ```
- Turn the station **Not operating** (switch on the Operation page) during the update.
- The Raspberry Pi needs Internet (Python packages download).

## 2. Update RotorWeb on the Raspberry Pi
1. Copy `rotorweb-v2.1.zip` to the Raspberry Pi (USB stick, `scp`, etc.), for example into your home folder.
2. Unzip it and go into the **new** folder:
   ```bash
   cd ~
   unzip -o rotorweb-v2.1.zip
   cd rotorweb-v2.1
   ```
3. Run the update:
   ```bash
   sudo ./update.sh
   ```
4. The script shows `Updating RotorWeb v1.6 → v2.1`, makes a **backup** of the old version (`/opt/rotorweb-backup-v1.6-…`), installs the files, applies the needed changes and restarts the service. It should end with “✔ RotorWeb updated and restarted (v2.1)”.

⚠ Always run `update.sh` from the **new** version's folder, not from `/opt/rotorweb`.
⚠ Don't use `install.sh` for an update: it asks every question again.

### What `update.sh` adapts automatically (v1.6 or v1.7 → v2.1)
- Allows the service to use **port 80 or 443** (fixes the “permission denied” error).
- Installs the system command behind the **Shut down / Reboot the Raspberry Pi** buttons and **online updates** (`/usr/local/sbin/rotorweb-helper`, with a `sudo` rule limited to that single script).
- Installs the **public key** that checks the update signatures (`/usr/local/share/rotorweb/release.pub`).
- Installs `openssl` and `unzip` if missing.
- Adds the **station language** (the installation language, can be changed in Settings ▸ Station).
- If the station was in **Automatic mode (WSJT-X)**, which no longer exists, it goes back to **Manual**.

## 3. Check
1. In the web page, the bottom of the menu shows **RotorWeb v2.1**, with the new logo at the top of the menu.
2. If the old page is still shown: reload it (**Ctrl+F5** on a computer; on the phone, close and reopen the app or pull the page down).
3. The traffic console shows “RotorWeb 2.1 started”.
4. Settings ▸ System ▸ Updates → **🔄 Check for updates**: should show “RotorWeb is up to date” (or a newer version if one exists).
5. **Make a backup**: Settings ▸ System ▸ Settings backup → **💾 Download the backup** (keep the file and its password off the Pi).
6. Turn the station back **Operating**.

If something goes wrong:
```bash
sudo systemctl status rotorweb
journalctl -u rotorweb -n 50 --no-pager
```

## 4. Go back to the previous version
If the new version causes trouble:
```bash
sudo /opt/rotorweb/update.sh --rollback
```
The script restores the latest backup (program and settings as they were before the update) and restarts the service. The last 3 backups are kept in `/opt/rotorweb-backup-…`.

## 5. App installed on the phone
The app (home screen) updates itself at the next launch. The app **icon** may keep the old drawing for a few days: the phone replaces it by itself. To change it right away, remove the app from the home screen and install it again. If the old version of the page stays:
- **Android**: close the app (swipe it away in recent apps), reopen it; otherwise Chrome → ⋮ → Settings → Site settings → the Pi address → Clear & reset.
- **iPhone**: close and reopen the app; otherwise delete the icon and add it again (Share ⬆ → Add to Home Screen).

**Dashboard layouts** and the **language** are stored on the Raspberry Pi for your account: nothing to redo.

## 6. Home Assistant
1. **Compass card**: copy the new `homeassistant/rotorweb-compass-card.js` to Home Assistant's `/config/www/` (replace the old one), then reload the dashboard with **Ctrl+F5**. The browser console shows `ROTORWEB-COMPASS-CARD v2.1`; the card now shows the logo next to the title (that is the only change: the old card keeps working).
   New option: `passes: 4` (number of next passes shown).
2. **Entities**: they update by themselves (MQTT discovery). New: “Next good satellite pass”, “Time of the next good pass” (v1.7) and **“RotorWeb update”** (v2.0): Home Assistant shows new versions and can install them.
3. **Mode**: the selector now offers Manual, Schedule, Tracking (or Manuel, Horaire, Suivi in French). If an automation selected “Automatique”, edit it.
4. **Language**: entity names follow the station language. If you switch it to English, the shown names change, but the identifiers (`sensor.rotorweb_…`) stay the same.
5. **New automation** (optional): no. 6 in `homeassistant/automations.yaml`, warning before a satellite pass.

## 7. Controller firmware
v1.7, v2.0 and v2.1 **do not change** any firmware. Nothing to do for a K3NG or a commercial controller.

For home builds:
- **RotorWeb Arduino**: only if the `firmware/rotorweb_diy` sketch changed (see CHANGELOG):
  ```bash
  sudo /opt/rotorweb/firmware/flash_diy.sh
  ```
- **K3NG** (update of the K3NG firmware itself, rarely needed):
  ```bash
  sudo /opt/rotorweb/firmware/flash_k3ng.sh
  ```
  Note your K3NG calibration settings before flashing.

## 8. What to do by hand for v2.1
- **Nothing mandatory**. If you come from v1.6 or v1.7, **make a settings backup** once the update is done (feature added in v2.0).
- Optional: copy the compass card to Home Assistant again to get the logo (section 6).
- For a station coming from v1.6 or v1.7, also optional:
  - Settings ▸ **Callsign lookup**: add a HamQTH (free) and/or QRZ.com account for exact station locations.
  - **Satellite passes** page: tick your bands and enable alerts if you want them.
  - Operation page → **✎ Customize**: choose your modules, on the computer and on the phone.
  - Settings ▸ **Account**: interface language (Français / English).
  - Settings ▸ Controller ▸ **Rotor profiles**: save your current configuration under a name.

## 9. Next updates (from v2.0 on)
No more copying files to the Pi:
1. A “New version available” banner shows in the page (and an email arrives).
2. **See what's new**, then **⬆ Update** and confirm.
3. The page shows the progress (download, signature check, antenna to rest, installation) then reloads by itself.
4. If the new version does not start, the Pi goes back to the old one by itself.

The Raspberry Pi needs access to github.com. Otherwise, the manual method of this guide always works. After each update, copy the compass card into Home Assistant again if the CHANGELOG asks for it.

## 10. Reinstall from a backup
New SD card or new Raspberry Pi: copy the version zip and your `.rwbackup` backup to the Pi, then `sudo ./install.sh`; at the start, give the backup path and its password. Everything is restored, you only confirm the controller port.

## 11. Change the controller (without reinstalling)
Since v1.7, a new controller is plugged in without reinstalling:
- web page: Settings ▸ **Controller → Change / re-detect the controller**;
- or terminal: `sudo /opt/rotorweb/detect.sh`.

The old configuration stays in the “↩ Previous” profile.

## 12. Command summary
```bash
cd ~/rotorweb-v2.1 && sudo ./update.sh            # update by hand
sudo /opt/rotorweb/update.sh --rollback      # roll back
sudo /opt/rotorweb/detect.sh                 # change / re-detect the controller
sudo /opt/rotorweb/restore.sh file.rwbackup      # restore a backup
cat /var/log/rotorweb-update.log             # online update log
journalctl -u rotorweb -f                    # live log (q to quit)
```

73!
