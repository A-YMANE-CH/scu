# Public Ubuntu Autoinstall Bundle

This repository contains the public installer bundle for store mini PCs.

Use this direct URL in the Ubuntu Desktop autoinstall URL field:

```text
https://raw.githubusercontent.com/A-YMANE-CH/scu/main/autoinstall.yaml
```

The installer creates the `store` user, downloads the sanitized application code
into `/home/store/store_counter_system`, installs first-boot setup logic, and
reboots.

On first boot, `store-counter-first-boot.service` runs once. It installs
TeamViewer, creates the Python runtime, and downloads the YOLOX-Tiny OpenVINO
model. Logs are written to:

```text
/var/log/store-counter-first-boot.log
```

Real DVR/camera credentials are intentionally not stored here. After installation,
edit:

```text
/home/store/store_counter_system/camera_config/cameras.json
```
