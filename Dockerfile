FROM python:3.7.7-slim-buster
MAINTAINER Dong Zhuang <dzhuang.scut@gmail.com>

COPY ["latex2pdf", "texlive_apt.list", "/opt/latex2pdf/"]
COPY extra_fonts /usr/share/fonts/extra_fonts
COPY zhmakeindex /usr/bin

RUN apt-get update \
    && apt-get install -y --no-install-recommends -qq nginx curl git memcached $(awk '{print $1'} /opt/latex2pdf/texlive_apt.list) \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f

COPY nginx.default /etc/nginx/sites-available/default
WORKDIR /opt/latex2pdf/
RUN ln -sf /dev/stdout /var/log/nginx/access.log \
    && ln -sf /dev/stderr /var/log/nginx/error.log \
    && echo gunicorn >> requirements.txt \
    && pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /opt/latex2pdf/tmp \
    && chown -R www-data:www-data /opt/latex2pdf

VOLUME /opt/latex2pdf/local_settings

# Fix lualatex https://github.com/overleaf/overleaf/pull/739/files
ENV TEXMFVAR=/opt/latex2pdf/tmp

EXPOSE 8030

# Start server
STOPSIGNAL SIGTERM
CMD ["/opt/latex2pdf/start-server.sh"]
