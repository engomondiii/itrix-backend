FROM nginx:stable-alpine
RUN apk add --no-cache ca-certificates
# Official entrypoint renders only the explicitly allowed environment variable.
COPY nginx.conf /etc/nginx/templates/default.conf.template
ENV NGINX_ENVSUBST_FILTER=^RAILWAY_WEB_HOST$
