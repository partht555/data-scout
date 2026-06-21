"""Temporary, deterministic dataset records for application-layer development.

Replace this module with an OpenSearch repository once the background pipeline
is indexing production metadata. The returned record shape deliberately mirrors
the background-layer metadata contract.
"""

from __future__ import annotations

from typing import Any


MOCK_DATASETS: tuple[dict[str, Any], ...] = (
    {
        "datasetId": "kaggle:utsavdey1410/food-nutrition-dataset",
        "title": "Food Nutrition Dataset",
        "url": "https://www.kaggle.com/datasets/utsavdey1410/food-nutrition-dataset",
        "source": "kaggle",
        "summary": "Food nutrition information including calories, protein, carbohydrates, and fat.",
        "tags": ["food", "nutrition", "health"],
        "license": "CC0",
        "files": [{"name": "food_nutrition.csv", "format": "csv", "sizeBytes": None}],
        "schema": [
            {"name": "food_name", "type": "string", "nullable": False},
            {"name": "calories", "type": "number", "nullable": True},
            {"name": "protein", "type": "number", "nullable": True},
            {"name": "carbohydrates", "type": "number", "nullable": True},
        ],
    },
    {
        "datasetId": "kaggle:ankurnapa/boston-housing",
        "title": "Boston Housing Dataset",
        "url": "https://www.kaggle.com/datasets/ankurnapa/boston-housing",
        "source": "kaggle",
        "summary": "Housing features and median home values for regression experiments.",
        "tags": ["housing", "regression", "real-estate"],
        "license": "Other",
        "files": [{"name": "housing.csv", "format": "csv", "sizeBytes": None}],
        "schema": [
            {"name": "median_value", "type": "number", "nullable": False},
            {"name": "rooms", "type": "number", "nullable": False},
        ],
    },
    {
        "datasetId": "kaggle:iamsouravbanerjee/heart-attack-prediction-dataset",
        "title": "Heart Attack Prediction Dataset",
        "url": "https://www.kaggle.com/datasets/iamsouravbanerjee/heart-attack-prediction-dataset",
        "source": "kaggle",
        "summary": "Clinical health measurements for heart-disease prediction and analysis.",
        "tags": ["health", "heart", "classification"],
        "license": "Other",
        "files": [{"name": "heart.csv", "format": "csv", "sizeBytes": None}],
        "schema": [
            {"name": "age", "type": "integer", "nullable": False},
            {"name": "cholesterol", "type": "number", "nullable": True},
            {"name": "target", "type": "integer", "nullable": False},
        ],
    },
    {
        "datasetId": "kaggle:shivkumarganesh/retail-sales-data",
        "title": "Retail Sales Data",
        "url": "https://www.kaggle.com/datasets/shivkumarganesh/retail-sales-data",
        "source": "kaggle",
        "summary": "Retail transactions with dates, products, quantities, and sales amounts.",
        "tags": ["retail", "sales", "forecasting"],
        "license": "CC0",
        "files": [{"name": "retail_sales.csv", "format": "csv", "sizeBytes": None}],
        "schema": [
            {"name": "date", "type": "date", "nullable": False},
            {"name": "quantity", "type": "integer", "nullable": False},
            {"name": "sales", "type": "number", "nullable": False},
        ],
    },
    {
        "datasetId": "kaggle:rohanrao/formula-1-world-championship-1950-2020",
        "title": "Formula 1 World Championship Results",
        "url": "https://www.kaggle.com/datasets/rohanrao/formula-1-world-championship-1950-2020",
        "source": "kaggle",
        "summary": "Formula 1 races, drivers, constructors, lap times, and championship results.",
        "tags": ["sports", "formula-1", "time-series"],
        "license": "Other",
        "files": [{"name": "results.csv", "format": "csv", "sizeBytes": None}],
        "schema": [
            {"name": "race_id", "type": "integer", "nullable": False},
            {"name": "driver_id", "type": "integer", "nullable": False},
            {"name": "position", "type": "integer", "nullable": True},
        ],
    },
)


def list_datasets() -> tuple[dict[str, Any], ...]:
    """Return normalized local fixtures without mutating the source records."""

    return tuple(
        {
            **dataset,
            "schemaStatus": "available",
            "status": "active",
            "version": 1,
            "lastUpdatedAt": "2025-01-01T00:00:00Z",
            "crawlObservedAt": "2025-01-01T00:00:00Z",
        }
        for dataset in MOCK_DATASETS
    )