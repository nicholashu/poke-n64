FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential binutils-mips-linux-gnu gcc-mips-linux-gnu \
    git ca-certificates curl wget unzip pkg-config \
    python3 python3-pip python3-venv libxml2-dev libpng-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /project
# Bind-mount the repo and supply a locally dumped base ROM at runtime.
# No copyrighted input or generated ROM is copied into the image.
CMD ["make", "test"]
