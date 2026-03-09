FROM registry.access.redhat.com/ubi9/python-311:1-66.1720018730

# Install git (needed for GitHub MCP server operations) and github-mcp-server binary
USER 0
RUN dnf install -y git-core && dnf clean all && \
    curl -L https://github.com/github/github-mcp-server/releases/download/v0.2.0/github-mcp-server_Linux_x86_64.tar.gz \
    | tar xz -C /usr/local/bin github-mcp-server && \
    chmod +x /usr/local/bin/github-mcp-server
USER 1001

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent source
COPY *.py .

CMD ["python", "agent.py"]
