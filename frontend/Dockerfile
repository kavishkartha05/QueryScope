FROM node:20-slim

WORKDIR /app

# Copy manifests first to cache the npm install layer separately from source.
COPY package.json package-lock.json ./

RUN npm ci --ignore-scripts

COPY . .

# Build the Vite production bundle.
RUN npm run build

EXPOSE 4173

# --host 0.0.0.0 is required: Vite's preview server binds to localhost by
# default, which is unreachable from outside the container. The host flag
# makes it listen on all interfaces so Docker's port mapping works.
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0"]
