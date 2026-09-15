FROM docker:27-cli
RUN apk add --no-cache python3
COPY updater.py /updater.py
EXPOSE 9000
CMD ["python3", "/updater.py"]
