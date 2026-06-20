FROM wordpress:php8.2-apache

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    default-mysql-client \
    less \
    openssh-server \
  && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /usr/local/bin/wp https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar \
  && chmod +x /usr/local/bin/wp \
  && wp --allow-root --info >/dev/null

COPY entrypoint.sh /usr/local/bin/wp-media-sync-docker-entrypoint.sh
RUN chmod +x /usr/local/bin/wp-media-sync-docker-entrypoint.sh

ENTRYPOINT ["wp-media-sync-docker-entrypoint.sh"]
CMD ["apache2-foreground"]
