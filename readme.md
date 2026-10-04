
![Logo](https://raw.githubusercontent.com/JortvanSchijndel/FusionSolarPlus/refs/heads/master/custom_components/fusionsolarplus/brand/logo.png)

<table align="center" border="0">
  <tr>
    <td align="center">
      <a href="https://github.com/Matthias2703/FusionSolarPlus/actions/workflows/lint.yml">
        <img alt="Lint Workflow" src="https://img.shields.io/github/actions/workflow/status/Matthias2703/FusionSolarPlus/lint.yml?branch=feature/charger-control&logo=testcafe&logoColor=%235c5c5c&label=Lint%20Workflow&labelColor=%23ffffff&color=%234983FF&cacheSeconds=600">
      </a>
    </td>
    <td align="center">
      <a href="https://github.com/Matthias2703/FusionSolarPlus/actions/workflows/validate.yml">
        <img alt="Hassfest & HACS Validation Workflow" src="https://img.shields.io/github/actions/workflow/status/Matthias2703/FusionSolarPlus/validate.yml?branch=feature/charger-control&logo=testcafe&logoColor=%235c5c5c&label=Hassfest%20%26%20HACS%20Validation%20Workflow&labelColor=%23ffffff&color=%234983FF&cacheSeconds=600">
      </a>
    </td>
    <td align="center">
      <a href="https://github.com/Matthias2703/FusionSolarPlus/actions/workflows/tests.yml">
        <img alt="Tests Workflow" src="https://img.shields.io/github/actions/workflow/status/Matthias2703/FusionSolarPlus/tests.yml?branch=feature/charger-control&logo=testcafe&logoColor=%235c5c5c&label=Tests%20Workflow&labelColor=%23ffffff&color=%234983FF&cacheSeconds=600">
      </a>
    </td>
  </tr>
</table>

___
> [!NOTE]
> **This is a fork** of [JortvanSchijndel/FusionSolarPlus](https://github.com/JortvanSchijndel/FusionSolarPlus), maintained separately by [Matthias2703](https://github.com/Matthias2703). It adds control of a Huawei SCharger wallbox (charging mode, schedule, cable lock, dynamic power) on top of the original's read-only entities. See [Changes in this fork](#changes-in-this-fork) for the full list.
>
> It has been tested on exactly one device (a SCharger-22KT-S0 with an EMMA) and is run on the author's own Home Assistant. Everything that writes to hardware is off by default (see [Charger control](#charger-control-experimental-off-by-default)) and was built carefully, but there is no guarantee it behaves the same on a different charger model. Use it, but keep an eye on it.

# FusionSolarPlus
This integration brings full FusionSolar support to Home Assistant, with entities for plants, inverters, and more. It authenticates using your FusionSolar username and password. No northbound API, OpenAPI, or kiosk URL required. Jort van Schijndel originally built it as a custom Python script that sent data via MQTT, but realizing others might want a Home Assistant integration with full entity support, he ported it with AI assistance into a proper integration for easier use. This fork builds on that work.

## Setup
Click the button below to add this fork as a custom repository in HACS.

<a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=Matthias2703&repository=FusionSolarPlus&category=Integration" target="_blank" rel="noreferrer noopener"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open your Home Assistant instance and open a repository inside the Home Assistant Community Store." /></a>

This fork is not in the HACS default store; the button above adds it as a custom repository. Select the `feature/charger-control` branch when prompted.

Once installed:

1. Restart Home Assistant and head over to **Settings » Devices & Services.**  
2. Click on **"Add Integration."**  
3. Search for **"FusionSolarPlus."**  
4. Enter your FusionSolar username, password and subdomain.
5. Select the device type you want to add, then choose the specific device.

Repeat step 2 - 5 for each of the devices you want to add.

# Energy Dashboard

FusionSolarPlus is fully compatible with the integrated Home Assistant energy dashboard. Please make sure you’ve already added the correct device types (See step 2-5 above). 

When configuring the energy dashboard you need to provide the following settings:

|                          | Energy dashboard setting         | Device Type  | Entity                           |
|--------------------------|----------------------------------|:------------:|----------------------------------|
| **Electricity Grid**     | Grid Consumption                 | Power Sensor | Negative Active Energy           |
|                          | Return to Grid                   | Power Sensor | Positive Active Energy           |
| **Home Battery Storage** | Energy going in to the battery   |   Battery    | Energy Charged Today             |
|                          | Energy coming out of the battery |   Battery    | Energy Discharged Today          |
| **Solar Panels**         | Solar Production                 |   Inverter   | Daily Energy (for each inverter) |

# Charger control (experimental, off by default)

For Huawei SCharger wallboxes the integration can also **write** to the charger through the FusionSolar cloud. Because this changes real hardware, it is **off by default** and has to be enabled per charger entry:

1. **Settings » Devices & Services » FusionSolarPlus**, open the **Charger** entry.
2. Click **Configure** and tick **Enable charger control**, then submit. The entry reloads and the entities below appear. Untick it to switch them off again; the entities are then removed from the registry automatically.

The read-only charger sensors (status, power, energy and charge history) do not depend on this option. The diagnostic values below (power limit, PV thresholds) are read from the cloud together with the control state, so they appear only when charger control is on; with it off the integration makes no control or schedule requests at all.

## Entities added by charger control

| Entity | Type | What it does | Cloud signal |
|---|---|---|---|
| Charging Mode | select | *Charge now*, *PV surplus* or *Scheduled*, the three modes of the FusionSolar app | working mode `20002` + schedule switch |
| Cable Lock | select | Always lock / lock when charging / lock after being inserted (the app's names) | `20005` |
| Dynamic Power | switch | Dynamic charge power on/off | `538976529` |
| Start charging / Stop charging | button | Starts or stops a charge, the same requests as the app's start/stop button | `charge/start-charge`, `charge/stop-charge` |

The cable lock and dynamic power are shown as configuration entities; only *Charging Mode* is a regular control.

How the three modes map to the cloud:

| Mode | Schedule | Working mode |
|---|---|---|
| Charge now | off | `0` normal charge |
| PV surplus | off | `1` PV power preferred |
| Scheduled | on (plans as configured in the app) | left as is |

If the schedule is on, *Scheduled* wins whatever the working mode says. The working mode is available as the `working_mode` attribute of the select.

## Read-only additions

* **Power Limit**, **PV Start Surplus** and **PV Max Grid Power** (diagnostic, only with charger control on): the power limit is read-only on purpose (see the limitations); the app flags the two PV values as internal defaults it never shows, so they can be read but not changed.
* **Charge Sessions (180 Days)**, **Last Session Energy / Duration / Start / Mode**: taken from the charge records, refreshed at most every 5 minutes.

## How writes behave

* Only a fixed list of signals can be written (working mode, cable lock, dynamic power and the schedule switch), plus the start and stop charge commands. Installer and safety values such as the main breaker, earthing system, networking mode, phase switching and the charging plans themselves are never written.
* Values are checked before anything is sent (allowed options only).
* Every change is confirmed by reading the value back (up to three checks, then one rewrite). While that happens the entity shows the requested value instead of turning *unavailable*; if the cloud never confirms it, the action fails with an error.
* Switching the schedule has to resend the whole plan list (the cloud replaces it as a whole), so it is done defensively: nothing is written if the schedule is already in the requested state, if the plan list is missing or empty, if two reads a moment apart disagree, or if a plan is a one-time plan or lacks a field (change the mode in the FusionSolar app then). Before the write the plans are logged as a WARNING and stored in `.storage/fusionsolarplus_plan_backup` (the last five). Afterwards every stored field is compared; if the plans did not come back exactly, one restore attempt is made and the action fails with an error that says whether it worked.
* The cloud sometimes answers HTTP 200 with an error inside the body; that is treated as an error, and a state that cannot be read makes the entity unavailable instead of guessing.

## Limitations

* **Cloud only, unofficial endpoints.** The ids and requests were captured from the FusionSolar app. Huawei can change them without notice.
* **Tested on one charger** (SCharger-22KT-S0 with an EMMA): charging mode, schedule, dynamic power and cable lock were exercised against the real device, and the cable lock request was compared with the one the FusionSolar app sends (identical). 
* **The power limit cannot be changed from Home Assistant.** On the tested charger, lowering it below the power of a saved charging schedule (11 kW to 10 kW) made the cloud delete all schedules. They had to be recreated in the app. Change the limit in the FusionSolar app, which warns about this.
* **Schedules are stored in UTC.** The cloud returns and expects the plan times in UTC and the app converts them (a plan shown as 17:00 in Germany in summer is stored as 15:00). The integration never edits plans; when switching the schedule it resends them exactly as read.
* **Only the first connector is used.** A charger with more than one connector is controlled through the first one and a warning is logged.
* **One-time plans block mode switching from Home Assistant.** They cannot be reproduced exactly, so switching the schedule is refused while one exists.
* **Starting or stopping a running charging session is not supported.** Only the mode and settings above are.
* **Two controllers.** An EMMA runs its own automatic charging logic. The integration only sees a change made by the EMMA or the app on the next update and does not fight it.
* Charge now, PV surplus and Scheduled describe what the cloud reports; the wallbox itself needs a connected and released car to actually charge.

## Other options

Every entry has an **Update interval** option (10–3600 s, default 15 s). Control state and the schedule are cached for 45 s and refreshed right after every change. The setup and options dialogs are available in English and German. If the FusionSolar login stops working (for example after a password change) Home Assistant asks for the password again instead of retrying forever; when the cloud is merely unreachable at startup, setup is retried automatically.

# Entities


<details>
<summary>Click here to see the list of entities </summary>

<details>
<summary><b><ins>Inverter</ins></b></summary>

<p><b>Inverter Signals</b></p>
<table>
   <tr>
      <td align="center"><b>#</b></td>
      <td><b>Entity Display Name</b></td>
      <td align="center"><b>Unit</b></td>
   </tr>
   <tr>
      <td align="center">1</td>
      <td>Status</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">2</td>
      <td>Power Factor</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">3</td>
      <td>Output Mode</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">4</td>
      <td>Last Startup Time</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">5</td>
      <td>Last Shutdown Time</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">6</td>
      <td>Daily Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">7</td>
      <td>Total Energy Produced</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">8</td>
      <td>Current Active Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">9</td>
      <td>Reactive Power</td>
      <td align="center">kvar</td>
   </tr>
   <tr>
      <td align="center">10</td>
      <td>Rated Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">11</td>
      <td>Grid Frequency</td>
      <td align="center">Hz</td>
   </tr>
   <tr>
      <td align="center">12</td>
      <td>Phase A Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">13</td>
      <td>Phase B Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">14</td>
      <td>Phase C Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">15</td>
      <td>Phase A Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">16</td>
      <td>Phase B Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">17</td>
      <td>Phase C Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">18</td>
      <td>Temperature</td>
      <td align="center">°C</td>
   </tr>
   <tr>
      <td align="center">19</td>
      <td>Insulation Resistance</td>
      <td align="center">MΩ</td>
   </tr>
</table>

<p><b>PV Signals</b></p>
<table>
   <tr>
      <td align="center"><b>#</b></td>
      <td><b>Entity Display Name</b></td>
      <td align="center"><b>Unit</b></td>
   </tr>
   <tr>
      <td align="center">1</td>
      <td>[PV 1] Input Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">2</td>
      <td>[PV 1] Input Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">3</td>
      <td>[PV 1] Input Power</td>
      <td align="center">W</td>
   </tr>
</table>
<p><i>* [PV 1] can be [PV 1] to [PV 20] depending on your device.</i></p>

<p><b>Optimizer Metrics</b></p>
<table>
   <tr>
      <td align="center"><b>#</b></td>
      <td><b>Entity Display Name</b></td>
      <td align="center"><b>Unit</b></td>
   </tr>
   <tr>
      <td align="center">1</td>
      <td>Output Power</td>
      <td align="center">W</td>
   </tr>
   <tr>
      <td align="center">2</td>
      <td>Total Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">3</td>
      <td>Input Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">4</td>
      <td>Running Status</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">5</td>
      <td>Temperature</td>
      <td align="center">°C</td>
   </tr>
   <tr>
      <td align="center">6</td>
      <td>SN</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">7</td>
      <td>Optimizer Number</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">8</td>
      <td>Output Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">9</td>
      <td>Input Current</td>
      <td align="center">A</td>
   </tr>
</table>
</details>

<details>
<summary><b><ins>Battery</ins></b></summary>

<p><b>Battery Status Signals</b></p>
<table>
   <tr>
      <td align="center"><b>#</b></td>
      <td><b>Entity Display Name</b></td>
      <td align="center"><b>Unit</b></td>
   </tr>
   <tr>
      <td align="center">1</td>
      <td>Operating Status</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">2</td>
      <td>Charge/Discharge Mode</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">3</td>
      <td>Rated Capacity</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">4</td>
      <td>Backup Time</td>
      <td align="center">min</td>
   </tr>
   <tr>
      <td align="center">5</td>
      <td>Energy Charged Today</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">6</td>
      <td>Energy Discharged Today</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">7</td>
      <td>Charge/Discharge Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">8</td>
      <td>Bus Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">9</td>
      <td>State of Charge</td>
      <td align="center">%</td>
   </tr>
</table>

<p><b>Battery Module Signals</b></p>
<table>
   <tr>
      <td align="center"><b>#</b></td>
      <td><b>Entity Display Name</b></td>
      <td align="center"><b>Unit</b></td>
   </tr>
   <tr>
      <td align="center">1</td>
      <td>[Module 1] No.</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">2</td>
      <td>[Module 1] Working Status</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">3</td>
      <td>[Module 1] SN</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">4</td>
      <td>[Module 1] Software Version</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">5</td>
      <td>[Module 1] SOC</td>
      <td align="center">%</td>
   </tr>
   <tr>
      <td align="center">6</td>
      <td>[Module 1] Charge and Discharge Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">7</td>
      <td>[Module 1] Internal Temperature</td>
      <td align="center">°C</td>
   </tr>
   <tr>
      <td align="center">8</td>
      <td>[Module 1] Daily Charge Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">9</td>
      <td>[Module 1] Daily Discharge Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">10</td>
      <td>[Module 1] Total Discharge Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">11</td>
      <td>[Module 1] Bus Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">12</td>
      <td>[Module 1] Bus Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">13</td>
      <td>[Module 1] FE Connection</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">14</td>
      <td>[Module 1] Total Charge Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">15</td>
      <td>[Module 1] Battery Pack 1 No.</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">16</td>
      <td>[Module 1] Battery Pack 2 No.</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">17</td>
      <td>[Module 1] Battery Pack 3 No.</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">18</td>
      <td>[Module 1] Battery Pack 1 Firmware Version</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">19</td>
      <td>[Module 1] Battery Pack 2 Firmware Version</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">20</td>
      <td>[Module 1] Battery Pack 3 Firmware Version</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">21</td>
      <td>[Module 1] Battery Pack 1 SN</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">22</td>
      <td>[Module 1] Battery Pack 2 SN</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">23</td>
      <td>[Module 1] Battery Pack 3 SN</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">24</td>
      <td>[Module 1] Battery Pack 1 Operating Status</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">25</td>
      <td>[Module 1] Battery Pack 2 Operating Status</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">26</td>
      <td>[Module 1] Battery Pack 3 Operating Status</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">27</td>
      <td>[Module 1] Battery Pack 1 Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">28</td>
      <td>[Module 1] Battery Pack 2 Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">29</td>
      <td>[Module 1] Battery Pack 3 Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">30</td>
      <td>[Module 1] Battery Pack 1 Charge/Discharge Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">31</td>
      <td>[Module 1] Battery Pack 2 Charge/Discharge Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">32</td>
      <td>[Module 1] Battery Pack 3 Charge/Discharge Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">33</td>
      <td>[Module 1] Battery Pack 1 Maximum Temperature</td>
      <td align="center">°C</td>
   </tr>
   <tr>
      <td align="center">34</td>
      <td>[Module 1] Battery Pack 2 Maximum Temperature</td>
      <td align="center">°C</td>
   </tr>
   <tr>
      <td align="center">35</td>
      <td>[Module 1] Battery Pack 3 Maximum Temperature</td>
      <td align="center">°C</td>
   </tr>
   <tr>
      <td align="center">36</td>
      <td>[Module 1] Battery Pack 1 Minimum Temperature</td>
      <td align="center">°C</td>
   </tr>
   <tr>
      <td align="center">37</td>
      <td>[Module 1] Battery Pack 2 Minimum Temperature</td>
      <td align="center">°C</td>
   </tr>
   <tr>
      <td align="center">38</td>
      <td>[Module 1] Battery Pack 3 Minimum Temperature</td>
      <td align="center">°C</td>
   </tr>
   <tr>
      <td align="center">39</td>
      <td>[Module 1] Battery Pack 1 SOC</td>
      <td align="center">%</td>
   </tr>
   <tr>
      <td align="center">40</td>
      <td>[Module 1] Battery Pack 2 SOC</td>
      <td align="center">%</td>
   </tr>
   <tr>
      <td align="center">41</td>
      <td>[Module 1] Battery Pack 3 SOC</td>
      <td align="center">%</td>
   </tr>
   <tr>
      <td align="center">42</td>
      <td>[Module 1] Battery Pack 1 Total Discharge Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">43</td>
      <td>[Module 1] Battery Pack 2 Total Discharge Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">44</td>
      <td>[Module 1] Battery Pack 3 Total Discharge Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">45</td>
      <td>[Module 1] Battery Pack 1 Battery Health Check</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">46</td>
      <td>[Module 1] Battery Pack 2 Battery Health Check</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">47</td>
      <td>[Module 1] Battery Pack 3 Battery Health Check</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">48</td>
      <td>[Module 1] Battery Pack 1 Heating Status</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">49</td>
      <td>[Module 1] Battery Pack 2 Heating Status</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">50</td>
      <td>[Module 1] Battery Pack 3 Heating Status</td>
      <td align="center"></td>
   </tr>
</table>
<p><i>* [Module 1] can be [Module 1] to [Module 4] depending on your device.</i></p>
</details>

<details>
<summary><b><ins>Power Sensor</ins></b></summary>

<p><b>Power Sensor Signals</b></p>
<table>
   <tr>
      <td align="center"><b>#</b></td>
      <td><b>Entity Display Name</b></td>
      <td align="center"><b>Unit</b></td>
   </tr>
   <tr>
      <td align="center">1</td>
      <td>Meter Status</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">2</td>
      <td>Positive Active Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">3</td>
      <td>Negative Active Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">4</td>
      <td>Reactive Power</td>
      <td align="center">var</td>
   </tr>
   <tr>
      <td align="center">5</td>
      <td>Active Power</td>
      <td align="center">W</td>
   </tr>
   <tr>
      <td align="center">6</td>
      <td>Power Factor</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">7</td>
      <td>Phase A Active Power</td>
      <td align="center">W</td>
   </tr>
   <tr>
      <td align="center">8</td>
      <td>Phase B Active Power</td>
      <td align="center">W</td>
   </tr>
   <tr>
      <td align="center">9</td>
      <td>Phase C Active Power</td>
      <td align="center">W</td>
   </tr>
   <tr>
      <td align="center">10</td>
      <td>Phase A Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">11</td>
      <td>Phase B Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">12</td>
      <td>Phase C Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">13</td>
      <td>Phase A Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">14</td>
      <td>Phase B Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">15</td>
      <td>Phase C Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">16</td>
      <td>Grid Frequency</td>
      <td align="center">Hz</td>
   </tr>
</table>

<p><b>Emma A02 Signals</b></p>
<table>
   <tr>
      <td align="center"><b>#</b></td>
      <td><b>Entity Display Name</b></td>
      <td align="center"><b>Unit</b></td>
   </tr>
   <tr>
      <td align="center">1</td>
      <td>Forward Active Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">2</td>
      <td>Reverse Active Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">3</td>
      <td>Reactive Power</td>
      <td align="center">kvar</td>
   </tr>
   <tr>
      <td align="center">4</td>
      <td>Active Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">5</td>
      <td>Power Factor</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">6</td>
      <td>Phase A Active Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">7</td>
      <td>Phase B Active Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">8</td>
      <td>Phase C Active Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">9</td>
      <td>Phase A Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">10</td>
      <td>Phase B Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">11</td>
      <td>Phase C Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">12</td>
      <td>Phase A Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">13</td>
      <td>Phase B Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">14</td>
      <td>Phase C Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">15</td>
      <td>RS485-2 Port Mode</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">16</td>
      <td>WiFi Signal Strength</td>
      <td align="center">dBm</td>
   </tr>
   <tr>
      <td align="center">17</td>
      <td>Signal Strength</td>
      <td align="center">dBm</td>
   </tr>
</table>

<p><b>DTSU666-FE Signals</b></p>
<table>
   <tr>
      <td align="center"><b>#</b></td>
      <td><b>Entity Display Name</b></td>
      <td align="center"><b>Unit</b></td>
   </tr>
   <tr>
      <td align="center">1</td>
      <td>Communication Status</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">2</td>
      <td>AB Line Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">3</td>
      <td>BC Line Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">4</td>
      <td>CA Line Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">5</td>
      <td>Phase A Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">6</td>
      <td>Phase B Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">7</td>
      <td>Phase C Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">8</td>
      <td>Phase A Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">9</td>
      <td>Phase B Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">10</td>
      <td>Phase C Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">11</td>
      <td>Active Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">12</td>
      <td>Reactive Power</td>
      <td align="center">kVar</td>
   </tr>
   <tr>
      <td align="center">13</td>
      <td>Power Factor</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">14</td>
      <td>Phase A Active Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">15</td>
      <td>Phase B Active Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">16</td>
      <td>Phase C Active Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">17</td>
      <td>iAcMeter</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">18</td>
      <td>iAcMeter IP</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">19</td>
      <td>Comm Status</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">20</td>
      <td>iAcMeter Mode</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">21</td>
      <td>Meter Data Source</td>
      <td align="center"></td>
   </tr>
</table>
</details>

<details>
<summary><b><ins>Charger</ins></b></summary>

<p><b>Charging Pile Signals</b></p>
<table>
   <tr>
      <td align="center"><b>#</b></td>
      <td><b>Entity Display Name</b></td>
      <td align="center"><b>Unit</b></td>
   </tr>
   <tr>
      <td align="center">1</td>
      <td>Connector Number</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">2</td>
      <td>Connector Type</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">3</td>
      <td>Rated Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">4</td>
      <td>Status</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">5</td>
      <td>Relay Status</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">6</td>
      <td>Connector Temp</td>
      <td align="center">°C</td>
   </tr>
   <tr>
      <td align="center">7</td>
      <td>Phase A Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">8</td>
      <td>Phase C Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">9</td>
      <td>Phase B Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">10</td>
      <td>Output Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">11</td>
      <td>PWM Duty</td>
      <td align="center">%</td>
   </tr>
   <tr>
      <td align="center">12</td>
      <td>Connector Lock</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">13</td>
      <td>Working Mode</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">14</td>
      <td>Departure Time</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">15</td>
      <td>Planned Charge Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">16</td>
      <td>Connection Status</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">17</td>
      <td>Charging Duration</td>
      <td align="center">s</td>
   </tr>
</table>

<p><b>Charger Device Signals</b></p>
<table>
   <tr>
      <td align="center"><b>#</b></td>
      <td><b>Entity Display Name</b></td>
      <td align="center"><b>Unit</b></td>
   </tr>
   <tr>
      <td align="center">1</td>
      <td>FW Version</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">2</td>
      <td>HW Version</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">3</td>
      <td>Serial Number</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">4</td>
      <td>Rated Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">5</td>
      <td>Phase A Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">6</td>
      <td>Phase B Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">7</td>
      <td>Phase C Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">8</td>
      <td>Model</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">9</td>
      <td>Total Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">10</td>
      <td>Charger Temp</td>
      <td align="center">°C</td>
   </tr>
   <tr>
      <td align="center">11</td>
      <td>Port Count</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">12</td>
      <td>Bluetooth Name</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">13</td>
      <td>Device Status</td>
      <td align="center"></td>
   </tr>
</table>
</details>

<details>
<summary><b><ins>Plant</ins></b></summary>

<p><b>Plant Signals</b></p>
<table>
   <tr>
      <td align="center"><b>#</b></td>
      <td><b>Entity Display Name</b></td>
      <td align="center"><b>Unit</b></td>
   </tr>
   <tr>
      <td align="center">1</td>
      <td>Monthly Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">2</td>
      <td>Total Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">3</td>
      <td>Today Income</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">4</td>
      <td>Today Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">5</td>
      <td>Yearly Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">6</td>
      <td>Self Used Energy Today</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">7</td>
      <td>Consumption Today</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">8</td>
      <td>PV Self Consumption</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">9</td>
      <td>PV Feed-In Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">10</td>
      <td>Imported Grid Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">11</td>
      <td>Total Consumption</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">12</td>
      <td>Grid Import Ratio</td>
      <td align="center">%</td>
   </tr>
   <tr>
      <td align="center">13</td>
      <td>Self Consumption Ratio</td>
      <td align="center">%</td>
   </tr>
   <tr>
      <td align="center">14</td>
      <td>Self Consumption Ratio (by PV production)</td>
      <td align="center">%</td>
   </tr>
   <tr>
      <td align="center">15</td>
      <td>Flow Solar Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">16</td>
      <td>Flow Battery Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">17</td>
      <td>Flow Load Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">18</td>
      <td>Flow Buy Power</td>
      <td align="center">kW</td>
   </tr>
</table>
</details>

<details>
<summary><b><ins>BackupBox</ins></b></summary>

<p><b>BackupBox Signals</b></p>
<table>
   <tr>
      <td align="center"><b>#</b></td>
      <td><b>Entity Display Name</b></td>
      <td align="center"><b>Unit</b></td>
   </tr>
   <tr>
      <td align="center">1</td>
      <td>Status</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">2</td>
      <td>Grid A Phase Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">3</td>
      <td>Grid B Phase Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">4</td>
      <td>Grid C Phase Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">5</td>
      <td>Phase A Voltage of Backup Load</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">6</td>
      <td>Phase B Voltage of Backup Load</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">7</td>
      <td>Phase C Voltage of Backup Load</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">8</td>
      <td>Internal Ambient Temperature</td>
      <td align="center">°C</td>
   </tr>
</table>
</details>

<details>
<summary><b><ins>EMMA</ins></b></summary>

<p><b>EMMA Signals</b></p>
<table>
   <tr>
      <td align="center"><b>#</b></td>
      <td><b>Entity Display Name</b></td>
      <td align="center"><b>Unit</b></td>
   </tr>
   <tr>
      <td align="center">1</td>
      <td>Forward Active Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">2</td>
      <td>Reverse Active Energy</td>
      <td align="center">kWh</td>
   </tr>
   <tr>
      <td align="center">3</td>
      <td>Reactive Power</td>
      <td align="center">kvar</td>
   </tr>
   <tr>
      <td align="center">4</td>
      <td>Active Power</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">5</td>
      <td>Power Factor</td>
      <td align="center"></td>
   </tr>
   <tr>
      <td align="center">6</td>
      <td>Active Power Pa</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">7</td>
      <td>Active Power Pb</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">8</td>
      <td>Active Power Pc</td>
      <td align="center">kW</td>
   </tr>
   <tr>
      <td align="center">9</td>
      <td>Phase A Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">10</td>
      <td>Phase B Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">11</td>
      <td>Phase C Voltage</td>
      <td align="center">V</td>
   </tr>
   <tr>
      <td align="center">12</td>
      <td>Phase A Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">13</td>
      <td>Phase B Current</td>
      <td align="center">A</td>
   </tr>
   <tr>
      <td align="center">14</td>
      <td>Phase C Current</td>
      <td align="center">A</td>
   </tr>
</table>
</details>

</details>

# Changes in this fork

Compared with the original integration:

* **Charger control** (charging mode, cable lock, dynamic power), off by default. See [Charger control](#charger-control-experimental-off-by-default).
* **Charger history and diagnostic sensors**: session count and last session energy, duration, start and mode; the two PV thresholds the app does not display.
* **Request timeouts.** Every request now has a default timeout (10 s connect, 30 s read). Without one a stalled Huawei endpoint could block the login and Home Assistant's startup indefinitely.
* **Update interval option** (10-3600 s, default 15 s) instead of a hardcoded 15 s.
* **Battery values.** A value that merely contained a minus sign was replaced by 0, so a negative discharge power read as 0. Only the portal's "-" placeholder is treated as missing now.
* **NaN values.** `NaN` and infinity are no longer passed on as sensor values.
* **Startup.** A failed first refresh raises `ConfigEntryNotReady` so Home Assistant retries, instead of leaving the entry failed. Errors in the login/retry path are logged instead of being swallowed.
* **German translation** of the setup and options dialogs.
* **Safer schedule switching.** Nothing is written unless two reads agree on a complete list of repeating plans; the previous plans are logged and backed up before every write and restored automatically if they do not come back unchanged.
* **Login errors** now map to `ConfigEntryAuthFailed`/`ConfigEntryNotReady` instead of a generic failure, with a reauthentication step for a changed password.
* **Entity registry cleanup.** Turning charger control off, or updating from a version that had a writable power limit, removes the now-unused entities instead of leaving them behind as unavailable.
* **Tests** for the charger API layer and the charger entities (`python -m pytest tests`), which run without Home Assistant.

# Issues
This fork is maintained separately from the original. For anything related to the changes listed above (in particular charger control), please [open an issue on this fork](https://github.com/Matthias2703/FusionSolarPlus/issues) rather than the original repository. For anything else, the [original repository's issues](https://github.com/JortvanSchijndel/FusionSolarPlus/issues) are the right place.
Be sure to include as much relevant information as possible, this helps with troubleshooting and speeds up the resolution process.

# Development

To contribute or run FusionSolarPlus locally, follow these steps:

1. **Install VS Code:**  
   [Download and install Visual Studio Code](https://code.visualstudio.com/).

2. **Install Docker:**  
   [Download and install Docker](https://docs.docker.com/get-docker/).

3. **Clone the repository:**
   ```bash
   git clone https://github.com/Matthias2703/FusionSolarPlus.git && cd FusionSolarPlus && git checkout feature/charger-control
   ```

4. **Copy the dev container configuration:**
   ```bash
   cp .devcontainer/devcontainer.json.sample .devcontainer/devcontainer.json
   ```

5. **Open the project in VS Code:**
   ```bash
   code .
   ```

6. **Start the development container:**
   - Open the Command Palette (Mac: `Cmd+Shift+P`, Windows/Linux: `Ctrl+Shift+P`)
   - Type `Dev Containers: Rebuild and Reopen in Container` and press Enter.

This will set up a reproducible development environment with all dependencies installed and Home Assistant will be accessible at http://localhost:8123.

# ❤️ Sponsors

This fork is free and open source. If it's useful to you and you'd like to support the work on it, you can sponsor [Matthias2703](https://github.com/sponsors/Matthias2703) on GitHub Sponsors.

The entities and API layer this fork is built on come from the original FusionSolarPlus by [JortvanSchijndel](https://github.com/JortvanSchijndel) - consider sponsoring [his work](https://github.com/sponsors/JortvanSchijndel) too.

# Legal Notice
This integration for Home Assistant uses a custom modified version of [FusionSolarPy](https://github.com/jgriss/FusionSolarPy).


