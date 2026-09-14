# AbinDebugger Architecture

This document outlines the system architecture of `AbinDebugger`, a high-performance, robust, and extensible automated program repair platform. 

---

## 1. Design Philosophy:

* **Test in RAM:** Candidate fixes are evaluated entirely inside virtual memory without ever touching the hard drive.
* **Self-Contained:** The platform requires zero external background services or daemons, utilizing embedded storage for maximum portability.
* **Modular Design:** Built around a headless, event-driven pipeline, allowing intelligent modules (like AI-Assisted Test Generation or LLM Code Reviewers) to integrate via standard I/O with zero friction.

---

## 2. Core Architectural Pillars

### Pillar A: Pure In-Memory Sandboxing
Instead of utilizing OS-level file loaders for patch evaluation, the engine manipulates Python syntax trees (ASTs) strictly in memory. Candidate ASTs are compiled directly to bytecode (`compile()`) and executed inside isolated virtual namespaces. 
* **Advantage:** Eliminates file overwriting race conditions, prevents `sys.modules` contamination, and allows the engine to evaluate hundreds of candidate repairs per second safely.

### Pillar B: Portable Embedded Storage
Pattern storage and retrieval are handled by an embedded **SQLite JSONB** database (`repair_knowledge.db`).
* **Advantage:** The entire repair database is a single, portable local file. A user or CI/CD runner can install the tool and immediately repair code offline without configuring or authenticating a background document database.

### Pillar C: Low-Overhead SBL Tracing
Fault localization tracks code coverage at near-native interpreter execution speeds by utilizing modern Python 3.12+ **`sys.monitoring`** (PEP 669), bypassing the massive execution penalties associated with legacy `sys.settrace` hooks.

---

## 3. High-Level Architecture Diagram

```mermaid
graph TD
    classDef core fill:#4f46e5,stroke:#312e81,stroke-width:2px,color:#fff;
    classDef plugin fill:#0d9488,stroke:#115e59,stroke-width:2px,color:#fff;
    classDef storage fill:#d97706,stroke:#92400e,stroke-width:2px,color:#fff;

    A[Buggy Source Code & Test Suite] --> B(Engine Orchestrator)
    B --> C{1. Fault Localization Engine}
    
    subgraph Storage Hub
        DB[(SQLite Pattern Knowledge Base)]:::storage
    end

    C -->|Flagged Lines & AST Context| D{2. Hypothesis Generation Hub}
    
    subgraph Plug-and-Play Generators
        D1[AST Search & Abduction Engine]:::plugin
        D2[AI / LLM Patch Generator Plugin]:::plugin
        D3[AI Test Case Generator Plugin]:::plugin
    end

    DB <--> D1
    D <--> D1 & D2 & D3

    D -->|Candidate Patches in RAM| E{3. In-Memory Flight Simulator}
    E -->|Run Virtual Tests| F{Passed Baseline Consistency?}
    
    F -->|No: Regressed Baseline| D
    F -->|Yes: Valid Repair| G[Verified Repaired Program]
```
