# Receipt workspace frontend

React + TypeScript + Vite and Tailwind CSS, with local UI primitives under `src/components/ui`.

From this directory, run `npm ci` and `npm run dev`, then open
`http://127.0.0.1:5173/ui/` with a backend on port 8000. Run `npm run lint`,
`npm run test:unit`, and `npm run build` before submitting a change.
The production build is served by FastAPI at `/ui/` in the Docker image.

See [developer setup](../docs/setup.md) and the [frontend workflow](../docs/frontend.md)
for authentication, review, testing and deployment details.
