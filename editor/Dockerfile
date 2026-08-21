# Редактор рецептов в контейнере.
#
# Вольт внутрь образа НЕ кладётся и класть его нельзя: редактор существует ради
# того, чтобы менять файл, а копия в образе — это правки, которые никто не
# увидит. Вольт подключается томом:
#
#   docker build -t everselife-vault-editor editor
#   docker run --rm -p 8765:8765 \
#       -v /path/to/everselife-vault:/vault \
#       -v /path/to/everselife/vault:/repo/vault \
#       -v /path/to/everselife-vault/editor/backups:/backups \
#       everselife-vault-editor
#
# Проще — `docker compose -f editor/compose.yaml up`, там всё это уже
# описано.

FROM python:3.12-slim

# Единственная зависимость — та же, что у сборки вольта. Её же требует
# `tools/build.py`, который редактор запускает кнопками «Проверить» и «Собрать».
RUN pip install --no-cache-dir pyyaml==6.0.2

WORKDIR /app
COPY . /app

ENV EVERSELIFE_VAULT=/vault \
    EVERSELIFE_EDITOR_BACKUPS=/backups \
    EVERSELIFE_EDITOR_HOST=0.0.0.0 \
    PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8765

# Проверка живости заодно проверяет и главное: что вольт подключён и читается.
# Без тома контейнер поднимется, но покажет пустой экран — пусть лучше он сразу
# считается нездоровым.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/state', timeout=4).status == 200 else 1)"

CMD ["python", "server.py", "--no-browser"]
