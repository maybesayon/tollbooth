# Tollbooth dashboard

React + TypeScript + Vite. Built into `dist/` and served by the backend at `/dashboard` when
`TOLLBOOTH_DASHBOARD_DIR` points at it (the Docker image does this).

```bash
npm install
npm run dev        # http://localhost:5173/dashboard/, proxies /admin to TOLLBOOTH_API (default :8080)
npm test
npm run lint && npm run typecheck
npm run build
```

Sign in with the backend's `TOLLBOOTH_ADMIN_TOKEN`. The token lives in `sessionStorage` for the tab.
