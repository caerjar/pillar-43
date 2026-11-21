# Multi-stage: build the bundle with the full toolchain, ship only the output.
#
# The single-stage predecessor ran `vite preview` as the production server, so
# 485 MB of node_modules lived in the running image and Vite's own dev server
# WAS the runtime — which turned build-time CVEs (postcss/vite, two HIGH) into
# runtime exposure. dist/ is ~1.5 MB; the image was 1.35 GB. See the 2026-07-30
# audit.

FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# Build stamp — baked into the JS bundle via vite `define`.
ARG PILLAR43_VERSION=dev
ENV PILLAR43_VERSION=${PILLAR43_VERSION}
ARG PILLAR43_GIT_SHA=unknown
ARG PILLAR43_BUILT_AT=unknown
ENV PILLAR43_GIT_SHA=${PILLAR43_GIT_SHA}
ENV PILLAR43_BUILT_AT=${PILLAR43_BUILT_AT}

RUN npm run build


FROM nginx:1.27-alpine AS runtime

# Serves dist/ and proxies /api — replaces vite.config.ts's `preview.proxy`,
# which no longer runs now that Vite isn't the server.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

# Left as root deliberately: nginx:alpine's entrypoint writes the pid and temp
# paths at startup and then drops its workers to the unprivileged `nginx` user.
# Forcing USER here breaks /var/run/nginx.pid on boot.
EXPOSE 5173

CMD ["nginx", "-g", "daemon off;"]
