FROM nginx:1.28-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY *.html *.css *.js /usr/share/nginx/html/
EXPOSE 3000
