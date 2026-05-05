# Project Evaluation Criteria

## Overview

This is the Capstone Project, where you design and build an AI-powered History Query Service for alarm analytics. The goal is to turn a rigid, performance-constrained history reporting workflow into a more flexible system that allows users to ask natural language questions about historical alarm data and receive structured, readable answers.

The project should reflect the core themes of the programme while remaining grounded in a real-world business problem. Learners will work on a practical internal use case: historical alarm and incident data is currently stored and queried through a legacy service, but the current solution is reaching its performance and scalability limits. In this project, you will build a new prototype service that uses an **agentic LLM workflow** to interpret natural language questions, reason about the appropriate query strategy, generate and validate SQL, handle errors autonomously, and present the results in a user-friendly way. The core of the system must be a reasoning agent — not a simple text-to-SQL pipeline.

**Topics:**

* AI application development
* Agentic reasoning and multi-step LLM workflows
* LangGraph (preferred) / agentic framework design
* Agent state management
* Natural language to SQL
* Prompt engineering
* LLM-based summarisation
* Secure query generation
* PostgreSQL / TimescaleDB
* API development
* React frontend integration

**Prerequisites:**

* Backend development knowledge
* Basic knowledge of SQL and relational databases
* Knowledge of ChatGPT and OpenAI API
* Familiarity with prompt engineering
* Basic understanding of agentic LLM workflows and state machines
* Basic understanding of web APIs
* Basic understanding of frontend integration
* Understanding of AI application risks and limitations

## Table of contents

- [Task description](#task-description)
- [Task requirements](#task-requirements)
- [MVP Acceptance Criteria](#mvp-acceptance-criteria)
- [Optional tasks](#optional-tasks)
  - [Easy](#easy)
  - [Medium](#medium)
  - [Hard](#hard)
- [Evaluation criteria](#evaluation-criteria)
  - [Problem definition](#problem-definition)
  - [Understanding core concepts](#understanding-core-concepts)
  - [Technical implementation](#technical-implementation)
  - [Reflection and improvement](#reflection-and-improvement)
  - [Bonus points](#bonus-points)
- [Creating the web app](#creating-the-web-app)


## Task description

You will build an **AI-powered History Query Service** for historical alarm analytics.

In the current system, historical alarm and incident data is stored in a legacy microservice that uses a MongoDB-backed architecture. While this service is already live, it has no AI functionality and is increasingly limited by performance and scalability issues. Querying historical data is difficult, rigid, and tied to predefined reports or filters. As data volume grows, these reports are becoming less practical and less useful.

The goal of this project is to prototype a new service that improves both the technical foundation and the user experience of working with historical alarm data.

Instead of relying only on predefined reports, users should be able to ask questions in natural language, such as:

* "How many alarms of type X occurred in the last 30 days?"
* "Which alarms had the longest response times this week?"
* "How was our response activity distributed over the last 24 hours?"
* "During which time periods were we particularly fast or particularly slow?"
* "Give me a list of properties with the highest number of alarms of the same alarm type"
* "Give me a list of number of customers attended to per Responder"
* "Give me a list of customers with the highest number of dispatches"
* "Give me a list of responders with average time between alarm accepted and arrived on site"

Your application should interpret these questions using a **reasoning agent** that manages the full workflow: clarifying intent, selecting a query strategy, generating a safe and valid SQL query, validating and executing it through the application layer, recovering from errors autonomously where possible, and returning the result in a human-readable format. The output should include:

* a natural language answer,
* a structured result exported as a CSV table,
* and a simple visualisation such as a chart where appropriate.

**Agentic Architecture:** The query handling must be implemented as a stateful agent graph — not a single LLM call. The agent should maintain state across its reasoning steps (e.g. the original question, generated SQL, execution result, error context) and make decisions at each node: whether to proceed, retry with a corrected query, request clarification, or reject the request. LangGraph is the preferred framework for implementing this graph, as it is taught in the course. Learners may use an alternative agentic framework if they can clearly justify the choice in their documentation.

The project is based on a realistic internal system context:

* the target data domain is **alarm and incident history**,
* the target storage is **PostgreSQL with TimescaleDB**,
* the service should be designed as a **Python microservice exposing a REST API**,
* the resulting functionality should be suitable for integration into an existing **React frontend**.

A critical requirement of the project is **data security and tenant isolation**. The system must ensure that users can only retrieve data belonging to their own customer or tenant. The tenant ID is derived from the login response of the existing authentication system. Since the SQL is generated with the help of an LLM, the application must include safeguards that prevent unsafe or unauthorised queries from being executed.

This project should focus on a practical MVP. It is not expected to fully replace the existing production history service during the capstone. The migration from the old storage model to the new one should be described in a written migration concept, but the primary focus should remain on the AI-assisted query workflow, secure query execution, and useful presentation of results.

You may also explore whether Retrieval-Augmented Generation (RAG) adds meaningful value for searching optional unstructured alarm notes. However, RAG is not a mandatory requirement for the core solution. A strong baseline solution can be achieved with structured data, SQL generation, and result interpretation alone.

**LLM Provider:** Selecting a cost-effective LLM provider is part of the task. Learners should evaluate available options and justify their choice based on cost, capability, and suitability for text-to-SQL tasks. The implementation should be designed with provider flexibility in mind, so that the underlying model can be swapped out in the future without requiring major architectural changes.

---

## Task requirements

The exact task requirements are as follows:

1. **Problem Definition**
   * Clearly explain the limitations of the current history reporting workflow.
   * Define the user problem that the new service is solving.
   * Identify the target users of the system.

2. **Natural Language Querying**
   * Allow users to submit natural language questions about historical alarm data.
   * Support the most commonly used query types listed in the task description.
   * Include examples of supported and unsupported query types.

3. **Agentic Query Workflow**
   * Implement the query handling as a stateful agent graph using LangGraph or a justified alternative framework.
   * The agent must maintain state across reasoning steps: question, intent classification, generated SQL, execution result, and error context.
   * The agent must reason at each node and decide whether to proceed, retry with a corrected query, or reject the request.
   * On SQL execution errors, the agent must attempt autonomous error recovery (e.g. regenerating the query with the error as context) before surfacing a failure to the user.
   * Provide schema context and other necessary instructions to the model at the appropriate graph node.
   * Ensure that SQL queries are executed by the Rails application layer, never directly by the model.
   * Ensure that queries are valid for PostgreSQL / TimescaleDB.

4. **Security and Guardrails**
   * Implement safeguards to prevent unsafe or unauthorised queries.
   * Enforce tenant or customer boundaries outside of the model, using the tenant ID retrieved from the existing authentication system login response.
   * Restrict the query surface to read-only access.
   * Handle invalid, ambiguous, or unsupported user requests gracefully.

5. **Data Presentation**
   * Return a human-readable answer generated from the query result.
   * Return the structured query result as a CSV file.
   * Include at least one basic visualisation for suitable query results.

6. **Technical Implementation**
   * Build the solution as a Python microservice exposing a REST API.
   * Implement the core query workflow as a stateful agent using LangGraph (preferred) or a justified alternative.
   * Use PostgreSQL with TimescaleDB as the target database.
   * Design the solution so that it can be integrated into an existing React frontend.
   * Implement proper error handling and sensible defaults, including agent-level error recovery.
   * Select and justify a cost-effective LLM provider; design the integration to be provider-agnostic where possible.

7. **Documentation**
   * Document the architecture and main technical decisions.
   * Explain how tenant safety is enforced.
   * Describe the boundaries of the MVP.
   * Include examples of typical user queries and expected outputs.
   * Provide a written migration concept describing how migration from the legacy service could be approached, without making it the main implementation focus.

---

## MVP Acceptance Criteria

The following acceptance criteria define the minimum required behaviour for the MVP. All items must be met for the project to be considered complete at the MVP level.

### Skipped: Authentication & Tenant Isolation

- [ ] The service integrates with the existing authentication system; unauthenticated requests are rejected with `401 Unauthorized`.
- [ ] The tenant ID is extracted from the login response and injected into every agent run as part of the initial state.
- [ ] Tenant scoping is enforced at the application layer and cannot be bypassed by prompt content or user input.
- [ ] Requests that cannot be safely scoped to a tenant are rejected with an appropriate error response.

#### Reason to skip

- We intentionally built this service as a standalone proof of concept, isolated from SEON's production infrastructure. Integrating with live services would have introduced two risks: (1) exposing sensitive production data during active development, and (2) coupling the agent's behavior to systems outside our scope. Instead, we used a controlled, minimal dataset and a manual company_id input to test tenant-scoped queries in isolation. This kept the blast radius small and let us focus on validating the agent's correctness, safety, and cost properties before any production integration."

### Natural Language Querying

- [x] A user can submit a natural language question via the API and receive a structured response.
- [x] All supported query types are documented and demonstrably working.
- [x] The system returns a clear, user-friendly error message (not a crash) for unsupported or ambiguous questions.

### Agentic Query Workflow

- [x] The query handling is implemented as a stateful agent graph using LangGraph or a documented and justified alternative framework.
- [x] The agent maintains state across its reasoning steps (question, intent, generated SQL, execution result, error context).
- [x] The agent makes an explicit routing decision at each node: proceed, retry, or reject.
- [x] On SQL execution failure, the agent attempts at least one autonomous retry by regenerating the query with the error as additional context, before surfacing a failure to the user.
- [x] The generated SQL is executed by the Python application layer — never directly by the model.
- [x] All queries are strictly read-only (`SELECT` only); any statement containing `INSERT`, `UPDATE`, `DELETE`, `DROP`, or `ALTER` is rejected before execution.
- [x] Generated SQL is valid and executable against the PostgreSQL / TimescaleDB schema.

### Security & Guardrails

- [x] A guardrail layer validates generated SQL before execution and blocks disallowed operations.
- [x] Invalid, malformed, or out-of-scope requests are handled gracefully without exposing internal details.

### Data Presentation

- [x] Every successful response includes a natural language answer summarising the result.
- [x] Every successful response includes the structured query result as a downloadable CSV file.
  - Note: Documents for <= rows are shown as inline csv, not downloadble
- [-] At least one supported query type returns chart-ready data alongside the CSV result.
  - We decided to support only csv_inline/downloads as first step since that's what our clients use at the moment. Current version does not show charts.

### API & Integration

- [x] The service exposes a documented REST endpoint suitable for consumption by a React frontend.
- [x] All responses follow a consistent JSON envelope containing: `answer`, `csv_url` (or inline CSV), `chart_data` (where applicable), and `error` (where applicable).
- [x] The API returns appropriate HTTP status codes: `200` for success, `400` for validation errors, `401` for authentication failures, and `500` for server errors.

### LLM Provider

- [x] The learner has selected and documented a cost-effective LLM provider with justification.
  - For purposes of evaluation we use Turing allowed models
- [x] The LLM integration is implemented behind an abstraction layer that allows the provider to be swapped without major rework.

### Error Handling

- [x] Invalid or malformed requests return a `400` with a descriptive, user-readable message.
  - Some responses return 422, not just 400
- [x] LLM or database failures return a `500` without leaking internal error details or stack traces.
  - Intentional decision to not return 500, we return `success: false` for requests with normal `V1QueryResponse` with the text of the error.
- [x] The service handles LLM timeouts gracefully without hanging or returning an incomplete response.

### Documentation

- [x] A written architecture overview documents the main components and their interactions.
- [x] Tenant safety enforcement is explained clearly in the documentation.
- [x] A written migration concept describes how the legacy MongoDB-backed service could be migrated to the new PostgreSQL / TimescaleDB architecture.
  - No dedicated document to "how to migrate". There's a script that imports data from one to another which would need to be validated for enterprise usage.

---

## Optional tasks

After the main functionality is implemented and your code works correctly, and you feel that you want to upgrade your project, choose various improvements from this list.
The list is sorted by difficulty levels.

**Caution: Some of the tasks in medium or hard categories may require research beyond the main programme content.**

### Easy

1. [x] Add a curated list of example questions that users can click to test the system.
2. [x] Show the generated SQL query in the UI for transparency and debugging.
3. [x] Expose the agent's reasoning steps (graph nodes visited, decisions made, retries attempted) in the API response for transparency.
    - API response and Langsmith tracing show this information
4. [ ] Add a short explanation of why a particular query was generated.
    - Not met/missed
5. [x] Improve the tone and structure of the final answer for business users.
6. [x] Add graceful fallback behaviour for unsupported questions.

### Medium

1. [x] Add token usage and cost tracking for all LLM calls.
2. [x] Implement SQL validation or sanitisation before execution.
3. [x] Add query history so that users can review previous questions and outputs.
4. [x] Add support for follow-up questions in the same session.
5. [x] Build a benchmark set of example alarm questions and evaluate answer quality against expected outputs.
6. [ ] Add role- or tenant-aware query templates to improve safety and consistency.
7. [-] Add chart type selection depending on the shape of the result set.
8. [ ] Add user feedback collection for generated answers.

### Hard

1. [ ] Evaluate whether RAG improves the handling of optional unstructured alarm notes, and implement it if justified.
  - We decided  in favor of having a simpler schema approach as supposed to RAG based querying to reduce complexity in the scope of this MVP version.
2. [ ] Implement a hybrid approach that uses structured SQL retrieval for core alarm data and semantic retrieval for note-like text fields.
  - Not met due to lack of semantic search needs
3. [x] Add full observability or tracing for the agent graph (node transitions, state snapshots, LLM call metadata).
4. [x] Create an automated evaluation pipeline for query correctness, agent behaviour, safety, and answer quality.
5. [-] Design and implement a more advanced guardrail layer that restricts allowed tables, joins, filters, and time windows.
    - Partially met: Guardrails exist at a table level
6. [ ] Extend the agent with a clarification node that asks the user a follow-up question when intent is ambiguous, rather than rejecting the request.
7. [x] Prepare the service for clean integration into an existing production-oriented frontend and backend architecture.
    - Minimal production ready integration points
8. [x] Compare two different prompting or agent graph strategies for text-to-SQL and justify the final design choice.

---

## Evaluation criteria

### Problem definition

* The learner has clearly defined the business and technical problem addressed by the project.
* The learner can explain why the current history reporting workflow is insufficient.
* The learner can articulate how the new service improves usability, flexibility, or performance.

### Understanding core concepts

* The learner understands the difference between a single-shot LLM call and a stateful agentic workflow, and can explain why the latter is required here.
* The learner can describe the agent graph: its nodes, state schema, routing logic, and error recovery behaviour.
* The learner can explain why LLM-generated SQL requires guardrails, and how those guardrails are enforced outside the model.
* The learner understands how to provide schema context and constraints to the model at the appropriate graph node.
* The learner demonstrates awareness of tenant isolation, safety, and read-only query execution.
* The learner can explain the limitations of the chosen approach.

### Technical implementation

* The learner has implemented a working prototype as a Python microservice with a clean REST API.
* The learner has implemented the query workflow as a stateful agent graph, with clearly defined nodes, state management, and routing decisions.
* The learner has implemented autonomous error recovery within the agent (e.g. SQL retry with error context).
* The learner has created a clear backend flow from user question through the agent graph to SQL generation, validation, execution, and answer generation.
* The learner has used PostgreSQL / TimescaleDB appropriately for the target domain.
* The learner has built a usable interface or integration layer for presenting answers, CSV exports, and charts.
* The learner has implemented appropriate security considerations for query execution.
* The learner has selected and justified a cost-effective LLM provider and designed the integration with future flexibility in mind.

### Reflection and improvement

* The learner understands the trade-offs of the implemented solution, including the complexity cost of an agentic architecture versus a simpler pipeline.
* The learner can explain which parts are MVP and which parts would be needed for production readiness.
* The learner can reflect on the agent design: which nodes were most critical, where the graph could fail, and how it could be extended.
* The learner can suggest future improvements for performance, usability, safety, agent robustness, or integration.

### Bonus points

* For maximum points, the learner should implement at least 2 medium and 1 hard optional tasks.
