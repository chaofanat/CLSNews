FROM python:3.12-slim

RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ARG INSTALL_LITELLM=false
RUN if [ "$INSTALL_LITELLM" = "true" ]; then pip install --no-cache-dir "litellm>=1.50"; fi

COPY . .
RUN mkdir -p db

CMD ["python", "server.py"]
