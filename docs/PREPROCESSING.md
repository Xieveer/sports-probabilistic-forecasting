# Preprocessing Pipeline для моделей

## 📋 **Обзор**

Разные модели машинного обучения имеют различные требования к предобработке данных:

| Модель | Категории | Пропуски | Масштабирование |
|--------|-----------|----------|------------------|
| **CatBoost** | ✅ Native | ✅ Native | ✅ Не нужно |
| **LightGBM** | ⚠️ Требует `category` dtype | ✅ Native | ✅ Не нужно |
| **LogisticRegression** | ❌ Нужен OneHotEncoder | ❌ Нужен Imputer | ❌ **КРИТИЧНО StandardScaler** |
| **Neural Networks** | ❌ Нужен Embedding/OneHot | ❌ Нужен Imputer | ❌ **КРИТИЧНО Normalization** |

---

## 🏗️ **Архитектура**

### **Базовый метод `_preprocess_data()`**

Каждая модель наследуется от `BaseSingleModel` и может переопределить метод `_preprocess_data()`:

```python
def _preprocess_data(
    self,
    X: pd.DataFrame,
    y: pd.Series | None = None,
    fit: bool = True,
) -> tuple[pd.DataFrame, pd.Series | None]:
    """
    Предобработка данных перед обучением/предсказанием.

    Args:
        X: Фичи.
        y: Таргет (для fit=True).
        fit: Если True, обучаем preprocessor. Если False, только трансформируем.

    Returns:
        Кортеж (X_transformed, y).
    """
    return X, y  # По умолчанию ничего не делает
```

### **Интеграция в `fit()` и `predict_proba()`**

```python
# В BaseSingleModel.fit()
X_processed, y_processed = self._preprocess_data(X, y, fit=True)
self._fit_implementation(X_processed, y_processed, **kwargs)

# В BaseSingleModel.predict_proba()
X_processed, _ = self._preprocess_data(X, y=None, fit=False)
proba = self.model_.predict_proba(X_processed)
```

---

## 🔧 **Реализации по моделям**

### **1. CatBoostModel**

**Не требует предобработки** — использует дефолтную реализацию.

```python
# _preprocess_data() не переопределяется
# CatBoost умеет работать с категориями и пропусками из коробки
```

---

### **2. LGBMModel**

**Конвертирует `object` → `category` dtype** для категориальных фичей.

```python
def _preprocess_data(
    self,
    X: pd.DataFrame,
    y: pd.Series | None = None,
    fit: bool = True,
) -> tuple[pd.DataFrame, pd.Series | None]:
    X = X.copy()

    # Конвертируем object -> category
    for col in X.columns:
        if X[col].dtype == "object":
            X[col] = X[col].astype("category")

    return X, y
```

**Почему:**
- LightGBM требует, чтобы категориальные фичи были явно помечены как `category` dtype
- Либо их нужно передавать в параметре `categorical_feature`

---

### **3. LogRegModel**

**Полный pipeline предобработки:**
- `StandardScaler` для числовых фичей
- `OneHotEncoder` для категориальных фичей

```python
def _preprocess_data(
    self,
    X: pd.DataFrame,
    y: pd.Series | None = None,
    fit: bool = True,
) -> tuple[pd.DataFrame, pd.Series | None]:
    if fit:
        # Определяем типы фичей
        self.numeric_features_ = [col for col in X.columns if X[col].dtype != "object"]
        self.categorical_features_ = [col for col in X.columns if X[col].dtype == "object"]

        # Создаём preprocessor
        transformers = []
        if self.numeric_features_:
            transformers.append(("num", StandardScaler(), self.numeric_features_))
        if self.categorical_features_:
            transformers.append((
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                self.categorical_features_,
            ))

        self.preprocessor_ = ColumnTransformer(
            transformers=transformers,
            remainder="drop",
        )

        # Обучаем preprocessor
        X_transformed = self.preprocessor_.fit_transform(X)
    else:
        # Только трансформируем
        X_transformed = self.preprocessor_.transform(X)

    # Преобразуем обратно в DataFrame
    feature_names = self.preprocessor_.get_feature_names_out()
    X_transformed = pd.DataFrame(X_transformed, columns=feature_names, index=X.index)

    return X_transformed, y
```

**Почему:**
- LogisticRegression **критично требует** масштабирования числовых фичей
- Категориальные фичи нужно конвертировать в OneHot (или Ordinal)
- `handle_unknown="ignore"` позволяет обрабатывать новые категории в inference

---

## 💾 **Сохранение и загрузка preprocessor**

### **Сохранение**

```python
def save(self, path: Path, version: str = "prod") -> None:
    # Сохраняем модель
    joblib.dump(self.model_, save_path)

    # Сохраняем preprocessor отдельно (если есть)
    if self.preprocessor_ is not None:
        preprocessor_path = path.parent / f"{path.stem}_{version}_preprocessor.pkl"
        joblib.dump(self.preprocessor_, preprocessor_path)
```

### **Загрузка**

```python
def load(self, path: Path) -> BaseSingleModel:
    # Загружаем модель
    self.model_ = joblib.load(path)

    # Загружаем preprocessor (если есть)
    preprocessor_path = path.parent / f"{path.stem}_preprocessor.pkl"
    if preprocessor_path.exists():
        self.preprocessor_ = joblib.load(preprocessor_path)

    self.is_fitted_ = True
    return self
```

**Структура файлов:**

```
models/uel_kz_1/
├── is_win_shadow.pkl               # Модель (shadow версия)
├── is_win_shadow_preprocessor.pkl  # Preprocessor (shadow версия)
├── is_win_prod.pkl                 # Модель (prod версия)
└── is_win_prod_preprocessor.pkl    # Preprocessor (prod версия)
```

---

## 🧪 **Тестирование**

### **Тесты для LogReg preprocessing**

```python
def test_logreg_preprocessing_numeric_only(sample_data):
    """Тест preprocessing LogReg с только числовыми фичами."""
    X, y = sample_data
    model = LogRegModel(params={"max_iter": 100})

    model.fit(X, y)

    assert model.preprocessor_ is not None
    assert len(model.numeric_features_) == X.shape[1]
    assert len(model.categorical_features_) == 0


def test_logreg_preprocessing_with_categorical(sample_data_with_cat):
    """Тест preprocessing LogReg с категориальными фичами."""
    X, y = sample_data_with_cat
    model = LogRegModel(params={"max_iter": 100})

    model.fit(X, y)

    assert model.preprocessor_ is not None
    assert len(model.numeric_features_) == 2
    assert len(model.categorical_features_) == 2

    # Предсказание должно работать даже с новыми категориями
    X_test = X.copy()
    X_test.loc[0, "f_cat_1"] = "NEW_CATEGORY"

    proba = model.predict_proba(X_test)
    assert proba.shape == (len(X_test), 2)


def test_logreg_save_load_with_preprocessor(sample_data_with_cat, tmp_path):
    """Тест сохранения/загрузки LogReg с preprocessor."""
    X, y = sample_data_with_cat
    model = LogRegModel(params={"max_iter": 100})

    model.fit(X, y)
    proba_before = model.predict_proba(X)

    # Сохранение
    save_path = tmp_path / "logreg_test"
    model.save(save_path, version="shadow")

    # Загрузка в новую модель
    model_loaded = LogRegModel()
    model_loaded.load(save_path.parent / "logreg_test_shadow.pkl")

    assert model_loaded.preprocessor_ is not None

    # Предсказания должны совпадать
    proba_after = model_loaded.predict_proba(X)
    np.testing.assert_array_almost_equal(proba_before, proba_after)
```

---

## 🚀 **Добавление новых моделей**

При добавлении новой модели (например, Neural Networks):

1. **Наследуйтесь от `BaseSingleModel`**
2. **Переопределите `_preprocess_data()`** если нужна предобработка
3. **Реализуйте `_create_model()`** и `_fit_implementation()`**
4. **Убедитесь, что preprocessor сохраняется/загружается**

### **Пример: Neural Network**

```python
class NeuralNetModel(BaseSingleModel):
    def _preprocess_data(
        self,
        X: pd.DataFrame,
        y: pd.Series | None = None,
        fit: bool = True,
    ) -> tuple[pd.DataFrame, pd.Series | None]:
        if fit:
            # Создаём pipeline:
            # - Imputer для пропусков
            # - StandardScaler для числовых фичей
            # - OneHotEncoder для категориальных фичей
            self.preprocessor_ = create_neural_net_preprocessor(X)
            X_transformed = self.preprocessor_.fit_transform(X)
        else:
            X_transformed = self.preprocessor_.transform(X)

        return X_transformed, y

    def _create_model(self):
        return build_pytorch_model(self.params)

    def _fit_implementation(self, X, y, **fit_kwargs):
        self.model_.fit(X, y, **fit_kwargs)
```

---

## ✅ **Преимущества подхода**

1. **Прозрачность** — вся логика предобработки в одном месте
2. **Гибкость** — каждая модель контролирует свою предобработку
3. **Масштабируемость** — легко добавлять новые модели
4. **MLOps-ready** — preprocessor сохраняется вместе с моделью
5. **Stacking поддержка** — каждая базовая модель обрабатывает данные сама

---

## 📊 **Примеры использования**

### **CatBoost (без preprocessing)**

```python
from sports_forecast.training.models.catboost import CatBoostModel

model = CatBoostModel(params={"iterations": 500})
model.fit(X_train, y_train)
proba = model.predict_proba(X_test)
```

### **LightGBM (автоматическая конвертация категорий)**

```python
from sports_forecast.training.models.lgbm import LGBMModel

model = LGBMModel(params={"n_estimators": 500})
model.fit(X_train, y_train)
proba = model.predict_proba(X_test)
```

### **LogisticRegression (полный preprocessing)**

```python
from sports_forecast.training.models.logreg import LogRegModel

model = LogRegModel(params={"C": 1.0, "penalty": "l2"})
model.fit(X_train, y_train)  # Автоматически применяется StandardScaler + OneHotEncoder
proba = model.predict_proba(X_test)

# Preprocessor сохраняется вместе с моделью
model.save(Path("models/logreg"), version="prod")
```

---

## 🔗 **См. также**

- `sports_forecast/training/base.py` — базовые классы
- `sports_forecast/training/models/logreg.py` — реализация LogReg preprocessing
- `sports_forecast/training/models/lgbm.py` — реализация LGBM preprocessing
- `tests/test_training.py` — тесты для preprocessing
