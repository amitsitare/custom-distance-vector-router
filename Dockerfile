FROM alpine:latest

# Install Python + networking tools
RUN apk add --no-cache python3 iproute2

# Copy file
COPY router.py /app/router.py

WORKDIR /app

ENV PYTHONUNBUFFERED=1

CMD ["python3", "-u", "router.py"]