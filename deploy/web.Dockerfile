# Web image: the React build behind Nginx with HTTPS. Build context is the repository root:
#   docker build -f deploy/web.Dockerfile -t neurotlon-web:local .
FROM node:24-slim AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# Tests and typecheck read the shared contracts (e.g. participant-code.cases.json) at ../shared.
COPY shared/ /shared/
RUN npm run build

FROM nginx:stable-alpine AS runtime
RUN rm -f /etc/nginx/conf.d/default.conf
COPY deploy/nginx.conf /etc/nginx/conf.d/neurotlon.conf
COPY deploy/nginx/security-headers.conf /etc/nginx/neurotlon-security-headers.conf
COPY --from=build /web/dist /usr/share/nginx/html
# The certificate and key are mounted at run time (deploy/certs), never baked into the image.
EXPOSE 80 443
HEALTHCHECK --interval=10s --timeout=4s --start-period=10s --retries=3 \
    CMD wget -q --no-check-certificate -O /dev/null https://127.0.0.1/health || exit 1
