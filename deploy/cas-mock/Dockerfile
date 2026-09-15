FROM python:3.11-slim

WORKDIR /opt/cas-mock
COPY server.py ./server.py

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

RUN addgroup --system casmock && adduser --system --ingroup casmock casmock
USER casmock

CMD ["python", "server.py"]
