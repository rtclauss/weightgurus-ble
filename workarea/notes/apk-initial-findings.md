# APK Initial Findings

## Source APK

- File: `workarea/apks/AF3DWBfkGpzLDiMDFxTo4XhicYUCStAldu_bYSMV_CIXaT0cwiYwWVWe654K367ifGaYTlEYmihjpDLc0Puq_StLDYWGRlBRo1aoCkcq3D1s5SyHOGOw3nnamzcUd7VhR_z0HxidQCd6YOe4xCY3ioQIG2OMXnP9eg.apk`
- SHA-256: `5b74484503ee0590b1baccefcf5b2b72433681e9572a963fad2bec5065e5fb13`
- Android package: `com.dmdbrands.gurus.weight`

## High-level architecture

- The app is a Capacitor app with a native Android BLE plugin.
- The Capacitor plugin ID is `GGBluetoothIonic`.
- The plugin package is `com.greatergoods.plugin.bluetooth`.
- BLE operations are routed through `GGBluetoothSDKHelper`, which uses the vendor SDK exposed through `GGIStub.getHandler(...)`.
- The `WEIGHT_GURUS` app type sets the SDK license key, which directly sets the
  internal SDK namespace. That namespace controls scan filters.

## Weight Gurus app namespace

- App type string: `WEIGHT_GURUS`
- Weight Gurus namespace/license key: `a7b3f494990146d083530e3e1befa2907fd256ce2a2840d49a1a979193fd7c83`

## Supported Weight Gurus device names in this APK

The SDK has an explicit allowlist for Weight Gurus devices:

- `10376B`
- `0376B`
- `0202B`
- `1202B`
- `202B`
- `11251B`
- `1251B`
- `01251B`
- `1270B`
- `11270B`
- `01270B`
- `GG BS 0351`
- `GG BS 0344`
- `LS212-B`
- `GG BS 0412`

Important nuance:

- The list exists in `DeviceConfigConstants`, but the namespace filter does not
  appear to use it as a hard allowlist for Weight Gurus scanning.
- In `GGUUIDManager.isDeviceInNamespace(...)`, only the `RPM` namespace is
  explicitly gated by device name.
- For the Weight Gurus namespace, the effective gate is:
  - detected device type must be `GG_WEIGHING_SCALE_DEVICE`
  - plus the service UUID-based scan filter

## Weight Gurus BLE protocol families

The Weight Gurus namespace scans for four service UUIDs and maps them to three
weighing-scale protocol families:

- `00007802-0000-1000-8000-00805F9B34FB`
  - Generic weight scale service
- `20568521-5ACD-4C5A-9294-EB2691C8B8BF`
  - A6 family scale service
- `0d005750-c36b-11e3-9c1a-0800200c9a66`
  - A3 family scale service
- `0000FFF0-0000-1000-8000-00805F9B34FB`
  - R4 data transmission service

Protocol mapping used by the SDK:

- A3 protocol
  - Triggered by `FAT_SCALE_A3_SERVICE_UUID`, `DMD_A3_SCALE_SERVICE_UUID`, or the A3 BPM UUID
- A6 protocol
  - Triggered by the A6 scale and A6 device service UUIDs
- R4 protocol
  - Triggered by `DATA_TRANSMISSION_SERVICE_UUID` (`FFF0`)

## Namespace scan behavior

- `BluetoothHandler.startScan(...)` scans only for service UUIDs returned by
  `GGUUIDManager.getServiceUUIDof(namespace)`.
- For the Weight Gurus namespace, the scan filters are:
  - `00007802-0000-1000-8000-00805F9B34FB`
  - `20568521-5ACD-4C5A-9294-EB2691C8B8BF`
  - `0d005750-c36b-11e3-9c1a-0800200c9a66`
  - `0000FFF0-0000-1000-8000-00805F9B34FB`
- The scan parser (`GGScanResult`) infers protocol and device type from
  advertised service UUIDs before any connection is made.

## Advertisement parsing behavior

## User-provided sample advertisement

The sample advertisement captured outside this workspace was:

```json
{
  "name": "F3:07:D5:F4:2B:A4",
  "address": "F3:07:D5:F4:2B:A4",
  "rssi": -66,
  "manufacturer_data": {
    "76": "12021401"
  },
  "service_data": {},
  "service_uuids": [],
  "connectable": true,
  "raw": "07ff4c0012021401"
}
```

This does not match the Weight Gurus scan signatures from the APK:

- manufacturer company ID `76` is `0x004C` (Apple), not a scale vendor ID
- the payload `12021401` lines up with Apple accessory metadata
- no Weight Gurus service UUIDs are present
- the device name being a randomized MAC-like string is also consistent with
  Apple BLE privacy beacons

Practical conclusion:

- this sample is almost certainly an Apple device beacon, not the scale
- the scale should instead advertise at least one of:
  - `00007802-0000-1000-8000-00805F9B34FB`
  - `20568521-5ACD-4C5A-9294-EB2691C8B8BF`
  - `0d005750-c36b-11e3-9c1a-0800200c9a66`
  - `0000FFF0-0000-1000-8000-00805F9B34FB`

### A3 advertisement handling

- A3 devices encode pairing mode in the first character of the local name:
  - `0...` means not in pairing mode
  - `1...` means in pairing mode
- For local names starting with `0`, the trailing 8 characters are reused as the
  broadcast ID.
- The visible device name is derived from the local name after stripping the
  leading pairing flag and optional trailing broadcast suffix.

### R4 advertisement handling

- R4 parsing uses manufacturer data.
- If manufacturer data length is at least 7 bytes:
  - byte `0` is treated as battery level
  - bytes `1..6` become the broadcast ID and MAC
- If manufacturer data length is at least 9 bytes:
  - byte `7` encodes multiple flags:
    - weight unit
    - impedance measurement enabled/disabled
    - heart-rate measurement enabled/disabled
    - wifi connected/not connected
    - start animation enabled/disabled
    - end animation enabled/disabled
  - byte `8` is user count

### A6 advertisement handling

- A6 parsing also uses manufacturer data.
- Bytes `5..10` are used as the broadcast ID and MAC.
- If the company ID is `AE12`, the app derives an encryption key as:
  - `hex("TranstekA6") + broadcastId`

## A6 scale protocol details

- Primary scale services observed in the SDK:
  - `20568521-5ACD-4C5A-9294-EB2691C8B8BF`
  - `E492C1FB-2466-4749-AB37-69433D2D7846`
  - `0000A602-0000-1000-8000-00805F9B34FB`
- The `LS212-B` export aligns with the first UUID above, which is the expected
  Weight Gurus A6 scale path.

Characteristic map from `GGUUIDManager`:

- `0000A620-0000-1000-8000-00805F9B34FB`
  - indicate data
- `0000A621-0000-1000-8000-00805F9B34FB`
  - notify data
- `0000A622-0000-1000-8000-00805F9B34FB`
  - write acknowledgement
- `0000A623-0000-1000-8000-00805F9B34FB`
  - write data
- `0000A624-0000-1000-8000-00805F9B34FB`
  - write command
- `0000A625-0000-1000-8000-00805F9B34FB`
  - notify acknowledgement
- `0000A640-0000-1000-8000-00805F9B34FB`
  - battery / voltage info (read)
- `0000A641-0000-1000-8000-00805F9B34FB`
  - feature bitmap (read)

Important correction versus earlier guesses:

- `A640` and `A641` are not the likely control-write characteristics.
- The actual command channel is `A624`.
- The SDK writes ACK frames to `A622`.
- The SDK listens on `A620`, `A621`, and `A625`.

Observed A6 connection behavior in the SDK:

- On connect, the app reads device info first.
- If `A624` is present, it then reads:
  - feature bitmap from `A641`
  - battery / voltage from `A640`
- Notification subscriptions for A6 are:
  - `A621`
  - `A625`
  - `A620`

Likely interpretation of the user-observed repeating frame:

- The observed payload `10 0A 00 07 00 00 00 00 00 00 2B` is not just a generic
  heartbeat.
- In `GGBathScaleA6.parseA621Response(...)`, command `0x0007` is parsed as a
  login request.
- That means the frame likely decodes as:
  - prefix `0x10`
  - length `0x0A`
  - command `0x0007`
  - 6-byte token/challenge
  - 1-byte user number
  - 1-byte battery level (`0x2B` = 43)

Likely app response sequence for A6:

- Write ACK to `A622`:
  - success payload: `00 01 01`
- Write login response to `A624` (command `0x0008`)
  - structure:
    - `10`
    - `0B`
    - `0008`
    - `01`
    - echoed 6-byte token from the login request
    - pairing-screen flag (`00` or `01`)
    - trailing `02`
- If the scale then sends command `0x0009` (initialization request), the app:
  - ACKs on `A622`
  - responds on `A624` with command `0x000A`:
    - `10`
    - `08`
    - `000A`
    - 1-byte argument echoed from the request
    - 4-byte UTC timestamp
    - 1-byte timezone flag

Likely live-data start command:

- `GGBathScaleA6.subscribeToLiveData()` writes command `18433` (`0x4801`) to
  `A624`.
- The constructed payload is:
  - `10 04 48 01 00 01`
- The response command `18434` (`0x4802`) is parsed as the synchronized
  measurement payload, including:
  - timestamp
  - weight
  - unit
  - optional impedance

Practical implication:

- If `LS212-B` only emits `0x0007` login requests every few seconds, the device
  is waiting for the app-side login response, not merely a passive notify
  subscription.
- The fastest path forward is:
  - capture the exact official-app writes to `A622` and `A624`, or
  - replicate the `0x0007 -> 0x0008`, `0x0009 -> 0x000A`, and `0x4801`
    sequence directly in a probe script.

Confirmed live capture from the local Terminal session:

- Device matched as:
  - local name `LS212-B`
  - advertised service `20568521-5ACD-4C5A-9294-EB2691C8B8BF`
  - manufacturer data `0x3412 = 567801a4c138ced856`
- GATT subscription confirmed:
  - `A620` indicate
  - `A621` notify
  - `A625` notify
- Repeating frame observed on `A621` every ~3 seconds:
  - `10 0A 00 07 00 00 00 00 00 00 2B`

This confirms three important points:

- the physical scale is on the A6 family path
- the scale is actively requesting a login/session response
- passive notification subscription alone is not sufficient to reach weight data

## A3 scale protocol details

- Primary service:
  - `0d005750-c36b-11e3-9c1a-0800200c9a66`
- Command/write characteristic:
  - `00008a81-0000-1000-8000-00805F9B34FB`
- Event/upload notify characteristic:
  - `00008a82-0000-1000-8000-00805F9B34FB`
- Additional measurement notifies enabled by the app:
  - `00008A22-0000-1000-8000-00805F9B34FB`
  - `00008A24-0000-1000-8000-00805F9B34FB`
  - `00008A25-0000-1000-8000-00805F9B34FB`

Observed handshake/state logic:

- The device can send command `0xA0` to provide a 4-byte password.
- The device can send command `0xA1` to provide a 4-byte random number.
- The app computes a verification code from `passwordBytes` and `randomNumber`
  using `Utils.createVerificationCode(...)`, then sends command `0x20`.
- `Utils.createVerificationCode(...)` is not complex encryption. It is a
  straight 4-byte XOR:
  - `verification[i] = password[i] ^ random[i]`
- During pairing, the app also generates a random 4-byte account ID and sends
  it with command `0x21`.

Concrete A3 commands visible in decompiled code:

- `0x02` + timestamp payload
  - set time
- `0x10 0x03 0x0100/0x0101`
  - set weight unit (`kg` or `lb`)
- `0x20` + 4-byte XOR verification code
  - authenticate using password/random challenge
- `0x21` + 4-byte random account ID
  - set account/broadcast ID during pairing
- `0x22`
  - disconnect request

Service subscription behavior after connect:

- On A3 connect, the SDK always enables notify on:
  - `8A82`
- If the device is not in pairing mode, it also enables:
  - `8A24`
  - `8A22`
- If the device is in pairing mode, the SDK reads device info first instead of
  immediately treating it as a live measurement device.

Measurement parsing:

- The app parses the main A3 measurement payload as:
  - weight in kg
  - optional timestamp
  - optional weight delta
  - optional impedance
  - optional user ID
  - status flags for stability, impedance state, append-measurement, and scale accuracy
- A follow-up append payload can include:
  - basal metabolism
  - body fat
  - body water
  - visceral fat
  - muscle mass
  - bone density
  - battery

## R4 scale protocol details

- Primary service:
  - `0000FFF0-0000-1000-8000-00805F9B34FB`
- Characteristics:
  - `FFF1` control class
  - `FFF2` data class
  - `FFF3` realtime data

Observed behavior:

- The app subscribes to `FFF3` for live measurement updates.
- It writes commands to both `FFF1` and `FFF2` depending on operation.
- It explicitly acknowledges some responses on `FFF2`.
- The decompiled `parseFFF1Response(...)` method is large and partially failed in
  `jadx`, but the surrounding code still shows the command channel split and
  realtime payload handling.

Concrete R4 commands visible in decompiled code:

- `0x25 0x0A ...`
  - set time, written to `FFF1`
- `0x05 0x01 0x02`
  - read weight unit, written to `FFF1`
- `0x05 0x02 0x01 <0|1>`
  - set weight unit (`kg` or `lb`), written to `FFF1`
- `0x06 0x02 0x01 <0|1>`
  - set heart-rate switch, written to `FFF1`
- `0x01 0x01 0x03`
  - acknowledge log/raw-data received, written to `FFF2`

Service subscription behavior after connect:

- On R4 connect, the SDK:
  - reads device info
  - enables notify on `FFF1`
  - enables notify on `FFF2`
  - starts a keepalive workflow
- Live measurement subscription is separate and uses notify on `FFF3`.

Known realtime fields in `FFF3` parsing:

- weight in kg
- weight in lb
- unit type
- impedance
- encrypted impedance
- heart rate
- stability flag
- impedance measurement mode
- heart-rate mode
- accuracy-check status

## Decompiled outputs

- Java/Kotlin source:
  - `workarea/decompiled/jadx_app`
- Smali/resources:
  - `workarea/decompiled/apktool_app`

## Next practical steps

- Identify which of the Weight Gurus model strings matches your physical scale.
- Use Android as the reference client and capture app behavior during:
  - scan
  - pair
  - first measurement
  - repeated measurement
- If your scale is A3:
  - focus on the `8A81` write path and the `A0/A1/20/21` handshake
- If your scale is R4:
  - focus on `FFF1`, `FFF2`, and `FFF3` traffic and response ACK rules
