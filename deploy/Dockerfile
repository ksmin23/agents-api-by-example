# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159
FROM ${PYTHON_IMAGE} AS packages
COPY .generated/index /srv
USER 65534:65534
CMD ["python", "-m", "http.server", "8080", "--directory", "/srv"]

FROM ${PYTHON_IMAGE} AS worker
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv && mkdir -p /workspace /evidence && chown -R 10001:10001 /opt/venv /workspace /evidence
ENV PATH="/opt/venv/bin:${PATH}"
COPY .generated/data /workspace
COPY .generated/requirements*.txt /opt/install/
COPY skills /opt/capabilities/skills
COPY native_hooks /opt/tutorial/native_hooks
COPY install_and_exec.py /opt/tutorial/install_and_exec.py
USER 10001:10001
WORKDIR /workspace
CMD ["python", "-c", "import time; time.sleep(3600)"]

FROM node:22-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da AS codex_binary
ARG CODEX_VERSION=0.167.0-alpha.3
RUN npm install -g @openai/codex@${CODEX_VERSION}

FROM worker AS executor
USER root
COPY --from=codex_binary /usr/local/bin/node /usr/local/bin/node
COPY --from=codex_binary /usr/local/lib/node_modules/@openai /usr/local/lib/node_modules/@openai
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex && mkdir -p /workspace/.codex && chown 10001:10001 /workspace/.codex
USER 10001:10001
ENV CODEX_HOME=/workspace/.codex
ENTRYPOINT ["/opt/venv/bin/python", "/opt/tutorial/install_and_exec.py"]
