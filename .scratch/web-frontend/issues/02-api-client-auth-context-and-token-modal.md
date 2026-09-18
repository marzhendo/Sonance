# 02: API Client, Auth Context, and Token Modal

**What to build:** An HTTP client wrapper and global authentication state that persists the API bearer token in browser storage, prompts the user via modal when missing or invalid, and attaches authorization headers to all requests.

**Blocked by:** 01: Project Setup, Tooling, and Theme Shell

**Status:** ready-for-agent

- [ ] API client wrapper in `lib/api.ts` supporting type-safe GET, POST, PUT, DELETE, and multipart requests.
- [ ] Bearer token persistence via `localStorage` with fallback to `NEXT_PUBLIC_API_TOKEN` environment variable.
- [ ] React Auth Context providing `token`, `setToken`, `clearToken`, and `isAuthenticated`.
- [ ] Global token input dialog appearing on 401 response or when unconfigured.
- [ ] Custom hook `useAuth` exposing auth state and actions.
