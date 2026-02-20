# Use a recent Ubuntu LTS as a base image
FROM ubuntu:22.04

# Set non-interactive frontend to avoid prompts during build
ENV DEBIAN_FRONTEND=noninteractive

# Install necessary dependencies: Python, Java, and common tools
RUN apt-get update && apt-get install -y 
    python3 
    openjdk-17-jdk 
    git 
    unzip 
    p7zip-full 
    && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Copy the entire project into the container
COPY . .

# Grant execute permissions to the binary tools
RUN chmod +x -R bin/linux/x86_64/

# Set Python 3 as the default python command
RUN ln -s /usr/bin/python3 /usr/bin/python

# The entrypoint is not set, as the script requires file paths from the host.
# The container should be run with `docker run` and volume mounts.
# See README.md for usage instructions.
LABEL description="Environment for ColorOS-Port-Python tool"
