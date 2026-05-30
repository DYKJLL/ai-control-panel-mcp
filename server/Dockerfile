FROM python:3.12-slim

WORKDIR /app

# Playwright 需要的系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk-bridge2.0-0 libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libatspi2.0-0 && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Chromium（playwright 内置）
RUN python -m playwright install chromium
RUN python -m playwright install-deps chromium

COPY . .

# 创建数据目录
RUN mkdir -p data/profiles data/vision_dir output

# 环境变量
ENV PYTHONUNBUFFERED=1

EXPOSE 1984

CMD ["python", "main.py"]
