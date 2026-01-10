#!/bin/bash

# Полный прогон обучения для турнира uel_kz_1
# 1. Winner (long format) - все модели + ансамбль
# 2. Total 6.5 over (wide format) - все модели + ансамбль

set -e  # Выход при ошибке

TOURNAMENT="uel_kz_1"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 ПОЛНЫЙ ПРОГОН ОБУЧЕНИЯ: $TOURNAMENT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ============================================================================
# 1. WINNER (long format)
# ============================================================================
echo "📊 [1/2] WINNER MARKET (long format)"
echo "  Модели: dummy, logreg, catboost, lgbm, stacking"
echo "  Featureset: basic"
echo ""

uv run python -m sports_forecast.train \
    tournament=$TOURNAMENT \
    market=winner \
    market_spec=winner \
    recipe=winner_with_ensemble \
    features=basic

echo "✅ Winner market завершён!"
echo ""

# ============================================================================
# 2. TOTAL 6.5 OVER (wide format)
# ============================================================================
echo "📊 [2/2] TOTAL 6.5 OVER MARKET (wide format)"
echo "  Модели: dummy, logreg, catboost, lgbm, stacking"
echo "  Featureset: basic"
echo "  Line: 6.5"
echo ""

uv run python -m sports_forecast.train \
    tournament=$TOURNAMENT \
    market=total \
    market_spec=total_over \
    market_spec.line=6.5 \
    recipe=total_with_ensemble \
    features=basic

echo "✅ Total 6.5 over market завершён!"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 ПОЛНЫЙ ПРОГОН ЗАВЕРШЁН!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📊 Проверьте результаты в MLflow:"
echo "   make mlflow-ui"
echo ""
echo "Эксперименты:"
echo "  1. sports_prob_forecasting_winner"
echo "  2. sports_prob_forecasting_total"
echo ""
