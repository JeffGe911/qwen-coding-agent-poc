FROM python:3.13.4-slim
COPY requirements-lock.txt /tmp/requirements-lock.txt
RUN pip install --no-cache-dir -r /tmp/requirements-lock.txt
WORKDIR /opt/agent
COPY pyproject.toml ./
COPY qwen_agent ./qwen_agent
RUN pip install --no-cache-dir --no-deps .
ENV PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1
USER 65534:65534

