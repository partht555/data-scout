# Application Layer - Implementation TODO

## First goal: deployed dataset-search API

Build one thin, end-to-end path before adding Bedrock, OpenSearch, or a polished frontend:

```text
User query
  -> API Gateway
  -> Query Lambda
  -> OpenSearch `datasets-v1` projection
  -> JSON response
```

**Definition of done:** a deployed endpoint accepts a natural-language dataset request and returns public Kaggle metadata from the active search projection.

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

## Phase 4.5 - Optional web hosting

- [x] Scaffold a small static web app ready for AWS Amplify hosting.
- [x] Add a chat search entry that derives query, limit, source, and format filters.
- [x] Configure the API endpoint through an Amplify environment variable; never hard-code it in the UI.
- [x] Display dataset titles, canonical Kaggle links, summaries, formats, schema fields, scores, and match reasons.
- [x] Implement loading, empty-result, invalid-request, and dependency-error states.
- [ ] Configure production CORS only for the selected hosted domain.
- [ ] Build and deploy the static UI with Amplify or another host after the demo; local hosting is the current supported path.

## Phase 5 - Integrate the real search pipeline

- [x] Add the signed-IAM `OpenSearchRepository` for the `datasets-v1` projection.
- [x] Add a bounded validated OpenSearch query builder using the shared metadata/index mapping.
- [x] Filter to active records, apply explicit source/format/license filters, cap at 20, and return canonical URLs only.
- [x] Keep the mock repository available automatically for offline/unit-test use.
- [x] Exercise real API Gateway retrieval, explicit filters, empty results, cursor response, and enriched `useCaseSummary` output.

## Phase 6 - Add Bedrock intent understanding

- [x] Define the strict JSON search-plan schema produced by Claude.
- [x] Add a Bedrock adapter behind an intent-parser interface.
- [x] Validate model output; never let model output become raw OpenSearch DSL.
- [x] Fall back to keyword search when Bedrock is unavailable or output is invalid.
- [x] Add the real Bedrock invocation, feature flag, and narrow Lambda IAM permission for Claude Haiku.
- [x] Add CloudWatch-safe logging for request ID, latency, result count, repository mode, interpretation mode, and fallback mode.

## Coordination contract with the background layer

- [x] Agree on DynamoDB/OpenSearch document fields: `datasetId`, `title`, `url`, `source`, `description`, `tags`, `files`, `schema`, `license`, `status`, and `version`.
- [x] Agree that DynamoDB is the source of truth and OpenSearch is the read-only search projection.
- [x] Agree on index `datasets-v1`; inactive/deleted datasets are removed from the projection and all queries require `status=active`.
- [x] Test the application against indexed background-pipeline metadata, including enriched `useCaseSummary` output.

## Cost and safety guardrails

- [x] Keep the deployed query path minimal: Lambda, API Gateway, CloudWatch, Bedrock, and the existing hackathon OpenSearch domain.
- [x] Keep the development OpenSearch domain minimal and delete it after the hackathon.
- [ ] Add $10/$20/$24 budget alerts once the team provides a billing-alert email recipient.
- [ ] Before the hackathon ends, run a resource audit and delete the deployed stack if it is no longer needed.
