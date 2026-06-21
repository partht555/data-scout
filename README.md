# Dataset Scout

Dataset Scout is a chat-based dataset discovery assistant. It interprets a
plain-language request with Bedrock, searches an OpenSearch index of enriched
dataset metadata, and returns grounded Kaggle recommendations.

## Search API

`POST https://lepdzanhh1.execute-api.us-east-1.amazonaws.com/v1/datasets/search`

The deployed Dataset Scout stack provides API Gateway, Lambda, Amazon Bedrock,
CloudWatch logs, and IAM-signed access to the background-owned OpenSearch index.

## CLI

```powershell
$env:DATA_CURATOR_API_URL = 'https://lepdzanhh1.execute-api.us-east-1.amazonaws.com/v1/datasets/search'
python search_datasets.py 'food datasets for nutrition analysis' --source kaggle --format csv
```

Use `--json` to print the full response. Run `python -m unittest discover -s tests -v`
for the local test suite.

## Read-only ranking evaluation

Compare the current lexical query builder with a phrase-aware candidate without
changing Lambda, DynamoDB, or OpenSearch:

```powershell
$env:OPENSEARCH_ENDPOINT = 'https://your-domain.us-east-1.es.amazonaws.com'
$env:AWS_PROFILE = 'AdministratorAccess-958975572378'
python scripts/evaluate_ranking.py
```

The representative cases are in `scripts/ranking_queries.json`. The harness
uses deterministic keyword plans to avoid Bedrock variability and cost.
