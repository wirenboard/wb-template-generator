FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.title="wb-template-generator-frontend" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.source="https://github.com/wirenboard/wb-template-generator"
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80

# Проверка живости (/healthz) — в compose-файле: dev здесь, прод — в роли инфраструктуры.
