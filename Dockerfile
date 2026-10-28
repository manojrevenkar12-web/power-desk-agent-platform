# One build, two images (both linux/arm64), pushed by CI as <version>-lambda and <version>-runtime.
#   lambda : the tool Lambda and the gateway interceptors (handler chosen by the function's CMD)
#   runtime: the desk agent on AgentCore Runtime (POST /invocations, GET /ping on port 8080)

FROM public.ecr.aws/lambda/python:3.13-arm64 AS lambda
COPY pyproject.toml README.md ${LAMBDA_TASK_ROOT}/
COPY src ${LAMBDA_TASK_ROOT}/src
RUN pip install --no-cache-dir ${LAMBDA_TASK_ROOT} --target ${LAMBDA_TASK_ROOT} \
 && rm -rf ${LAMBDA_TASK_ROOT}/src
COPY config ${LAMBDA_TASK_ROOT}/config
COPY policies ${LAMBDA_TASK_ROOT}/policies
COPY kb ${LAMBDA_TASK_ROOT}/kb
COPY skills ${LAMBDA_TASK_ROOT}/skills
ENV POWERDESK_ROOT=${LAMBDA_TASK_ROOT}
CMD ["powerdesk.aws.tool_lambda.handler"]

FROM python:3.13-slim AS runtime
RUN useradd --create-home --uid 10001 desk
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && rm -rf src
COPY config ./config
COPY policies ./policies
COPY kb ./kb
COPY skills ./skills
ENV POWERDESK_ROOT=/app PYTHONUNBUFFERED=1
USER desk
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ping')"
CMD ["uvicorn", "powerdesk.aws.runtime_app:app", "--host", "0.0.0.0", "--port", "8080"]
