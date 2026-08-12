FROM python:3.11-slim

# Security: Create non-root user
RUN groupadd -r optirc && useradd -r -g optirc -s /bin/false optirc

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml .
COPY src/ ./src/

# Install dependencies
RUN uv pip install --system -e .

# Security: Remove write permissions
RUN chmod -R 555 /app/src && \
    mkdir -p /app/uploads /app/data && \
    chown -R optirc:optirc /app/uploads /app/data

# Switch to non-root user
USER optirc

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/v1/health')" || exit 1

# Run API
CMD ["uv", "run", "python", "-m", "optirc.api.main"]
