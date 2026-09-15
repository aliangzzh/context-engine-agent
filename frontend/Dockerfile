# Frontend image: build the Vue3 + Vite SPA, then serve the static bundle
# through Nginx, which also reverse-proxies /api and /health to the backend.
#
# Build & run from repo root:
#   docker compose build frontend
#   docker compose up frontend    # http://localhost:8080
FROM node:20-alpine AS build
WORKDIR /app

# package-lock.json is committed -> npm ci gives a reproducible install.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# vue-tsc type-check + vite build -> /app/dist
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
