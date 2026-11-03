FROM python:3.11-slim
WORKDIR /app
COPY services/notification-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/common/emitter.py ./emitter.py
COPY services/notification-service/main.py .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
