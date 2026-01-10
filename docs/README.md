# 📚 Документация проекта

## 🎯 Главные документы

### 1. [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) ⭐
**Полное описание системы** - начни отсюда!

Содержит:
- Общую архитектуру проекта
- Описание всех модулей, классов, методов
- Процесс обучения (end-to-end)
- MLflow интеграцию
- Исправления утечек данных
- Дальнейшие планы

### 2. [CONFIG_ARCHITECTURE_V2.md](CONFIG_ARCHITECTURE_V2.md)
Детальное описание конфигурационной системы (Hydra)

### 3. [ARCHITECTURE_PRINCIPLES.md](ARCHITECTURE_PRINCIPLES.md)
Принципы разделения конфигов и архитектурные решения

### 4. [LEAK_FIXES_SUMMARY.md](LEAK_FIXES_SUMMARY.md)
Описание исправления утечки данных (LogLoss 0.0000 → 0.70)

---

## 📊 Технические документы

### Фичи
- [FEATURE_GENERATION_ARCHITECTURE.md](FEATURE_GENERATION_ARCHITECTURE.md)
- [FEATURE_SYSTEM_QUICKSTART.md](FEATURE_SYSTEM_QUICKSTART.md)

### Данные
- [PREPROCESSING.md](PREPROCESSING.md)
- [MODELS_AND_TARGETS.md](MODELS_AND_TARGETS.md)

### Букмекерские данные
- [ODDS_ARCHITECTURE.md](ODDS_ARCHITECTURE.md)
- [TOTAL_RANGES.md](TOTAL_RANGES.md)

### История
- [CONFIG_V2_IMPLEMENTATION_SUMMARY.md](CONFIG_V2_IMPLEMENTATION_SUMMARY.md)
- [TRAINING_V2_SUCCESS.md](TRAINING_V2_SUCCESS.md)

---

## 🚀 Быстрый старт

1. **Изучи архитектуру:**
   ```bash
   cat docs/SYSTEM_ARCHITECTURE.md
   ```

2. **Запусти обучение:**
   ```bash
   make train
   ```

3. **Проверь MLflow:**
   ```bash
   make mlflow-ui
   # Открой http://127.0.0.1:5000
   ```

4. **Задай вопросы!**
   Если что-то непонятно - формируй список вопросов.

---

## 📝 Текущее состояние

✅ **Production Ready:**
- Утечка данных исправлена
- Метрики реалистичные (LogLoss ~0.68-0.76)
- TSCV + Shadow/Prod models работают
- MLflow интеграция полная
- Код чистый (без v2/v3 версий)
- Документация актуальна

⏳ **В разработке:**
- Stacking Ensemble (требует тестирования)
- Optuna оптимизация (модуль готов, не подключен)
- Калибровка (отключена для оценки baseline)

---

**Последнее обновление:** 10 января 2026
**Версия:** 2.0
