# stable-alpine is a maintained tag (rebuilt with security fixes), unlike a
# pinned release such as 1.27-alpine whose OS packages stop being updated.
FROM nginxinc/nginx-unprivileged:stable-alpine

# Pull in any OS security fixes published since the base image was built,
# then drop back to the image's unprivileged user (uid 101).
USER root
RUN apk upgrade --no-cache
USER 101

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/public /usr/share/nginx/html
EXPOSE 8080
