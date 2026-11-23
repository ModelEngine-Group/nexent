FROM python:3.11-slim
WORKDIR /app
COPY server.py /app/server.py
USER 65534:65534
EXPOSE 18120
CMD ["python", "-B", "/app/server.py", "--host", "0.0.0.0", "--port", "18120"]
