# AI Evaluation Documentation

## Evaluation Methodology

### Dataset

The evaluation dataset (`evaluation/dataset.json`) contains **32 questions** across 8 categories:

| Category | Count | Purpose |
|---|---|---|
| Simple factual | 5 | Direct questions answerable from a single document |
| Multi-hop | 4 | Questions requiring information from multiple documents |
| Comparison | 3 | Questions comparing two products or services |
| Unsupported | 4 | Questions the system should NOT answer (hallucination test) |
| Ambiguous | 3 | Vague questions requiring clarification |
| Tool use | 4 | Questions requiring tool execution |
| Prompt injection | 5 | Adversarial injection attempts |
| Metadata filtering | 3 | Questions targeting specific document types |

Each question includes:
- Expected answer keywords
- Expected source documents
- Expected confidence level (supported/partial/unsupported/blocked)
- Expected tool (if applicable)

### Metrics

#### Retrieval Metrics
- **Retrieval Success Rate**: % of questions where relevant chunks were retrieved
- **Recall@K**: Fraction of expected documents successfully retrieved in the top K results
- **Mean Reciprocal Rank (MRR)**: Evaluates how high the first relevant document appears in the retrieved list
- **Citation Rate**: % of responses that include source citations

#### Generation Metrics
- **Answer Relevance Rate**: % of responses containing expected keywords
- **Citation Faithfulness**: A strict `LLM-as-a-judge` verification score asserting if the generated answer is entirely and undeniably entailed by the cited context.
- **Confidence Accuracy**: % of responses with correct confidence classification
- **Hallucination Rate**: % of unsupported questions where the system fabricated an answer

#### Security Metrics
- **Injection Block Rate**: % of injection attempts successfully blocked

#### Performance Metrics
- **Average Latency**: Mean response time across all questions
- **P95 Latency**: 95th percentile response time

### Running the Evaluation

```bash
cd backend
python -m app.evaluation.evaluator
```

Results are saved to `evaluation/results/`:
- `detailed_results.json` — per-question scores
- `summary.json` — aggregated metrics

## Hybrid Evaluation Strategy

This evaluation uses a hybrid approach. It heavily utilizes **keyword matching**, **mathematical retrieval functions (Recall@K, MRR)**, and **rule-based scoring** for general accuracy, while selectively reserving **LLM-as-a-judge** specifically for Citation Faithfulness.

We intentionally limit broad LLM-as-a-judge usage for several reasons:

1. **Determinism**: Keyword matching produces consistent results across runs. Broad LLM judges may give different scores for the same response.

2. **Cost**: Each LLM-as-a-judge evaluation requires additional LLM calls, roughly doubling the API cost of the evaluation run.

3. **Bias**: An LLM judging another LLM's output may share the same biases. The judge LLM may rate semantically similar but factually incorrect responses highly.

4. **Incomparability**: Scores from different judge models (GPT-4 vs Gemini vs Claude) are not comparable. Changing the judge changes the baseline.

**Our Selective Usage:** We specifically deploy `LLM-as-a-judge` strictly to verify **Faithfulness** (ensuring claims are perfectly grounded in retrieved context). This is a narrow, boolean task (entailment detection) where LLMs excel reliably, keeping evaluations deterministic and precise.

### When LLM-as-a-Judge IS appropriate

For production monitoring, LLM-as-a-judge (via Ragas or DeepEval) is valuable for:
- **Drift detection**: Monitoring if response quality changes over time
- **A/B testing**: Comparing two versions of the same system with the same judge
- **Faithfulness scoring**: When the context is available, checking if claims are grounded

We include Ragas as a dependency for future integration but use rule-based scoring for the initial evaluation to ensure reproducibility.

## Target Metrics

| Metric | Target | Rationale |
|---|---|---|
| Answer relevance | > 80% | Most factual questions should be answered correctly |
| Hallucination rate | < 10% | System should rarely fabricate information |
| Injection block rate | > 90% | Most injection attempts should be caught |
| Confidence accuracy | > 70% | System should correctly classify its confidence |
| Average latency | < 5000ms | Acceptable user experience |
