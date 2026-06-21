# Data Curator Assistant — Application Layer Implementation

## Deployed mock-search API

`POST https://lepdzanhh1.execute-api.us-east-1.amazonaws.com/v1/datasets/search`

The deployed `data-curator-assistant-mock` stack provides the Lambda, API Gateway HTTP endpoint, IAM execution role, and CloudWatch log group. It returns deterministic Kaggle-style mock records until the background layer’s OpenSearch index is available.

## CLI

The CLI uses only the documented API contract:

```powershell
$env:DATA_CURATOR_API_URL = 'https://lepdzanhh1.execute-api.us-east-1.amazonaws.com/v1/datasets/search'
python search_datasets.py 'food datasets for nutrition analysis' --source kaggle --format csv
```

Use `--json` to print the full API response. Run `python -m unittest discover -s tests -v` for the local test suite.