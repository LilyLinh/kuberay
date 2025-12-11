FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir \
    tensorflow==2.15.0 \
    numpy==1.24.3 \
    requests==2.31.0

# Install kubectl for scaling RayCluster
RUN apt-get update && apt-get install -y curl && \
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    chmod +x kubectl && mv kubectl /usr/local/bin/ && \
    rm -rf /var/lib/apt/lists/*

# Copy CPA scripts
COPY metric.py /app/metric.py
COPY metric_simple.py /app/metric_simple.py
COPY evaluate.py /app/evaluate.py
COPY controller.py /app/controller.py

# Copy trained model (placed by build script)
COPY gru_model.keras /app/model/gru_model.keras
COPY scaler_params.json /app/model/scaler_params.json

RUN mkdir -p /tmp

# Make scripts executable
RUN chmod +x /app/*.py

CMD ["python3", "/app/controller.py"]
