FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /service

COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock

COPY app ./app
COPY scenarios ./scenarios

RUN useradd --create-home --uid 10001 mockuser && chown -R mockuser:mockuser /service
USER mockuser

EXPOSE 8888

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8888"]

