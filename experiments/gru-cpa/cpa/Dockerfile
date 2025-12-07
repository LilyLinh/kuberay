# GRU-CPA Custom Pod Autoscaler Image
FROM python:3.10-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir \
    tensorflow==2.15.0 \
    numpy \
    requests

# Copy CPA scripts
COPY metric.py /app/
COPY evaluate.py /app/

# Copy pre-trained model (built during image build)
COPY model/ /app/model/

# Make scripts executable
RUN chmod +x /app/metric.py /app/evaluate.py

# Default environment variables
ENV PROMETHEUS_URL="http://prometheus-server.monitoring:9090"
ENV METRIC_NAME="ray_tasks"
ENV METRIC_STATE="PENDING_ARGS_AVAIL"
ENV SEQUENCE_LENGTH="60"
ENV CPUS_PER_POD="1"
ENV MIN_REPLICAS="1"
ENV MAX_REPLICAS="10"
ENV MODEL_PATH="/app/model/gru_model.h5"
ENV SCALER_PATH="/app/model/scaler_params.json"

