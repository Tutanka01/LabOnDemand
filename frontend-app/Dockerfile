# Build : Node.js 24, LTS actuelle (maintenue jusqu'en avril 2028)
FROM node:24-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# nginx stable épinglé : nginx/nginx.conf utilise « server api:8000 resolve »,
# disponible seulement à partir de nginx 1.27.3.
FROM nginx:1.30.5-alpine
COPY --from=build /app/dist /usr/share/nginx/html
