# Avelin Health: архитектура персонального агента

## Platform decision (2026-10-10)

The first release is a responsive web application backed by a VPS (Ubuntu planned). Desktop/Tauri and native iOS are deferred. The current localhost server and SQLite implement a development prototype; authentication, consent and server deployment are still pending. The sections below describe the target agent design, including features not yet implemented.

## Контекстные слои

1. **Health facts** — измерения, сон, питание, тренировки и самочувствие.
2. **Food catalog** — товары, магазины, цены, наличие, нутриенты и состав.
3. **User profile** — цели и подтверждённые пользователем ограничения.
4. **Memory** — наблюдаемые привычки и предпочтения с уровнем уверенности.
5. **Planner** — варианты действий с объяснением, почему они предложены.
6. **Delivery** — интерфейс и уведомления, которыми управляет пользователь.

## Инструменты LLM

Модель не получает прямой доступ к таблицам. Она вызывает узкие инструменты:

- `get_health_summary(period)`
- `get_sleep_trend(days)`
- `get_nutrition_gap(date)`
- `get_recent_workouts(days)`
- `search_store_products(store, constraints)`
- `compose_meal(targets, products, preferences)`
- `get_user_profile()`
- `propose_memory(fact, evidence, confidence)`
- `create_notification_draft(reason, scheduled_at)`

Инструменты возвращают агрегаты и происхождение данных. Отправка уведомления — отдельное подтверждаемое действие, а не побочный эффект ответа модели.

## Память пользователя

Каждый факт хранится отдельно и виден пользователю:

```text
fact: "Предпочитает ужины до 20 минут"
kind: preference
status: confirmed | inferred | rejected
confidence: 0.0–1.0
evidence: сообщения или повторяющиеся действия
created_at / last_confirmed_at / expires_at
```

Жёсткие ограничения (`allergy`, лекарства, диагнозы) модель не должна добавлять как подтверждённые самостоятельно. Пользователь может исправить или удалить любой факт. Наблюдения вроде боли или плохого самочувствия по умолчанию временны.

## Редактируемые измерения

Рост хранится в профиле, а талия и бицепс — как датированные ручные измерения. Они не выводятся моделью и не перезаписываются автоматически. LLM получает их только через `get_user_profile()` и `get_body_measurements(period)` вместе с датой и источником `manual`.

## Будущий импорт ZIP через сайт

Сервер принимает архив экспорта Apple Health, но не доверяет его содержимому:

- ограничивает размер загрузки и суммарный размер распаковки;
- блокирует абсолютные пути, `..` и zip-bomb;
- извлекает только ожидаемый `apple_health_export/export.xml`;
- проверяет XML-сигнатуру Apple Health;
- импортирует потоково и идемпотентно по стабильному идентификатору;
- удаляет временный архив после обработки;
- показывает прогресс и отчёт об изменениях;
- шифрует данные на диске и отделяет базы пользователей.

Повторная загрузка полного экспорта дополняет историю: уже известные записи пропускаются, новые добавляются. Это проще и надёжнее, чем пытаться вычислять дельту на телефоне.

## Проактивность

Правила и аналитика определяют, **когда** есть основание что-то предложить; LLM формулирует **как** это объяснить. Это делает поведение проверяемым:

```text
nutrition_gap(protein >= 35 g)
+ local_time near preferred_lunch_time
+ products available
+ notifications enabled
→ draft suggestion
→ rate-limit / quiet-hours check
→ notification
```

Никаких диагнозов, автоматических покупок или изменения медицинского поведения без явного участия пользователя.
