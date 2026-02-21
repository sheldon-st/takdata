# TAK Manager — Auth Frontend Brief

---

## What changed

The backend now requires authentication on every endpoint. Auth is handled at the infrastructure level (Traefik + Authentik) — **the frontend does not manage login, sessions, or tokens**. By the time the React app loads, the user is already authenticated. The frontend's only job is to:

1. Fetch the current user's identity and role from the API
2. Conditionally render or disable write controls based on role
3. Handle auth error responses gracefully
4. Provide a logout link

---

## Roles

Two roles exist. The API returns one of these strings from `GET /api/v1/me`:

| Role       | Can do                                  |
| ---------- | --------------------------------------- |
| `"admin"`  | Everything — read + write + delete      |
| `"viewer"` | Read-only — no mutations, no start/stop |

---

## New endpoint

### `GET /api/v1/me`

Call once on app load. No request body. Returns:

```json
{ "username": "alice", "role": "admin" }
```

- `username` — display name from the identity provider
- `role` — always `"admin"` or `"viewer"`

**If this request fails with `401`**: the session has expired. Call `window.location.reload()` — Traefik will redirect the browser to the login page automatically.

---

## No login page

Do not build a login page or any auth flow. If a user is unauthenticated, Traefik redirects them to the Authentik login page before the React app ever loads. The app can assume the user is always authenticated when it renders.

---

## Logout

Add a logout link in the nav/header pointing to:

```
https://auth.opengeo.space/application/o/tak-manager/end-session/
```

This is a plain `<a href>` — no JavaScript needed. After logout the user is redirected to the Authentik login page.

---

## Auth context

Fetch `/api/v1/me` once on load and store the result in a React context. All components read from this context — no prop-drilling.

```tsx
// src/context/AuthContext.tsx
import { createContext, useContext } from "react";
import { useQuery } from "@tanstack/react-query";

type User = { username: string; role: "admin" | "viewer" };

const AuthContext = createContext<User | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { data: user, isLoading } = useQuery<User>({
    queryKey: ["me"],
    queryFn: () =>
      fetch("/api/v1/me").then((r) => {
        if (!r.ok) throw Object.assign(new Error(), { status: r.status });
        return r.json();
      }),
    staleTime: Infinity, // role doesn't change mid-session
    retry: false,
  });

  if (isLoading) return <AppLoadingShell />;

  return (
    <AuthContext.Provider value={user ?? null}>{children}</AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
export const useIsAdmin = () => useAuth()?.role === "admin";
```

Wrap the app root in `<AuthProvider>` above the router.

---

## AdminOnly component

Gate every write control behind this component:

```tsx
// src/components/AdminOnly.tsx
import { useIsAdmin } from "@/context/AuthContext";

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

export function AdminOnly({ children, fallback = null }: Props) {
  return useIsAdmin() ? <>{children}</> : <>{fallback}</>;
}
```

---

## Global error handling

Add these to your TanStack Query client config. The API returns `401` if the session expires mid-use, and `403` if a viewer somehow hits an admin endpoint.

```ts
// src/lib/queryClient.ts
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error: any) => {
        if (error?.status === 401 || error?.status === 403) return false;
        return count < 2;
      },
    },
    mutations: {
      onError: (error: any) => {
        if (error?.status === 401) window.location.reload();
        if (error?.status === 403) toast.error("Admin access required");
      },
    },
  },
});
```

Make sure your API fetch wrapper surfaces a `status` field on errors:

```ts
async function apiFetch(path: string, init?: RequestInit) {
  const res = await fetch(`/api/v1${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw Object.assign(new Error(body.detail ?? res.statusText), {
      status: res.status,
    });
  }
  return res.status === 204 ? null : res.json();
}
```

---

## Nav / header additions

```tsx
function NavHeader() {
  const user = useAuth();
  return (
    <header>
      {/* existing nav items */}
      <div className="ml-auto flex items-center gap-4">
        <span className="text-sm text-muted-foreground">{user?.username}</span>
        <a
          href="https://auth.opengeo.space/application/o/tak-manager/end-session/"
          className="text-sm"
        >
          Sign out
        </a>
      </div>
    </header>
  );
}
```

---

## What to gate per page

Apply `<AdminOnly>` to every write action. Viewers see a read-only version of the app — data is always visible, controls that would mutate it are not.

### Dashboard (`/`)

| Control                            | Who sees it |
| ---------------------------------- | ----------- |
| Connect button                     | Admin only  |
| Disconnect button                  | Admin only  |
| Start / Stop toggle per enablement | Admin only  |
| All status data (WS stream)        | Everyone    |

### TAK Server Settings (`/settings/tak`)

| Control                      | Who sees it |
| ---------------------------- | ----------- |
| Save button                  | Admin only  |
| Cert upload button           | Admin only  |
| Delete button per cert       | Admin only  |
| Connect / Reconnect button   | Admin only  |
| Config fields (read display) | Everyone    |
| Cert list (read display)     | Everyone    |

### Enablements list (`/enablements`)

| Control                         | Who sees it |
| ------------------------------- | ----------- |
| New Enablement button           | Admin only  |
| Start / Stop button per card    | Admin only  |
| Edit button                     | Admin only  |
| Delete button                   | Admin only  |
| Enablement cards (read display) | Everyone    |

### Enablement detail (`/enablements/:id`)

| Control                       | Who sees it                                       |
| ----------------------------- | ------------------------------------------------- |
| Config form fields (editable) | Admin only — show as read-only display for viewer |
| Save button                   | Admin only                                        |
| Add Source button             | Admin only                                        |
| Edit source                   | Admin only                                        |
| Delete source                 | Admin only                                        |
| Source enabled toggle         | Admin only                                        |
| Live status panel             | Everyone                                          |

### Packages (`/packages`)

| Control                   | Who sees it |
| ------------------------- | ----------- |
| Upload area               | Admin only  |
| Delete button per package | Admin only  |
| Download button / link    | Everyone    |
| Package list              | Everyone    |

---

## WebSocket

No changes. The WebSocket connection at `wss://data.opengeo.space/api/v1/ws/status` is authenticated via the Authentik session cookie, which the browser sends automatically on the upgrade request. Connect as before on app load.

If the WebSocket closes unexpectedly (including due to a `4403` close code from an expired session), treat it as a normal disconnect: show the reconnecting banner and retry with exponential backoff. A successful reconnect means the session is still valid. A persistent failure will resolve itself when the user reloads the page and re-authenticates.

---

## Summary checklist

- [ ] `GET /api/v1/me` called on app load, result stored in `AuthContext`
- [ ] `useIsAdmin()` / `<AdminOnly>` used to gate all write controls
- [ ] Username shown in nav header
- [ ] Logout link in nav pointing to Authentik end-session URL
- [ ] `401` → `window.location.reload()` in global error handler
- [ ] `403` → toast "Admin access required" in global error handler
- [ ] No login page built
- [ ] `packages-frontend-brief.md` note about "no auth" disregarded
