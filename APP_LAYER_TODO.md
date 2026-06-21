# Application Layer - Implementation TODO

## First goal: deployed mock-search API

Build one thin, end-to-end path before adding Bedrock, OpenSearch, or a polished frontend:

```text
User query
  -> API Gateway
  -> Query Lambda
  -> mocked dataset records
  -> JSON response
```

**Definition of done:** a deployed endpoint accepts a natural-language dataset request and returns realistic mocked Kaggle dataset links.

## Phase 1 - API contract

- [x] Agree on one endpoint: `POST /v1/datasets/search`.
- [x] Define and document the request body:
  ```json
  {
    "query": "food datasets for nutrition analysis",
    "limit": 5,
    "filters": {
      "source": ["kaggle"],
      "format": ["csv"]
    }
  }
  ```

- [x] Define the response body with `query`, `interpretedIntent`, `results`, and `nextCursor`.
- [x] Define error responses for invalid requests (`400`), no results (`200` with `[]`), and unavailable dependencies (`503`).
- [x] Add example request/response payloads under `events/` or `docs/`.

## Phase 2 - Lambda implementation

- [x] Choose the runtime (recommendation: Python 3.12 for the hackathon).
- [x] Create a Lambda handler that validates `query` and `limit`.
- [x] Create `mock_repository` with 3-5 normalized Kaggle dataset records.
- [x] Return only the public response contract; do not expose internal AWS/OpenSearch details.
- [x] Include cases for a matching query, no matches, and invalid input.
- [x] Add unit tests for validation and result shaping.

## Phase 3 - Infrastructure and deployment

- [x] Add AWS SAM infrastructure-as-code (`template.yaml`).
- [x] Define the Query Lambda, API Gateway route, IAM execution role, and CloudWatch log group.
- [x] Configure `POST /v1/datasets/search` to invoke the Lambda.
- [x] Deploy with the local AWS SSO profile.
- [x] Invoke the deployed endpoint from the CLI and save a successful example response.
- [x] Add resource tags: `project=data-curator-assistant`, `environment=hackathon`, and `owner=team`.

## Phase 4 - Minimal client

- [x] Create a small CLI command or frontend form that sends a search request.
- [x] Display title, source, link, summary, schema/format information, and match reasons.
- [x] Add loading, empty-result, and API-error states.
- [x] Keep the UI/CLI dependent only on the documented API contract.

## Phase 4.5 - Amplify web UI

- [x] Scaffold a small static web app ready for AWS Amplify hosting.
- [x] Add a chat search entry that derives query, limit, source, and format filters.
- [x] Configure the API endpoint through an Amplify environment variable; never hard-code it in the UI.
- [x] Display dataset titles, canonical Kaggle links, summaries, formats, schema fields, scores, and match reasons.
- [x] Implement loading, empty-result, invalid-request, and dependency-error states.
- [ ] Configure API Gateway CORS only for the deployed Amplify domain before production deployment.
- [ ] Build and deploy the UI with Amplify, then run one end-to-end search against the mock API.

## Phase 5 - Integrate the real search pipeline

- [ ] Replace `mock_repository` with an OpenSearch repository once the background layer has indexed metadata.
- [ ] Add a validated OpenSearch query builder using the shared metadata/index mapping.
- [ ] Filter to active records and return canonical URLs only.
- [ ] Keep the mock repository available for offline development and demos.

## Phase 6 - Add Bedrock intent understanding

- [ ] Define the strict JSON search-plan schema produced by Claude.
- [ ] Add a Bedrock adapter behind an intent-parser interface.
- [ ] Validate model output; never let model output become raw OpenSearch DSL.
- [ ] Fall back to keyword search when Bedrock is unavailable or output is invalid.
- [ ] Add CloudWatch-safe logging for request ID, latency, result count, and fallback mode.

## Coordination contract with the background layer

- [ ] Agree on DynamoDB/OpenSearch document fields: `datasetId`, `title`, `url`, `source`, `description`, `tags`, `files`, `schema`, `license`, `status`, and `version`.
- [ ] Agree that DynamoDB is the source of truth and OpenSearch is the read-only search projection.
- [ ] Agree on one OpenSearch index name/version and how inactive/deleted datasets are handled.
- [ ] Test the application against at least five metadata documents indexed by the background pipeline.

## Cost and safety guardrails

- [ ] Keep this first API deployment to Lambda + API Gateway + CloudWatch only.
- [ ] Do not create OpenSearch until the indexing contract and minimum demo data are ready.
- [ ] Add a billing alarm/budget before deploying persistent paid services.
- [ ] Before the hackathon ends, run a resource audit and delete the deployed stack if it is no longer needed.
