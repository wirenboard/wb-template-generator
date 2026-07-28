FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
# PRJ-1089 pilot: git-SHA как метка образа (якорь отката/аудита)
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.title="wb-template-generator-frontend" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.source="https://github.com/wirenboard/wb-template-generator"
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80

# Раньше healthcheck у фронта не было вовсе → rolling-update «слепой» (Swarm/compose
# не видят, поднялся ли контейнер). Добавлен лёгкий /healthz в nginx (см. nginx.conf).
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=5s \
  CMD wget -qO- http://localhost/healthz >/dev/null 2>&1 || exit 1
