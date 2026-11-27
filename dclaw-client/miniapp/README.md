# DClaw WeChat Mini Program

## Local Docker API

The mini-program is configured for the local Docker SaaS service by default:

```bash
http://127.0.0.1:18088
```

This matches the `qwenpaw-saas` compose mapping:

```text
127.0.0.1:18088 -> 8088/tcp
```

Check the local API before opening WeChat DevTools:

```bash
curl http://127.0.0.1:18088/api/version
```

Build the WeChat output:

```bash
npm run build:weapp
```

Open this folder in WeChat DevTools:

```text
/Users/zu/Documents/workes/qwenpaw/miniapp
```

For a different local service port, override the build-time API base:

```bash
TARO_APP_API_BASE=http://127.0.0.1:8088 npm run build:weapp
```

When testing with the simulator, keep "do not verify legal domain names / web-view / TLS versions and HTTPS certificates" enabled in WeChat DevTools local settings.

For physical-device preview, `127.0.0.1` points to the phone, not the Mac.
Expose the Docker API beyond localhost first:

```bash
cd /Users/zu/Documents/workes/qwenpaw
QWENPAW_SAAS_BIND_HOST=0.0.0.0 \
QWENPAW_IMAGE=qwenpaw-saas-local:latest \
QWENPAW_SAAS_HOST_PORT=18088 \
docker compose --profile saas up -d qwenpaw-saas
```

Then build the mini-program with the Mac LAN IP injected into the bundle:

```bash
cd /Users/zu/Documents/workes/qwenpaw/miniapp
npm run build:weapp:device
```

If the script picks the wrong network interface, pass the host explicitly:

```bash
TARO_APP_API_HOST=192.168.x.x TARO_APP_API_PORT=18088 npm run build:weapp:device
```
