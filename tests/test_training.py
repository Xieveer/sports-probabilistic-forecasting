"""
Тесты для системы обучения моделей.

Покрывают:
- TimeSeriesCrossValidator
- Базовые модели (Dummy, CatBoost)
- Калибратор
- Базовые операции (fit, predict_proba, save, load)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sports_forecast.training.calibration import ModelCalibrator
from sports_forecast.training.models.catboost import CatBoostModel
from sports_forecast.training.models.dummy import DummyModel
from sports_forecast.training.models.logreg import LogRegModel
from sports_forecast.training.optimization.tscv import TimeSeriesCrossValidator


# ==================== Fixtures ====================


@pytest.fixture
def sample_data():
    """Создать тестовые данные для обучения."""
    np.random.seed(777)

    n_samples = 200
    n_features = 10

    X = pd.DataFrame(
        np.random.randn(n_samples, n_features),
        columns=[f"f_{i}" for i in range(n_features)],
    )

    # Бинарный таргет (50/50)
    y = pd.Series(np.random.randint(0, 2, n_samples))

    return X, y


@pytest.fixture
def sample_data_with_cat():
    """Создать тестовые данные с категориальными фичами."""
    np.random.seed(777)

    n_samples = 200

    X = pd.DataFrame(
        {
            "f_numeric_1": np.random.randn(n_samples),
            "f_numeric_2": np.random.randn(n_samples),
            "f_cat_1": np.random.choice(["A", "B", "C"], n_samples),
            "f_cat_2": np.random.choice(["X", "Y"], n_samples),
        }
    )

    y = pd.Series(np.random.randint(0, 2, n_samples))

    return X, y


# ==================== TSCV Tests ====================


def test_tscv_initialization():
    """Тест инициализации TSCV."""
    tscv = TimeSeriesCrossValidator(n_splits=4)
    assert tscv.n_splits == 4
    assert tscv.test_size == 0.1


def test_tscv_split(sample_data):
    """Тест разбиения данных на фолды."""
    X, y = sample_data
    tscv = TimeSeriesCrossValidator(n_splits=4)

    folds = list(tscv.split(X, y))

    # Должно быть 4 фолда
    assert len(folds) == 4

    # Каждый фолд должен иметь train и val индексы
    for train_idx, val_idx in folds:
        assert len(train_idx) > 0
        assert len(val_idx) > 0
        # Train и val не должны пересекаться
        assert len(set(train_idx) & set(val_idx)) == 0


def test_tscv_expanding_window(sample_data):
    """Тест expanding window (train растёт с каждым фолдом)."""
    X, y = sample_data
    tscv = TimeSeriesCrossValidator(n_splits=4)

    folds = list(tscv.split(X, y))

    # Train должен расти с каждым фолдом
    train_sizes = [len(train_idx) for train_idx, _ in folds]
    assert train_sizes == sorted(train_sizes)  # Возрастающая последовательность


# ==================== DummyModel Tests ====================


def test_dummy_model_initialization():
    """Тест инициализации DummyModel."""
    model = DummyModel(name="dummy_test")
    assert model.name == "dummy_test"
    assert not model.is_fitted()


def test_dummy_model_fit_predict(sample_data):
    """Тест обучения и предсказания DummyModel."""
    X, y = sample_data
    model = DummyModel()

    # Обучение
    model.fit(X, y)
    assert model.is_fitted()

    # Предсказание
    proba = model.predict_proba(X)
    assert proba.shape == (len(X), 2)
    assert np.allclose(proba.sum(axis=1), 1.0)  # Сумма вероятностей = 1


def test_dummy_model_predicts_class_frequencies(sample_data):
    """Тест что DummyModel предсказывает частоты классов."""
    X, y = sample_data
    model = DummyModel()

    model.fit(X, y)
    proba = model.predict_proba(X)

    # Все предсказания должны быть одинаковыми (частоты классов)
    assert np.allclose(proba[0], proba[1])

    # Вероятности должны соответствовать частотам в y
    expected_freq_class_1 = y.mean()
    assert np.isclose(proba[0, 1], expected_freq_class_1, atol=0.01)


# ==================== CatBoostModel Tests ====================


def test_catboost_model_initialization():
    """Тест инициализации CatBoostModel."""
    model = CatBoostModel(name="catboost_test")
    assert model.name == "catboost_test"
    assert not model.is_fitted()


def test_catboost_model_fit_predict(sample_data):
    """Тест обучения и предсказания CatBoostModel."""
    X, y = sample_data
    model = CatBoostModel(params={"iterations": 10, "verbose": False})

    # Обучение
    model.fit(X, y)
    assert model.is_fitted()

    # Предсказание
    proba = model.predict_proba(X)
    assert proba.shape == (len(X), 2)
    assert np.allclose(proba.sum(axis=1), 1.0)


def test_catboost_model_with_categorical_features(sample_data_with_cat):
    """Тест CatBoost с категориальными фичами."""
    X, y = sample_data_with_cat
    model = CatBoostModel(params={"iterations": 10, "verbose": False})

    # Обучение (автоматически определит категориальные фичи)
    model.fit(X, y)
    assert model.is_fitted()

    # Должны быть найдены категориальные фичи
    assert len(model.cat_features_) == 2
    assert "f_cat_1" in model.cat_features_
    assert "f_cat_2" in model.cat_features_


def test_catboost_model_feature_importance(sample_data):
    """Тест получения важности фичей."""
    X, y = sample_data
    model = CatBoostModel(params={"iterations": 10, "verbose": False})

    model.fit(X, y)

    importance = model.get_feature_importance()
    assert isinstance(importance, pd.DataFrame)
    assert "feature" in importance.columns
    assert "importance" in importance.columns
    assert len(importance) == X.shape[1]


# ==================== LogRegModel Tests ====================


def test_logreg_model_fit_predict(sample_data):
    """Тест обучения и предсказания LogRegModel."""
    X, y = sample_data
    model = LogRegModel(params={"max_iter": 100})

    model.fit(X, y)
    assert model.is_fitted()

    proba = model.predict_proba(X)
    assert proba.shape == (len(X), 2)


# ==================== ModelCalibrator Tests ====================


def test_calibrator_initialization():
    """Тест инициализации ModelCalibrator."""
    calibrator = ModelCalibrator(threshold_ece=0.1, method="isotonic")
    assert calibrator.threshold_ece == 0.1
    assert calibrator.method == "isotonic"


def test_calibrator_no_calibration_needed(sample_data):
    """Тест что калибровка не применяется если ECE < threshold."""
    X, y = sample_data

    # Разбиваем данные
    split_idx = int(len(X) * 0.6)
    X_train = X.iloc[:split_idx]
    X_cal = X.iloc[split_idx : int(len(X) * 0.8)]
    X_val = X.iloc[int(len(X) * 0.8) :]
    y_train = y.iloc[:split_idx]
    y_cal = y.iloc[split_idx : int(len(y) * 0.8)]
    y_val = y.iloc[int(len(y) * 0.8) :]

    # Обучаем LogReg (обычно хорошо откалиброван)
    model = LogRegModel()
    model.fit(X_train, y_train)

    # Калибратор с высоким порогом
    calibrator = ModelCalibrator(threshold_ece=0.5, method="isotonic")

    calibrated_model, is_calibrated, ece_before, ece_after = calibrator.calibrate_if_needed(
        model, X_cal, y_cal, X_val, y_val
    )

    # Калибровка не должна была применяться
    assert not is_calibrated
    assert ece_before is not None
    assert ece_after is None


# ==================== Save/Load Tests ====================


def test_model_save_load(sample_data, tmp_path):
    """Тест сохранения и загрузки модели."""
    X, y = sample_data

    # Обучаем модель
    model = CatBoostModel(params={"iterations": 10, "verbose": False})
    model.fit(X, y)

    # Предсказания до сохранения
    proba_before = model.predict_proba(X)

    # Сохраняем
    save_path = tmp_path / "test_model"
    model.save(save_path, version="shadow")

    # Загружаем новую модель
    model_loaded = CatBoostModel()
    model_loaded.load(save_path.parent / "test_model_shadow.cbm")

    # Предсказания после загрузки
    proba_after = model_loaded.predict_proba(X)

    # Должны быть идентичными
    assert np.allclose(proba_before, proba_after)


# ==================== Integration Tests ====================


def test_tscv_cross_validate(sample_data):
    """Тест полного цикла TSCV с моделью."""
    X, y = sample_data

    model = CatBoostModel(params={"iterations": 10, "verbose": False})
    tscv = TimeSeriesCrossValidator(n_splits=4)

    results = tscv.cross_validate(model, X, y)

    # Проверяем наличие метрик
    assert "mean_logloss" in results
    assert "std_logloss" in results
    assert "mean_auc" in results
    assert "n_folds" in results
    assert results["n_folds"] == 4

    # Проверяем метрики по фолдам
    for fold_idx in range(1, 5):
        assert f"fold_{fold_idx}_logloss" in results
        assert f"fold_{fold_idx}_auc" in results
