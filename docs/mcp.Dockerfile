# MCP server image for Glama introspection checks.
# Starts the Logica Mind MCP server over stdio; Glama sends initialize + tools/list
# and reads the 32 memory tools. No data needed — it just has to start and respond.
FROM python:3.11-slim
RUN pip install --no-cache-dir logica-mind
ENTRYPOINT ["logica-mind", "mcp"]
