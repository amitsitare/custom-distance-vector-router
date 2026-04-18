FROM alpine:latest

# Install Python and networking tools
RUN apk add --no-cache python3 iproute2

# Copy router code
COPY router.py /app/router.py

WORKDIR /app

# Run router
CMD ["python3", "router.py"]