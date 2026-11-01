# DockShift frontend

React + Vite + Tailwind interface for the DockShift backend.

## Run

The backend serves the built app, so the usual flow is just:

```bash
npm install
npm run build          # writes dist/, which FastAPI serves at /ui/
```

Then open <http://127.0.0.1:8000/ui/> with the backend running.

For live reloading while editing:

```bash
npm run dev            # http://localhost:3000, proxies /api to :8000
```

The dev server proxies `/api` and `/health` to `http://127.0.0.1:8000`, so there
is no CORS setup and no second origin to configure.

## Layout

```
src/
  App.tsx                 view routing and shared state
  dockshiftApi.ts         the only place that talks to the backend
  components/
    NavigationSidebar     left rail
    ScreenView            target, candidates, QSAR results
    LiteratureView        literature search
    CompareView           candidate comparison
    MolecularViewer       3Dmol viewer: pocket and interaction modes
    MolecularInspector    per-candidate detail
  lib/pocketModes.ts      pocket and contact selection, by distance from the ligand
  services/dockingService.ts
  types/docking.ts
```

`dist/` is committed so a clone serves the UI immediately. Rebuild after any
change to `src/`.

## Notes

- `dockshiftApi.ts` keeps predicted and measured potency in separate types, so a
  predicted value cannot be rendered as if it were experimental.
- The viewer selects the pocket by distance from ligand `55C`, not by chain id,
  because the chain assignment in 9Q14 is not verified here.
- Contacts are heavy-atom separations, not bonds. 9Q14 is a 3.0 Å cryo-EM
  structure, so hydrogens are unresolved and a hydrogen bond cannot be confirmed
  from those coordinates.
