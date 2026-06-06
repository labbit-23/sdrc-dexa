# dev-work (Legacy TypeScript Frontend)

⚠️ **This code is NOT actively used in production.**

## Purpose
This folder contains the original TypeScript implementation of the BMD/DEXA report frontend. The logic here (osteo-compute, bmd-compute, HTML templates) has been manually ported to JavaScript and is maintained in the separate [`sdrc-dexa-app`](../sdrc-dexa-app/) repository, which is the actual deployed application.

## Status
- **Not deployed** — The actual frontend runs from `sdrc-dexa-app/`
- **Not imported** — This code is not referenced anywhere in the active codebase
- **Kept for reference** — Preserved as documentation of the original TypeScript source

## If You Need To Use This
1. The compute logic (osteo-compute.ts, bmd-compute.ts) is synced with `sdrc-dexa-app/lib/` but manually
2. Consider consolidating back to a single source of truth instead of maintaining two copies
3. Or delete this folder entirely if it's no longer needed

## Related
- **Active frontend:** `../sdrc-dexa-app/` (JavaScript version, deployed to `/opt/sdrc/sdrc-dexa-app`)
- **Python worker:** `../worker/` (collector API that feeds data to the frontend)
