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
from omegaconf import DictConfig

from sports_forecast.training.calibration import ModelCalibrator
from sports_forecast.training.ensembles.stacking import StackingEnsemble
from sports_forecast.training.model_factory import ModelFactory
from sports_forecast.training.models.catboost import CatBoostModel
from sports_forecast.training.models.dummy import DummyModel
from sports_forecast.training.models.lgbm import LGBMModel
from sports_forecast.training.models.logreg import LogRegModel
from sports_forecast.training.optimization.tscv import TimeSeriesCrossValidator


# ==================== Fixtures ====================


@pytest.fixture
def sample_data():
    """Создать тестовые данные для обучения."""
    np.random.seed(777)

    n_samples = 200
    n_features = 10

    features = pd.DataFrame(
        np.random.randn(n_samples, n_features),
        columns=[f"f_{i}" for i in range(n_features)],
    )

    # Бинарный таргет (50/50)
    target = pd.Series(np.random.randint(0, 2, n_samples))

    return features, target


@pytest.fixture
def sample_data_with_cat():
    """Создать тестовые данные с категориальными фичами."""
    np.random.seed(777)

    n_samples = 200

    features = pd.DataFrame(
        {
            "f_numeric_1": np.random.randn(n_samples),
            "f_numeric_2": np.random.randn(n_samples),
            "f_cat_1": np.random.choice(["A", "B", "C"], n_samples),
            "f_cat_2": np.random.choice(["X", "Y"], n_samples),
        }
    )

    target = pd.Series(np.random.randint(0, 2, n_samples))

    return features, target


# ==================== TSCV Tests ====================


def test_tscv_initialization():
    """Тест инициализации TSCV."""
    tscv = TimeSeriesCrossValidator(n_splits=4)
    assert tscv.n_splits == 4
    assert tscv.test_size == 0.1


def test_tscv_split(sample_data):
    """Тест разбиения данных на фолды."""
    features, target = sample_data
    tscv = TimeSeriesCrossValidator(n_splits=4)

    folds = list(tscv.split(features, target))

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
    features, target = sample_data
    tscv = TimeSeriesCrossValidator(n_splits=4)

    folds = list(tscv.split(features, target))

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
    features, target = sample_data
    model = DummyModel()

    # Обучение
    model.fit(features, target)
    assert model.is_fitted()

    # Предсказание
    proba = model.predict_proba(features)
    assert proba.shape == (len(features), 2)
    assert np.allclose(proba.sum(axis=1), 1.0)  # Сумма вероятностей = 1


def test_dummy_model_predicts_class_frequencies(sample_data):
    """Тест что DummyModel предсказывает частоты классов."""
    features, target = sample_data
    model = DummyModel()

    model.fit(features, target)
    proba = model.predict_proba(features)

    # Все предсказания должны быть одинаковыми (частоты классов)
    assert np.allclose(proba[0], proba[1])

    # Вероятности должны соответствовать частотам в y
    expected_freq_class_1 = target.mean()
    assert np.isclose(proba[0, 1], expected_freq_class_1, atol=0.01)


# ==================== CatBoostModel Tests ====================


def test_catboost_model_initialization():
    """Тест инициализации CatBoostModel."""
    model = CatBoostModel(name="catboost_test")
    assert model.name == "catboost_test"
    assert not model.is_fitted()


def test_catboost_model_fit_predict(sample_data):
    """Тест обучения и предсказания CatBoostModel."""
    features, target = sample_data
    model = CatBoostModel(params={"iterations": 10, "verbose": False})

    # Обучение
    model.fit(features, target)
    assert model.is_fitted()

    # Предсказание
    proba = model.predict_proba(features)
    assert proba.shape == (len(features), 2)
    assert np.allclose(proba.sum(axis=1), 1.0)


def test_catboost_model_with_categorical_features(sample_data_with_cat):
    """Тест CatBoost с категориальными фичами."""
    features, target = sample_data_with_cat
    model = CatBoostModel(params={"iterations": 10, "verbose": False})

    # Обучение (автоматически определит категориальные фичи)
    model.fit(features, target)
    assert model.is_fitted()

    # Должны быть найдены категориальные фичи
    assert len(model.cat_features_) == 2
    assert "f_cat_1" in model.cat_features_
    assert "f_cat_2" in model.cat_features_


def test_catboost_model_feature_importance(sample_data):
    """Тест получения важности фичей."""
    features, target = sample_data
    model = CatBoostModel(params={"iterations": 10, "verbose": False})

    model.fit(features, target)

    importance = model.get_feature_importance()
    assert isinstance(importance, pd.DataFrame)
    assert "feature" in importance.columns
    assert "importance" in importance.columns
    assert len(importance) == features.shape[1]


# ==================== LogRegModel Tests ====================


def test_logreg_model_fit_predict(sample_data):
    """Тест обучения и предсказания LogRegModel."""
    features, target = sample_data
    model = LogRegModel(params={"max_iter": 100, "solver": "lbfgs"})

    model.fit(features, target)
    assert model.is_fitted()

    proba = model.predict_proba(features)
    assert proba.shape == (len(features), 2)


def test_logreg_preprocessing_numeric_only(sample_data):
    """Тест preprocessing LogReg с только числовыми фичами."""
    features, target = sample_data
    model = LogRegModel(params={"max_iter": 100})

    # Обучение
    model.fit(features, target)

    # Preprocessor должен быть создан
    assert model.preprocessor_ is not None
    assert len(model.numeric_features_) == features.shape[1]
    assert len(model.categorical_features_) == 0


def test_logreg_preprocessing_with_categorical(sample_data_with_cat):
    """Тест preprocessing LogReg с категориальными фичами."""
    features, target = sample_data_with_cat
    model = LogRegModel(params={"max_iter": 100})

    # Обучение
    model.fit(features, target)

    # Preprocessor должен быть создан
    assert model.preprocessor_ is not None
    assert len(model.numeric_features_) == 2
    assert len(model.categorical_features_) == 2

    # Предсказание должно работать (даже с новыми категориями)
    test_features = features.copy()
    test_features.loc[0, "f_cat_1"] = "NEW_CATEGORY"  # Новая категория

    proba = model.predict_proba(test_features)
    assert proba.shape == (len(test_features), 2)


def test_logreg_save_load_with_preprocessor(sample_data_with_cat, tmp_path):
    """Тест сохранения/загрузки LogReg с preprocessor."""
    features, target = sample_data_with_cat
    model = LogRegModel(params={"max_iter": 100})

    # Обучение
    model.fit(features, target)
    proba_before = model.predict_proba(features)

    # Сохранение (save_path — директория модели)
    save_path = tmp_path / "logreg_test"
    model.save(save_path, version="shadow")

    # Загрузка в новую модель (файл внутри директории)
    model_loaded = LogRegModel()
    model_loaded.load(save_path / "logreg_test_shadow.pkl")

    # Preprocessor должен быть загружен
    assert model_loaded.preprocessor_ is not None

    # Предсказания должны совпадать
    proba_after = model_loaded.predict_proba(features)
    np.testing.assert_array_almost_equal(proba_before, proba_after)


# ==================== LGBMModel Tests ====================


def test_lgbm_preprocessing_converts_object_to_category(sample_data_with_cat):
    """Тест что LGBM конвертирует object -> category."""
    features, target = sample_data_with_cat
    model = LGBMModel(params={"n_estimators": 10, "verbose": -1})

    # Обучение
    model.fit(features, target)

    # Категориальные фичи должны быть найдены
    assert len(model.cat_features_) == 2


def test_lgbm_fit_predict(sample_data_with_cat):
    """Тест обучения и предсказания LGBMModel."""
    features, target = sample_data_with_cat
    model = LGBMModel(params={"n_estimators": 10, "verbose": -1})

    # Обучение
    model.fit(features, target)
    assert model.is_fitted()

    # Предсказание
    proba = model.predict_proba(features)
    assert proba.shape == (len(features), 2)
    assert np.allclose(proba.sum(axis=1), 1.0)


# ==================== ModelCalibrator Tests ====================


def test_calibrator_initialization():
    """Тест инициализации ModelCalibrator."""
    calibrator = ModelCalibrator(threshold_ece=0.1, method="isotonic")
    assert calibrator.threshold_ece == 0.1
    assert calibrator.method == "isotonic"


def test_calibrator_no_calibration_needed(sample_data):
    """Тест что калибровка не применяется если ECE < threshold."""
    features, target = sample_data

    # Разбиваем данные
    split_idx = int(len(features) * 0.6)
    train_features = features.iloc[:split_idx]
    cal_features = features.iloc[split_idx : int(len(features) * 0.8)]
    val_features = features.iloc[int(len(features) * 0.8) :]
    train_target = target.iloc[:split_idx]
    cal_target = target.iloc[split_idx : int(len(target) * 0.8)]
    val_target = target.iloc[int(len(target) * 0.8) :]

    # Обучаем LogReg (обычно хорошо откалиброван)
    model = LogRegModel()
    model.fit(train_features, train_target)

    # Калибратор с высоким порогом
    calibrator = ModelCalibrator(threshold_ece=0.5, method="isotonic")

    calibrated_model, is_calibrated, ece_before, ece_after = calibrator.calibrate_if_needed(
        model, cal_features, cal_target, val_features, val_target
    )

    # Калибровка не должна была применяться
    assert not is_calibrated
    assert ece_before is not None
    # Когда калибровка не нужна, ece_after == ece_before
    assert ece_after == ece_before


# ==================== Save/Load Tests ====================


def test_model_save_load(sample_data, tmp_path):
    """Тест сохранения и загрузки модели."""
    features, target = sample_data

    # Обучаем модель
    model = CatBoostModel(params={"iterations": 10, "verbose": False})
    model.fit(features, target)

    # Предсказания до сохранения
    proba_before = model.predict_proba(features)

    # Сохраняем (save_path — директория модели)
    save_path = tmp_path / "test_model"
    model.save(save_path, version="shadow")

    # Загружаем новую модель (файл внутри директории)
    model_loaded = CatBoostModel()
    model_loaded.load(save_path / "test_model_shadow.cbm")

    # Предсказания после загрузки
    proba_after = model_loaded.predict_proba(features)

    # Должны быть идентичными
    assert np.allclose(proba_before, proba_after)


# ==================== ModelFactory Tests ====================


class TestModelFactory:
    """Тесты для ModelFactory."""

    def test_create_dummy(self):
        """ModelFactory создаёт DummyModel по имени."""
        cfg = DictConfig(
            {
                "name": "dummy",
                "_target_": "sports_forecast.training.models.dummy.DummyModel",
                "params": {},
            }
        )
        model = ModelFactory.create_model(cfg)
        assert isinstance(model, DummyModel)
        assert model.name == "dummy"

    def test_create_logreg(self):
        """ModelFactory создаёт LogRegModel по имени."""
        cfg = DictConfig(
            {
                "name": "logreg",
                "_target_": "sports_forecast.training.models.logreg.LogRegModel",
                "params": {"max_iter": 100},
            }
        )
        model = ModelFactory.create_model(cfg)
        assert isinstance(model, LogRegModel)
        assert model.name == "logreg"

    def test_create_catboost(self):
        """ModelFactory создаёт CatBoostModel по имени."""
        cfg = DictConfig(
            {
                "name": "catboost",
                "_target_": "sports_forecast.training.models.catboost.CatBoostModel",
                "params": {"iterations": 10, "verbose": False},
            }
        )
        model = ModelFactory.create_model(cfg)
        assert isinstance(model, CatBoostModel)

    def test_create_lgbm(self):
        """ModelFactory создаёт LGBMModel по имени."""
        cfg = DictConfig(
            {
                "name": "lgbm",
                "_target_": "sports_forecast.training.models.lgbm.LGBMModel",
                "params": {"n_estimators": 10, "verbose": -1},
            }
        )
        model = ModelFactory.create_model(cfg)
        assert isinstance(model, LGBMModel)

    def test_create_by_target_only(self):
        """ModelFactory создаёт модель по _target_ даже если name нестандартный."""
        cfg = DictConfig({"name": "my_custom", "_target_": "CatBoostModel", "params": {}})
        model = ModelFactory.create_model(cfg)
        assert isinstance(model, CatBoostModel)

    def test_unknown_model_raises_error(self):
        """ModelFactory выбрасывает ValueError для неизвестной модели."""
        cfg = DictConfig({"name": "unknown_model", "_target_": "UnknownClass", "params": {}})
        with pytest.raises(ValueError, match="Не удалось определить класс модели"):
            ModelFactory.create_model(cfg)

    def test_created_model_can_fit_predict(self, sample_data):
        """Модель, созданная через ModelFactory, обучается и предсказывает."""
        features, target = sample_data
        cfg = DictConfig(
            {
                "name": "catboost",
                "_target_": "CatBoostModel",
                "params": {"iterations": 10, "verbose": False},
            }
        )
        model = ModelFactory.create_model(cfg)

        model.fit(features, target)
        assert model.is_fitted()

        proba = model.predict_proba(features)
        assert proba.shape == (len(features), 2)

    def test_params_passed_correctly(self):
        """ModelFactory передаёт params из конфига в модель."""
        cfg = DictConfig(
            {
                "name": "catboost",
                "_target_": "CatBoostModel",
                "params": {"iterations": 42, "depth": 3, "verbose": False},
            }
        )
        model = ModelFactory.create_model(cfg)
        assert model.params["iterations"] == 42
        assert model.params["depth"] == 3

    def test_stacking_without_base_models_raises_error(self):
        """ModelFactory выбрасывает ValueError для Stacking без base_models."""
        cfg = DictConfig(
            {
                "name": "stacking",
                "_target_": "StackingEnsemble",
                "params": {},
                "meta_model": {"type": "logreg", "params": {}},
            }
        )
        with pytest.raises(ValueError, match="base_models"):
            ModelFactory.create_model(cfg)

    def test_stacking_factory_creates_ensemble(self):
        """ModelFactory корректно создаёт StackingEnsemble из конфига."""
        cfg = DictConfig(
            {
                "name": "stacking",
                "_target_": "StackingEnsemble",
                "params": {},
                "base_models": ["logreg", "dummy"],
                "meta_model": {"type": "logreg", "params": {"C": 0.1}},
                "tscv_n_splits": 3,
                "optuna_space": None,
            }
        )
        model = ModelFactory.create_model(cfg)
        assert isinstance(model, StackingEnsemble)
        assert len(model.base_models) == 2
        assert model.n_splits == 3


# ==================== Stacking Integration Tests ====================


class TestStackingEnsemble:
    """Интеграционные тесты для полного цикла Stacking Ensemble."""

    def test_fit_predict_cycle(self, sample_data):
        """Полный цикл: create → fit → predict_proba."""
        features, target = sample_data

        base_models = [
            LogRegModel(name="logreg_base", params={"max_iter": 200}),
            DummyModel(name="dummy_base"),
        ]
        meta_model = LogRegModel(name="meta_logreg", params={"C": 0.1, "max_iter": 200})

        stacking = StackingEnsemble(
            name="test_stacking",
            base_models=base_models,
            meta_model=meta_model,
            n_splits=3,
        )

        # fit
        stacking.fit(features, target)
        assert stacking.is_fitted_

        # predict_proba
        proba = stacking.predict_proba(features)
        assert proba.shape == (len(features), 2)
        assert np.allclose(proba.sum(axis=1), 1.0, atol=1e-6)
        assert (proba >= 0).all()
        assert (proba <= 1).all()

    def test_predict_before_fit_raises_error(self, sample_data):
        """predict_proba до fit вызывает ValueError."""
        features, _ = sample_data

        stacking = StackingEnsemble(
            name="test_stacking",
            base_models=[DummyModel(name="dummy")],
            meta_model=LogRegModel(name="meta"),
        )

        with pytest.raises(ValueError, match="не обучен"):
            stacking.predict_proba(features)

    def test_save_load_cycle(self, sample_data, tmp_path):
        """Полный цикл: fit → save → load → predict_proba."""
        features, target = sample_data

        base_models = [
            LogRegModel(name="logreg_base", params={"max_iter": 200}),
            DummyModel(name="dummy_base"),
        ]
        meta_model = LogRegModel(name="meta_logreg", params={"C": 0.1, "max_iter": 200})

        stacking = StackingEnsemble(
            name="test_stacking",
            base_models=base_models,
            meta_model=meta_model,
            n_splits=3,
        )
        stacking.fit(features, target)

        # save
        save_path = tmp_path / "stacking_test"
        stacking.save(save_path, version="prod")

        # Проверяем что файлы созданы
        saved_dir = tmp_path / "stacking_test_prod"
        assert saved_dir.exists()

        # load в новый экземпляр
        new_base = [
            LogRegModel(name="logreg_base"),
            DummyModel(name="dummy_base"),
        ]
        new_meta = LogRegModel(name="meta_logreg")
        new_stacking = StackingEnsemble(
            name="test_stacking",
            base_models=new_base,
            meta_model=new_meta,
        )
        new_stacking.load(saved_dir)
        assert new_stacking.is_fitted_

        # predict_proba должен давать тот же результат
        proba_orig = stacking.predict_proba(features)
        proba_loaded = new_stacking.predict_proba(features)
        np.testing.assert_allclose(proba_orig, proba_loaded, atol=1e-6)

    def test_no_base_models_raises_error(self):
        """Конструктор отклоняет пустой список base_models."""
        with pytest.raises(ValueError, match="base_models"):
            StackingEnsemble(name="bad", base_models=[], meta_model=LogRegModel("m"))

    def test_no_meta_model_raises_error(self):
        """Конструктор отклоняет None meta_model."""
        with pytest.raises(ValueError, match="meta_model"):
            StackingEnsemble(name="bad", base_models=[DummyModel("d")], meta_model=None)

    def test_save_before_fit_raises_error(self, tmp_path):
        """save до fit вызывает ValueError."""
        stacking = StackingEnsemble(
            name="test",
            base_models=[DummyModel(name="d")],
            meta_model=LogRegModel(name="m"),
        )
        with pytest.raises(ValueError, match="не обучен"):
            stacking.save(tmp_path / "model", version="prod")


# ==================== Integration Tests ====================


def test_tscv_cross_validate(sample_data):
    """Тест полного цикла TSCV с моделью."""
    features, target = sample_data

    model = CatBoostModel(params={"iterations": 10, "verbose": False})
    tscv = TimeSeriesCrossValidator(n_splits=4)

    results = tscv.cross_validate(model, features, target)

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
