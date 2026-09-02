# Public Ubuntu autoinstall bundle

Host this folder from a public HTTPS location for Ubuntu autoinstall.

Required files:

- `user-data`: Ubuntu autoinstall cloud-init file.
- `meta-data`: NoCloud metadata file.
- `scripts/`: store counter setup and launch scripts.

Example installer URL:

```text
autoinstall ds=nocloud-net;s=https://raw.githubusercontent.com/YOUR_USER/YOUR_REPO/main/public_autoinstall/
```

Important:

- The URL must end with `/`.
- The installer will download `user-data` and `meta-data` from that folder.
- Do not publish a real reusable password. Use a temporary password hash and
  change the password after installation, or use SSH keys and disable password
  login later.
