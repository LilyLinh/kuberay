# Benchmark workload image for GRU-CPA experiments
FROM rayproject/ray:2.9.0-py310

WORKDIR /app

# Install additional dependencies
RUN pip install --no-cache-dir numpy

# Copy benchmark script
COPY ray_tune_benchmark.py /app/

# Set entrypoint
ENTRYPOINT ["python", "/app/ray_tune_benchmark.py"]

