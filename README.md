# EKM Local

A Home Assistant integration for EKM Omnimeters behind an **EKM Push3 gateway**.
It reads the gateway's local `readMeter` API on your LAN, with no EKM cloud access.

One config entry covers a gateway. Each meter it serves becomes its own device, and
meters added to the gateway later appear automatically.

## Entities (per meter)

| Entity | Field | Default |
|---|---|---|
| Power, Power L1/L2 | `RMS_Watts_Tot`, `RMS_Watts_Ln_n` | enabled |
| Reactive power (v4 meters) | `Reactive_Pwr_Tot` | enabled |
| Current, voltage, power factor L1/L2 | `Amps_Ln_n`, `RMS_Volts_Ln_n`, `Cos_Theta_Ln_n` | enabled |
| Frequency (v4) | `Line_Freq` | enabled |
| Energy (total increasing, Energy-dashboard ready) | `kWh_Tot` | enabled |
| Read reliability | `Reliability_Ratio` | enabled (diagnostic) |
| All L3 values, per-line energy and reactive power, tariff 1–4 energy, reverse and reactive energy, max demand, pulse counts, last reading time | | disabled |

Entities exist only for fields the meter reports, so v3 meters get no reactive power
or frequency.

The gateway keeps serving a meter's last reading after it stops answering. When a
reading is more than 5 minutes old, that meter's entities go unavailable. A failed
poll also makes them unavailable straight away, with no grace period, so automations
that watch for utility outages never act on stale data.

## Install

Add this repository to HACS as a custom repository (category: Integration), install
**EKM Local**, restart, then add **EKM Local** under **Settings → Devices & services**.
Enter the gateway's IP address and its API key. The key is the `key=` parameter of a
`readMeter` URL. It's stored in the config entry and redacted from diagnostics.

## Migrating from REST sensors without losing history

Recorder history, long-term statistics and Energy dashboard references are all stored
by entity ID. For each meter, the setup flow can take over your existing REST entity
IDs so all three continue unbroken:

1. When setup asks you to name each meter, also enter the REST sensors' common prefix
   (e.g. `sensor.house_power`). The next step matches `_total_watts`, `_reactive_watts`,
   `_total_energy`, `_l1_amps`, `_l2_amps` and so on to the new sensors. Edit or clear
   any match.
2. Setup then waits (it shows *Waiting to take over …*) until nothing else provides
   those IDs. Remove the `rest:` block and reload **RESTful** from Developer tools →
   YAML.
3. The entry retries on its own, or you can reload it.

## Options

**Polling interval** (default 60 s, minimum 5 s).
