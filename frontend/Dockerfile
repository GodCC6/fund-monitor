# Stage 1: Build Vue3 app
FROM node:22-alpine AS build

WORKDIR /app

COPY package*.json .
RUN npm ci

COPY . .

# Empty VITE_API_URL = use relative URLs, Nginx proxies /api to backend
ENV VITE_API_URL=""
RUN npm run build

# Stage 2: Serve with Nginx
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
