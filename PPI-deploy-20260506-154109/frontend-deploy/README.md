# PPI Calculator Frontend

This folder contains only the frontend entry page for the Feishu Base extension.

## Deploy

Upload `index.html` to a static hosting platform such as Replit, Vercel, or Cloudflare Pages.

## Configure Backend

Pass the backend URL as a query parameter:

```text
https://your-frontend-url/?backend=https%3A%2F%2Fyour-backend-url%2Frun-ppi&token=dev-token-change-me
```

For local testing:

```text
http://localhost:5173/?backend=http%3A%2F%2Flocalhost%3A8000%2Frun-ppi&token=dev-token-change-me
```

Do not put Feishu app secrets or LorealGPT credentials in this frontend.
