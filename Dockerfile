FROM python:3.11-slim
ENV TZ=Asia/Ho_Chi_Minh PYTHONUNBUFFERED=1 DATA_DIR=/var/lib/resolveai
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY web web
COPY scripts scripts
COPY evals evals
COPY data data
RUN useradd -r -u 10001 appuser && mkdir -p /var/lib/resolveai && chown appuser /var/lib/resolveai
USER appuser
EXPOSE 8000
# Một worker: bộ đếm giới hạn tần suất và khóa phiên nằm trong bộ nhớ tiến trình
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
