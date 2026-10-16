# SAP Water - Android app

A thin Android client for the SAP edge controller. The decision engine, safety
interlocks and event log all run on the **controller** (Raspberry Pi or laptop on
the farm Wi-Fi). The app stores the controller's address and shows its dashboard
full-screen so operators can approve runs, hold, stop and view the log from a
phone. **No water decision is made on the phone.**

## Use

1. On the controller: `SAP_PIN=<your pin> SAP_HOST=0.0.0.0 sap-server`
2. Phone on the same Wi-Fi: open the app, enter the controller address, e.g. `192.168.1.20:8080`, tap **Connect**.
3. Use the dashboard PIN for actions. **Change** switches controller; **Refresh** reloads.

The controller serves plain HTTP on the local network, so the app allows
cleartext traffic and only ever loads the address you entered. Use only on a
trusted farm network.

## Build

Android 8.0+ (API 26). Requires JDK 17 and the Android SDK.

```bash
cd android
gradle assembleDebug        # APK: app/build/outputs/apk/debug/app-debug.apk
```

GitHub Actions (`.github/workflows/android.yml`) builds the debug APK on every
change under `android/` and uploads it as the `sap-water-debug-apk` artifact.

## Status

First version: it is a dashboard client only, with no native screens, push
notifications or offline use without the controller. It is a debug build, not
signed for the Play Store, and has not yet been tested on a physical phone.
