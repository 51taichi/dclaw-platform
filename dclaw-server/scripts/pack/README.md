# DClaw Desktop packaging scripts

One-click build: each script first builds a **wheel** via
`scripts/wheel_build.sh` (includes the console frontend), then uses a
**temporary conda environment** and **conda-pack** (no current dev env).
Dependencies follow `pyproject.toml`.

The packaged app defaults to a **DClaw remote desktop client**: it loads the
packaged frontend shell and points API requests at the domestic API domain
`https://dclaw.deepmega.cn`, instead of starting a local qwenpaw backend on
the user's machine. Set `DCLAW_DESKTOP_LOCAL_BACKEND=1` before packaging or
launching if you need the private/local-backend mode.

- **Windows**: wheel → conda-pack → unpack → NSIS installer (`.exe`)
- **macOS**: wheel → conda-pack → unpack into `.app` → optional zip

## System Requirements

- **Windows**: Windows 10 or later
- **macOS**: macOS 14 (Sonoma) or later, Apple Silicon (M1/M2/M3/M4) recommended

## Prerequisites

- **conda** (Miniconda/Anaconda) on PATH
- **Node.js / npm** (for the console frontend)
- (Windows only) **NSIS**: `makensis` on PATH
- **Icons**: Pre-generated `icon.ico` (Windows) and `icon.icns` (macOS) are included in `scripts/pack/assets/`

## One-click build

From the **repo root**:

**macOS**
```bash
bash ./scripts/pack/build_macos.sh
# Output: dist/DClaw.app

CREATE_ZIP=1 bash ./scripts/pack/build_macos.sh   # also create .zip
```

**Windows (PowerShell)**
```powershell
./scripts/pack/build_win.ps1
# Output: dist/DClaw-Setup-<version>.exe
# Creates two launchers:
#   - DClaw Desktop.vbs (silent, no console window)
#   - DClaw Desktop (Debug).bat (shows console for troubleshooting)
# Note: Pre-compiles all Python files to .pyc for faster startup
```

## Domestic release config

Copy the example config, then edit the local file:

```bash
cp scripts/pack/desktop_release.config.example.json scripts/pack/desktop_release.local.json
```

```json
{
  "index_url": "https://static.deepmega.cn/metadata/apps/desktop/index.json",
  "bucket": "oss://your-dclaw-download-bucket",
  "download_base_url": "https://static.deepmega.cn",
  "desktop_api_url": "https://dclaw.deepmega.cn",
  "cdn_refresh_command": "",
  "oss": {
    "config_file": ".ossutilconfig",
    "endpoint": "oss-cn-hangzhou.aliyuncs.com",
    "access_key_id": "replace-with-your-access-key-id",
    "access_key_secret": "replace-with-your-access-key-secret"
  }
}
```

`download_base_url` is the public download/metadata domain. `desktop_api_url`
is the online API domain embedded into the desktop launcher.

## Run from terminal and see logs (macOS)

If the .app crashes on double-click, run it from Terminal to see the full error and logs:

```bash
# From repo root; force packed env only (no system conda / PYTHONPATH). Adjust path if needed.
APP_ENV="$(pwd)/dist/DClaw.app/Contents/Resources/env"
PYTHONNOUSERSITE=1 PYTHONPATH= PYTHONHOME="$APP_ENV" "$APP_ENV/bin/python" -m qwenpaw desktop --remote-api-url https://dclaw.deepmega.cn
```

The `PYTHONNOUSERSITE=1` prevents Python from loading packages from `~/.local/lib/pythonX.Y/site-packages`, which can conflict with the packaged environment. All stdout/stderr (including Python tracebacks) will appear in the terminal. Use this to debug startup errors or to run with `--log-level debug`.

When you **double-click** the .app and nothing appears, the launcher writes stderr/stdout to `~/.qwenpaw/desktop.log`. Inspect that file for errors.

On first launch macOS may ask for “Desktop” or “Files and Folders” access: click **Allow** so the app can run properly; if you click Don’t Allow, the window may close.

## macOS: if “Apple cannot verify” / Gatekeeper blocks the app

When users download the DClaw macOS app (e.g. from Releases) as a `.app` (in a zip), macOS may show: *"Apple cannot verify that 'DClaw' contains no malicious software"*. The app is not notarized. They can still open it as follows:

- **Right-click to open (recommended)**
  Right-click (or Control+click) the DClaw app → **Open** → in the dialog click **Open** again. Gatekeeper will allow it; after that double-click works as usual.

- **Allow in System Settings**
  If still blocked, go to **System Settings → Privacy & Security**, find the message like *"DClaw was blocked because it is from an unidentified developer"*, and click **Open Anyway** or **Allow**.

- **Remove quarantine attribute (not recommended for most users)**
  In Terminal: `xattr -cr /Applications/DClaw.app` (or the path to the `.app` after unzipping). This clears the download quarantine flag; less safe than right-click → Open.

## CI

`.github/workflows/desktop-release.yml`:

- **Triggers**: Release publish or manual workflow_dispatch
- **Windows**: Build console → temporary conda env + conda-pack → NSIS → upload artifact
- **macOS**: Build console → temporary conda env + conda-pack → .app → zip → upload artifact
- **Release**: When triggered by a release, uploads the Windows installer and macOS zip as release assets

## Script reference

| File | Description |
|------|-------------|
| `build_common.py` | Create temporary conda env, install `qwenpaw[full]` from a wheel, conda-pack; produces archive. |
| `build_macos.sh` | One-click: build wheel → build_common → unpack into DClaw.app; optional zip. |
| `build_win.ps1` | One-click: build wheel → build_common → unpack → create VBS/BAT launchers → makensis installer. |
| `desktop.nsi` | NSIS script: pack `dist/win-unpacked`, add icons, and create shortcuts. |
| `assets/icon.ico` | Pre-generated Windows icon (installer and shortcuts). |
| `assets/icon.icns` | Pre-generated macOS icon (app bundle). |
