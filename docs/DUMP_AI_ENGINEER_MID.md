# Job Interview Blueprint: AI Engineer (LLM & GenAI) (Mid)
- **Job ID**: `915c2ea4-84c7-4e8c-a944-cbdb3c25cff2`
- **Role Key**: `ai_engineer`
- **Department**: Engineering
- **Seniority Level**: mid
- **Total Duration**: 30 minutes
- **Blueprint Version**: v1 (APPROVED)
- **Blueprint ID**: `c3e2fa3a-2215-4555-b94c-016d16d5b3e1`
- **Is Stale**: ✅ NO (Up to Date)
- **Input Hash**: `e3b35d361a81f0b01735d96b19563b6c821535cce1c2c830ee986cbcb32921d5`
- **Approved At**: 2026-10-13T16:46:37.703733

## Budget & Capacity Metrics
| Metric | Value |
| :--- | :--- |
| Total Duration | 30 mins |
| Active Skill Assessment Time | 24.0 mins |
| Fixed Overhead (Welcome/Intro/QA/Closing) | 6.0 mins |
| Total Expectations | 12 (Core: 8) |
| Expected Capacity (~2.0m / exp) | 12.0 |
| Reachability Density Ratio | 0.67 |

## Interview Structure & Spoken Script
### [Section 1] Welcome & Candidate Setup (1.5m)
**Spoken Welcome Script:**
> "Hello, and welcome to your technical interview for the AI Engineer (LLM & GenAI) (Mid) role. Over the next 30 minutes, we will walk through your background and explore technical architecture, trade-offs, and practical engineering challenges. Take your time when answering, and when you are ready, let's begin."

### [Section 2] Candidate Introduction & Career Journey (2.0m)
_Candidate self-introduction, journey overview, and key technical focus areas._

### [Section 3] Skill: LLM Application Design & RAG (7.0m, P0)
#### Evaluated Expectations:
1. **[CORE | L3]** Designs advanced retrieval pipelines utilizing hybrid search, metadata filtering, and cross-encoder reranking.
2. **[CORE | L4]** Resolves retrieval failures and improves context relevance using query rewriting or contextual compression.
3. **[STRETCH | L5]** Architects multi-hop reasoning graphs or dynamic agentic retrieval workflows under strict latency constraints.

**Anchor Question** (21 words):
> "Can you walk me through how you designed a production retrieval pipeline to handle ambiguous user queries and irrelevant retrieved chunks?"

**Anchor Alt Question (Hypothetical)** (19 words):
> "Suppose you need to build a retrieval system where initial searches return noisy chunks. How would you approach this?"

**Escalation Question** (21 words):
> "How would you redesign a multi-hop retrieval workflow to maintain answer accuracy when downstream latency budgets drop below five hundred milliseconds?"

**Probes with Trigger Conditions (3 total):**
- **Probe 1** (14 words | Target Exp #1):
  - *Trigger Condition*: `Candidate mentions chunking strategy or document preparation.`
  - *Spoken Probe*: "How did you determine the optimal chunk size and strategy for your source documents?"
- **Probe 2** (16 words | Target Exp #1, #2):
  - *Trigger Condition*: `Candidate mentions adding a reranker to the pipeline.`
  - *Spoken Probe*: "What criteria did you use to evaluate whether the additional scoring step actually improved generation quality?"
- **Probe 3** (14 words | Target Exp #2, #3):
  - *Trigger Condition*: `Candidate discusses handling complex or multi-part queries.`
  - *Spoken Probe*: "How did you handle user queries that required information synthesized across multiple disparate documents?"

### [Section 4] Skill: Prompt & Context Engineering and Evaluation (6.5m, P0)
#### Evaluated Expectations:
1. **[CORE | L3]** Implements structured JSON output schemas and automated evaluation metrics like faithfulness and answer relevance.
2. **[CORE | L4]** Designs robust LLM-as-a-judge evaluation pipelines with calibration against human ground-truth labels and bias mitigation.
3. **[STRETCH | L5]** Establishes continuous evaluation CI/CD regression gates, synthetic dataset generation, and dynamic context budgeting engines.

**Anchor Question** (19 words):
> "Can you walk me through how you structured your prompt pipelines and measured response quality in your last project?"

**Anchor Alt Question (Hypothetical)** (18 words):
> "Suppose you were tasked with building a RAG evaluation pipeline from scratch. How would you measure answer faithfulness?"

**Escalation Question** (20 words):
> "When deploying an automated LLM evaluation pipeline to a CI/CD environment, how do you handle prompt regression gating and variance?"

**Probes with Trigger Conditions (3 total):**
- **Probe 1** (15 words | Target Exp #1):
  - *Trigger Condition*: `Candidate discusses output formatting or schemas`
  - *Spoken Probe*: "How do you handle situations where the output schema drifts or validation fails during inference?"
- **Probe 2** (14 words | Target Exp #2):
  - *Trigger Condition*: `Candidate mentions LLM-as-a-judge or evaluation metrics`
  - *Spoken Probe*: "What specific strategy did you use to align automated evaluation scores with human judgment?"
- **Probe 3** (15 words | Target Exp #3):
  - *Trigger Condition*: `Candidate mentions context window management or RAG`
  - *Spoken Probe*: "How do you manage token budget constraints when context windows are flooded with retrieved documents?"

### [Section 5] Skill: Production AI Systems (latency, cost, monitoring, guardrails) (5.5m, P1)
#### Evaluated Expectations:
1. **[CORE | L3]** Implements production streaming with time to first token optimization, token spend budgets, and content safety filters.
2. **[CORE | L4]** Architects comprehensive guardrail layers including semantic safety checks and fallback model cascades.
3. **[STRETCH | L5]** Designs enterprise-scale inference infrastructure managing thousands of concurrent requests while maintaining strict sub-second response times.

**Anchor Question** (15 words):
> "How did you optimize latency and manage token spend for a production language model application?"

**Anchor Alt Question (Hypothetical)** (22 words):
> "Suppose you were asked to deploy a high-traffic chatbot with tight latency budgets and safety filters. How would you approach the architecture?"

**Escalation Question** (24 words):
> "How would you redesign an inference pipeline to handle a tenfold traffic spike while keeping the time to first token under five hundred milliseconds?"

**Probes with Trigger Conditions (3 total):**
- **Probe 1** (14 words | Target Exp #1, #2):
  - *Trigger Condition*: `Candidate discusses security or input validation without detailing threat defense.`
  - *Spoken Probe*: "How do you detect and block malicious inputs before they reach the primary model?"
- **Probe 2** (14 words | Target Exp #2):
  - *Trigger Condition*: `Candidate mentions latency issues or reliability concerns without explaining mitigation mechanisms.`
  - *Spoken Probe*: "What strategies did you use to maintain acceptable response times during upstream provider outages?"
- **Probe 3** (15 words | Target Exp #1):
  - *Trigger Condition*: `Candidate mentions cost management without specifying attribution or tracking methodology.`
  - *Spoken Probe*: "How do you track token consumption trends and attribute costs back to specific user workflows?"

### [Section 6] Skill: Data & Retrieval Pipelines (5.0m, P1)
#### Evaluated Expectations:
1. **[CORE | L3]** Builds robust ETL pipelines extracting text and tables from complex documents while maintaining vector store freshness.
2. **[CORE | L4]** Designs incremental change data capture pipelines to synchronize enterprise data stores with vector indexes efficiently.
3. **[STRETCH | L5]** Architects multimodal ingestion systems handling complex assets with semantic graph linkages and lineage.

**Anchor Question** (21 words):
> "Walk me through how you designed a document ingestion pipeline to handle complex table extractions and keep your vector store fresh?"

**Anchor Alt Question (Hypothetical)** (20 words):
> "Suppose you were tasked with building an ETL pipeline for unstructured documents and vector synchronization; how would you approach it?"

**Escalation Question** (23 words):
> "Suppose an ingestion system must process mixed multimodal content like diagrams and audio alongside text; how would you maintain semantic relationships across them?"

**Probes with Trigger Conditions (4 total):**
- **Probe 1** (14 words | Target Exp #1):
  - *Trigger Condition*: `Candidate mentions issues with document parsing or layout extraction.`
  - *Spoken Probe*: "How did you handle documents where standard text parsers failed on embedded layout structures?"
- **Probe 2** (14 words | Target Exp #2):
  - *Trigger Condition*: `Candidate discusses vector store updates or synchronization.`
  - *Spoken Probe*: "What strategy did you use to prevent duplicate chunk insertions during concurrent pipeline runs?"
- **Probe 3** (14 words | Target Exp #2):
  - *Trigger Condition*: `Candidate talks about database syncing or metadata management.`
  - *Spoken Probe*: "How did you verify metadata synchronization between the primary database and the vector index?"
- **Probe 4** (14 words | Target Exp #3):
  - *Trigger Condition*: `Candidate brings up multimodal ingestion or tracking data flow.`
  - *Spoken Probe*: "How would you approach capturing automated lineage for data transformations in a multimodal pipeline?"

### [Section 7] Candidate Q&A (2.0m)
_Candidate asks questions about the team, role, and engineering stack._

### [Section 8] Session Wrap-up & Closing (0.5m)
**Spoken Closing Script:**
> "Thank you for sharing your experience and technical perspective with me today. That concludes our interview for AI Engineer (LLM & GenAI) (Mid). Our recruiting team will review the session transcript and be in touch regarding next steps. Have a wonderful rest of your day!"

## Validation & Voice Rules Audit
- **Status**: ✅ VALID
- **Warnings**:
  - ⚠️ escalation_question may hint at expectation #3 with overlapping keywords: latency, multi, retrieval
  - ⚠️ anchor_alt_question may hint at expectation #1 with overlapping keywords: answer, evaluation, faithfulness
  - ⚠️ anchor_question may hint at expectation #1 with overlapping keywords: production, spend, token
  - ⚠️ anchor_alt_question may hint at expectation #1 with overlapping keywords: budgets, filters, safety
  - ⚠️ probe_2 names technique keywords (response, times) without trigger stating candidate mentioned them
  - ⚠️ anchor_question may hint at expectation #1 with overlapping keywords: complex, store, vector
  - ⚠️ escalation_question may hint at expectation #3 with overlapping keywords: ingestion, multimodal, semantic
  - ⚠️ Anchor variety alert: 2 of 4 anchors (50%) share opening phrase 'can you walk' (guideline is <= 40%)