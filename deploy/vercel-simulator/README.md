# FieldSight simulator on Vercel

Production project: `shellhacks-relay-robotics`. Replace `YOUR_VERCEL_TEAM_SCOPE`
with the approved Vercel team scope in the commands below.
Assigned URL: https://shellhacks-relay-robotics.vercel.app

This is a static deployment of the rover, crawler and arm simulator. The exact
three Python simulation modules run inside a Pyodide Web Worker in each browser
tab. Vercel serves assets only: no server functions, provider credentials, robot
connections or shared mission database are deployed. Reloading clears that tab's
simulations and taught virtual poses. The full local mission lab and live arm
command-line tools remain separate.

The session banner offers **Reset all simulations**, including when the Python
worker cannot start. It reloads the tab to discard all three scenes and taught
virtual arm poses. Each scene also has a visible reset for that scene alone;
the text beside each control explains what it clears. This global reload-based
reset is hosted-only because the local FastAPI service retains server state.

Technology badges distinguish the running Python/Pyodide/WebAssembly and
React/TypeScript scenes from the separate recorded OpenJev/Pollard workflow.
The workflow evidence page labels Gemini's fixture role in those trials.

**Street inspection** on the same page (`/simulator#street-simulator`) adapts
the teammate's React scene from `Diego-Crawler-Plan` commit
`4d1e8ad1b474104824df5b8aaf8e187f7378a1f0`. It replays two existing synthetic
hazard fixtures: a pothole and standing water. Its clock, controls and evidence
preview are independent of the fleet and arm engines. It makes no live API or
model calls, connects no robot, and submits no observations to the team backend.

Use Node 24 or newer. From this directory:

```powershell
npm ci
npm run build
node test-runtime.mjs
node test-bridge.mjs
node --test ../../tests/test_simulator_ui.cjs ../../tests/test_arm_simulator_ui.cjs ../../tests/test_team_rover_demo.cjs
node prepare-vercel.mjs
npx vercel@60.1.3 deploy --prebuilt --prod --yes --scope YOUR_VERCEL_TEAM_SCOPE
```

The checkout must already be linked to the named project. For a new authorized
checkout, use `npx vercel@60.1.3 link --yes --scope YOUR_VERCEL_TEAM_SCOPE --project shellhacks-relay-robotics`.
Linking can create a local `.env.local` containing an OIDC token. It is ignored
and must never be printed, committed or uploaded. The prebuilt deployment sends
only the audited `.vercel/output` package; do not deploy the repository root.

`build.mjs` copies an explicit asset list into `dist/`. The simulation sources
are copied without alteration and their hashes are recorded in
`build-manifest.json`. Pyodide is pinned in the lockfile and hosted on this same
origin; runtime actions need no external requests. `prepare-vercel.mjs` rejects
linked output directories and secret/state paths before packaging static files.

The same `npm ci` / `npm run build` sequence also generates the ignored
`web/team-simulator/generated/street.js` bundle for the local FastAPI page,
then copies it into the static deployment. The build emits dependency licenses
under `licenses/`, bundle legal notices, and `team-simulator-provenance.json`
with the pinned upstream sources and adaptation notes. No separate team backend
or full dashboard is bundled.

To test the exact security headers locally, from the repository root run:

```powershell
.\.venv\Scripts\python.exe deploy/vercel-simulator/serve-preview.py
```

Open http://127.0.0.1:8771/simulator. Verify the browser-runtime ready banner,
fleet inspection/review/return, arm preset and teaching/replay, fault recovery,
street replay start/pause/reset and evidence details, and an empty browser error
log. On Vercel, `/` and `/simulator` open the simulator;
the arm is linked at `/simulator#arm-simulator`. There are no public server API
routes; the four simulator requests are handled locally by the page's worker.

The generated simulator navigation links to `/workflow-proof.html`, a static
HTML/CSS evidence page for the recorded September 26–27 OpenJev/pollard-jev
trials. It separates actual local inference, Gemini fixture roles, the offline
strategy comparison, and the browser simulator's modeled request comparison.
Only approved artifact names and SHA-256 hashes are published; no raw artifacts,
private endpoints, model worker, or inference controls are included. The local
FastAPI simulator has no link to this deployment-only proof page.
`node --test test-bridge.mjs` checks this asset boundary and the reference hashes.

Hosting uses the existing Pro plan; its subscription is not a new purchase.
The canonical spending ledger holds a separate conservative $1 allowance for
this project's first demo day, with actual hosting charges pending provider
billing. This reservation is not a Vercel invoice or a provider hard cap.
Review this task-only project after the demo before extending the planned
hosting period; unrelated projects and account-wide settings remain untouched.
