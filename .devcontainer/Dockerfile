FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

# Java — потрібна для SQLcl (мінімум 17). Ставимо 21 LTS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      openjdk-21-jre-headless \
      unzip \
 && rm -rf /var/lib/apt/lists/*

# SQLcl — і CLI до Oracle, і MCP-сервер для Claude Code (`sql -mcp`).
# Посилання віддає завжди актуальну версію без автентифікації.
#
# ВАЖЛИВО: архів розпаковується з правами -rw-r----- root:root, тобто
# jar-и недоступні на читання звичайному користувачу. Контейнер працює
# під vscode, і без chmod нижче SQLcl падає з
#   Could not find or load main class oracle.dbtools.raptor...SqlCli
# що виглядає як зламаний classpath, а насправді — права доступу.
RUN curl -fsSL -o /tmp/sqlcl.zip \
      https://download.oracle.com/otn_software/java/sqldeveloper/sqlcl-latest.zip \
 && unzip -q /tmp/sqlcl.zip -d /opt \
 && rm /tmp/sqlcl.zip \
 && chmod -R a+rX /opt/sqlcl \
 && chmod a+x /opt/sqlcl/bin/sql \
 && ln -sf /opt/sqlcl/bin/sql /usr/local/bin/sql

# Перевірка збірки — саме від імені користувача, який запускатиме SQLcl.
# Перевіряємо ВИВІД, а не код виходу: при помилці класу `sql -V`
# усе одно повертає 0, тому проста наявність команди нічого не доводить.
USER vscode
RUN sql -V 2>&1 | tee /tmp/sqlcl-check.txt | grep -qiE 'release|[0-9]+\.[0-9]+' \
    || { echo "SQLcl не працює під користувачем vscode:"; cat /tmp/sqlcl-check.txt; exit 1; }
USER root
