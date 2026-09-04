# Linux deployment

These scripts are Ubuntu/Debian equivalents of the Windows `.bat` launchers.
They keep the same local `.runtime` folder and the same project-relative paths.

## First setup

```bash
cd ~/store_counter_system
chmod +x *.sh
sudo apt update
sudo apt install -y python3 python3-venv python3-pip curl libgl1 libglib2.0-0
./SETUP_FIRST_RUN.sh
./DOWNLOAD_YOLOX_TINY_OPENVINO.sh
```

## Manual launch

Web UI:

```bash
./START_WITH_WEB_UI.sh
```

Headless terminal mode:

```bash
./START_STORE_COUNTER.sh
```

Two cameras:

```bash
./START_WITH_TWO_CAMERAS.sh
```

Open the UI from another machine on the same network:

```text
http://MINI_PC_IP:8090
```

## Auto-start with systemd

Copy the service template:

```bash
sudo cp store-counter.service.example /etc/systemd/system/store-counter.service
```

Edit it and replace `STORE_USER` plus the `WorkingDirectory`/`ExecStart` paths:

```bash
sudo nano /etc/systemd/system/store-counter.service
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable store-counter.service
sudo systemctl start store-counter.service
```

Check logs:

```bash
journalctl -u store-counter.service -f
```

Restart after editing `cameras.json`:

```bash
sudo systemctl restart store-counter.service
```

## Apps Script Sync

Linux does not have the same official Google Drive desktop sync client as
Windows. The app can instead mirror entries and health reports directly to the
central Google Apps Script endpoint while still keeping local CSV exports.

Create a local config file:

```bash
cd ~/store_counter_system
cp cloud_config.example.json cloud_config.json
nano cloud_config.json
```

Set `appscript_secret` to the same secret configured in `Code.gs`, then restart
the app. The terminal should show:

```text
[cloud] Apps Script sync enabled -> https://script.google.com/...
```
