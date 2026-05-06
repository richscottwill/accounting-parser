# frontend

React + TypeScript + Vite SPA for accounting-parser.

## Dev loop

```bash
pnpm install
pnpm test
pnpm dev     # http://localhost:3000 (proxies /api → http://localhost:8000)
```

## Scripts

| Command              | What it does                          |
| -------------------- | ------------------------------------- |
| `pnpm dev`           | Vite dev server on port 3000          |
| `pnpm build`         | Production build into `dist/`         |
| `pnpm test`          | Vitest single-run                     |
| `pnpm test:watch`    | Vitest watch mode                     |
| `pnpm lint`          | ESLint                                |
| `pnpm format`        | Prettier write                        |
| `pnpm format:check`  | Prettier check (CI)                   |
| `pnpm typecheck`     | tsc --noEmit                          |
