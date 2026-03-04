# Frontend – Vite + React

Interface oficial das ofertas de voos do **ScrapeAero**. O `web_app.py` serve apenas este frontend (build em `dist/`).

- **Stack:** Vite 7, React 19, TypeScript
- **API:** Flask em `http://localhost:5000` (proxy em dev)

## Desenvolvimento

1. Na raiz do projeto: `python web_app.py` (porta 5000).
2. Aqui no `frontend/`: `npm install` e `npm run dev` (porta 5173).
3. Acesse **http://localhost:5173**. O Vite faz proxy de `/api` para o Flask.

## Produção (uma única porta)

1. Aqui no `frontend/`: `npm run build`.
2. Na raiz do projeto: `python web_app.py`.
3. Acesse **http://localhost:5000** — a API e o frontend React são servidos juntos.

Se `frontend/dist` não existir, o Flask ainda sobe e a API responde; a rota `/` exibe instruções para rodar `npm run build`.

## Em outra máquina (clone / deploy)

A pasta `dist/` está no `.gitignore`, então **não é enviada** com o repositório. Na máquina onde for rodar o app:

1. `cd frontend`
2. `npm install`
3. `npm run build`
4. Volte à raiz e rode `python web_app.py`

Ou copie a pasta `frontend/dist` da máquina onde você já fez o build.
