# Hardware bring-up

No physical motion or servo calibration runs unattended. A present teammate owns power-on, a clear workspace, and the vendor's stop procedure. Software simulation and read-only preparation may continue while the lead is away.

## Confirmed inventory and unresolved details

| Device | Confirmed from the user | Still needed |
|---|---|---|
| Freenove hexapod for Raspberry Pi | Owned, unopened at planning time | Exact kit number, PCB revision, Pi model/presence, microSD, matching cells, stock camera contents |
| Quarky Intellio Rover Kit | Rover version confirmed | Installed firmware, supplied battery/charging accessories, working camera access and control method |
| Hiwonder LeArm | Owned, unopened at planning time | Exact generation, controller board, included adapter, remote battery compartment label |
| StackChan | Owned, new in box | Manufacturer/version, included power accessories, supported programming path |
| Sensor station parts | Several sensors owned | Actual sensor models, controller board, voltage requirements, water sensor availability |
| IMREN K4 charger | Already owned | Inspect the unit and use its own matching instructions/power input |

## Purchases: model-dependent facts only

The [IMREN K4 manufacturer listing](https://imrenbatteries.com/products/batterycharger-universal-k4) describes a four-slot charger compatible with rechargeable 18650 Li-ion cells. A duplicate charger is not on the shopping list. The web listing mixes some input/connector descriptions, so follow the label on the owned unit rather than assuming a cable or adapter type from the web page.

**Only if the hexapod is FNK0052:** Freenove specifies four unprotected 18650 cells with discharge capability greater than 15 A; its product page calls for 3.7 V flat-top cells. The Raspberry Pi is listed as a separately required component. Match the actual kit and its guide before buying or installing cells. [Parts requirements](https://docs.freenove.com/projects/fnk0052/en/latest/fnk0052/codes/tutorial/List.html), [product page](https://store.freenove.com/products/fnk0052).

**Only for the documented LeArm AI version:** Hiwonder's remote-control guide specifies two AAA batteries in the wireless gamepad. That does not establish what the user's unidentified LeArm generation needs, or whether the arm itself needs a battery pack. Inventory its included adapter and read its board/adapter labels first. [LeArm AI remote guide](https://docs.hiwonder.com/projects/LeArm_AI/en/latest/docs/2.Remote_Control.html).

The official LeArm AI documentation describes several materially different
configurations: ESP32, STM32, or C51 core boards; bus-servo or PWM-servo arm
versions; and USB/serial, Bluetooth, controller, app, or PC-software control.
The documented PC path powers the servo controller from its specified adapter,
connects the core board to a computer by USB Type-C, selects the resulting COM
port, and places factory firmware into PC-control mode. This is evidence of a
possible integration boundary, not evidence that the user's unidentified arm
uses that board, firmware, power supply, or protocol. See the official
[LeArm AI overview](https://docs.hiwonder.com/projects/LeArm_AI/en/latest/docs/1.Geting_Ready.html)
and [PC connection guide](https://docs.hiwonder.com/projects/LeArm_AI/en/latest/docs/3.PC_Software_Action_Group_Control.html).

The FieldSight dashboard reads LeArm's existing Relay inventory declaration and
truthfully displays it as **not connected / physical response blocked**. Do not
change that state or implement a serial driver until the exact product label,
servo type, core-board label, included power adapter, observed COM port, and a
supervised stock PC-software movement/stop test have been recorded.

Intellio's documentation lists a microSD limit of 32 GB and a 3.7 V 1000 mAh Li-ion battery for the module. Check the actual Rover kit contents before adding another battery purchase; module specifications alone do not establish all rover power accessories. [Intellio documentation](https://ai.thestempedia.com/docs/quarky-intellio/).

Useful pending items are matching hexapod cells, microSD cards where required, a USB card reader if missing, the correctly identified remote batteries, and any missing Pi/controller/cables. StackChan storage and power remain conditional on its exact version. Do not treat four microSD cards as a confirmed requirement for four distinct computers.

## Teammate A: hexapod

- [ ] Photograph/record model and PCB revision; locate the matching official guide.
- [ ] Inventory Pi, camera, cards, battery holders, cells, and cables.
- [ ] Assemble and calibrate following that revision's vendor procedure with a person present.
- [ ] Demonstrate supervised stand, short walk, turn, and stop.
- [ ] Save one accessible camera image and the command/example that produced it.
- [ ] Handoff the working vendor command and connection details to the lead; do not invent a network-control API.

## Teammate B: rover and station

- [ ] Record Intellio firmware/tool version and supplied power components.
- [ ] Demonstrate supervised move and stop using the stock example.
- [ ] Obtain one image accessible from the laptop; record whether access is file, serial, stream, or vendor software.
- [ ] Identify a suitable actual water sensor and controller; verify their interface/voltage in their own documentation.
- [ ] Record dry and wet readings with timestamps. Keep electronics outside the demonstration tray.
- [ ] Handoff one real sample with units and calibration notes. The scenario's normalized `value_milli` is synthetic, not a physical voltage or calibrated leak volume.

## Next available teammate: arm and announcer

- [ ] Record LeArm generation and included adapter labels; check the gamepad compartment before buying batteries.
- [ ] Demonstrate one supervised taught movement with a lightweight marker at a fixed position.
- [ ] Record StackChan version and demonstrate its stock status/audio example.
- [ ] Determine a supported way for the laptop to request status/audio; make no movement dependency on speech playback.

For each handoff, record: date, device/version, connection method, exact reproducible example, observed result, stop method where relevant, and next blocker. A checked item means someone observed it working on this hardware.
