FROM python:3.12-slim
RUN pip install --no-cache-dir websockets==15.0.1
WORKDIR /app
COPY serve_boxing.py /app/serve_boxing.py
USER nobody
EXPOSE 8790
CMD ["python", "serve_boxing.py", "--host", "0.0.0.0", "--port", "8790"]
