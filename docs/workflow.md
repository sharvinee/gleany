# Gleany — Workflow Diagram

```mermaid
flowchart TD
    subgraph Frontend["Frontend (Browser)"]
        UI["static/index.html<br/>Dark theme, vanilla JS"]
        ClickGO["▶ Run GO Scenario"]
        ClickAbandon["⚠ Run ABANDON Scenario"]
        Gate["Human Approval Gate<br/>Approve & Send / Abort"]
    end

    subgraph API["FastAPI Backend"]
        Eval["POST /api/evaluate"]
        Send["POST /api/send-advisory"]
    end

    subgraph Data["Live Data Sources"]
        AMS1["USDA AMS Slug 2390<br/>Fresno Shipping Point<br/>Santa Maria strawberries"]
        AMS2["USDA AMS Slug 2306<br/>LA Terminal Market<br/>Central Coast strawberries"]
    end

    subgraph Deterministic["Deterministic Python — No LLM"]
        Wage["get_wage_floors<br/>CA 2026 entry level<br/>3 candidates → $16.90 binds"]
        Cost["compute_cost_floor<br/>harvest_labour = wage / pick_rate<br/>+ cooling + commission + freight"]
        Decide["decide()<br/>Confidence gate → Band"]
        Record["write_decision_record<br/>→ decision_record.md"]
    end

    subgraph Agent["LangChain Agent Layer"]
        MainAgent["Decision Agent<br/>GPT-4o + 5 tools<br/>Gathers signals, drafts advisory"]
        RecoveryAgent["Recovery Agent<br/>GPT-4o + 2 tools<br/>Finds food banks + processors"]
    end

    subgraph Delivery["Delivery"]
        Composio["Composio Gmail<br/>send_advisory_via_composio"]
        Email["📧 Real email sent<br/>to food bank / grower"]
    end

    %% User flow
    UI --> ClickGO
    UI --> ClickAbandon
    ClickGO --> Eval
    ClickAbandon --> Eval

    %% Evaluate pipeline
    Eval -->|httpx basic auth| AMS1
    Eval -->|httpx basic auth| AMS2
    AMS1 -->|2 rows filtered from 53| Decide
    AMS2 -->|5 rows filtered| Decide
    Eval --> Wage
    Wage -->|binding $16.90/hr| Cost
    Cost -->|total cost per flat| Decide
    Decide -->|"net > 0 → GO"| Record
    Decide -->|"net < -labour → ABANDON"| Record
    Decide -->|"&lt;2 sources → SILENT"| Record

    %% ABANDON branch
    Decide -->|"ABANDON"| MainAgent
    MainAgent -->|"drafts advisory"| RecoveryAgent
    RecoveryAgent -->|"food banks + processors"| Eval
    Eval -->|returns recovery text| UI
    UI --> Gate
    Gate -->|"Approve"| Send
    Gate -->|"Abort"| UI
    Send --> Composio
    Composio --> Email

    %% GO branch direct
    Eval -->|returns JSON| UI

    %% Styling
    classDef go fill:#1a3a2a,stroke:#3fb950,color:#3fb950
    classDef abandon fill:#3a1a1a,stroke:#f85149,color:#f85149
    classDef silent fill:#2a2a2a,stroke:#8b949e,color:#8b949e
    classDef live fill:#1a253a,stroke:#58a6ff,color:#58a6ff
    classDef gate fill:#3a3a1a,stroke:#d29922,color:#d29922

    class ClickGO go
    class ClickAbandon abandon
    class Decide go
    class Gate gate
    class AMS1,AMS2 live
    class Composio,Email live
```

## Flow explanation

### GO path (green)
1. User clicks "Run GO Scenario"
2. Backend fetches live prices from 2 USDA AMS sources
3. Wage floors selected — $16.90/hr (CA minimum wage) binds over $16.45 (OEWS) and $13.45 (H-2A adjusted)
4. Cost floor computed: labour $3.38 + cooling $1.50 + commission $0.96 + freight $2.00 = $7.84/flat
5. Net = $8.00 - $7.84 = **+$0.16/flat → GO**
6. Decision record written to disk
7. JSON returned to frontend, displayed

### ABANDON path (red)
1. User clicks "Run ABANDON Scenario" (higher placeholder costs)
2. Same price + wage pipeline runs
3. Cost floor = $11.98/flat, net = **-$3.98/flat → ABANDON**
4. Recovery agent finds food banks (Santa Barbara, San Luis Obispo, Ventura) + processors (Strawberry Commission network)
5. Advisory text returned to frontend
6. **Human Approval Gate** — user must click "Approve & Send"
7. Only after approval → Composio Gmail sends real email to sharvineeeducation@gmail.com
8. The agent never holds the send tool — structural gate, not prompted

### SILENT path (grey)
1. If fewer than 2 independent price sources → SILENT
2. If data_age_hours > 72 → SILENT
3. No action taken, reason recorded

### Key principle
**The agent gathers, the code decides.** The model extracts, summarises, and drafts.
The cost floor is arithmetic and the decision bands are thresholds — both are plain Python.
This makes the output auditable and stops the model from producing a plausible wrong number.
