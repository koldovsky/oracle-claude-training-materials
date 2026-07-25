FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

# Java — потрібна для SQLcl (мінімум 17). Ставимо 21 LTS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      openjdk-21-jre-headless \
      unzip \
 && rm -rf /var/lib/apt/lists/*

# SQLcl — і CLI до Oracle, і MCP-сервер для Claude Code (`sql -mcp`).
# Посилання віддає завжди актуальну версію без автентифікації.
RUN curl -fsSL -o /tmp/sqlcl.zip \
      https://download.oracle.com/otn_software/java/sqldeveloper/sqlcl-latest.zip \
 && unzip -q /tmp/sqlcl.zip -d /opt \
 && rm /tmp/sqlcl.zip \
 && chmod +x /opt/sqlcl/bin/sql \
 && ln -sf /opt/sqlcl/bin/sql /usr/local/bin/sql

# Перевіряємо на етапі збірки — краще впасти тут, ніж у сесії учасника
RUN sql -V
