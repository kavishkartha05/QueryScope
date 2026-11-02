# syntax=docker/dockerfile:1

# ---- build the static bundle ----------------------------------------------
FROM node:20-slim AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

COPY . .

# Vite bakes VITE_* values into the bundle at build time, so the API URL is a
# build argument (docker build --build-arg VITE_API_URL=https://api.example.com).
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# ---- serve it as static files (no vite preview) -----------------------------
FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
# Same port the Vite preview server used, so compose and k8s mappings still hold.
EXPOSE 4173
