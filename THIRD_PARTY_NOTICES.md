# Sources and licenses

`soundbar_status.py` adapts the framing, status request and initial field layout
from Michael Obst's `yamaha-sr-c20a`, licensed under GNU AGPL v3. This project
is distributed under AGPL-3.0; see `LICENSE`. The original author and protocol researcher Michal Jirku are credited here.

- Source: https://github.com/MichaelObst/yamaha-sr-c20a
- Retrieved upstream main: `f785d8dcfa6aedcc5e97fbabe03b6bd4648187c1`
- Earlier research: https://github.com/wejn/yamaha-yas-207

The proprietary Yamaha Sound Bar Remote APK is used only as a local analysis
input. It and its decompiled output in `artifacts/` are excluded from Git and
are not covered by this project's AGPL license. No APK or decompiled code is
installed as an application on MBP. The reader contains protocol constants and a separate Python
implementation, not the Android application's implementation.

Bleak 3.0.2 and its dependencies are installed separately in MBP's project
virtual environment, under their respective upstream licenses. Local JADX
1.5.6 under `tools/` is only an analysis tool and is excluded from Git.
