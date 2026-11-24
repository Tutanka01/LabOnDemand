# Stage 1: type-check and build the Vite bundle.
FROM node:20-alpine AS build
WORKDIR /app
# Install dependencies first so this layer is reused when only sources change.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tsconfig.json vite.config.ts index.html ./
COPY public ./public
COPY src ./src
RUN npm run build

# Stage 2: static files served by nginx. The server config (SPA fallback,
# caching, /api/ proxy) is nginx/nginx.conf, mounted by compose.yaml.
# nginx >= 1.27.3 is required for "server ... resolve" in the upstream block.
FROM nginx:1.28-alpine
COPY --from=build /app/dist /usr/share/nginx/html
