FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Shell form to ensure $PORT is expanded by the shell
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
