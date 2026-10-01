# --- deps stage(開發模式dev override會target到這一層，跑 `npm run dev` 而不build，
#     搭配bind mount達到熱更新，不需每次改前端都重新build image) ---
FROM node:20-alpine AS deps

WORKDIR /app

COPY package*.json ./
RUN npm ci

# --- build stage(正式環境用) ---
FROM deps AS build

COPY . .
RUN npm run build

# --- serve stage ---
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
# nginx.conf 不在此build context內(位於 config/docker/)，改由 docker-compose 以volume掛載

EXPOSE 80
