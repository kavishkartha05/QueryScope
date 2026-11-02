FROM node:20-slim

WORKDIR /app

# Copy manifests first to cache the npm install layer separately from source.
COPY package.json package-lock.json ./

RUN npm ci --ignore-scripts

COPY . .

# Vite bakes VITE_* values into the bundle at build time, so the API URL has to
# be a build argument (docker build --build-arg VITE_API_URL=https://api.example.com).
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL

# Build the Vite production bundle.
RUN npm run build

EXPOSE 4173

# --host 0.0.0.0 is required: Vite's preview server binds to localhost by
# default, which is unreachable from outside the container. The host flag
# makes it listen on all interfaces so Docker's port mapping works.
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0"]
