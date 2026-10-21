FROM eclipse-temurin:17-jre-jammy
ARG JENA_VERSION=5.3.0
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fSL --retry 3 "https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-${JENA_VERSION}.tar.gz" -o /tmp/fuseki.tar.gz \
    && curl -fSL --retry 3 "https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-${JENA_VERSION}.tar.gz.sha512" -o /tmp/fuseki.sha512 \
    && expected=$(awk '{print $1}' /tmp/fuseki.sha512) \
    && echo "$expected  /tmp/fuseki.tar.gz" | sha512sum -c - \
    && mkdir -p /opt/fuseki /data/database \
    && tar -xzf /tmp/fuseki.tar.gz --strip-components=1 -C /opt/fuseki \
    && useradd --system --uid 10001 fuseki && chown -R fuseki:fuseki /data /opt/fuseki \
    && rm -rf /tmp/fuseki.* /var/lib/apt/lists/*
WORKDIR /opt/fuseki
USER fuseki
ENV FUSEKI_BASE=/data
ENV JVM_ARGS="-Xms64m -Xmx512m -XX:ActiveProcessorCount=2"
EXPOSE 3030
CMD ["sh", "-c", "mkdir -p /data/database && exec ./fuseki-server --update --tdb2 --loc=/data/database /counteruav"]
