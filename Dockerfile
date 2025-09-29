FROM n8nio/n8n:latest

USER root

# Cài Python, pip không dùng virtualenv
RUN apk update && apk add --no-cache python3 py3-pip

RUN apk add --no-cache \
    tesseract-ocr \
    tesseract-ocr-data-eng \
    py3-pillow
    
RUN pip3 install --break-system-packages --no-cache-dir pytesseract

# Cài các thư viện hệ thống cho cairosvg
RUN apk add --no-cache \
    cairo cairo-dev \
    pango pango-dev \
    gdk-pixbuf \
    libxml2 libxslt \
    freetype freetype-dev \
    harfbuzz fribidi fontconfig \
    libffi

# Cài Chromium và Driver
RUN apk add --no-cache \
    chromium \
    chromium-chromedriver \
    udev \
    ttf-freefont \
    dumb-init \
    py3-requests

# Cài Python packages vào hệ thống
RUN pip3 install --break-system-packages --no-cache-dir \
    selenium \
    pytesseract \
    cairosvg \
    numpy \
    pillow \
    python-docx

# Đặt path trình duyệt cho Selenium
ENV CHROME_BIN=/usr/bin/chromium-browser
ENV CHROMEDRIVER_PATH=/usr/lib/chromium/chromedriver

# Tạo thư mục scripts
RUN mkdir -p /data/scripts && chown -R node:node /data

USER node
