FROM public.ecr.aws/lambda/python:3.11

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR ${LAMBDA_TASK_ROOT}

COPY pyproject.toml README.md ./
COPY polyautomate ./polyautomate

RUN pip install --no-cache-dir .[deploy]

CMD ["polyautomate.runtime.lambda_handlers.executor_handler"]
