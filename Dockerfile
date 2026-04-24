FROM alpine:3.20

RUN apk add --no-cache python3 iproute2

COPY router.py /app/router.py

WORKDIR /app

ENV PYTHONUNBUFFERED=1

CMD ["python3", "-u", "router.py"]
